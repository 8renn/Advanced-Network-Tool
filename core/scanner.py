from __future__ import annotations

import ipaddress
import json
import re
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Generator

from core.runtime_paths import resource_path


def _subprocess_no_window_kwargs() -> dict:
    """Suppress console window on Windows."""
    if sys.platform == "win32":
        kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
        return kwargs
    return {}


def _normalize_mac(mac: str) -> str:
    """Normalize MAC to uppercase colon-separated format: AA:BB:CC:DD:EE:FF"""
    mac = (mac or "").strip().upper()
    # Remove all separators, then re-insert colons
    hex_only = re.sub(r"[^0-9A-F]", "", mac)
    if len(hex_only) != 12:
        return mac  # return as-is if not a valid MAC
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


def _load_vendor_db() -> dict[str, str]:
    """Load mac_vendors.json and build OUI→vendor lookup dict."""
    candidates = [
        resource_path("mac_vendors.json"),
        Path.cwd() / "mac_vendors.json",
        Path(__file__).resolve().parents[1] / "mac_vendors.json",
        Path(__file__).resolve().parent / "mac_vendors.json",
    ]

    data = None
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            break
        except Exception:
            continue

    if not isinstance(data, dict):
        return {}

    vendor_by_oui: dict[str, str] = {}
    for vendor, prefixes in data.items():
        if not vendor or not isinstance(prefixes, list):
            continue
        vendor_name = str(vendor)
        # Clean IEEE raw format: "2C4F52     (base 16)\t\tCisco Systems, Inc"
        if "(base 16)" in vendor_name:
            # Extract the actual name after "(base 16)" and any whitespace/tabs
            parts = vendor_name.split("(base 16)")
            if len(parts) > 1:
                vendor_name = parts[1].strip().strip("\t").strip()
            if not vendor_name:
                vendor_name = parts[0].strip()
        for prefix in prefixes:
            key = str(prefix).replace(":", "").replace("-", "").strip().upper()
            if len(key) >= 6:
                vendor_by_oui[key[:6]] = vendor_name
    return vendor_by_oui


_VENDOR_BY_OUI: dict[str, str] = _load_vendor_db()


def lookup_vendor(mac: str) -> str:
    mac_hex = (mac or "").replace(":", "").replace("-", "").strip().upper()
    if len(mac_hex) < 6:
        return "Unknown"
    return _VENDOR_BY_OUI.get(mac_hex[:6], "Unknown")


def _ping_host(ip: str, timeout_ms: int = 500) -> bool:
    """Ping a single host. Returns True if alive. Populates OS ARP cache as side effect."""
    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), str(ip)]
        else:
            timeout_s = max(1, timeout_ms // 1000)
            cmd = ["ping", "-c", "1", "-W", str(timeout_s), str(ip)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_ms / 1000 + 2,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _read_arp_table() -> dict[str, str]:
    """Parse the OS ARP table. Returns {ip: mac} dict."""
    entries: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
        output = result.stdout or ""

        if sys.platform == "win32":
            # Windows arp -a format:
            #   192.168.68.1          2c-4f-52-3c-94-24     dynamic
            pattern = re.compile(
                r"(\d+\.\d+\.\d+\.\d+)\s+"
                r"([0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2}[-:][0-9a-fA-F]{2})\s+"
                r"(dynamic|static)",
                re.IGNORECASE,
            )
        else:
            # Linux/Mac arp -a format:
            #   ? (192.168.68.1) at 2c:4f:52:3c:94:24 [ether] on eth0
            pattern = re.compile(
                r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+"
                r"([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})"
            )

        for match in pattern.finditer(output):
            ip = match.group(1)
            mac = _normalize_mac(match.group(2))
            # Skip broadcast and incomplete entries
            if mac and mac != "FF:FF:FF:FF:FF:FF" and mac != "00:00:00:00:00:00":
                entries[ip] = mac

    except (subprocess.TimeoutExpired, OSError):
        pass
    return entries


def _get_local_mac() -> str:
    """Get the MAC address of the default network interface."""
    try:
        if sys.platform == "win32":
            # Use getmac command
            result = subprocess.run(
                ["getmac", "/fo", "csv", "/nh", "/v"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                **_subprocess_no_window_kwargs(),
            )
            output = result.stdout or ""
            for line in output.strip().splitlines():
                # CSV format: "Connection Name","Network Adapter","Physical Address","Transport Name"
                parts = line.split(",")
                if len(parts) >= 3:
                    mac_raw = parts[2].strip().strip('"')
                    if mac_raw and mac_raw != "N/A" and "Media disconnected" not in line:
                        mac = _normalize_mac(mac_raw)
                        if mac and mac != "00:00:00:00:00:00":
                            return mac
        else:
            # Best-effort fallback for non-Windows platforms
            import uuid

            mac_int = uuid.getnode()
            mac = ":".join(f"{(mac_int >> ele) & 0xFF:02X}" for ele in range(40, -1, -8))
            return _normalize_mac(mac)
    except Exception:
        pass
    return ""


def _windows_arp_probe(hosts: list[str], already_alive: set[str], max_workers: int = 32) -> None:
    """Send ARP-populating pings for hosts that did not answer ICMP."""
    if sys.platform != "win32":
        return
    silent_hosts = [ip for ip in hosts if ip not in already_alive]
    if not silent_hosts:
        return

    def _arp_ping(ip: str) -> None:
        try:
            subprocess.run(
                ["ping", "-n", "1", "-w", "200", ip],
                capture_output=True,
                timeout=3,
                check=False,
                **_subprocess_no_window_kwargs(),
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_arp_ping, ip) for ip in silent_hosts[:254]]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass


def _seen_has_ip(seen: set[str], ip: str) -> bool:
    return any(k.split("|", 1)[0] == ip for k in seen)


def scan_network(cidr: str) -> Generator[dict, None, None]:
    """
    Network scan using ping sweep + ARP table read.

    1. Pings all hosts concurrently to populate OS ARP cache
    2. Reads ARP table for IP→MAC mappings
    3. Yields devices as discovered

    Yields: {"ip": str, "mac": str, "vendor": str}
    """
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(h) for h in network.hosts()]

    if not hosts:
        return

    # Phase 0: Self-discovery — add the local machine
    seen: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        finally:
            s.close()

        if local_ip and ipaddress.ip_address(local_ip) in network:
            local_mac = _get_local_mac()
            if local_mac:
                key = f"{local_ip}|{local_mac}"
                seen.add(key)
                yield {"ip": local_ip, "mac": local_mac, "vendor": lookup_vendor(local_mac)}
    except OSError:
        pass

    # Phase 1: Read existing ARP cache (devices already known to OS)
    arp_before = _read_arp_table()
    for ip, mac in arp_before.items():
        try:
            if ipaddress.ip_address(ip) in network:
                key = f"{ip}|{mac}"
                if key not in seen:
                    seen.add(key)
                    yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}
        except ValueError:
            continue

    # Phase 2: Ping sweep to discover new hosts and populate ARP cache
    alive_ips: set[str] = set()
    alive_lock = threading.Lock()

    def _ping_and_track(ip: str) -> None:
        if _ping_host(ip, timeout_ms=800):
            with alive_lock:
                alive_ips.add(ip)

    # Use up to 64 concurrent ping threads for speed
    max_workers = min(64, len(hosts))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_ping_and_track, ip): ip for ip in hosts}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass

    # Phase 2b: Windows ARP probe for ping-silent devices
    if sys.platform == "win32":
        _windows_arp_probe(hosts, alive_ips)

    # Phase 3: Read ARP cache again after ping sweep
    arp_after = _read_arp_table()
    for ip, mac in arp_after.items():
        try:
            if ipaddress.ip_address(ip) in network:
                key = f"{ip}|{mac}"
                if key not in seen:
                    seen.add(key)
                    yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}
        except ValueError:
            continue

    # Phase 4: For alive hosts not yet in ARP table (unlikely but possible),
    # yield them with MAC if a final ARP read finds one
    arp_final = _read_arp_table()
    for ip in alive_ips:
        if _seen_has_ip(seen, ip):
            continue
        mac = arp_final.get(ip, "")
        if mac:
            mac = _normalize_mac(mac)
            key = f"{ip}|{mac}"
            if key not in seen:
                seen.add(key)
                yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}
