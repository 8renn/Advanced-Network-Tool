"""SIP ALG detector: receiver + sender threads, UDP loopback compare (fixed 192.81.82.254 target)."""

from __future__ import annotations

import re
import socket
import threading
import time
import datetime
import os

from PySide6.QtCore import QThread, Signal

import random
import time
from core.runtime_paths import user_data_dir

def write_sip_log(section: str, content: str):
    log_path = str(user_data_dir() / "sip_alg_debug.log")

    print("WRITING LOG TO:", log_path)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n===== {section} =====\n")
        f.write(f"{datetime.datetime.now()}\n")
        f.write(content + "\n")

def build_sip_invite(target_ip: str, target_port: int):
    """
    Builds SIP INVITE packet EXACTLY matching reverse engineered executable.
    """

    call_id = str(random.randint(1000000000, 9999999999))
    import socket

    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    local_ip = get_local_ip()
    local_port = 5060

    branch = f"z9hG4bK{random.randint(100000,999999)}"
    tag = str(random.randint(100000,999999))

    sdp_body = (
        "v=0\r\n"
        "o=7635551212 8000 8000 IN IP4 0.0.0.0\r\n"
        "s=SIP Call\r\n"
        "c=IN IP4 0.0.0.0\r\n"
        "t=0 0\r\n"
        "m=audio 6646 RTP/AVP 0 101\r\n"
        "a=sendrecv\r\n"
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=ptime:20\r\n"
        "a=rtpmap:101 telephone-event/8000\r\n"
        "a=fmtp:101 0-15\r\n"
    )

    content_length = len(sdp_body)

    sip_packet = (
        f"INVITE sip:7635551213@{target_ip} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {local_ip}:{local_port};branch={branch}\r\n"
        f'From: "Test" <sip:7635551212@{local_ip}>;tag={tag}\r\n'
        f"To: <sip:7635551213@{target_ip}>\r\n"
        f"Call-ID: {call_id}@{local_ip}\r\n"
        f"CSeq: 10 INVITE\r\n"
        f"Contact: \"Test\" <sip:7635551212@{local_ip}:{local_port}>\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: Grandstream GXP934512 1.0.5.15\r\n"
        f"Privacy: none\r\n"
        f'P-Preferred-Identity: "Test" <sip:7635551212@{local_ip}>\r\n'
        f"Content-Type: application/sdp\r\n"
        f"Content-Length: {content_length}\r\n\r\n"
        f"{sdp_body}"
    )

    write_sip_log("SENT PACKET", sip_packet)

    return sip_packet

import socket

def send_sip_packet(target_ip: str, target_port: int, timeout: float = 3.0):
    """
    Sends SIP INVITE over UDP and waits for response.
    Matches real executable behavior.
    """

    sip_packet = build_sip_invite(target_ip, target_port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    try:
        print("Sending SIP Packet")
        sock.sendto(sip_packet.encode(), (target_ip, target_port))

        print("Receiving Packet")
        data, addr = sock.recvfrom(4096)

        response = data.decode(errors="ignore")
        write_sip_log("RECEIVED PACKET", response or "NO RESPONSE")
        return response

    except socket.timeout:
        return None

    except Exception as e:
        print(f"SIP send error: {e}")
        return None

    finally:
        sock.close()

def parse_sip_response(response: str):
    """
    Parses raw SIP response into header dictionary.
    String-level parsing ONLY.
    """

    if not response:
        return None

    lines = response.split("\r\n")
    headers = {}

    for line in lines:
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key.strip().lower()] = value.strip()

    return headers

TARGET_HOST = "192.81.82.254"
TARGET_PORT = 5060
RECV_BIND = ("0.0.0.0", 5060)
_RECEIVER_DEADLINE_SEC = 5.0
_SENDER_DELAY_SEC = 0.5

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_VIA_SENT_BY = re.compile(
    r"Via:\s*SIP/\S+\s+([^;\s]+)",
    re.IGNORECASE,
)
_CONTACT_HOST = re.compile(
    r"<sip:[^@>]+@(\d{1,3}(?:\.\d{1,3}){3})",
    re.IGNORECASE,
)
_SDP_C = re.compile(r"^c\s*=\s*IN\s+IP4\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_SDP_M = re.compile(r"^m=audio\s+(\d+)", re.IGNORECASE | re.MULTILINE)


def _local_ip_toward_target() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((TARGET_HOST, TARGET_PORT))
        return s.getsockname()[0]
    finally:
        s.close()


def _build_invite_packet(local_ip: str) -> bytes:
    sdp = (
        f"v=0\r\n"
        f"o=- 123456 123456 IN IP4 {local_ip}\r\n"
        f"s=-\r\n"
        f"c=IN IP4 {local_ip}\r\n"
        f"t=0 0\r\n"
        f"m=audio 49170 RTP/AVP 0\r\n"
    )
    body = sdp.encode("utf-8")
    clen = len(body)
    headers = (
        f"INVITE sip:7635551213@{TARGET_HOST} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {local_ip}:5060;branch=z9hG4bK123456\r\n"
        f"Max-Forwards: 70\r\n"
        f'From: "Test" <sip:test@{local_ip}>;tag=12345\r\n'
        f"To: <sip:7635551213@{TARGET_HOST}>\r\n"
        f"Call-ID: 123456789\r\n"
        f"CSeq: 10 INVITE\r\n"
        f"Contact: <sip:test@{local_ip}>\r\n"
        f"User-Agent: Grandstream HT801 1.0.0.85\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Content-Length: {clen}\r\n"
        f"\r\n"
    )
    return headers.encode("ascii", errors="strict") + body


def _split_message(raw: str) -> tuple[str, str]:
    if "\r\n\r\n" in raw:
        h, b = raw.split("\r\n\r\n", 1)
        return h, b
    if "\n\n" in raw:
        h, b = raw.split("\n\n", 1)
        return h, b
    return raw, ""


def _parse_via_ip_port(hdrs: str) -> tuple[str | None, int | None]:
    for line in hdrs.splitlines():
        if not line.lower().startswith("via:"):
            continue
        if "z9hG4bK123456" not in line:
            continue
        m = _VIA_SENT_BY.match(line.strip())
        if not m:
            continue
        sent = m.group(1).strip().strip('"')
        if ":" in sent:
            host, p = sent.rsplit(":", 1)
            if _IPV4_RE.fullmatch(host):
                try:
                    return host, int(p)
                except ValueError:
                    return host, None
        if _IPV4_RE.fullmatch(sent):
            return sent, 5060
    return None, None


def _parse_contact_ip(hdrs: str) -> str | None:
    for line in hdrs.splitlines():
        if line.lower().startswith("contact:"):
            m = _CONTACT_HOST.search(line)
            if m:
                return m.group(1)
    return None


def _parse_sdp_c_and_m(sdp: str) -> tuple[str | None, int | None]:
    cm = _SDP_C.search(sdp)
    mm = _SDP_M.search(sdp)
    c_ip = cm.group(1).strip() if cm else None
    m_port = int(mm.group(1)) if mm else None
    return c_ip, m_port


def _extract_compare_fields(
    packet_bytes: bytes,
) -> tuple[str | None, int | None, str | None, str | None, int | None]:
    try:
        text = packet_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None, None, None, None, None
    hdrs, body = _split_message(text)
    vh, vp = _parse_via_ip_port(hdrs)
    ctip = _parse_contact_ip(hdrs)
    c_ip, m_port = _parse_sdp_c_and_m(body)
    return vh, vp, ctip, c_ip, m_port


def _unable(sub: str) -> dict[str, str]:
    return {
        "state": "orange",
        "headline": "UNABLE TO DETERMINE",
        "subtext": sub,
    }


def _detected(sub: str) -> dict[str, str]:
    return {"state": "red", "headline": "DETECTED", "subtext": sub}


def _not_detected(sub: str) -> dict[str, str]:
    return {"state": "green", "headline": "NOT DETECTED", "subtext": sub}


class _RecvState:
    __slots__ = ("lock", "data", "error")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data: bytes | None = None
        self.error: str | None = None


def _is_sip_datagram(data: bytes) -> bool:
    return b"SIP/2.0" in data or (b"INVITE" in data and b"sip:" in data.lower())


def _receiver_thread(state: _RecvState) -> None:
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(RECV_BIND)
        deadline = time.monotonic() + _RECEIVER_DEADLINE_SEC
        while time.monotonic() < deadline:
            sock.settimeout(max(0.02, deadline - time.monotonic()))
            try:
                data, _ = sock.recvfrom(65535)
                if _is_sip_datagram(data):
                    with state.lock:
                        state.data = data
                    return
            except TimeoutError:
                continue
            except socket.timeout:
                continue
    except OSError as e:
        with state.lock:
            state.error = str(e)
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _sender_thread(packet: bytes) -> None:
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet, (TARGET_HOST, TARGET_PORT))
    except OSError:
        pass
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def run_sip_alg_detection() -> dict[str, str]:
    try:
        local_ip = _local_ip_toward_target()
    except OSError:
        return _unable("Could not determine local IP (socket error).")

    original = _build_invite_packet(local_ip)

    ov_via_ip, ov_via_port, ov_ct_ip, ov_sdp_c, ov_sdp_m = _extract_compare_fields(
        original
    )
    if ov_via_ip != local_ip or ov_via_port != 5060:
        return _unable("Internal INVITE build mismatch.")
    if ov_ct_ip != local_ip or ov_sdp_c != local_ip or ov_sdp_m != 49170:
        return _unable("Internal INVITE build mismatch.")

    rstate = _RecvState()
    t_recv = threading.Thread(target=_receiver_thread, args=(rstate,), daemon=True)
    t_recv.start()
    time.sleep(_SENDER_DELAY_SEC)
    t_send = threading.Thread(target=_sender_thread, args=(original,), daemon=True)
    t_send.start()
    t_send.join()
    t_recv.join()

    with rstate.lock:
        err = rstate.error
        received = rstate.data

    if err is not None:
        return _unable(f"Receiver could not bind or listen on UDP 5060 ({err}).")

    if received is None:
        return _unable("No packet received within timeout (loopback or firewall).")

    if received == original:
        return _not_detected("Received packet matches the original INVITE exactly.")

    rv_via_ip, rv_via_port, rv_ct_ip, rv_sdp_c, rv_sdp_m = _extract_compare_fields(
        received
    )

    if rv_via_ip != ov_via_ip or rv_via_port != ov_via_port:
        return _detected("Via IP or port differs from the original packet.")

    if rv_ct_ip != ov_ct_ip:
        return _detected("Contact header IP differs from the original packet.")

    if rv_sdp_c != ov_sdp_c:
        return _detected("SDP c= IN IP4 address differs from the original packet.")

    if rv_sdp_m != ov_sdp_m:
        return _detected("SDP m= audio port differs from the original packet.")

    return _detected("Packet differs from original (headers or body modified).")


class SipAlgDetector(QThread):
    result_signal = Signal(dict)
    finished_signal = Signal()

    def run(self) -> None:
        try:
            try:
                out = run_sip_alg_detection()
            except Exception:
                out = _unable("No packet received within timeout (loopback or firewall).")
            self.result_signal.emit(out)
        finally:
            self.finished_signal.emit()


def detect_sip_alg(target_ip: str, target_port: int):
    """
    Performs SIP ALG detection by comparing sent vs received headers.
    Returns EXACT required output strings.
    """

    response = send_sip_packet(target_ip, target_port)

    if response is None:
        result_string = "Unable to determine – network blocking or timeout"
        write_sip_log("FINAL RESULT", result_string)
        return result_string

    parsed_headers = parse_sip_response(response)
    write_sip_log("PARSED HEADERS", str(parsed_headers))

    if not parsed_headers:
        result_string = "Unable to determine – network blocking or timeout"
        write_sip_log("FINAL RESULT", result_string)
        return result_string

    if response is None:
        return "Unable to determine – network blocking or timeout"

    def _extract_fields(msg: str):
        if not msg:
            return None

        hdrs, body = msg, ""
        if "\r\n\r\n" in msg:
            hdrs, body = msg.split("\r\n\r\n", 1)

        via_host = None
        via_port = None
        contact_host = None
        ppi_host = None
        sdp_c_ip = None
        sdp_m_port = None

        for line in hdrs.split("\r\n"):
            low = line.lower()
            if low.startswith("via:"):
                v = line.split(":", 1)[1].strip()
                parts = v.split()
                if len(parts) >= 2:
                    sent_by = parts[1].split(";", 1)[0].strip()
                    if ":" in sent_by:
                        h, p = sent_by.rsplit(":", 1)
                        via_host = h.strip()
                        try:
                            via_port = int(p)
                        except ValueError:
                            via_port = None
                    else:
                        via_host = sent_by.strip()
            elif low.startswith("contact:"):
                v = line.split(":", 1)[1]
                at = v.find("@")
                if at != -1:
                    rest = v[at + 1 :]
                    end = len(rest)
                    for ch in (">", ";", "\r", "\n"):
                        i = rest.find(ch)
                        if i != -1:
                            end = min(end, i)
                    hostport = rest[:end].strip()
                    if ":" in hostport:
                        hostport = hostport.split(":", 1)[0].strip()
                    contact_host = hostport.strip()
            elif low.startswith("p-preferred-identity:"):
                v = line.split(":", 1)[1]
                at = v.find("@")
                if at != -1:
                    rest = v[at + 1 :]
                    end = len(rest)
                    for ch in (">", ";", "\r", "\n"):
                        i = rest.find(ch)
                        if i != -1:
                            end = min(end, i)
                    hostport = rest[:end].strip()
                    if ":" in hostport:
                        hostport = hostport.split(":", 1)[0].strip()
                    ppi_host = hostport.strip()

        if body:
            for bline in body.split("\r\n"):
                bl = bline.strip()
                if bl.lower().startswith("c=in ip4 "):
                    sdp_c_ip = bl.split(None, 2)[-1].strip()
                elif bl.lower().startswith("m=audio "):
                    parts = bl.split()
                    if len(parts) >= 2:
                        try:
                            sdp_m_port = int(parts[1])
                        except ValueError:
                            sdp_m_port = None

        return {
            "via_host": via_host,
            "via_port": via_port,
            "contact_host": contact_host,
            "ppi_host": ppi_host,
            "sdp_c_ip": sdp_c_ip,
            "sdp_m_port": sdp_m_port,
        }

    sent_packet = build_sip_invite(target_ip, target_port)
    sent_fields = _extract_fields(sent_packet)
    recv_fields = _extract_fields(response)

    if not sent_fields or not recv_fields:
        result_string = "Unable to determine – network blocking or timeout"
        write_sip_log("FINAL RESULT", result_string)
        return result_string

    def _ip_only(v):
        if not v:
            return None
        s = str(v).strip()
        if ":" in s:
            s = s.split(":", 1)[0].strip()
        if _IPV4_RE.fullmatch(s):
            return s
        return s

    sent_via = _ip_only(sent_fields.get("via_host"))
    recv_via = _ip_only(recv_fields.get("via_host"))
    sent_contact = _ip_only(sent_fields.get("contact_host"))
    recv_contact = _ip_only(recv_fields.get("contact_host"))
    sent_ppi = _ip_only(sent_fields.get("ppi_host"))
    recv_ppi = _ip_only(recv_fields.get("ppi_host"))
    sent_sdp_c = sent_fields.get("sdp_c_ip")
    recv_sdp_c = recv_fields.get("sdp_c_ip")
    sent_sdp_m = sent_fields.get("sdp_m_port")
    recv_sdp_m = recv_fields.get("sdp_m_port")

    comparison_log = f"""
Via Sent: {sent_via}
Via Received: {recv_via}

Contact Sent: {sent_contact}
Contact Received: {recv_contact}

P-Preferred-Identity Sent: {sent_ppi}
P-Preferred-Identity Received: {recv_ppi}

SDP c= Sent: {sent_sdp_c}
SDP c= Received: {recv_sdp_c}

SDP m= Sent: {sent_sdp_m}
SDP m= Received: {recv_sdp_m}
"""

    write_sip_log("FIELD COMPARISON", comparison_log)

    if recv_contact and sent_contact:
        if recv_contact != sent_contact:
            result_string = "SIP ALG detected"
            write_sip_log("FINAL RESULT", result_string)
            return result_string

    if recv_via and sent_via:
        if recv_via != sent_via:
            result_string = "SIP ALG detected"
            write_sip_log("FINAL RESULT", result_string)
            return result_string

    if recv_ppi and sent_ppi:
        if recv_ppi != sent_ppi:
            result_string = "SIP ALG detected"
            write_sip_log("FINAL RESULT", result_string)
            return result_string

    if recv_fields.get("sdp_c_ip") and sent_fields.get("sdp_c_ip"):
        if recv_fields["sdp_c_ip"] != sent_fields["sdp_c_ip"]:
            result_string = "SIP ALG detected"
            write_sip_log("FINAL RESULT", result_string)
            return result_string

    if recv_fields.get("sdp_m_port") is not None and sent_fields.get("sdp_m_port") is not None:
        if recv_fields["sdp_m_port"] != sent_fields["sdp_m_port"]:
            result_string = "SIP ALG detected"
            write_sip_log("FINAL RESULT", result_string)
            return result_string

    result_string = "SIP ALG is NOT detected"
    write_sip_log("FINAL RESULT", result_string)
    return result_string
