"""Windows IPv4 discovery with explicit adapter selection and bounded work."""

import ctypes
import ipaddress
import json
import os
import socket
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .domain import canonical_mac, scope_for


def powershell(script, timeout=10):
    if os.name != "nt":
        raise OSError("Network discovery currently requires Windows.")
    # Scripts contain fixed code and validated integer/IP literals, never user text.
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; "
            + script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise OSError(
            "Windows network command failed. Check adapter availability and permissions."
        )
    return result.stdout.strip().lstrip("\ufeff")


def as_list(value):
    return value if isinstance(value, list) else ([value] if value else [])


def interfaces():
    output = powershell("""
    $items = @(Get-NetIPConfiguration -All | Where-Object {$_.NetAdapter.Status -eq 'Up'} | ForEach-Object {
      $c = $_;
      foreach ($ip in $c.IPv4Address) {
        [pscustomobject]@{index=[int]$c.InterfaceIndex; name=[string]$c.InterfaceAlias;
          guid=[string]$c.NetAdapter.InterfaceGuid; mac=[string]$c.NetAdapter.MacAddress;
          ip=[string]$ip.IPAddress; prefix=[int]$ip.PrefixLength;
          profile=[string]$c.NetProfile.Name; gateway=[string]($c.IPv4DefaultGateway.NextHop | Select-Object -First 1)}
      }
    }); ConvertTo-Json -InputObject $items -Compress
    """)
    result = []
    for item in as_list(json.loads(output or "[]")):
        address = ipaddress.IPv4Address(item["ip"])
        if (
            address.is_loopback
            or address.is_unspecified
            or address.is_multicast
            or address.is_link_local
        ):
            continue
        item["mac"] = canonical_mac(item.get("mac"))
        item["scope"] = str(
            ipaddress.IPv4Network(f"{address}/{item['prefix']}", strict=False)
        )
        # Name/profile/gateway guard against using a saved target after a network change.
        item["key"] = "|".join(
            str(item.get(k) or "") for k in ("guid", "profile", "gateway", "scope")
        )
        result.append(item)
    return result


def neighbors(interface):
    output = powershell(
        f"$items=@(Get-NetNeighbor -InterfaceIndex {int(interface['index'])} -AddressFamily IPv4 | Select-Object IPAddress,LinkLayerAddress,State); ConvertTo-Json -InputObject $items -Compress"
    )
    result = {}
    for row in as_list(json.loads(output or "[]")):
        try:
            mac = canonical_mac(row.get("LinkLayerAddress"))
            ip = str(ipaddress.IPv4Address(row["IPAddress"]))
        except (ValueError, KeyError):
            continue
        if mac:
            result[ip] = mac  # All cached entries remain hints, including Reachable.
    return result


def probe(ip, source, timeout_ms=800):
    """ICMP status code, not localized ping output; bind to the selected IPv4 source."""
    if os.name != "nt":
        raise OSError("Windows discovery is unavailable.")
    api = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
    api.IcmpCreateFile.restype = ctypes.c_void_p
    api.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
    api.IcmpSendEcho2Ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_ushort,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    api.IcmpSendEcho2Ex.restype = ctypes.c_uint32
    handle = api.IcmpCreateFile()
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError("Could not open Windows ICMP. Check network permissions.")
    payload = ctypes.create_string_buffer(b"LANObserver")
    reply = ctypes.create_string_buffer(256)
    try:
        count = api.IcmpSendEcho2Ex(
            handle,
            None,
            None,
            None,
            int.from_bytes(socket.inet_aton(source), "little"),
            int.from_bytes(socket.inet_aton(ip), "little"),
            payload,
            len(payload),
            None,
            reply,
            len(reply),
            timeout_ms,
        )
        if count:
            return int.from_bytes(reply.raw[4:8], "little") == 0
        error = ctypes.get_last_error()
        if error not in (0, 11002, 11003, 11004, 11005, 11010, 11013):
            raise OSError(f"Windows ICMP failed (code {error}).")
        return False
    finally:
        api.IcmpCloseHandle(handle)


def hostname(ip):
    ip = str(ipaddress.IPv4Address(ip))
    # The child process is killed on timeout, including a blocked OS DNS resolver.
    try:
        return (
            powershell(f"[System.Net.Dns]::GetHostEntry('{ip}').HostName", timeout=3)
            or None
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def bounded_map(values, function, cancel, deadline, workers=16):
    """Never enqueue the whole range; bound active calls and stop submitting on cancel."""
    iterator = iter(values)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        active = {}
        while True:
            while (
                len(active) < workers
                and not cancel.is_set()
                and time.monotonic() < deadline
            ):
                value = next(iterator, None)
                if value is None:
                    break
                active[executor.submit(function, value)] = value
            if not active:
                break
            done, _ = wait(active, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                value = active.pop(future)
                try:
                    yield value, future.result(), None
                except Exception as exc:
                    yield value, None, type(exc).__name__


def scan(
    interface,
    scope,
    cancel,
    progress,
    vendors=None,
    resolve_names=True,
    deadline_seconds=30,
):
    target = scope_for(interface, scope)
    addresses = [str(ip) for ip in target.hosts()]
    warnings = []
    responders = set()
    completed = 0
    failed = False
    deadline = time.monotonic() + deadline_seconds
    for ip, response, error in bounded_map(
        addresses, lambda address: probe(address, interface["ip"]), cancel, deadline
    ):
        completed += 1
        if response:
            responders.add(ip)
        if error:
            failed = True
        progress("discovering", completed)
    if cancel.is_set():
        return dict(
            status="canceled",
            observations=[],
            warnings=["Scan canceled. Previous observations preserved."],
        )
    if completed != len(addresses):
        failed = True
        warnings.append(
            "Discovery deadline reached; only part of the range was checked."
        )
    if failed:
        warnings.append(
            "Some probes did not complete. Absence cannot be inferred from this scan."
        )
    try:
        arp = neighbors(interface)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        arp = {}
        failed = True
        warnings.append(
            "Windows neighbor information was unavailable. MAC identities may be missing."
        )
    ips = responders | {
        ip for ip in arp if ipaddress.IPv4Address(ip) in target and ip in addresses
    }
    local_in_scope = interface["ip"] in addresses
    if local_in_scope:
        ips.add(interface["ip"])
    observations = []
    for ip in sorted(ips, key=ipaddress.IPv4Address):
        local = ip == interface["ip"]
        mac = interface["mac"] if local else arp.get(ip)
        observations.append(
            dict(
                ip=ip,
                mac=mac,
                hostname=socket.gethostname() if local else None,
                vendor=(vendors or {}).get(mac[:8].replace(":", "").upper())
                if mac
                else None,
                evidence="local"
                if local
                else ("response" if ip in responders else "cache"),
            )
        )
    if resolve_names:
        progress("enriching", completed)
        mapping = {o["ip"]: o for o in observations if o["evidence"] == "response"}
        resolved = 0
        for ip, name, error in bounded_map(
            list(mapping), hostname, cancel, time.monotonic() + 10, workers=4
        ):
            mapping[ip]["hostname"] = name
            resolved += bool(name)
        if resolved < len(mapping):
            warnings.append(
                "Some hostnames were unavailable. Previous known names have been retained."
            )
    if cancel.is_set():
        return dict(
            status="canceled",
            observations=[],
            warnings=["Scan canceled. Previous observations preserved."],
        )
    status = (
        (
            "partial"
            if any(o["evidence"] == "response" for o in observations)
            else "failed"
        )
        if failed
        else "completed"
    )
    return dict(status=status, observations=observations, warnings=warnings)
