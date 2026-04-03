"""Windows tracert subprocess runner with line-by-line hop parsing."""

from __future__ import annotations

import locale
import re
import subprocess
import sys
import threading

from PySide6.QtCore import QThread, Signal

# Windows tracert hop line: hop + three latency columns + tail (IP or timeout text).
_LATENCY = r"(?:\*|<\d+\s*ms|\d+\s+ms)"
_HOP_LINE_RE = re.compile(
    rf"^\s*(\d+)\s+({_LATENCY})\s+({_LATENCY})\s+({_LATENCY})\s+(.+?)\s*$",
    re.IGNORECASE,
)
_IP_IN_BRACKETS_RE = re.compile(r"\[(\d{1,3}(?:\.\d{1,3}){3})\]\s*$")
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_TRACING_BRACKET_RE = re.compile(
    r"Tracing\s+route\s+to\s+.+\[(\d{1,3}(?:\.\d{1,3}){3})\]",
    re.IGNORECASE,
)
_TRACING_TO_IPV4_RE = re.compile(
    r"Tracing\s+route\s+to\s+(\d{1,3}(?:\.\d{1,3}){3})\b",
    re.IGNORECASE,
)
_UNRESOLVABLE_SNIP = "unable to resolve target system name"

# macOS: BSD traceroute -n hop lines (three probes, milliseconds).
_DARWIN_TIMEOUT_LINE_RE = re.compile(r"^\s*(\d+)\s+\*\s+\*\s+\*\s*$")
_DARWIN_HOP_LINE_RE = re.compile(
    r"^\s*(\d+)\s+(\S+)\s+"
    r"(\d+(?:\.\d+)?)\s+ms\s+"
    r"(\*|\d+(?:\.\d+)?)\s+ms\s+"
    r"(\*|\d+(?:\.\d+)?)\s+ms\s*$"
)
_DARWIN_TRACE_DEST_PARENS_RE = re.compile(
    r"traceroute\s+to\s+[^\s(]+\s+\((\d{1,3}(?:\.\d{1,3}){3})\)",
    re.IGNORECASE,
)
_DARWIN_TRACE_DEST_IP_RE = re.compile(
    r"traceroute\s+to\s+(\d{1,3}(?:\.\d{1,3}){3})\b",
    re.IGNORECASE,
)


def _parse_hop_line(line: str) -> dict | None:
    raw = (line or "").strip()
    if not raw:
        return None
    m = _HOP_LINE_RE.match(raw)
    if not m:
        return None
    hop = int(m.group(1))
    latency_1 = m.group(2).strip()
    latency_2 = m.group(3).strip()
    latency_3 = m.group(4).strip()
    tail = m.group(5).strip()

    if latency_1 == "*" and latency_2 == "*" and latency_3 == "*":
        return {
            "hop": hop,
            "hostname": "-",
            "ip": "-",
            "latency_1": "*",
            "latency_2": "*",
            "latency_3": "*",
        }

    hostname = ""
    ip = ""
    bm = _IP_IN_BRACKETS_RE.search(tail)
    if bm:
        ip = bm.group(1)
        hostname = tail[: bm.start()].strip()
    elif _IPV4_RE.fullmatch(tail):
        ip = tail
        hostname = ""
    else:
        ip = tail
        hostname = ""

    return {
        "hop": hop,
        "hostname": hostname,
        "ip": ip,
        "latency_1": latency_1,
        "latency_2": latency_2,
        "latency_3": latency_3,
    }


def _parse_darwin_hop_line(line: str) -> dict | None:
    # macOS: map BSD traceroute output to the same hop dict shape as Windows tracert.
    raw = (line or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("traceroute to"):
        return None

    m_timeout = _DARWIN_TIMEOUT_LINE_RE.match(raw)
    if m_timeout:
        hop = int(m_timeout.group(1))
        return {
            "hop": hop,
            "hostname": "-",
            "ip": "-",
            "latency_1": "*",
            "latency_2": "*",
            "latency_3": "*",
        }

    m = _DARWIN_HOP_LINE_RE.match(raw)
    if not m:
        return None
    hop = int(m.group(1))
    addr = m.group(2).strip()
    lat1_raw, lat2_raw, lat3_raw = m.group(3), m.group(4), m.group(5)

    def _fmt_lat(part: str) -> str:
        return "*" if part == "*" else f"{part} ms"

    lat1 = _fmt_lat(lat1_raw)
    lat2 = _fmt_lat(lat2_raw)
    lat3 = _fmt_lat(lat3_raw)

    if _IPV4_RE.fullmatch(addr):
        return {
            "hop": hop,
            "hostname": "",
            "ip": addr,
            "latency_1": lat1,
            "latency_2": lat2,
            "latency_3": lat3,
        }
    return {
        "hop": hop,
        "hostname": addr,
        "ip": addr,
        "latency_1": lat1,
        "latency_2": lat2,
        "latency_3": lat3,
    }


class TracerouteWorker(QThread):
    hop_signal = Signal(dict)
    finished_signal = Signal(str)

    def __init__(self, target: str, parent=None) -> None:
        super().__init__(parent)
        self._target = (target or "").strip()
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True
        with self._proc_lock:
            proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _finalize_message(
        self,
        *,
        resolved: bool,
        reached_destination: bool,
        hop_events: list[str],
    ) -> str:
        if not resolved:
            return "Unable to resolve target system name."
        if reached_destination:
            return "Trace complete."
        trailing = 0
        for h in reversed(hop_events):
            if h == "timeout":
                trailing += 1
            else:
                break
        if trailing >= 2:
            return "Request timed out."
        return "Unable to reach target."

    def _run_tracert_windows(self, target: str) -> None:
        popen_kwargs: dict = {
            "args": ["tracert", target],
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": locale.getpreferredencoding(False) or "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.Popen(**popen_kwargs)
        except Exception:
            self.finished_signal.emit("Unable to reach target.")
            return

        with self._proc_lock:
            self._proc = proc

        resolved = True
        reached_destination = False
        trace_reported_complete = False
        hop_events: list[str] = []
        dest_ip: str | None = None
        last_ok_ip: str | None = None
        if _IPV4_RE.fullmatch(target):
            dest_ip = target

        try:
            stdout = proc.stdout
            if stdout is not None:
                while True:
                    line = stdout.readline()
                    if line == "":
                        break
                    line_lower = line.lower()
                    if _UNRESOLVABLE_SNIP in line_lower:
                        resolved = False
                    if "trace complete" in line_lower:
                        trace_reported_complete = True

                    if dest_ip is None:
                        m_b = _TRACING_BRACKET_RE.search(line)
                        if m_b:
                            dest_ip = m_b.group(1)
                        else:
                            m_i = _TRACING_TO_IPV4_RE.search(line)
                            if m_i:
                                dest_ip = m_i.group(1)

                    parsed = _parse_hop_line(line)
                    if parsed is not None:
                        self.hop_signal.emit(parsed)
                        if (
                            parsed["latency_1"] == "*"
                            and parsed["latency_2"] == "*"
                            and parsed["latency_3"] == "*"
                        ):
                            hop_events.append("timeout")
                        else:
                            hop_events.append("ok")
                            ip_val = (parsed.get("ip") or "").strip()
                            if _IPV4_RE.fullmatch(ip_val):
                                last_ok_ip = ip_val
            proc.wait(timeout=None)
        except Exception:
            pass
        finally:
            with self._proc_lock:
                self._proc = None
            if trace_reported_complete or (
                last_ok_ip and dest_ip and last_ok_ip == dest_ip
            ):
                reached_destination = True
            if self._stop_requested:
                self.finished_signal.emit("")
            else:
                msg = self._finalize_message(
                    resolved=resolved,
                    reached_destination=reached_destination,
                    hop_events=hop_events,
                )
                self.finished_signal.emit(msg)

    def _run_traceroute_darwin(self, target: str) -> None:
        # macOS: numeric traceroute, same hop_signal / finished_signal contract as Windows.
        popen_kwargs: dict = {
            "args": ["traceroute", "-n", "-m", "30", target],
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": locale.getpreferredencoding(False) or "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }

        try:
            proc = subprocess.Popen(**popen_kwargs)
        except Exception:
            self.finished_signal.emit("Unable to reach target.")
            return

        with self._proc_lock:
            self._proc = proc

        resolved = True
        reached_destination = False
        trace_reported_complete = False
        hop_events: list[str] = []
        dest_ip: str | None = None
        last_ok_ip: str | None = None
        if _IPV4_RE.fullmatch(target):
            dest_ip = target

        try:
            stdout = proc.stdout
            if stdout is not None:
                while True:
                    line = stdout.readline()
                    if line == "":
                        break
                    line_lower = line.lower()
                    if "unknown host" in line_lower or "could not resolve" in line_lower:
                        resolved = False
                    if dest_ip is None:
                        m_p = _DARWIN_TRACE_DEST_PARENS_RE.search(line)
                        if m_p:
                            dest_ip = m_p.group(1)
                        else:
                            m_i = _DARWIN_TRACE_DEST_IP_RE.search(line)
                            if m_i:
                                dest_ip = m_i.group(1)

                    parsed = _parse_darwin_hop_line(line)
                    if parsed is not None:
                        self.hop_signal.emit(parsed)
                        if (
                            parsed["latency_1"] == "*"
                            and parsed["latency_2"] == "*"
                            and parsed["latency_3"] == "*"
                        ):
                            hop_events.append("timeout")
                        else:
                            hop_events.append("ok")
                            ip_val = (parsed.get("ip") or "").strip()
                            if _IPV4_RE.fullmatch(ip_val):
                                last_ok_ip = ip_val
                    if dest_ip and last_ok_ip and last_ok_ip == dest_ip:
                        trace_reported_complete = True
            proc.wait(timeout=None)
        except Exception:
            pass
        finally:
            with self._proc_lock:
                self._proc = None
            if trace_reported_complete or (
                last_ok_ip and dest_ip and last_ok_ip == dest_ip
            ):
                reached_destination = True
            if self._stop_requested:
                self.finished_signal.emit("")
            else:
                msg = self._finalize_message(
                    resolved=resolved,
                    reached_destination=reached_destination,
                    hop_events=hop_events,
                )
                self.finished_signal.emit(msg)

    def run(self) -> None:
        target = self._target
        self._stop_requested = False
        if not target:
            self.finished_signal.emit("")
            return

        if sys.platform == "win32":
            self._run_tracert_windows(target)
        elif sys.platform == "darwin":
            self._run_traceroute_darwin(target)
        else:
            # Non-Windows, non-macOS: tracert is Windows-only; do not invoke it here.
            self.finished_signal.emit("Unable to reach target.")
