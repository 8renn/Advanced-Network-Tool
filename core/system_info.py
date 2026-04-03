"""Collect local network identity, default-route adapter details, and optional speed tests."""

from __future__ import annotations

import ipaddress
import json
import math
import re
import shutil
import socket
import ssl
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import logger
from core.runtime_paths import resource_path

USER_AGENT = "Advanced-IP-Scanner/1.0 (System Info)"
PUBLIC_IP_URL = "https://api.ipify.org?format=json"
PUBLIC_IP_TIMEOUT = 6.0
# Google speed test endpoints
# dl.google.com hosts large files for Chrome/Android; stable URLs, global CDN.
_GOOGLE_DOWNLOAD_URLS = [
    "https://dl.google.com/dl/android/studio/install/2024.2.1.11/android-studio-2024.2.1.11-windows.exe",
    "https://dl.google.com/chrome/install/ChromeStandaloneSetup64.exe",
]
_GOOGLE_DOWNLOAD_BYTES = 50_000_000  # Read up to 50MB for accurate measurement on fast connections
_GOOGLE_LATENCY_HOST = "8.8.8.8"
_GOOGLE_LATENCY_PORT = 443
GOOGLE_TEST_TIMEOUT = 60.0


@dataclass
class SpeedTestPanel:
    """One provider's speed/latency metrics for UI display."""

    download: str = "Unavailable"
    upload: str = "Unavailable"
    latency: str = "Unavailable"
    jitter: str = "Unavailable"
    status: str = "Unavailable"  # Completed | Failed | Not Installed | Unavailable


@dataclass
class SystemInfoSnapshot:
    hostname: str = "Unavailable"
    primary_local_ipv4: str = "Unavailable"
    subnet_mask: str = "Unavailable"
    default_gateway: str = "Unavailable"
    mac_address: str = "Unavailable"
    public_ip: str = "Unavailable"
    adapter_name: str = "Unavailable"
    adapter_ipv4: str = "Unavailable"
    ookla: SpeedTestPanel = field(default_factory=SpeedTestPanel)
    google: SpeedTestPanel = field(default_factory=SpeedTestPanel)
    error: str = ""


def _subprocess_no_window_kwargs() -> dict[str, Any]:
    if sys.platform == "win32":
        kwargs: dict[str, Any] = {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        }
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
        return kwargs
    return {}


def _run_ps_json(script: str) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
        out = (proc.stdout or "").strip()
        if not out or proc.returncode != 0:
            return None
        return json.loads(out)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _windows_default_route_adapter() -> dict[str, str] | None:
    """Resolve the IPv4 default route and matching adapter (Windows / PowerShell)."""
    script = r"""
$ErrorActionPreference = 'Stop'
try {
  $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue
  if (-not $routes) { throw 'no default route' }
  $picked = $routes | Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
  $ifIndex = $picked.InterfaceIndex
  $gw = $picked.NextHop
  $ips = @(Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -and $_.IPAddress -notlike '169.254.*' })
  $ipObj = $ips | Sort-Object SkipAsSource, IPAddress | Select-Object -First 1
  if (-not $ipObj) { throw 'no ipv4 on if' }
  $adapter = Get-NetAdapter -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue
  $mac = if ($adapter) { $adapter.MacAddress } else { '' }
  $name = if ($adapter) { $adapter.Name } else { '' }
  [PSCustomObject]@{
    Gateway     = [string]$gw
    IPv4        = [string]$ipObj.IPAddress
    PrefixLength= [int]$ipObj.PrefixLength
    IfIndex     = [int]$ifIndex
    AdapterName = [string]$name
    MAC         = [string]$mac
  } | ConvertTo-Json -Compress
} catch {
  [PSCustomObject]@{ Error = $_.Exception.Message } | ConvertTo-Json -Compress
}
""".strip()
    data = _run_ps_json(script)
    if not data or data.get("Error"):
        return None
    try:
        prefix = int(data["PrefixLength"])
        mask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}", strict=False).netmask)
    except (KeyError, ValueError, ipaddress.AddressValueError):
        mask = "Unavailable"
    gw = str(data.get("Gateway") or "").strip()
    ipv4 = str(data.get("IPv4") or "").strip()
    name = str(data.get("AdapterName") or "").strip()
    mac = str(data.get("MAC") or "").strip()
    if not gw or not ipv4:
        return None
    return {
        "gateway": gw,
        "ipv4": ipv4,
        "mask": mask,
        "adapter_name": name or "Unavailable",
        "mac": mac or "Unavailable",
    }


def _fallback_connect_local_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def _linux_default_route_adapter() -> dict[str, str] | None:
    try:
        proc = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            return None
        first = line[0]
        m_dev = re.search(r"\bdev\s+(\S+)", first)
        m_via = re.search(r"\bvia\s+(\d+\.\d+\.\d+\.\d+)", first)
        if not m_dev:
            return None
        dev = m_dev.group(1)
        gw = m_via.group(1) if m_via else "Unavailable"
        proc2 = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", dev],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        out = proc2.stdout or ""
        m_ip = re.search(
            r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s",
            out,
        )
        if not m_ip:
            return None
        ipv4 = m_ip.group(1)
        prefix = int(m_ip.group(2))
        mask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}", strict=False).netmask)
        mac = "Unavailable"
        proc3 = subprocess.run(
            ["cat", f"/sys/class/net/{dev}/address"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc3.returncode == 0 and proc3.stdout.strip():
            mac = proc3.stdout.strip().replace(":", "-").upper()
        return {
            "gateway": gw,
            "ipv4": ipv4,
            "mask": mask,
            "adapter_name": dev,
            "mac": mac,
        }
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _darwin_default_route_adapter() -> dict[str, str] | None:
    try:
        proc = subprocess.run(
            ["route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        out = proc.stdout or ""
        m_if = re.search(r"interface:\s*(\S+)", out)
        m_gw = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", out)
        if not m_if:
            return None
        dev = m_if.group(1)
        gw = m_gw.group(1) if m_gw else "Unavailable"
        proc2 = subprocess.run(
            ["ifconfig", dev],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        txt = proc2.stdout or ""
        m_inet = re.search(
            r"inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+0x([0-9a-fA-F]+)",
            txt,
        )
        ipv4: str
        mask: str
        if m_inet:
            ipv4 = m_inet.group(1)
            nm_int = int(m_inet.group(2), 16)
            mask = str(ipaddress.IPv4Address(nm_int))
        else:
            m_dotted = re.search(
                r"inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(\d+\.\d+\.\d+\.\d+)",
                txt,
            )
            if not m_dotted:
                return None
            ipv4 = m_dotted.group(1)
            mask = m_dotted.group(2)
        mac = "Unavailable"
        m_mac = re.search(r"ether\s+([0-9a-fA-F:]+)", txt)
        if m_mac:
            mac = m_mac.group(1).replace(":", "-").upper()
        return {
            "gateway": gw,
            "ipv4": ipv4,
            "mask": mask,
            "adapter_name": dev,
            "mac": mac,
        }
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def collect_local_network() -> dict[str, str]:
    """Return flat keys: hostname, primary_local_ipv4, subnet_mask, default_gateway, mac_address, adapter_name, adapter_ipv4."""
    hn = socket.gethostname() or "Unavailable"
    result = {
        "hostname": hn,
        "primary_local_ipv4": "Unavailable",
        "subnet_mask": "Unavailable",
        "default_gateway": "Unavailable",
        "mac_address": "Unavailable",
        "public_ip": "Unavailable",
        "adapter_name": "Unavailable",
        "adapter_ipv4": "Unavailable",
    }
    info: dict[str, str] | None = None
    if sys.platform == "win32":
        info = _windows_default_route_adapter()
    elif sys.platform == "linux":
        info = _linux_default_route_adapter()
    elif sys.platform == "darwin":
        info = _darwin_default_route_adapter()

    if info:
        result["primary_local_ipv4"] = info["ipv4"]
        result["adapter_ipv4"] = info["ipv4"]
        result["subnet_mask"] = info["mask"]
        result["default_gateway"] = info["gateway"]
        result["mac_address"] = info["mac"]
        result["adapter_name"] = info["adapter_name"]
    else:
        lip = _fallback_connect_local_ip()
        if lip:
            result["primary_local_ipv4"] = lip
            result["adapter_ipv4"] = lip
            result["subnet_mask"] = "Unavailable"
            result["default_gateway"] = "Unavailable"
            result["adapter_name"] = "Unavailable"
            result["mac_address"] = "Unavailable"
    return result


def fetch_public_ip() -> str:
    """Return public IPv4 string or 'Unavailable'. Never raises."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        PUBLIC_IP_URL,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            req, timeout=PUBLIC_IP_TIMEOUT, context=ctx
        ) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        ip = str(data.get("ip") or "").strip()
        if ip and re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
            return ip
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TypeError):
        pass
    return "Unavailable"


def _jitter_from_ms(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    diffs = [abs(samples[i] - samples[i - 1]) for i in range(1, len(samples))]
    return sum(diffs) / len(diffs)


def _format_mbps(bits_per_sec: float) -> str:
    if bits_per_sec <= 0 or math.isnan(bits_per_sec):
        return "Unavailable"
    mbps = bits_per_sec / 1_000_000
    if mbps >= 100:
        return f"{mbps:.0f} Mbps"
    if mbps >= 10:
        return f"{mbps:.1f} Mbps"
    return f"{mbps:.2f} Mbps"


def _find_speedtest_exe() -> str | None:
    """Find the bundled or installed speedtest CLI executable."""
    if sys.platform == "darwin":
        # macOS: Unix CLI `speedtest` + optional assets/speedtest bundle
        bundled_unix = resource_path("assets/speedtest")
        if bundled_unix.is_file():
            return str(bundled_unix)
        project_unix = Path(__file__).resolve().parents[1] / "assets" / "speedtest"
        if project_unix.is_file():
            return str(project_unix)
        found = shutil.which("speedtest")
        if found:
            return found
        return None

    # Check bundled location first (assets/speedtest.exe)
    bundled = resource_path("assets/speedtest.exe")
    if bundled.exists():
        return str(bundled)

    # Check project assets folder (dev mode)
    project_assets = Path(__file__).resolve().parents[1] / "assets" / "speedtest.exe"
    if project_assets.exists():
        return str(project_assets)

    # Check PATH
    found = shutil.which("speedtest.exe") or shutil.which("speedtest")
    if found:
        return found

    return None


def run_ookla_speedtest() -> SpeedTestPanel:
    """
    Run Ookla Speedtest CLI and parse JSON output.
    Returns accurate download, upload, latency, and jitter.
    """
    panel = SpeedTestPanel(status="Failed")

    exe = _find_speedtest_exe()
    if exe is None:
        logger.debug("Ookla: speedtest.exe not found")
        panel.status = "Not Installed"
        return panel

    try:
        result = subprocess.run(
            [exe, "--accept-license", "--accept-gdpr", "-f", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
    except FileNotFoundError:
        panel.status = "Not Installed"
        return panel
    except subprocess.TimeoutExpired:
        panel.status = "Failed"
        return panel

    stdout = (result.stdout or "").strip()
    if not stdout:
        logger.debug("Ookla: empty output, stderr=%s", (result.stderr or "")[:400])
        panel.status = "Failed"
        return panel

    # Parse JSON — Ookla CLI may output JSONL (one object per line), last type==result wins
    data: dict[str, Any] | None = None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # Try JSONL format
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    if obj.get("type") == "result" or "download" in obj:
                        data = obj
                        break
            except json.JSONDecodeError:
                continue

    if not data:
        logger.debug("Ookla: no parseable JSON output")
        panel.status = "Failed"
        return panel

    # Parse download (bits per second or nested dict)
    dl_raw = data.get("download")
    if isinstance(dl_raw, dict):
        dl_bps = float(dl_raw.get("bandwidth", 0)) * 8  # bandwidth is bytes/sec
    elif isinstance(dl_raw, (int, float)):
        dl_bps = float(dl_raw)
    else:
        dl_bps = 0.0
    if dl_bps > 0:
        panel.download = _format_mbps(dl_bps)

    # Parse upload
    ul_raw = data.get("upload")
    if isinstance(ul_raw, dict):
        ul_bps = float(ul_raw.get("bandwidth", 0)) * 8
    elif isinstance(ul_raw, (int, float)):
        ul_bps = float(ul_raw)
    else:
        ul_bps = 0.0
    if ul_bps > 0:
        panel.upload = _format_mbps(ul_bps)

    # Parse latency
    ping_raw = data.get("ping")
    if isinstance(ping_raw, dict):
        lat = ping_raw.get("latency")
        jit = ping_raw.get("jitter")
    elif isinstance(ping_raw, (int, float)):
        lat = float(ping_raw)
        jit = data.get("jitter")
    else:
        lat = None
        jit = None

    if lat is not None:
        panel.latency = f"{float(lat):.1f} ms"
    if jit is not None:
        panel.jitter = f"{float(jit):.2f} ms"

    if panel.download != "Unavailable" or panel.upload != "Unavailable":
        panel.status = "Completed"

    return panel


def _has_curl() -> bool:
    """Check if curl is available on the system."""
    try:
        curl_cmd = "curl.exe" if sys.platform == "win32" else "curl"
        result = subprocess.run(
            [curl_cmd, "--version"],
            capture_output=True,
            timeout=5,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _curl_download_speed(url: str, duration: float = 6.0) -> float:
    """
    Measure download speed using curl. Returns bits per second.
    """
    try:
        curl_cmd = "curl.exe" if sys.platform == "win32" else "curl"
        cmd = [
            curl_cmd,
            "--silent",
            "--output",
            "NUL" if sys.platform == "win32" else "/dev/null",
            "--max-time",
            str(int(duration)),
            "--write-out",
            "%{size_download}",
            url,
        ]
        t0 = time.perf_counter()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=duration + 10,
            check=False,
            **_subprocess_no_window_kwargs(),
        )
        elapsed = time.perf_counter() - t0
        output = (result.stdout or "").strip()
        if output and elapsed > 0.1:
            downloaded = float(output)
            if downloaded > 0:
                return (downloaded * 8) / elapsed
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        logger.debug("curl download speed failed: %s", e)
    return 0.0


def run_google_speedtest() -> SpeedTestPanel:
    """
    Measure download speed from Google's CDN and latency to Google DNS.
    Uses curl for download when available, urllib fallback; TCP connect for latency.
    """
    panel = SpeedTestPanel(status="Failed")
    ctx = ssl.create_default_context()

    # --- Latency & Jitter (TCP connect to Google DNS on port 443) ---
    lat_samples: list[float] = []
    try:
        for _ in range(15):
            t0 = time.perf_counter()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            try:
                s.connect((_GOOGLE_LATENCY_HOST, _GOOGLE_LATENCY_PORT))
                lat_samples.append((time.perf_counter() - t0) * 1000.0)
            finally:
                s.close()
            time.sleep(0.05)
    except (OSError, socket.timeout) as e:
        logger.debug("Google latency probe failed: %s", e)

    if len(lat_samples) >= 3:
        med_lat = statistics.median(lat_samples)
        jit = _jitter_from_ms(lat_samples)
        panel.latency = f"{med_lat:.1f} ms"
        panel.jitter = f"{jit:.2f} ms"

    # --- Download (curl for accuracy, urllib fallback) ---
    use_curl = _has_curl()
    if use_curl:
        for url in _GOOGLE_DOWNLOAD_URLS:
            dl_bps = _curl_download_speed(url, duration=8.0)
            if dl_bps > 0:
                panel.download = _format_mbps(dl_bps)
                break
        else:
            panel.download = "Unavailable"
    else:
        for url in _GOOGLE_DOWNLOAD_URLS:
            try:
                headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
                req = urllib.request.Request(url, headers=headers, method="GET")
                t0 = time.perf_counter()
                total_bytes = 0
                with urllib.request.urlopen(req, timeout=GOOGLE_TEST_TIMEOUT, context=ctx) as resp:
                    while total_bytes < _GOOGLE_DOWNLOAD_BYTES:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                elapsed = time.perf_counter() - t0
                if elapsed > 0.1 and total_bytes > 500_000:
                    panel.download = _format_mbps((total_bytes * 8) / elapsed)
                    break
            except (urllib.error.URLError, OSError) as e:
                logger.debug("Google download from %s failed: %s", url, e)
                continue

    panel.upload = "N/A"

    if panel.download != "Unavailable" or panel.latency != "Unavailable":
        panel.status = "Completed"
    else:
        panel.status = "Failed"
    return panel


def collect_full_snapshot(
    *,
    include_speedtests: bool = True,
) -> SystemInfoSnapshot:
    snap = SystemInfoSnapshot()
    try:
        net = collect_local_network()
        snap.hostname = net["hostname"]
        snap.primary_local_ipv4 = net["primary_local_ipv4"]
        snap.subnet_mask = net["subnet_mask"]
        snap.default_gateway = net["default_gateway"]
        snap.mac_address = net["mac_address"]
        snap.adapter_name = net["adapter_name"]
        snap.adapter_ipv4 = net["adapter_ipv4"]
    except OSError:
        snap.error = "Local network collection failed."

    try:
        snap.public_ip = fetch_public_ip()
    except OSError:
        snap.public_ip = "Unavailable"

    if include_speedtests:
        try:
            snap.ookla = run_ookla_speedtest()
        except Exception:
            snap.ookla = SpeedTestPanel(status="Failed")
        try:
            snap.google = run_google_speedtest()
        except Exception:
            snap.google = SpeedTestPanel(status="Failed")

    return snap


def snapshot_to_dict(s: SystemInfoSnapshot) -> dict[str, Any]:
    return {
        "hostname": s.hostname,
        "primary_local_ipv4": s.primary_local_ipv4,
        "subnet_mask": s.subnet_mask,
        "default_gateway": s.default_gateway,
        "mac_address": s.mac_address,
        "public_ip": s.public_ip,
        "adapter_name": s.adapter_name,
        "adapter_ipv4": s.adapter_ipv4,
        "ookla": {
            "download": s.ookla.download,
            "upload": s.ookla.upload,
            "latency": s.ookla.latency,
            "jitter": s.ookla.jitter,
            "status": s.ookla.status,
        },
        "google": {
            "download": s.google.download,
            "upload": s.google.upload,
            "latency": s.google.latency,
            "jitter": s.google.jitter,
            "status": s.google.status,
        },
        "error": s.error,
    }
