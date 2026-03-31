"""Collect local network identity, default-route adapter details, and optional speed tests."""

from __future__ import annotations

import ipaddress
import json
import math
import os
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
from typing import Any

from core.logger import logger

USER_AGENT = "Advanced-IP-Scanner/1.0 (System Info)"
CF_DOWN = "https://speed.cloudflare.com/__down"
CF_UP = "https://speed.cloudflare.com/__up"
PUBLIC_IP_URL = "https://api.ipify.org?format=json"
PUBLIC_IP_TIMEOUT = 6.0
# Cloudflare rejects some large ?bytes= values with HTTP 403; stay under ~11–12M.
_CF_DOWNLOAD_BYTE_CANDIDATES = (10_485_760, 8_000_000, 5_000_000, 2_500_000, 1_000_000)
CF_TEST_TIMEOUT = 90.0
OOKLA_TIMEOUT = 180.0

_CF_REQ_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "identity",
}


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
    cloudflare: SpeedTestPanel = field(default_factory=SpeedTestPanel)
    ookla: SpeedTestPanel = field(default_factory=SpeedTestPanel)
    error: str = ""


def _subprocess_no_window_kwargs() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
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
        if not m_inet:
            return None
        ipv4 = m_inet.group(1)
        nm_int = int(m_inet.group(2), 16)
        mask = str(ipaddress.IPv4Address(nm_int))
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


def _cf_download_bytes(ctx: ssl.SSLContext, byte_size: int) -> tuple[float, int]:
    """Return (elapsed_seconds, total_bytes_read). Raises on HTTP/network errors."""
    url = f"{CF_DOWN}?bytes={byte_size}"
    t0 = time.perf_counter()
    req = urllib.request.Request(
        url,
        headers=dict(_CF_REQ_HEADERS),
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=CF_TEST_TIMEOUT, context=ctx) as resp:
        total = 0
        chunk = 256 * 1024
        while True:
            block = resp.read(chunk)
            if not block:
                break
            total += len(block)
    return time.perf_counter() - t0, total


def run_cloudflare_speedtest() -> SpeedTestPanel:
    """
    Measure against Cloudflare's public __down / __up endpoints (same hosts as speed.cloudflare.com).
    Large ?bytes= values can return HTTP 403; we try several sizes under Cloudflare's cap.
    """
    panel = SpeedTestPanel(status="Failed")
    ctx = ssl.create_default_context()
    lat_samples: list[float] = []

    try:
        for _ in range(18):
            url = f"{CF_DOWN}?bytes=0"
            t0 = time.perf_counter()
            req = urllib.request.Request(
                url,
                headers=dict(_CF_REQ_HEADERS),
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                resp.read()
            lat_samples.append((time.perf_counter() - t0) * 1000.0)
    except (urllib.error.URLError, OSError) as e:
        logger.debug("Cloudflare latency probe failed: %s", e)
        panel.status = "Unavailable"
        return panel

    if len(lat_samples) < 3:
        panel.status = "Failed"
        return panel

    med_lat = statistics.median(lat_samples)
    jit = _jitter_from_ms(lat_samples)
    panel.latency = f"{med_lat:.1f} ms"
    panel.jitter = f"{jit:.2f} ms"

    dl_bps = 0.0
    last_dl_err: str | None = None
    for byte_size in _CF_DOWNLOAD_BYTE_CANDIDATES:
        try:
            elapsed, total = _cf_download_bytes(ctx, byte_size)
            if elapsed > 0.05 and total > 0:
                dl_bps = (total * 8) / elapsed
                panel.download = _format_mbps(dl_bps)
                break
        except urllib.error.HTTPError as e:
            last_dl_err = f"HTTP {e.code}"
            logger.debug(
                "Cloudflare download bytes=%s failed: HTTP %s", byte_size, e.code
            )
            if e.code == 403:
                continue
            panel.download = "Unavailable"
            break
        except (urllib.error.URLError, OSError) as e:
            last_dl_err = str(e)
            logger.debug("Cloudflare download bytes=%s failed: %s", byte_size, e)
            panel.download = "Unavailable"
            break
    else:
        if last_dl_err:
            logger.debug("Cloudflare download exhausted sizes; last error: %s", last_dl_err)
        panel.download = "Unavailable"

    ul_bps = 0.0
    try:
        ubytes = 5_000_000
        body = b"\x00" * ubytes
        t0 = time.perf_counter()
        headers = dict(_CF_REQ_HEADERS)
        headers["Content-Type"] = "application/octet-stream"
        req = urllib.request.Request(
            CF_UP,
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=CF_TEST_TIMEOUT, context=ctx) as resp:
            resp.read()
        elapsed = time.perf_counter() - t0
        if elapsed > 0.05:
            ul_bps = (len(body) * 8) / elapsed
        panel.upload = _format_mbps(ul_bps)
    except (urllib.error.URLError, OSError) as e:
        logger.debug("Cloudflare upload failed: %s", e)
        panel.upload = "Unavailable"

    if (
        panel.download != "Unavailable"
        or panel.upload != "Unavailable"
        or panel.latency != "Unavailable"
    ):
        panel.status = "Completed"
    else:
        panel.status = "Failed"
    return panel


def _bps_from_ookla_download_field(raw: Any) -> float:
    """Ookla nested objects use bandwidth in bytes/sec; speedtest-cli uses bits/sec at top level."""
    if isinstance(raw, dict):
        bw = raw.get("bandwidth")
        if isinstance(bw, (int, float)) and bw > 0:
            return float(bw) * 8.0
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return 0.0


def _parse_ookla_dict(data: dict[str, Any]) -> SpeedTestPanel | None:
    if not isinstance(data, dict):
        return None

    d_bps = _bps_from_ookla_download_field(data.get("download"))
    u_bps = _bps_from_ookla_download_field(data.get("upload"))

    ping_raw = data.get("ping")
    lat: float | None = None
    jit: float | None = None
    if isinstance(ping_raw, dict):
        if isinstance(ping_raw.get("latency"), (int, float)):
            lat = float(ping_raw["latency"])
        if isinstance(ping_raw.get("jitter"), (int, float)):
            jit = float(ping_raw["jitter"])
    elif isinstance(ping_raw, (int, float)):
        lat = float(ping_raw)
    if jit is None and isinstance(data.get("jitter"), (int, float)):
        jit = float(data["jitter"])

    panel = SpeedTestPanel(status="Completed")
    panel.download = _format_mbps(d_bps) if d_bps > 0 else "Unavailable"
    panel.upload = _format_mbps(u_bps) if u_bps > 0 else "Unavailable"
    panel.latency = f"{lat:.1f} ms" if lat is not None else "Unavailable"
    panel.jitter = f"{jit:.2f} ms" if jit is not None else "Unavailable"
    return panel


def _parse_ookla_stdout(stdout: str, stderr: str) -> SpeedTestPanel | None:
    """Official Ookla CLI often prints JSONL (one object per line); last `type==result` wins."""
    text = (stdout or "").strip()
    if not text:
        logger.debug("Ookla CLI empty stdout; stderr=%s", (stderr or "")[:400])
        return None

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            parsed = _parse_ookla_dict(data)
            if parsed:
                return parsed
    except json.JSONDecodeError:
        pass

    result_line: dict[str, Any] | None = None
    last_obj: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
            if obj.get("type") == "result":
                result_line = obj
    if result_line is not None:
        return _parse_ookla_dict(result_line)
    if last_obj is not None and (
        "download" in last_obj or "upload" in last_obj or "ping" in last_obj
    ):
        return _parse_ookla_dict(last_obj)
    return None


def _ookla_official_candidates() -> list[str]:
    """PATH + common Windows install locations for Ookla Speedtest CLI."""
    ordered: list[str] = []
    seen: set[str] = set()
    for name in ("speedtest.exe", "speedtest"):
        found = shutil.which(name)
        if found and os.path.isfile(found):
            key = os.path.normcase(os.path.abspath(found))
            if key not in seen:
                seen.add(key)
                ordered.append(found)
    if sys.platform == "win32":
        for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env_key)
            if not base:
                continue
            for tail in (
                os.path.join(base, "Speedtest", "speedtest.exe"),
                os.path.join(base, "Ookla Speedtest", "speedtest.exe"),
            ):
                if os.path.isfile(tail):
                    key = os.path.normcase(os.path.abspath(tail))
                    if key not in seen:
                        seen.add(key)
                        ordered.append(tail)
    return ordered


def _run_speedtest_executable(exe: str) -> SpeedTestPanel | None:
    """
    Run either Ookla Speedtest CLI (-f json + license flags) or speedtest-cli (--json).
    Pip installs often expose `speedtest.exe` that only supports the latter.
    """
    variants = (
        ["--accept-license", "--accept-gdpr", "-f", "json"],
        ["--json"],
    )
    last_failure: SpeedTestPanel | None = None
    for argv_suffix in variants:
        try:
            proc = subprocess.run(
                [exe, *argv_suffix],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=OOKLA_TIMEOUT,
                check=False,
                **_subprocess_no_window_kwargs(),
            )
        except FileNotFoundError:
            logger.debug("Speedtest executable missing at path: %s", exe)
            return None
        except subprocess.TimeoutExpired:
            logger.debug("Speedtest CLI timed out: %s", exe)
            return SpeedTestPanel(status="Failed")

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            logger.debug(
                "Speedtest %s %s rc=%s stderr=%s",
                exe,
                argv_suffix[0],
                proc.returncode,
                err[:600] if err else "(empty)",
            )

        win_missing = sys.platform == "win32" and proc.returncode == 9009
        if win_missing or (
            proc.returncode != 0
            and "not recognized" in ((err + out).lower())
            and not out
        ):
            return None

        parsed = _parse_ookla_stdout(out, err)
        if parsed:
            parsed.status = "Completed"
            return parsed

        if err and ("403" in err or "Forbidden" in err):
            logger.debug("Speedtest blocked or forbidden (403): %s", exe)
            return SpeedTestPanel(status="Unavailable")

        if out or proc.returncode != 0:
            last_failure = SpeedTestPanel(status="Failed")

    if last_failure is not None:
        logger.debug(
            "No parseable JSON from %s after trying Ookla and speedtest-cli modes",
            exe,
        )
        return last_failure
    return SpeedTestPanel(status="Failed")


def run_ookla_speedtest() -> SpeedTestPanel:
    """Ookla Speedtest CLI and/or speedtest-cli (JSON or JSONL), via PATH and common paths."""
    missing = SpeedTestPanel(status="Not Installed")

    for exe in _ookla_official_candidates():
        result = _run_speedtest_executable(exe)
        if result is not None:
            return result

    for cli in filter(
        None,
        (shutil.which("speedtest-cli"), shutil.which("speedtest-cli.exe")),
    ):
        result = _run_speedtest_executable(cli)
        if result is not None:
            return result

    logger.debug("No speedtest / speedtest.exe / speedtest-cli found")
    return missing


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
            snap.cloudflare = run_cloudflare_speedtest()
        except Exception:
            snap.cloudflare = SpeedTestPanel(status="Failed")
        try:
            snap.ookla = run_ookla_speedtest()
        except Exception:
            snap.ookla = SpeedTestPanel(status="Failed")

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
        "cloudflare": {
            "download": s.cloudflare.download,
            "upload": s.cloudflare.upload,
            "latency": s.cloudflare.latency,
            "jitter": s.cloudflare.jitter,
            "status": s.cloudflare.status,
        },
        "ookla": {
            "download": s.ookla.download,
            "upload": s.ookla.upload,
            "latency": s.ookla.latency,
            "jitter": s.ookla.jitter,
            "status": s.ookla.status,
        },
        "error": s.error,
    }
