import struct
import socket
import threading
import time
import os
import select
import sys
import ctypes
import ctypes.wintypes

MAX_HOPS = 30
ECHO_REPLY_TIMEOUT = 5.0        # seconds (float, used with select)
ICMP_ECHO_REQUEST = 8
ICMP_ECHO_REPLY = 0
ICMP_TIME_EXCEEDED = 11
IPFLAG_DONT_FRAGMENT = 0x02
DEFAULT_PAYLOAD_SIZE = 64
ICMP_HEADER_FORMAT = "!BBHHH"   # type, code, checksum, identifier, sequence
ICMP_HEADER_SIZE = 8
REPORT_INTERVAL = 2.0  # seconds between table refreshes in console mode
MIN_PAYLOAD_SIZE = 64
MAX_PAYLOAD_SIZE = 4096
DEFAULT_INTERVAL = 1.0

DEBUG_MTR_CONSOLE = False

# Windows ICMP API status codes
IP_SUCCESS = 0
IP_STATUS_BASE = 11000
IP_BUF_TOO_SMALL = 11001
IP_DEST_NET_UNREACHABLE = 11002
IP_DEST_HOST_UNREACHABLE = 11003
IP_DEST_PROT_UNREACHABLE = 11004
IP_DEST_PORT_UNREACHABLE = 11005
IP_NO_RESOURCES = 11006
IP_BAD_OPTION = 11007
IP_HW_ERROR = 11008
IP_PACKET_TOO_BIG = 11009
IP_REQ_TIMED_OUT = 11010
IP_BAD_REQ = 11011
IP_BAD_ROUTE = 11012
IP_TTL_EXPIRED_TRANSIT = 11013
IP_TTL_EXPIRED_REASSEM = 11014
IP_PARAM_PROBLEM = 11015
IP_SOURCE_QUENCH = 11016
IP_OPTION_TOO_BIG = 11017
IP_BAD_DESTINATION = 11018
IP_GENERAL_FAILURE = 11050


def _calculate_checksum(data: bytes) -> int:
    total = 0
    length = len(data)
    i = 0
    while i + 1 < length:
        total += (data[i] << 8) + data[i + 1]
        i += 2
    if length & 1:
        total += data[-1] << 8
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (total ^ 0xFFFF) & 0xFFFF


def _build_icmp_packet(identifier: int, sequence: int, payload_size: int) -> bytes:
    header = struct.pack(
        ICMP_HEADER_FORMAT,
        ICMP_ECHO_REQUEST,
        0,
        0,
        identifier,
        sequence,
    )
    if payload_size <= ICMP_HEADER_SIZE:
        payload = b""
    else:
        payload = b" " * (payload_size - ICMP_HEADER_SIZE)
    checksum = _calculate_checksum(header + payload)
    header = struct.pack(
        ICMP_HEADER_FORMAT,
        ICMP_ECHO_REQUEST,
        0,
        checksum,
        identifier,
        sequence,
    )
    return header + payload


def _parse_icmp_response(data: bytes, expected_id: int, expected_seq: int) -> dict | None:
    try:
        ihl = (data[0] & 0x0F) * 4
        icmp_type, icmp_code, checksum, recv_id, recv_seq = struct.unpack(
            ICMP_HEADER_FORMAT,
            data[ihl:ihl + ICMP_HEADER_SIZE],
        )
        source_ip = socket.inet_ntoa(data[12:16])

        if icmp_type == ICMP_ECHO_REPLY:
            if recv_id == expected_id and recv_seq == expected_seq:
                return {"type": "reply", "addr": source_ip, "id": recv_id, "seq": recv_seq}
            return None

        if icmp_type == ICMP_TIME_EXCEEDED:
            embedded_ihl = (data[ihl + ICMP_HEADER_SIZE] & 0x0F) * 4
            embedded_icmp_offset = ihl + ICMP_HEADER_SIZE + embedded_ihl
            orig_type, orig_code, orig_checksum, orig_id, orig_seq = struct.unpack(
                ICMP_HEADER_FORMAT,
                data[embedded_icmp_offset:embedded_icmp_offset + ICMP_HEADER_SIZE],
            )
            if orig_id == expected_id and orig_seq == expected_seq:
                return {"type": "ttl_exceeded", "addr": source_ip, "id": orig_id, "seq": orig_seq}
            return None

        return None
    except (struct.error, IndexError, Exception):
        return None


class _IP_OPTION_INFORMATION(ctypes.Structure):
    """Windows IP_OPTION_INFORMATION structure (used by ICMP API)."""
    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _ICMP_ECHO_REPLY(ctypes.Structure):
    """Windows ICMP_ECHO_REPLY structure."""
    _fields_ = [
        ("Address", ctypes.c_ulong),
        ("Status", ctypes.c_ulong),
        ("RoundTripTime", ctypes.c_ulong),
        ("DataSize", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort),
        ("Data", ctypes.c_void_p),
        ("Options", _IP_OPTION_INFORMATION),
    ]


class _WinICMPAPI:
    """Wrapper around Windows ICMP.DLL for sending echo requests with TTL control."""

    def __init__(self):
        self._icmp_dll = ctypes.windll.LoadLibrary("ICMP.DLL")
        # Define function signature for IcmpSendEcho (CRITICAL)
        self._icmp_dll.IcmpSendEcho.argtypes = [
            ctypes.wintypes.HANDLE,      # IcmpHandle
            ctypes.wintypes.DWORD,       # DestinationAddress
            ctypes.c_void_p,             # RequestData
            ctypes.wintypes.WORD,        # RequestSize
            ctypes.c_void_p,             # RequestOptions
            ctypes.c_void_p,             # ReplyBuffer
            ctypes.wintypes.DWORD,       # ReplySize
            ctypes.wintypes.DWORD        # Timeout
        ]
        self._icmp_dll.IcmpSendEcho.restype = ctypes.wintypes.DWORD
        self._icmp_dll.IcmpCreateFile.restype = ctypes.wintypes.HANDLE
        self._icmp_dll.IcmpCloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        self._icmp_dll.IcmpCloseHandle.restype = ctypes.wintypes.BOOL
        self._handle = self._icmp_dll.IcmpCreateFile()
        if not self._handle:
            raise OSError("Failed to create ICMP handle")

    def send_echo(self, dest_addr_str: str, ttl: int, payload_size: int, timeout_ms: int) -> dict | None:
        """Send an ICMP echo request with specified TTL. Returns dict with addr/rtt or None on timeout."""
        # IcmpSendEcho expects DestinationAddress as a ULONG containing the
        # IPv4 address in network byte order.  inet_aton() already gives us
        # 4 bytes in network order; we just need to load them into a c_ulong
        # WITHOUT swapping, so use LITTLE-ENDIAN unpack ("<I") because
        # c_ulong stores its value in native (little-endian on x86) format
        # and IcmpSendEcho will reinterpret those same bytes as network order.
        dest_addr = struct.unpack("<I", socket.inet_aton(dest_addr_str))[0]

        # Set up IP options with TTL
        ip_options = _IP_OPTION_INFORMATION()
        ip_options.Ttl = ttl
        ip_options.Tos = 0
        ip_options.Flags = IPFLAG_DONT_FRAGMENT
        ip_options.OptionsSize = 0
        ip_options.OptionsData = None

        # Create send buffer (filled with spaces like WinMTR)
        send_size = max(0, payload_size - 8)
        send_buf = ctypes.create_string_buffer(b' ' * send_size, send_size) if send_size > 0 else ctypes.create_string_buffer(0)

        # Create reply buffer — must be at least sizeof(ICMP_ECHO_REPLY) + 8
        reply_size = ctypes.sizeof(_ICMP_ECHO_REPLY) + payload_size + 8
        reply_buf = ctypes.create_string_buffer(reply_size)

        # Call IcmpSendEcho
        ret = self._icmp_dll.IcmpSendEcho(
            self._handle,
            dest_addr,
            send_buf,
            send_size,
            ctypes.byref(ip_options),
            reply_buf,
            reply_size,
            timeout_ms,
        )

        if ret == 0:
            return None

        # Parse the reply
        reply = ctypes.cast(reply_buf, ctypes.POINTER(_ICMP_ECHO_REPLY)).contents

        status = reply.Status
        rtt = reply.RoundTripTime

        # Address field is in network byte order stored in a ULONG —
        # pack as little-endian to get the original network-order bytes,
        # then inet_ntoa converts them to dotted-quad string.
        addr_bytes = struct.pack("<I", reply.Address)
        addr_str = socket.inet_ntoa(addr_bytes)

        if status == IP_SUCCESS or status == IP_TTL_EXPIRED_TRANSIT:
            return {
                "addr": addr_str,
                "rtt_ms": rtt,
                "status": status,
                "type": "reply" if status == IP_SUCCESS else "ttl_exceeded",
            }
        else:
            return None

    def close(self):
        """Close the ICMP handle."""
        try:
            self._icmp_dll.IcmpCloseHandle(self._handle)
        except Exception:
            pass


class HopData:
    def __init__(self):
        self.addr = ""           # IP address string, empty string if unknown
        self.xmit = 0            # packets sent
        self.returned = 0        # replies received
        self.total_ms = 0        # cumulative RTT in milliseconds (integer)
        self.last_ms = 0         # last RTT
        self.best_ms = 0         # best RTT
        self.worst_ms = 0        # worst RTT
        self.name = ""           # resolved hostname or IP string


class MTREngine:
    def __init__(self, target_host: str, payload_size: int = DEFAULT_PAYLOAD_SIZE, interval: float = DEFAULT_INTERVAL, use_dns: bool = True):
        self._target_host = target_host
        self._target_addr = None          # will be resolved to IP string
        self._payload_size = max(MIN_PAYLOAD_SIZE, min(payload_size, MAX_PAYLOAD_SIZE))
        if self._payload_size != payload_size:
            if DEBUG_MTR_CONSOLE:
                print(f"Payload size clamped to {self._payload_size} (requested {payload_size}, valid range {MIN_PAYLOAD_SIZE}-{MAX_PAYLOAD_SIZE})")
        self._base_identifier = os.getpid() & 0xFFFF
        self._lock = threading.RLock()    # MUST be RLock, NOT Lock
        self._hops = [HopData() for _ in range(MAX_HOPS)]
        self._tracing = False
        self._threads = []
        self._sequences = [0] * MAX_HOPS  # per-TTL sequence counter
        self._use_dns = use_dns
        # Initialize Windows ICMP API if on Windows
        self._use_win_api = sys.platform == "win32"
        self._win_icmp = None
        self._destination_ttl = None  # set when IP_SUCCESS reply received
        self._interval = max(0.1, interval)

    def resolve_target(self) -> bool:
        try:
            self._target_addr = socket.gethostbyname(self._target_host)
            return True
        except socket.gaierror:
            print(f"Failed to resolve {self._target_host}")
            return False

    def start_trace(self):
        if not self.resolve_target():
            return
        self._tracing = True
        self._hops = [HopData() for _ in range(MAX_HOPS)]
        self._sequences = [0] * MAX_HOPS
        self._destination_ttl = None
        self._threads = []
        for ttl in range(1, MAX_HOPS + 1):
            t = threading.Thread(target=self._probe_loop, args=(ttl,), daemon=True)
            self._threads.append(t)
        for t in self._threads:
            t.start()

        # Start report thread for periodic console output
        self._report_thread = threading.Thread(
            target=self._report_loop,
            daemon=True
        )
        self._report_thread.start()

    @property
    def is_running(self) -> bool:
        """Check if trace is currently active."""
        return self._tracing

    @property
    def target_addr(self) -> str:
        """Return resolved target IP address."""
        return self._target_addr if self._target_addr else ""

    def stop_trace(self):
        """Stop all probe threads and clean up."""
        self._tracing = False

        # Join probe threads with timeout
        for t in self._threads:
            t.join(timeout=ECHO_REPLY_TIMEOUT + 1)
            if t.is_alive():
                print(f"Warning: probe thread {t.name} did not stop within timeout")
        self._threads = []

        # Join report thread if it exists
        if hasattr(self, '_report_thread') and self._report_thread is not None:
            self._report_thread.join(timeout=REPORT_INTERVAL + 1)
            self._report_thread = None

    def _get_max(self) -> int:
        with self._lock:
            # If we know the destination TTL, use it
            if self._destination_ttl is not None:
                return self._destination_ttl

            # Otherwise find the highest hop that has responded
            max_hops = MAX_HOPS
            for i in range(MAX_HOPS):
                if self._hops[i].addr == self._target_addr:
                    max_hops = i + 1
                    break
            if max_hops == MAX_HOPS:
                # Find highest responding hop
                for i in range(MAX_HOPS - 1, -1, -1):
                    if self._hops[i].addr != "":
                        max_hops = i + 1
                        break
                else:
                    max_hops = 1  # At least show 1 hop while waiting
            return max_hops

    def _probe_loop(self, ttl: int):
        """Per-TTL probe thread. Uses Windows ICMP API on Windows, raw sockets on Linux."""
        try:
            if self._use_win_api:
                self._probe_loop_win(ttl)
            else:
                self._probe_loop_raw(ttl)
        except Exception as e:
            print(f"TTL {ttl} thread terminated unexpectedly: {e}")

    def _probe_loop_win(self, ttl: int):
        """Probe loop using Windows ICMP API (IcmpSendEcho)."""
        # Each thread gets its own ICMP API handle
        win_icmp = _WinICMPAPI()
        try:
            while self._tracing:
                # Check early exit — stop threads beyond the destination
                with self._lock:
                    dest_ttl = self._destination_ttl
                if dest_ttl is not None and ttl > dest_ttl:
                    break

                # Increment xmit counter
                with self._lock:
                    self._hops[ttl - 1].xmit += 1

                send_time = time.perf_counter()

                # Send echo with TTL via Windows ICMP API
                timeout_ms = int(ECHO_REPLY_TIMEOUT * 1000)
                result = win_icmp.send_echo(
                    self._target_addr,
                    ttl,
                    self._payload_size,
                    timeout_ms
                )

                recv_time = time.perf_counter()
                rtt_ms = int((recv_time - send_time) * 1000)

                if result is not None:
                    # Use the API-reported RTT (more accurate than our measurement)
                    actual_rtt = result["rtt_ms"] if result["rtt_ms"] > 0 else rtt_ms
                    self._update_hop(ttl - 1, result["addr"], actual_rtt)

                    # Mark destination TTL when we get an actual echo reply (IP_SUCCESS)
                    if result["type"] == "reply":
                        with self._lock:
                            if self._destination_ttl is None or ttl < self._destination_ttl:
                                self._destination_ttl = ttl

                    hop_name = ""
                    with self._lock:
                        hop_name = self._hops[ttl - 1].name
                    display = hop_name if hop_name else result["addr"]
                    if DEBUG_MTR_CONSOLE:
                        print(f"TTL {ttl} → {display} ({result['addr']}) → {actual_rtt}ms")

                # Always sleep between probes to avoid flooding
                elapsed = recv_time - send_time
                sleep_time = max(0, self._interval - elapsed)
                time.sleep(sleep_time)

        finally:
            win_icmp.close()

    def _probe_loop_raw(self, ttl: int):
        """Probe loop using raw ICMP sockets (Linux/Mac)."""
        while self._tracing:
            # Check early exit — stop threads beyond the destination
            with self._lock:
                dest_ttl = self._destination_ttl
            if dest_ttl is not None and ttl > dest_ttl:
                break

            # Increment sequence and xmit
            with self._lock:
                self._sequences[ttl - 1] += 1
                seq = self._sequences[ttl - 1] & 0xFFFF
                self._hops[ttl - 1].xmit += 1

            ttl_identifier = (self._base_identifier + ttl) & 0xFFFF
            packet = _build_icmp_packet(ttl_identifier, seq, self._payload_size)

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
                sock.settimeout(ECHO_REPLY_TIMEOUT)
                try:
                    send_time = time.perf_counter()
                    sock.sendto(packet, (self._target_addr, 0))

                    while True:
                        remaining = ECHO_REPLY_TIMEOUT - (time.perf_counter() - send_time)
                        if remaining <= 0:
                            break
                        ready = select.select([sock], [], [], remaining)
                        if not ready[0]:
                            break
                        data, addr = sock.recvfrom(4096)
                        recv_time = time.perf_counter()
                        result = _parse_icmp_response(data, ttl_identifier, seq)
                        if result is None:
                            continue
                        rtt_ms = int((recv_time - send_time) * 1000)
                        self._update_hop(ttl - 1, result["addr"], rtt_ms)

                        if result["type"] == "reply":
                            with self._lock:
                                if self._destination_ttl is None or ttl < self._destination_ttl:
                                    self._destination_ttl = ttl

                        hop_name = ""
                        with self._lock:
                            hop_name = self._hops[ttl - 1].name
                        display = hop_name if hop_name else result["addr"]
                        if DEBUG_MTR_CONSOLE:
                            print(f"TTL {ttl} → {display} ({result['addr']}) → {rtt_ms}ms")

                        sleep_time = max(0, self._interval - (recv_time - send_time))
                        time.sleep(sleep_time)
                        break

                finally:
                    sock.close()

            except PermissionError:
                print(f"ERROR: Raw socket access denied. Run as root.")
                self._tracing = False
                return
            except OSError as e:
                if e.errno == 1:
                    print(f"ERROR: Raw socket access denied (errno 1). Run as root.")
                    self._tracing = False
                    return
                elif e.errno == 101:
                    print(f"TTL {ttl}: Network unreachable")
                else:
                    print(f"TTL {ttl} socket error: {e}")
            except socket.timeout:
                pass

    def _resolve_dns(self, index: int, addr: str):
        """DNS resolver thread function. Runs once per hop when address is first discovered."""
        try:
            # Set a timeout for DNS resolution to prevent blocking
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5.0)
            try:
                hostinfo = socket.gethostbyaddr(addr)
                hostname = hostinfo[0]
            finally:
                socket.setdefaulttimeout(old_timeout)
        except (socket.herror, socket.gaierror, socket.timeout, OSError):
            hostname = addr

        with self._lock:
            self._hops[index].name = hostname

        if DEBUG_MTR_CONSOLE:
            print(f"DNS: hop {index + 1} → {addr} → {hostname}")

    def _update_hop(self, index: int, addr: str, rtt_ms: int):
        with self._lock:
            first_discovery = False
            if self._hops[index].addr == "":
                self._hops[index].addr = addr
                first_discovery = True

        if first_discovery and self._use_dns:
            dns_thread = threading.Thread(
                target=self._resolve_dns,
                args=(index, addr),
                daemon=True
            )
            dns_thread.start()

        with self._lock:
            self._hops[index].returned += 1
            self._hops[index].last_ms = rtt_ms
            self._hops[index].total_ms += rtt_ms
            if self._hops[index].xmit == 1 or rtt_ms < self._hops[index].best_ms:
                self._hops[index].best_ms = rtt_ms
            if rtt_ms > self._hops[index].worst_ms:
                self._hops[index].worst_ms = rtt_ms

    def get_hop_data(self, index: int) -> dict:
        with self._lock:
            xmit = self._hops[index].xmit
            returned = self._hops[index].returned
            loss_percent = 0 if xmit == 0 else 100 - (100 * returned // xmit)
            avg = 0 if returned == 0 else self._hops[index].total_ms // returned
            return {
                "addr": self._hops[index].addr,
                "xmit": xmit,
                "returned": returned,
                "loss_percent": loss_percent,
                "last": self._hops[index].last_ms,
                "best": self._hops[index].best_ms,
                "worst": self._hops[index].worst_ms,
                "avg": avg,
                "name": self._hops[index].name,
            }

    def get_all_hops(self) -> list:
        """Return list of hop data dicts for all active hops up to current max."""
        max_hops = self._get_max()

        results = []
        for i in range(max_hops):
            hop = self.get_hop_data(i)
            # Only include hops that have responded at least once
            if hop["addr"] == "":
                continue
            hop["nr"] = i + 1
            results.append(hop)
        return results

    def print_report(self):
        """Print a formatted WinMTR-style table to console."""
        hops = self.get_all_hops()
        if not hops:
            print("No hops detected yet.")
            return

        # Header
        header = f"{'|':>1} {'Nr':>3} {'Hostname':<40} {'Loss%':>6} {'Sent':>6} {'Recv':>6} {'Best':>6} {'Avrg':>6} {'Wrst':>6} {'Last':>6}"
        separator = "-" * len(header)

        print(separator)
        print(f"  WinMTR-style trace to {self._target_host} ({self._target_addr})")
        print(separator)
        print(header)
        print(separator)

        for hop in hops:
            display_name = hop["name"] if hop["name"] else hop["addr"] if hop["addr"] else "???"
            # Truncate long hostnames to fit column
            if len(display_name) > 40:
                display_name = display_name[:37] + "..."

            print(
                f"  {hop['nr']:>3} {display_name:<40} {hop['loss_percent']:>5}% {hop['xmit']:>6} {hop['returned']:>6} {hop['best']:>6} {hop['avg']:>6} {hop['worst']:>6} {hop['last']:>6}"
            )

        print(separator)

    def _report_loop(self):
        """Background thread that periodically prints the hop table."""
        while self._tracing:
            time.sleep(REPORT_INTERVAL)
            if self._tracing and DEBUG_MTR_CONSOLE:
                self.print_report()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python mtr_engine.py <hostname>")
        sys.exit(1)
    use_dns = "--no-dns" not in sys.argv
    target = sys.argv[1]

    # Parse optional interval
    interval = DEFAULT_INTERVAL
    for i, arg in enumerate(sys.argv):
        if arg in ("-i", "--interval") and i + 1 < len(sys.argv):
            try:
                interval = float(sys.argv[i + 1])
            except ValueError:
                print(f"Invalid interval value: {sys.argv[i + 1]}, using default {DEFAULT_INTERVAL}")

    # Parse optional payload size
    payload_size = DEFAULT_PAYLOAD_SIZE
    for i, arg in enumerate(sys.argv):
        if arg in ("-s", "--size") and i + 1 < len(sys.argv):
            try:
                payload_size = int(sys.argv[i + 1])
            except ValueError:
                print(f"Invalid size value: {sys.argv[i + 1]}, using default {DEFAULT_PAYLOAD_SIZE}")

    engine = MTREngine(target, payload_size=payload_size, interval=interval, use_dns=use_dns)
    print(f"Tracing {target} | interval={engine._interval}s | size={engine._payload_size} | dns={'on' if use_dns else 'off'}")
    engine.start_trace()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping trace...")
        engine.stop_trace()
        print("\n--- FINAL REPORT ---")
        engine.print_report()
