"""Identity and observation rules shared by storage, discovery and the UI."""

import ipaddress
import re
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_mac(value):
    if not value or str(value).lower() == "unknown":
        return None
    raw = re.sub(r"[:.\-]", "", str(value)).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", raw):
        raise ValueError("Invalid MAC address")
    if raw in {"000000000000", "ffffffffffff"} or int(raw[:2], 16) & 1:
        return None
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def meaningful(value):
    return value if value and str(value).lower() != "unknown" else None


def stamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
        return (
            result.astimezone(timezone.utc)
            if result.tzinfo
            else result.astimezone().astimezone(timezone.utc)
        )
    except (ValueError, TypeError):
        return None


def pretty_time(value):
    result = stamp(value)
    return (
        result.astimezone().strftime("%b %d, %Y · %H:%M") if result else "Not recorded"
    )


def display_name(device):
    return (
        device.get("nickname")
        or meaningful(device.get("hostname"))
        or (
            (device.get("vendor") or "Unidentified device")
            + " · "
            + (device.get("mac") or device.get("ip") or "")[-8:]
        )
    )


def evidence_label(value):
    return {
        "response": "Responded in scan",
        "local": "This computer",
        "cache": "Cached · uncertain",
        "not_seen": "Not observed in scan",
        "legacy": "Historical observation",
    }.get(value, "Unknown evidence")


def friendly_edit_detail(value):
    """Render old and new edit events without exposing database field names."""
    if not value.startswith("Changed: "):
        return value
    labels = {
        "nickname": "device name",
        "notes": "notes and tags",
        "known": "recognition",
        "reviewed": "review status",
        "archived": "archive status",
    }
    fields = [labels.get(field, field) for field in value[9:].split(", ")]
    if not fields:
        return value
    return (
        "Updated "
        + ", ".join(fields[:-1])
        + (" and " if len(fields) > 1 else "")
        + fields[-1]
        + "."
    )


def presence(device, fresh_seconds=900):
    observed = stamp(device.get("observed_at"))
    if (
        not observed
        or (datetime.now(timezone.utc) - observed).total_seconds() > fresh_seconds
    ):
        return "Stale observation"
    if device.get("evidence") == "cache":
        return "Cached · uncertain"
    if device.get("evidence") == "not_seen":
        return "Not observed in scan"
    if device.get("evidence") == "response":
        return "Responded in scan"
    if device.get("evidence") == "local":
        return "This computer"
    return "Historical observation"


def scope_for(interface, requested=None, max_hosts=1024):
    attached = ipaddress.IPv4Network(
        f"{interface['ip']}/{interface['prefix']}", strict=False
    )
    target = ipaddress.IPv4Network(requested or str(attached), strict=False)
    if not target.subnet_of(attached):
        raise ValueError("Choose a range inside the selected adapter's network.")
    if target.num_addresses > max_hosts + 2:
        raise ValueError(f"Choose a smaller range (at most {max_hosts} hosts).")
    return target
