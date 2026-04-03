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
from core.system_info import collect_local_network

# TCP ports for macOS fallback when ICMP does not get a reply (Angry IP Scanner–style).
_DARWIN_TCP_PROBE_PORTS = (80, 443, 22, 445)


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


def _udp_local_ipv4() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _darwin_cidr_via_netifaces() -> str | None:
    try:
        import netifaces
    except ImportError:
        return None
    try:
        gateways = netifaces.gateways()
        default = gateways.get("default", {})
        row = default.get(netifaces.AF_INET)
        if not row:
            return None
        default_iface = row[1]
        addrs = netifaces.ifaddresses(default_iface)
        inet_rows = addrs.get(netifaces.AF_INET) or []
        if not inet_rows:
            return None
        ip = (inet_rows[0].get("addr") or "").strip()
        netmask = (inet_rows[0].get("netmask") or "").strip()
        if not ip or not netmask:
            return None
        iface = ipaddress.IPv4Interface(f"{ip}/{netmask}")
        return str(iface.network)
    except (KeyError, ValueError, TypeError, ipaddress.AddressValueError, OSError):
        return None


def get_local_ipv4_scan_cidr() -> str:
    """
    Return the local IPv4 subnet as CIDR (e.g. 192.168.1.0/24).
    On macOS, prefers netifaces on the default route interface, then route/ifconfig (collect_local_network).
    Windows/Linux: ipconfig/PowerShell or ip route; falls back to /24.
    """
    if sys.platform == "darwin":
        cidr = _darwin_cidr_via_netifaces()
        if cidr:
            return cidr
    net = collect_local_network()
    ip = (net.get("primary_local_ipv4") or "").strip()
    mask = (net.get("subnet_mask") or "").strip()
    if ip and ip != "Unavailable" and mask and mask != "Unavailable":
        try:
            iface = ipaddress.IPv4Interface(f"{ip}/{mask}")
            return str(iface.network)
        except (ValueError, ipaddress.AddressValueError):
            pass
    lip = _udp_local_ipv4()
    if lip:
        try:
            return str(ipaddress.ip_network(f"{lip}/24", strict=False))
        except (ValueError, ipaddress.AddressValueError):
            pass
    return "192.168.1.0/24"


def _ping_host(ip: str, timeout_ms: int = 500) -> bool:
    """Ping a single host. Returns True if alive. Populates OS ARP cache as side effect."""
    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), str(ip)]
        elif sys.platform == "darwin":
            # macOS: -W is milliseconds; keep bounded so scans finish promptly
            wait_ms = max(200, min(int(timeout_ms), 3000))
            cmd = ["ping", "-c", "1", "-W", str(wait_ms), str(ip)]
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
        output = (result.stdout or "") + "\n" + (result.stderr or "")

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
            # BSD/macOS/Linux arp -a variants:
            #   hostname (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0
            pattern = re.compile(
                r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+"
                r"((?:[0-9a-fA-F]{1,2}[:-]){5}[0-9a-fA-F]{1,2})\b"
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


def _darwin_local_ip_and_mac() -> tuple[str, str]:
    """macOS: prefer netifaces on default IPv4 interface; fall back to UDP trick + uuid MAC."""
    ip = ""
    mac = ""
    try:
        import netifaces
    except ImportError:
        netifaces = None  # type: ignore[assignment]
    if netifaces is not None:
        try:
            gateways = netifaces.gateways()
            default = gateways.get("default", {})
            row = default.get(netifaces.AF_INET)
            if row:
                default_iface = row[1]
                addrs = netifaces.ifaddresses(default_iface)
                inet_rows = addrs.get(netifaces.AF_INET) or []
                if inet_rows:
                    ip = (inet_rows[0].get("addr") or "").strip()
                link_rows = addrs.get(netifaces.AF_LINK) or []
                if link_rows:
                    raw = (link_rows[0].get("addr") or "").strip()
                    if raw:
                        mac = _normalize_mac(raw)
        except (KeyError, TypeError, ValueError, OSError):
            pass
    if not ip:
        ip = _udp_local_ipv4() or ""
    if not mac:
        mac = _get_local_mac()
    return ip, mac


def _darwin_ping_once(ip: str) -> tuple[str, bool]:
    """macOS: /sbin/ping sweep (no root). -W is milliseconds on Darwin (1000 = 1 s cap per probe)."""
    try:
        result = subprocess.run(
            ["/sbin/ping", "-c", "1", "-W", "1000", str(ip)],
            capture_output=True,
            timeout=3,
            check=False,
        )
        return (str(ip), result.returncode == 0)
    except (subprocess.TimeoutExpired, OSError):
        return (str(ip), False)


def _darwin_tcp_any_port_open(ip: str, timeout_s: float = 0.35) -> bool:
    for port in _DARWIN_TCP_PROBE_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout_s)
            try:
                s.connect((ip, port))
                return True
            finally:
                s.close()
        except OSError:
            continue
    return False


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


def _unix_arp_probe(hosts: list[str], already_alive: set[str], max_workers: int = 32) -> None:
    """Second ping pass for ping-silent hosts (non-Windows, non-macOS)."""
    if sys.platform == "win32" or sys.platform == "darwin":
        return
    silent_hosts = [ip for ip in hosts if ip not in already_alive]
    if not silent_hosts:
        return

    def _arp_ping(ip: str) -> None:
        _ping_host(ip, timeout_ms=600)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_arp_ping, ip) for ip in silent_hosts[:254]]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass


def _seen_has_ip(seen: set[str], ip: str) -> bool:
    return any(k.split("|", 1)[0] == ip for k in seen)


def _scan_network_macos(network: ipaddress.IPv4Network, hosts: list[str]) -> Generator[dict, None, None]:
    """
    macOS-only: parallel /sbin/ping sweep, ARP for MACs, TCP connect fallback on common ports.
    """
    seen: set[str] = set()

    # Phase 0: local host
    local_ip, local_mac = _darwin_local_ip_and_mac()
    try:
        if (
            local_ip
            and local_mac
            and ipaddress.ip_address(local_ip) in network
            and local_mac != "00:00:00:00:00:00"
        ):
            key = f"{local_ip}|{local_mac}"
            seen.add(key)
            yield {"ip": local_ip, "mac": local_mac, "vendor": lookup_vendor(local_mac)}
    except ValueError:
        pass

    # Phase 1: existing ARP entries
    arp_initial = _read_arp_table()
    for ip, mac in arp_initial.items():
        try:
            if ipaddress.ip_address(ip) not in network:
                continue
        except ValueError:
            continue
        if not mac:
            continue
        key = f"{ip}|{mac}"
        if key not in seen:
            seen.add(key)
            yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}

    # Phase 2: parallel ping sweep (ThreadPoolExecutor, max 50 workers)
    alive_ips: set[str] = set()
    max_workers = min(50, max(1, len(hosts)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_darwin_ping_once, ip) for ip in hosts]
        for fut in as_completed(futures):
            try:
                ip, ok = fut.result()
                if ok:
                    alive_ips.add(ip)
            except Exception:
                pass

    # Phase 3: ARP after ping
    arp_after_ping = _read_arp_table()
    for ip, mac in arp_after_ping.items():
        try:
            if ipaddress.ip_address(ip) not in network:
                continue
        except ValueError:
            continue
        if not mac:
            continue
        key = f"{ip}|{mac}"
        if key not in seen:
            seen.add(key)
            yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}

    for ip in alive_ips:
        if _seen_has_ip(seen, ip):
            continue
        mac = arp_after_ping.get(ip, "")
        if mac:
            mac = _normalize_mac(mac)
            key = f"{ip}|{mac}"
            if key not in seen:
                seen.add(key)
                yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}
        else:
            key = f"{ip}|"
            if key not in seen:
                seen.add(key)
                yield {"ip": ip, "mac": "", "vendor": "Unknown"}

    # Phase 4: TCP fallback on 80, 443, 22, 445
    tcp_candidates = [
        ip for ip in hosts if ip not in alive_ips and not _seen_has_ip(seen, ip)
    ]
    tcp_alive: set[str] = set()
    if tcp_candidates:
        tw = min(50, max(1, len(tcp_candidates)))

        def _tcp_probe(ip: str) -> tuple[str, bool]:
            return (ip, _darwin_tcp_any_port_open(ip))

        with ThreadPoolExecutor(max_workers=tw) as pool:
            futures = [pool.submit(_tcp_probe, ip) for ip in tcp_candidates]
            for fut in as_completed(futures):
                try:
                    ip, ok = fut.result()
                    if ok:
                        tcp_alive.add(ip)
                except Exception:
                    pass

    arp_final = _read_arp_table()
    for ip in tcp_alive:
        if _seen_has_ip(seen, ip):
            continue
        mac = arp_final.get(ip, "")
        if mac:
            mac = _normalize_mac(mac)
            key = f"{ip}|{mac}"
            if key not in seen:
                seen.add(key)
                yield {"ip": ip, "mac": mac, "vendor": lookup_vendor(mac)}
        else:
            key = f"{ip}|"
            if key not in seen:
                seen.add(key)
                yield {"ip": ip, "mac": "", "vendor": "Unknown"}


def scan_network(cidr: str) -> Generator[dict, None, None]:
    """
    Network scan using ping sweep + ARP table read.

    On macOS (Darwin), uses /sbin/ping, ARP, and TCP fallback — see _scan_network_macos.
    On Windows/Linux, uses the original multi-phase ping + ARP path.

    Yields: {"ip": str, "mac": str, "vendor": str}
    """
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(h) for h in network.hosts()]

    if not hosts:
        return

    if sys.platform == "darwin":
        yield from _scan_network_macos(network, hosts)
        return

    # --- Windows and Linux (unchanged strategy vs. prior Windows-focused path) ---
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

    # Phase 2b: Extra pings for ping-silent devices (ARP cache population)
    if sys.platform == "win32":
        _windows_arp_probe(hosts, alive_ips)
    else:
        _unix_arp_probe(hosts, alive_ips)

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

    # Phase 4: Alive hosts not yet in ARP table
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
        else:
            key = f"{ip}|"
            if key not in seen:
                seen.add(key)
                yield {"ip": ip, "mac": "", "vendor": "Unknown"}
