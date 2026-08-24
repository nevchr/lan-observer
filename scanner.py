import concurrent.futures
import re
import socket
import subprocess
import uuid
from mac_vendor_lookup import MacLookup

mac_lookup = MacLookup()

def get_local_ip():
    """Get this computer's local network IP."""
    hostname = socket.gethostname()
    return socket.gethostbyname(hostname)

def get_local_mac():
    """Get this computer's MAC address."""
    mac = uuid.getnode()

    return ":".join(
        f"{(mac >> i) & 0xff:02x}"
        for i in range(40, -1, -8)
    )


def get_subnet():
    """
    Example:
    192.168.0.20 -> 192.168.0
    """
    local_ip = get_local_ip()
    return ".".join(local_ip.split(".")[:3])


def ping_device(ip):
    """Returns True if a device responds to one ping."""
    result = subprocess.run(
        ["ping", "-n", "1", "-w", "800", ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return result.returncode == 0


def get_hostname(ip):
    """Try to get a hostname for an IP."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return "Unknown"


def get_arp_table():
    """Return the Windows ARP table as {IP: MAC}."""
    result = subprocess.run(
        ["arp", "-a"],
        capture_output=True,
        text=True
    )

    arp_table = {}

    for line in result.stdout.splitlines():
        match = re.search(
            r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})",
            line
        )

        if match:
            ip = match.group(1)
            mac = match.group(2)

            arp_table[ip] = mac

    return arp_table


def scan_network():
    subnet = get_subnet()
    local_ip = get_local_ip()
    local_mac = get_local_mac()

    addresses = [
        f"{subnet}.{i}"
        for i in range(1, 255)
    ]

    print(f"Scanning {subnet}.1 - {subnet}.254...\n")

    discovered_ips = set()

    # 1. Ping the whole subnet
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = executor.map(ping_device, addresses)

        for ip, online in zip(addresses, results):
            if online:
                discovered_ips.add(ip)

    # 2. Read the ARP table after scanning
    arp_table = get_arp_table()

    # Add normal LAN addresses found in ARP
    for ip in arp_table:
        if ip.startswith(subnet + "."):
            last_octet = int(ip.split(".")[-1])

            # Ignore broadcast/network addresses
            if 1 <= last_octet <= 254:
                discovered_ips.add(ip)

    # 3. Always include this computer
    discovered_ips.add(local_ip)

    devices = []

    for ip in sorted(
        discovered_ips,
        key=lambda address: int(address.split(".")[-1])
    ):
        if ip == local_ip:
            mac = local_mac
        else:
            mac = arp_table.get(ip, "Unknown")

        device = {
    "ip": ip,
    "hostname": get_hostname(ip),
    "mac": mac,
    "vendor": get_vendor(mac)
}

        devices.append(device)

    return devices

def get_vendor(mac):
    """Try to identify the manufacturer from a MAC address."""
    if mac == "Unknown":
        return "Unknown"

    try:
        return mac_lookup.lookup(mac)
    except Exception:
        return "Unknown"


if __name__ == "__main__":
    from database import init_database, save_scan, get_devices

    init_database()

    devices = scan_network()
    save_scan(devices)

    print("\nCURRENT DATABASE:\n")

    for device in get_devices():
        print(
            f"{device['ip']:<15} "
            f"{device['mac']:<20} "
            f"{device['hostname']:<25} "
            f"{'ONLINE' if device['online'] else 'OFFLINE'}"
        )