import datetime
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class FullReportView(QWidget):
    """Aggregates results from all tools into a single exportable text report."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_shell = None  # set by app_shell after construction
        self._setup_ui()

    def set_app_shell(self, shell):
        """Called by AppShellWindow to give this view access to other views."""
        self._app_shell = shell

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Top bar with buttons
        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self._generate_btn = QPushButton("Generate Report", top_bar)
        self._generate_btn.setFixedWidth(140)
        self._generate_btn.clicked.connect(self._generate_report)
        top_layout.addWidget(self._generate_btn)

        self._copy_btn = QPushButton("Copy to Clipboard", top_bar)
        self._copy_btn.setFixedWidth(140)
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        top_layout.addWidget(self._copy_btn)

        self._export_btn = QPushButton("Export to File", top_bar)
        self._export_btn.setFixedWidth(120)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_to_file)
        top_layout.addWidget(self._export_btn)

        top_layout.addStretch(1)
        layout.addWidget(top_bar)

        # Report text area
        self._text_edit = QTextEdit(self)
        self._text_edit.setObjectName("reportTextEdit")
        self._text_edit.setReadOnly(True)
        self._text_edit.setPlaceholderText(
            "Click 'Generate Report' to compile results from all tools."
        )
        self._text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text_edit.setStyleSheet(
            """
            QTextEdit#reportTextEdit {
                background-color: #1f2646;
                color: #e8eeff;
                border: 1px solid #334071;
                border-radius: 10px;
                padding: 12px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
            }
            """
        )
        layout.addWidget(self._text_edit, 1)

        # Status label
        self._status_label = QLabel("Ready", self)
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._status_label)

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _generate_report(self):
        if self._app_shell is None:
            self._text_edit.setPlainText(
                "Error: Report view not connected to application."
            )
            return

        sep = "=" * 72
        thin = "-" * 72
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sections = [
            sep,
            "  NETWORK TOOL — FULL REPORT",
            f"  Generated: {timestamp}",
            sep,
            "",
            self._section_system_info(thin),
            "",
            self._section_ip_scanner(thin),
            "",
            self._section_mtr(thin),
            "",
            self._section_traceroute(thin),
            "",
            self._section_sip_alg(thin),
            "",
            sep,
            "  END OF REPORT",
            sep,
        ]

        report_text = "\n".join(sections)
        self._text_edit.setPlainText(report_text)
        self._copy_btn.setEnabled(True)
        self._export_btn.setEnabled(True)
        self._status_label.setText(f"Report generated at {timestamp}")

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _section_system_info(self, sep: str) -> str:
        lines = [sep, "  SYSTEM INFORMATION", sep]
        try:
            view = self._app_shell.system_info_view

            # Read network fields from the QLabel value widgets.
            # _net_labels is dict[str, tuple[QLabel, QLabel]] — we want index [1] (value).
            net_labels = getattr(view, "_net_labels", None)
            if net_labels is None or not net_labels:
                lines.append("  No data available — run System Info first.")
                return "\n".join(lines)

            # Check if data has been loaded (value is still "—" when not yet run)
            hostname_val = ""
            hostname_pair = net_labels.get("hostname")
            if hostname_pair:
                hostname_val = hostname_pair[1].text()
            if not hostname_val or hostname_val == "—":
                lines.append("  No data available — run System Info first.")
                return "\n".join(lines)

            field_order = [
                ("Hostname", "hostname"),
                ("Local IPv4", "primary_local_ipv4"),
                ("Subnet Mask", "subnet_mask"),
                ("Default Gateway", "default_gateway"),
                ("MAC Address", "mac_address"),
                ("Public IP", "public_ip"),
                ("Adapter", "adapter_name"),
                ("Adapter IPv4", "adapter_ipv4"),
            ]
            for display_name, key in field_order:
                pair = net_labels.get(key)
                val = pair[1].text() if pair else "Unavailable"
                lines.append(f"  {display_name + ':':<20} {val}")

            # Speed tests
            for label, speed_labels_attr, status_attr in [
                ("Ookla Speedtest", "_ookla_labels", "_ookla_status"),
                ("Google", "_google_labels", "_google_status"),
            ]:
                lines.append("")
                lines.append(f"  Speed Test — {label}:")
                speed_labels = getattr(view, speed_labels_attr, {})
                status_lbl = getattr(view, status_attr, None)
                if status_lbl:
                    lines.append(f"    Status:    {status_lbl.text()}")
                for key in ("download", "upload", "latency", "jitter"):
                    lbl = speed_labels.get(key)
                    val = lbl.text() if lbl else "Unavailable"
                    lines.append(f"    {key.capitalize() + ':':<11} {val}")

        except Exception as e:
            lines.append(f"  Error reading system info: {e}")
        return "\n".join(lines)

    def _section_ip_scanner(self, sep: str) -> str:
        lines = [sep, "  IP SCANNER RESULTS", sep]
        try:
            view = self._app_shell.scanner_view
            table = view.results_table
            row_count = table.rowCount()
            if row_count == 0:
                lines.append("  No data available — run IP Scanner first.")
                return "\n".join(lines)

            lines.append(f"  Devices found: {row_count}")
            lines.append("")
            lines.append(f"  {'Name':<30} {'IP':<18} {'MAC':<20} {'Vendor'}")
            lines.append("  " + "-" * 90)

            for row in range(row_count):
                name = table.item(row, 0).text() if table.item(row, 0) else ""
                ip = table.item(row, 1).text() if table.item(row, 1) else ""
                mac = table.item(row, 2).text() if table.item(row, 2) else ""
                vendor = table.item(row, 3).text() if table.item(row, 3) else ""
                lines.append(f"  {name:<30} {ip:<18} {mac:<20} {vendor}")
        except Exception as e:
            lines.append(f"  Error reading scanner data: {e}")
        return "\n".join(lines)

    def _section_mtr(self, sep: str) -> str:
        lines = [sep, "  MTR (WinMTR) RESULTS", sep]
        try:
            view = self._app_shell.mtr_view
            engine = getattr(view, "_engine", None)
            if engine is None:
                lines.append("  No data available — run MTR first.")
                return "\n".join(lines)

            target_host = getattr(engine, "_target_host", "Unknown")
            target_addr = getattr(engine, "_target_addr", "Unknown")
            lines.append(f"  Target: {target_host} ({target_addr})")
            lines.append("")

            hops = engine.get_all_hops()
            if not hops:
                lines.append("  No hops detected.")
                return "\n".join(lines)

            lines.append(
                f"  {'Nr':>3}  {'Hostname':<40} {'Loss%':>6} {'Sent':>6} "
                f"{'Recv':>6} {'Best':>6} {'Avrg':>6} {'Wrst':>6} {'Last':>6}"
            )
            lines.append("  " + "-" * 94)

            for hop in hops:
                display = hop["name"] if hop["name"] else hop["addr"] if hop["addr"] else "???"
                if len(display) > 40:
                    display = display[:37] + "..."
                lines.append(
                    f"  {hop['nr']:>3}  {display:<40} {hop['loss_percent']:>5}% "
                    f"{hop['xmit']:>6} {hop['returned']:>6} {hop['best']:>6} "
                    f"{hop['avg']:>6} {hop['worst']:>6} {hop['last']:>6}"
                )
        except Exception as e:
            lines.append(f"  Error reading MTR data: {e}")
        return "\n".join(lines)

    def _section_traceroute(self, sep: str) -> str:
        lines = [sep, "  TRACEROUTE RESULTS", sep]
        try:
            view = self._app_shell.traceroute_view
            table = view.results_table
            row_count = table.rowCount()
            if row_count == 0:
                lines.append("  No data available — run Traceroute first.")
                return "\n".join(lines)

            target = view.target_input.text().strip()
            if target:
                lines.append(f"  Target: {target}")
                lines.append("")

            lines.append(
                f"  {'Hop':>4}  {'Hostname':<35} {'IP':<18} "
                f"{'Time 1':>8} {'Time 2':>8} {'Time 3':>8}"
            )
            lines.append("  " + "-" * 90)

            for row in range(row_count):
                hop = table.item(row, 0).text() if table.item(row, 0) else ""
                hostname = table.item(row, 1).text() if table.item(row, 1) else ""
                ip = table.item(row, 2).text() if table.item(row, 2) else ""
                t1 = table.item(row, 3).text() if table.item(row, 3) else ""
                t2 = table.item(row, 4).text() if table.item(row, 4) else ""
                t3 = table.item(row, 5).text() if table.item(row, 5) else ""
                if len(hostname) > 35:
                    hostname = hostname[:32] + "..."
                lines.append(
                    f"  {hop:>4}  {hostname:<35} {ip:<18} "
                    f"{t1:>8} {t2:>8} {t3:>8}"
                )
        except Exception as e:
            lines.append(f"  Error reading traceroute data: {e}")
        return "\n".join(lines)

    def _section_sip_alg(self, sep: str) -> str:
        lines = [sep, "  SIP ALG DETECTION", sep]
        try:
            view = self._app_shell.sip_alg_view
            banner_text = view.banner.text()

            # Check if still in idle state
            if "Click Run Detection" in banner_text or not banner_text.strip():
                lines.append("  No data available — run SIP ALG Detection first.")
                return "\n".join(lines)

            # Strip HTML tags to get plain text result
            plain = re.sub(r"<[^>]+>", " ", banner_text)
            plain = re.sub(r"\s+", " ", plain).strip()
            lines.append(f"  Result: {plain}")
        except Exception as e:
            lines.append(f"  Error reading SIP ALG data: {e}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _copy_to_clipboard(self):
        text = self._text_edit.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self._status_label.setText("Report copied to clipboard.")

    def _export_to_file(self):
        text = self._text_edit.toPlainText()
        if not text:
            return
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"network_report_{timestamp}.txt"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Report",
            default_name,
            "Text Files (*.txt);;All Files (*)",
        )
        if filepath:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                self._status_label.setText(f"Report exported to {filepath}")
            except Exception as e:
                self._status_label.setText(f"Export failed: {e}")

