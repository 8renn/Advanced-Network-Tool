import ipaddress
import re
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.scanner import get_local_ipv4_scan_cidr, scan_network


def _subprocess_no_window_kwargs() -> dict:
    if sys.platform == "win32":
        kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
        return kwargs
    return {}


class _HostnameEmitter(QObject):
    resolved = Signal(str, str)  # ip, hostname


class _HostnameTask(QRunnable):
    def __init__(self, ip: str, emitter: _HostnameEmitter) -> None:
        super().__init__()
        self._ip = ip
        self._emitter = emitter

    def run(self) -> None:
        name = "Unknown"
        try:
            host, _, _ = socket.gethostbyaddr(self._ip)
            if host:
                name = str(host)
        except Exception:
            name = "Unknown"

        # Fallback: NetBIOS name via nbtstat if DNS is unknown (Windows only).
        if name == "Unknown" and sys.platform == "win32":
            try:
                proc = subprocess.run(
                    ["nbtstat", "-A", self._ip],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                    **_subprocess_no_window_kwargs(),
                )
                output = (proc.stdout or "") + "\n" + (proc.stderr or "")
                for line in output.splitlines():
                    if "<00>" in line and "UNIQUE" in line:
                        parts = line.strip().split()
                        if parts:
                            candidate = parts[0].strip()
                            if candidate and candidate.upper() not in {"UNIQUE", "GROUP"}:
                                name = candidate
                                break
            except Exception:
                pass

        # Final fallback: show IP when name cannot be resolved.
        if not name or name == "Unknown":
            name = self._ip
        self._emitter.resolved.emit(self._ip, name)


class _ScanWorker(QObject):
    device_found = Signal(dict)
    progress = Signal(int, int)
    subnet_completed = Signal(int, int)
    finished = Signal(int)
    error = Signal(str)

    def __init__(self, subnets: list[str]) -> None:
        super().__init__()
        self._subnets = subnets
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            count = 0
            count_lock = threading.Lock()
            seen: set[str] = set()
            seen_lock = threading.Lock()
            total = len(self._subnets)

            def _scan_one_subnet(idx: int, subnet: str) -> None:
                nonlocal count
                self.progress.emit(idx, total)
                for device in scan_network(subnet):
                    if self._stop_event.is_set():
                        break
                    ip = str(device.get("ip", ""))
                    mac = str(device.get("mac", "")).upper()
                    vendor = str(device.get("vendor", "Unknown"))
                    key = f"{ip}|{mac}"
                    if not ip:
                        continue
                    with seen_lock:
                        if key in seen:
                            continue
                        seen.add(key)
                    with count_lock:
                        count += 1
                    self.device_found.emit({"ip": ip, "mac": mac, "vendor": vendor})

            max_workers = 8
            submitted = 0
            completed = 0
            future_map: dict = {}
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for idx, subnet in enumerate(self._subnets, start=1):
                    if self._stop_event.is_set():
                        break
                    fut = pool.submit(_scan_one_subnet, idx, subnet)
                    future_map[fut] = idx
                    submitted += 1

                for fut in as_completed(future_map):
                    if self._stop_event.is_set():
                        break
                    try:
                        fut.result()
                    except Exception as e:
                        self.error.emit(str(e))
                        self._stop_event.set()
                        break
                    completed += 1
                    self.subnet_completed.emit(completed, submitted)
        except Exception as e:
            self.error.emit(str(e))
            return
        self.finished.emit(count)


class ScannerView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(10)

        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.scan_mode_combo = QComboBox(top_bar)
        self.scan_mode_combo.addItems(
            [
                "Auto",
                "Custom",
                "All Common Ranges",
                "192.168.0.1-254",
                "192.168.1.1-254",
                "10.0.0.1-254",
                "172.16.0.1-254",
            ]
        )
        self.scan_mode_combo.setMinimumHeight(40)
        self.scan_mode_combo.setStyleSheet("font-size: 14px; padding: 4px 8px;")

        self.scan_range_input = QLineEdit(top_bar)
        self.scan_range_input.setPlaceholderText("Scan range (e.g. 192.168.1.0/24)")
        self.scan_range_input.setClearButtonEnabled(True)
        self.scan_range_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scan_range_input.setMinimumWidth(260)
        self.scan_range_input.setMinimumHeight(40)
        self.scan_range_input.setStyleSheet("font-size: 14px; padding: 4px 8px;")

        self.scan_button = QPushButton("Scan", top_bar)
        self.scan_button.setMinimumHeight(40)
        self.scan_button.setMinimumWidth(80)
        self.scan_button.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 12px;")
        self.stop_button = QPushButton("Stop", top_bar)
        self.stop_button.setMinimumHeight(40)
        self.stop_button.setMinimumWidth(80)
        self.stop_button.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 12px;")
        self.stop_button.setEnabled(False)

        self.scan_all_checkbox = QCheckBox("All Subnets", top_bar)
        self.scan_all_checkbox.setStyleSheet("font-size: 14px;")
        self.scan_all_checkbox.setVisible(False)
        self.scan_all_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        top_layout.addWidget(self.scan_mode_combo)
        top_layout.addWidget(self.scan_all_checkbox)
        top_layout.addWidget(self.scan_range_input, 1)
        top_layout.addWidget(self.scan_button)
        top_layout.addWidget(self.stop_button)

        self.results_table = QTableWidget(0, 4, self)
        self.results_table.setObjectName("scannerTable")
        self.results_table.setHorizontalHeaderLabels(["Name", "IP", "MAC", "Vendor"])
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setShowGrid(False)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_table.setStyleSheet(
            """
            QTableWidget#scannerTable {
                background-color: #1f2646;
                alternate-background-color: #242d52;
                color: #e8eeff;
                border: 1px solid #334071;
                border-radius: 10px;
                gridline-color: #2c3764;
                selection-background-color: #315ea8;
                selection-color: #ffffff;
            }
            QTableWidget#scannerTable::item {
                padding: 6px 8px;
                border: none;
            }
            QTableWidget#scannerTable::item:hover {
                background-color: #2f6fed;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #19203d;
                color: #dbe5ff;
                border: none;
                border-bottom: 1px solid #334071;
                padding: 8px 6px;
                font-weight: 600;
            }
            """
        )

        self.status_label = QLabel("Ready", self)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        root_layout.addWidget(top_bar)
        root_layout.addWidget(self.results_table, 1)
        root_layout.addWidget(self.status_label)

        self._set_initial_column_widths()
        self._connect_signals()

        self._scan_thread: QThread | None = None
        self._scan_worker: _ScanWorker | None = None
        self._scan_count: int = 0
        self._sorting_was_enabled: bool = True

        self._hostname_pool = QThreadPool(self)
        self._hostname_pool.setMaxThreadCount(16)
        self._hostname_emitter = _HostnameEmitter()
        self._hostname_emitter.resolved.connect(self._on_hostname_resolved)
        self._name_item_by_ip: dict[str, QTableWidgetItem] = {}
        self._hostname_pending: set[str] = set()
        self.scan_all_subnets: bool = False

    def _connect_signals(self) -> None:
        self.scan_button.clicked.connect(self._on_scan_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.scan_range_input.returnPressed.connect(self._trigger_scan)
        self.scan_mode_combo.currentIndexChanged.connect(self._on_scan_mode_changed)
        self.scan_all_checkbox.toggled.connect(self._on_scan_all_toggled)
        self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self._show_results_context_menu)
        self._on_scan_mode_changed()

    @staticmethod
    def _cidr_to_host_range(cidr: str) -> str:
        """Convert '192.168.68.0/24' to '192.168.68.1-254' display format."""
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            hosts = list(net.hosts())
            if not hosts:
                return cidr
            first = str(hosts[0])
            last_octet = str(hosts[-1]).split(".")[-1]
            return f"{first}-{last_octet}"
        except Exception:
            return cidr

    def _detect_local_cidr(self) -> str:
        try:
            cidr = get_local_ipv4_scan_cidr()
            return self._cidr_to_host_range(cidr)
        except Exception:
            return "192.168.1.1-254"

    def _on_scan_all_toggled(self, checked: bool) -> None:
        self.scan_all_subnets = bool(checked)

    def _on_scan_mode_changed(self) -> None:
        mode = self.scan_mode_combo.currentText()
        if mode == "Custom":
            self.scan_range_input.setReadOnly(False)
            self.scan_range_input.setPlaceholderText("e.g. 192.168.1.1-254, 10.0.0.1-254")
            self.scan_range_input.setFocus()
            self.scan_all_checkbox.setVisible(False)
            return

        self.scan_range_input.setReadOnly(True)
        self.scan_all_checkbox.setVisible(mode == "Auto")

        if mode == "Auto":
            self.scan_range_input.setText(self._detect_local_cidr())
            return
        if mode == "All Common Ranges":
            self.scan_range_input.setText(
                "192.168.0.1-254, 192.168.1.1-254, 10.0.0.1-254, 172.16.0.1-254"
            )
            return
        self.scan_range_input.setText(mode)

    def _parse_subnets_for_scan(self) -> list[str]:
        """Parse the range input into a list of CIDR strings for scanning."""
        raw = self.scan_range_input.text().strip()
        if not raw:
            return []
        subnets: list[str] = []
        for part in raw.split(","):
            token = part.strip()
            if not token:
                continue
            token = token.replace("\u2013", "-").replace("\u2014", "-")  # en-dash, em-dash
            if "-" in token and "/" not in token:
                # Format: "192.168.68.1-254" → extract base IP, build /24
                left = token.split("-", 1)[0].strip()
                try:
                    # Validate it's a real IP
                    ipaddress.ip_address(left)
                    net = ipaddress.ip_network(f"{left}/24", strict=False)
                    subnets.append(str(net))
                    continue
                except (ValueError, Exception):
                    continue
            try:
                net = ipaddress.ip_network(token, strict=False)
                subnets.append(str(net))
            except (ValueError, Exception):
                continue
        return subnets

    def _trigger_scan(self) -> None:
        if self.scan_button.isEnabled():
            self.scan_button.click()

    def _is_valid_ipv4(self, ip: str) -> bool:
        ip = (ip or "").strip()
        if not ip or ip.upper() in {"UNKNOWN", "RESOLVING...", "N/A", "-"}:
            return False
        try:
            addr = ipaddress.ip_address(ip)
            return addr.version == 4
        except Exception:
            return False

    def _is_valid_mac(self, mac: str) -> bool:
        mac = (mac or "").strip().upper()
        if not mac or mac in {"UNKNOWN", "RESOLVING...", "N/A", "-"}:
            return False
        return re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac) is not None

    def _show_results_context_menu(self, pos) -> None:
        try:
            index = self.results_table.indexAt(pos)
        except Exception:
            return
        if not index.isValid():
            return
        row = index.row()
        if row < 0:
            return
        try:
            if row >= self.results_table.rowCount():
                return
        except Exception:
            return

        try:
            self.results_table.setCurrentCell(row, index.column())
            self.results_table.selectRow(row)
        except Exception:
            return

        try:
            ip_item = self.results_table.item(row, 1)
            mac_item = self.results_table.item(row, 2)
        except Exception:
            return
        ip = (ip_item.text().strip() if ip_item else "")
        mac = (mac_item.text().strip().upper() if mac_item else "")
        ip_valid = self._is_valid_ipv4(ip)
        mac_valid = self._is_valid_mac(mac)

        menu = QMenu(self)
        open_http = menu.addAction("Open HTTP")
        open_https = menu.addAction("Open HTTPS")
        menu.addSeparator()
        copy_ip = menu.addAction("Copy IP")
        copy_mac = menu.addAction("Copy MAC")
        open_http.setEnabled(ip_valid)
        open_https.setEnabled(ip_valid)
        copy_ip.setEnabled(ip_valid)
        copy_mac.setEnabled(mac_valid)

        def do_copy(text: str) -> None:
            try:
                QGuiApplication.clipboard().setText(text)
            except Exception:
                pass

        def do_open(url: str) -> None:
            try:
                QDesktopServices.openUrl(QUrl(url))
            except Exception:
                pass

        open_http.triggered.connect(lambda: do_open(f"http://{ip}"))
        open_https.triggered.connect(lambda: do_open(f"https://{ip}"))
        copy_ip.triggered.connect(lambda: do_copy(ip))
        copy_mac.triggered.connect(lambda: do_copy(mac))

        try:
            menu.exec(self.results_table.viewport().mapToGlobal(pos))
        except Exception:
            return

    def _on_scan_clicked(self) -> None:
        subnets = self._parse_subnets_for_scan()
        if not subnets:
            self.status_label.setText("Ready")
            return

        self.results_table.setRowCount(0)
        self.status_label.setText("Scanning...")
        self._scan_count = 0
        self._name_item_by_ip.clear()
        self._hostname_pending.clear()
        self._sorting_was_enabled = self.results_table.isSortingEnabled()
        self.results_table.setSortingEnabled(False)
        self.scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        thread = QThread(self)
        worker = _ScanWorker(subnets)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.device_found.connect(self._on_device_found)
        worker.progress.connect(self._on_scan_subnet_progress)
        worker.subnet_completed.connect(self._on_scan_subnet_completed)
        worker.finished.connect(self._on_scan_finished_with_count)
        worker.error.connect(self._on_scan_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_scan_finished)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _on_stop_clicked(self) -> None:
        if self._scan_worker is None:
            return
        self.status_label.setText("Stopping...")
        self.stop_button.setEnabled(False)
        self._scan_worker.request_stop()

    def _on_scan_subnet_progress(self, current: int, total: int) -> None:
        self.status_label.setText(f"Scanning subnet {current} of {total}")

    def _on_scan_subnet_completed(self, completed: int, total: int) -> None:
        self.status_label.setText(f"Completed subnet {completed} of {total}")

    def _on_device_found(self, device: dict) -> None:
        self._scan_count += 1
        ip = str(device.get("ip", "")).strip()
        mac = str(device.get("mac", "")).strip()
        vendor = str(device.get("vendor", "Unknown")).strip() or "Unknown"
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        name_item = QTableWidgetItem("Resolving...")
        self.results_table.setItem(row, 0, name_item)
        self.results_table.setItem(row, 1, QTableWidgetItem(ip))
        self.results_table.setItem(row, 2, QTableWidgetItem(mac))
        self.results_table.setItem(row, 3, QTableWidgetItem(vendor))
        if ip and ip not in self._name_item_by_ip:
            self._name_item_by_ip[ip] = name_item
            self._start_hostname_lookup(ip)

    def _on_scan_finished_with_count(self, count: int) -> None:
        self._scan_count = count
        self.status_label.setText(f"Completed - {count} devices found")

    def _on_scan_error(self, message: str) -> None:
        self.status_label.setText(f"Error - {message}")

    def _on_scan_finished(self) -> None:
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._scan_worker = None
        self._scan_thread = None
        self.results_table.setSortingEnabled(self._sorting_was_enabled)
        # Sort by IP address column (column 1) ascending
        self.results_table.sortByColumn(1, Qt.AscendingOrder)

    def _start_hostname_lookup(self, ip: str) -> None:
        if ip in self._hostname_pending:
            return
        self._hostname_pending.add(ip)
        self._hostname_pool.start(_HostnameTask(ip, self._hostname_emitter))

    def _on_hostname_resolved(self, ip: str, hostname: str) -> None:
        self._hostname_pending.discard(ip)
        item = self._name_item_by_ip.get(ip)
        if item is None:
            return
        item.setText(hostname if hostname and hostname != "Unknown" else ip)

    def _populate_results(self, devices: list[dict]) -> None:
        self.results_table.setRowCount(0)
        self.results_table.setSortingEnabled(False)
        try:
            for d in devices:
                row = self.results_table.rowCount()
                self.results_table.insertRow(row)
                self.results_table.setItem(row, 0, QTableWidgetItem("Unknown"))
                self.results_table.setItem(row, 1, QTableWidgetItem(str(d.get("ip", ""))))
                self.results_table.setItem(row, 2, QTableWidgetItem(str(d.get("mac", ""))))
                self.results_table.setItem(row, 3, QTableWidgetItem("Unknown"))
        finally:
            self.results_table.setSortingEnabled(True)

    def _set_initial_column_widths(self) -> None:
        self.results_table.setColumnWidth(0, 220)
        self.results_table.setColumnWidth(1, 140)
        self.results_table.setColumnWidth(2, 170)
        self.results_table.setColumnWidth(3, 260)
