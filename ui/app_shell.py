import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from ui.mtr import MTRWidget
from ui.scanner_view import ScannerView
from ui.sip_alg_view import SipAlgView
from ui.traceroute_view import TracerouteView
from ui.system_info import SystemInfoView
from ui.full_report_view import FullReportView
from core.logger import logger


class AppShellWindow(QMainWindow):
    _PAGE_TITLES: dict[str, str] = {
        "dashboard": "Welcome to Advanced Network Tool",
        "ip_scanner": "Welcome to IP Scanner",
        "mtr": "Welcome to MTR",
        "traceroute": "Welcome to Traceroute",
        "sip_alg_detector": "Welcome to SIP ALG Detector",
        "system_info": "Welcome to System Info",
        "full_report": "Welcome to Full Report",
    }
    _PAGE_HELP: dict[str, str] = {
        "ip_scanner": (
            "IP Scanner discovers devices on your local network.\n\n"
            "• Select a scan range or use Auto to detect your subnet\n"
            "• Click Scan to find devices via ping sweep + ARP\n"
            "• Results show hostname, IP, MAC address, and vendor\n"
            "• Right-click any device to copy IP/MAC or open in browser"
        ),
        "mtr": (
            "MTR (My Traceroute) combines traceroute and ping.\n\n"
            "• Enter a hostname or IP and click Start\n"
            "• Each hop shows packet loss, latency, and jitter over time\n"
            "• Requires Administrator privileges for raw ICMP sockets\n"
            "• Click Stop to end the trace — data is preserved for the report"
        ),
        "traceroute": (
            "Traceroute maps the network path to a destination.\n\n"
            "• Enter a hostname or IP and click Start\n"
            "• Shows each router hop with 3 latency measurements\n"
            "• Useful for identifying where latency or packet loss occurs"
        ),
        "sip_alg_detector": (
            "SIP ALG Detection checks if your router modifies SIP traffic.\n\n"
            "• Click Run Detection to send a SIP INVITE packet\n"
            "• Green = SIP ALG not detected (good for VoIP)\n"
            "• Red = SIP ALG detected (may cause VoIP issues)\n"
            "• Orange = Unable to determine (firewall may be blocking)"
        ),
        "system_info": (
            "System Info collects your network configuration and speed.\n\n"
            "• Shows hostname, IP addresses, gateway, and MAC address\n"
            "• Runs Cloudflare and Ookla speed tests automatically\n"
            "• Click Refresh to re-collect all information"
        ),
        "full_report": (
            "Full Report compiles results from all tools into one view.\n\n"
            "• Run your desired tools first, then come here\n"
            "• Click Generate Report to compile all results\n"
            "• Use Copy to Clipboard or Export to File to save\n"
            "• Re-generate anytime to capture updated data"
        ),
    }

    def __init__(self) -> None:
        super().__init__()
        logger.debug("UI: App shell initialized")
        self.setWindowTitle("Network Tool Dashboard")
        self.resize(1200, 750)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = self._build_sidebar()
        content = self._build_content_area()

        root.addWidget(sidebar)
        root.addWidget(content, 1)

        self._apply_styles()
        self._set_active_nav("dashboard")

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 20, 18, 20)
        layout.setSpacing(12)

        # Text-based logo: A•N•T
        logo_container = QWidget(sidebar)
        logo_layout = QVBoxLayout(logo_container)
        logo_layout.setContentsMargins(0, 10, 0, 0)
        logo_layout.setSpacing(2)
        logo_layout.setAlignment(Qt.AlignCenter)

        logo_text = QLabel("A\u2009•\u2009N\u2009•\u2009T", logo_container)
        logo_text.setAlignment(Qt.AlignCenter)
        logo_text.setStyleSheet(
            """
            QLabel {
                font-size: 42px;
                font-weight: 300;
                letter-spacing: 4px;
                color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #5bc4ff,
                    stop: 1 #8b6cff
                );
                background: transparent;
                border: none;
            }
            """
        )
        # Qt stylesheet color gradient on text doesn't work — use rich text colors
        logo_text.setTextFormat(Qt.RichText)
        logo_text.setText(
            '<span style="font-size:42px; font-weight:300; color:#6b9eff; letter-spacing:4px;">'
            'A<span style="font-size:10px; color:#4a5a8a; vertical-align:super;">•</span>'
            'N<span style="font-size:10px; color:#4a5a8a; vertical-align:super;">•</span>'
            'T</span>'
        )
        logo_layout.addWidget(logo_text)

        subtitle = QLabel("ADVANCED NETWORK TOOL", logo_container)
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            """
            QLabel {
                color: #6b7aaa;
                font-size: 8px;
                font-weight: 400;
                letter-spacing: 4px;
                background: transparent;
                border: none;
            }
            """
        )
        logo_layout.addWidget(subtitle)

        version_label = QLabel("v1.0", logo_container)
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setFixedWidth(48)
        version_label.setFixedHeight(18)
        version_label.setStyleSheet(
            """
            QLabel {
                color: #5b9bd5;
                font-size: 9px;
                font-weight: 600;
                background-color: #2e376d;
                border: 1px solid #39437b;
                border-radius: 9px;
            }
            """
        )
        # Center the version pill
        version_wrapper = QWidget(logo_container)
        version_wrapper_layout = QHBoxLayout(version_wrapper)
        version_wrapper_layout.setContentsMargins(0, 4, 0, 0)
        version_wrapper_layout.setAlignment(Qt.AlignCenter)
        version_wrapper_layout.addWidget(version_label)
        logo_layout.addWidget(version_wrapper)

        layout.addWidget(logo_container)
        layout.addSpacing(12)

        self.nav_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("dashboard", "Dashboard"),
            ("ip_scanner", "IP Scanner"),
            ("mtr", "MTR"),
            ("traceroute", "Traceroute"),
            ("sip_alg_detector", "SIP ALG Detector"),
            ("system_info", "System Info"),
            ("full_report", "Full Report"),
        ]
        for nav_key, nav_label in nav_items:
            btn = QPushButton(nav_label, sidebar)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setProperty("navRole", "item")
            layout.addWidget(btn)
            self.nav_buttons[nav_key] = btn

        layout.addStretch(1)

        self.nav_buttons["dashboard"].clicked.connect(
            lambda: self._switch_page(0, "dashboard")
        )
        self.nav_buttons["ip_scanner"].clicked.connect(
            lambda: self._switch_page(1, "ip_scanner")
        )
        self.nav_buttons["mtr"].clicked.connect(lambda: self._switch_page(2, "mtr"))
        self.nav_buttons["traceroute"].clicked.connect(
            lambda: self._switch_page(3, "traceroute")
        )
        self.nav_buttons["sip_alg_detector"].clicked.connect(
            lambda: self._switch_page(4, "sip_alg_detector")
        )
        self.nav_buttons["system_info"].clicked.connect(
            lambda: self._switch_page(5, "system_info")
        )
        self.nav_buttons["full_report"].clicked.connect(
            lambda: self._switch_page(6, "full_report")
        )
        return sidebar

    def _build_content_area(self) -> QWidget:
        content_wrap = QWidget(self)
        content_wrap.setObjectName("contentWrap")
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(16)

        self.header_bar = self._build_header_bar(content_wrap)
        content_layout.addWidget(self.header_bar)

        pages_widget = QWidget(content_wrap)
        self.pages = QStackedLayout(pages_widget)
        self.pages.setContentsMargins(0, 0, 0, 0)

        dashboard_page = self._build_dashboard_page()
        ip_scanner_page = self._build_ip_scanner_page()
        mtr_page = self._build_mtr_page()
        traceroute_page = self._build_traceroute_page()
        sip_alg_page = self._build_sip_alg_page()
        system_info_page = self._build_system_info_page()
        full_report_page = self._build_full_report_page()
        self.pages.addWidget(dashboard_page)
        self.pages.addWidget(ip_scanner_page)
        self.pages.addWidget(mtr_page)
        self.pages.addWidget(traceroute_page)
        self.pages.addWidget(sip_alg_page)
        self.pages.addWidget(system_info_page)
        self.pages.addWidget(full_report_page)
        self.pages.setCurrentIndex(0)

        content_layout.addWidget(pages_widget, 1)
        return content_wrap

    def _build_header_bar(self, parent: QWidget) -> QWidget:
        self.header_bar = QWidget(parent)
        self.header_bar.setObjectName("headerBar")
        self.header_bar.setFixedHeight(60)
        self.header_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self.header_bar)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(15)

        self.header_label = QLabel(self._PAGE_TITLES["dashboard"], self.header_bar)
        self.header_label.setStyleSheet(
            """
            QLabel {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3fb8c9,
                    stop: 1 #5b7cff
                );
                color: white;
                border-radius: 16px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: 600;
            }
            """
        )

        # Help info dot — shows tooltip with tool usage help
        self._help_dot = QLabel("ⓘ", self.header_bar)
        self._help_dot.setFixedSize(36, 36)
        self._help_dot.setAlignment(Qt.AlignCenter)
        self._help_dot.setCursor(Qt.PointingHandCursor)
        self._help_dot.setVisible(False)  # hidden on dashboard
        self._help_dot.setStyleSheet(
            """
            QLabel {
                color: #ff4d4d;
                font-size: 22px;
                font-weight: 700;
                background: transparent;
                border: none;
            }
            QLabel:hover {
                color: #ff6b6b;
            }
            QToolTip {
                background-color: #1a2040;
                color: #e0e6ff;
                border: 1px solid #3a4581;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            """
        )
        # Compact system info on the right
        import socket
        hostname = socket.gethostname()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except OSError:
            local_ip = "No network"

        self._header_info = QLabel(f"{hostname}  •  {local_ip}", self.header_bar)
        self._header_info.setStyleSheet(
            """
            QLabel {
                color: #8b97c9;
                font-size: 12px;
                font-weight: 500;
                padding-right: 4px;
            }
            """
        )

        # Left spacer — same width as the right info label to balance centering
        left_spacer = QWidget(self.header_bar)
        left_spacer.setFixedWidth(200)
        layout.addWidget(left_spacer)

        layout.addStretch(1)

        # Center group: dot + banner pill
        center_group = QWidget(self.header_bar)
        center_layout = QHBoxLayout(center_group)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)
        center_layout.addWidget(self._help_dot)
        center_layout.addWidget(self.header_label)

        layout.addWidget(center_group)

        layout.addStretch(1)

        # Right info — fixed width to match left spacer
        self._header_info.setFixedWidth(200)
        self._header_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._header_info)

        return self.header_bar

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("dashboardPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        # Welcome description card
        welcome_card = QFrame(self)
        welcome_card.setObjectName("dashCard")
        welcome_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        welcome_layout = QVBoxLayout(welcome_card)
        welcome_layout.setContentsMargins(24, 20, 24, 20)
        welcome_layout.setSpacing(8)

        welcome_desc = QLabel(
            "A comprehensive network diagnostics suite for IT professionals and network engineers. "
            "Scan your local network to discover devices, trace routes to diagnose connectivity issues, "
            "run continuous MTR tests to monitor link quality, detect SIP ALG interference on your router, "
            "and collect system network configuration with speed tests. "
            "Use the tools in the sidebar, then generate a Full Report to export all results.",
            welcome_card,
        )
        welcome_desc.setWordWrap(True)
        welcome_desc.setStyleSheet(
            """
            QLabel {
                color: #9aaad4;
                font-size: 13px;
                line-height: 1.5;
                background: transparent;
                border: none;
            }
            """
        )
        welcome_layout.addWidget(welcome_desc)

        outer.addWidget(welcome_card)

        # 3x2 grid of status cards
        grid_widget = QWidget(page)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        # Card 1: Network Status
        self._dash_net_card = self._create_dash_card(
            "Network Status",
            "Click Refresh or run System Info",
            icon="🌐"
        )
        grid.addWidget(self._dash_net_card, 0, 0)

        # Card 2: Devices on Network
        self._dash_devices_card = self._create_dash_card(
            "Devices Found",
            "Run IP Scanner to discover",
            icon="💻"
        )
        grid.addWidget(self._dash_devices_card, 0, 1)

        # Card 3: SIP ALG Status
        self._dash_sip_card = self._create_dash_card(
            "SIP ALG Status",
            "Not tested yet",
            icon="📞"
        )
        grid.addWidget(self._dash_sip_card, 0, 2)

        # Card 4: MTR Status
        self._dash_mtr_card = self._create_dash_card(
            "MTR Trace",
            "No trace run yet",
            icon="📡"
        )
        grid.addWidget(self._dash_mtr_card, 1, 0)

        # Card 5: Traceroute
        self._dash_traceroute_card = self._create_dash_card(
            "Traceroute",
            "No trace run yet",
            icon="🔗"
        )
        grid.addWidget(self._dash_traceroute_card, 1, 1)

        # Card 6: Quick Actions
        self._dash_actions_card = self._create_actions_card()
        grid.addWidget(self._dash_actions_card, 1, 2)

        # Make all rows and columns stretch equally
        for col in range(3):
            grid.setColumnStretch(col, 1)
        for row in range(2):
            grid.setRowStretch(row, 1)

        outer.addWidget(grid_widget, 1)  # grid gets the stretch

        # Timer to refresh dashboard cards
        from PySide6.QtCore import QTimer
        self._dash_timer = QTimer(self)
        self._dash_timer.setInterval(2000)
        self._dash_timer.timeout.connect(self._refresh_dashboard)
        self._dash_timer.start()

        return page

    def _create_dash_card(self, title: str, subtitle: str, icon: str = "") -> QFrame:
        """Create a dashboard status card with title, subtitle, and optional icon."""
        card = QFrame(self)
        card.setObjectName("dashCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        # Header row with icon and title
        header = QHBoxLayout()
        header.setSpacing(8)

        if icon:
            icon_label = QLabel(icon, card)
            icon_label.setStyleSheet("font-size: 22px; background: transparent; border: none;")
            header.addWidget(icon_label)

        title_label = QLabel(title, card)
        title_label.setObjectName("cardTitle")
        header.addWidget(title_label)
        header.addStretch(1)

        layout.addLayout(header)

        subtitle_label = QLabel(subtitle, card)
        subtitle_label.setObjectName("dashCardValue")
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet(
            """
            QLabel#dashCardValue {
                color: #9aaad4;
                font-size: 13px;
                padding-top: 4px;
            }
            """
        )
        layout.addWidget(subtitle_label)
        layout.addStretch(1)

        # Store reference to the subtitle for live updates
        card.setProperty("_value_label", subtitle_label)

        return card

    def _create_actions_card(self) -> QFrame:
        """Create the Quick Actions card with buttons to jump to each tool."""
        card = QFrame(self)
        card.setObjectName("dashCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_label = QLabel("⚡", card)
        icon_label.setStyleSheet("font-size: 22px; background: transparent; border: none;")
        header.addWidget(icon_label)
        title_label = QLabel("Quick Actions", card)
        title_label.setObjectName("cardTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        layout.addLayout(header)

        # Action buttons in a grid
        btn_grid = QGridLayout()
        btn_grid.setSpacing(6)

        actions = [
            ("Scan Network", lambda: self._switch_page(1, "ip_scanner")),
            ("Run MTR", lambda: self._switch_page(2, "mtr")),
            ("Traceroute", lambda: self._switch_page(3, "traceroute")),
            ("Full Report", lambda: self._switch_page(6, "full_report")),
        ]

        btn_style = """
            QPushButton {
                background-color: #2e376d;
                color: #d6dcff;
                border: 1px solid #39437b;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3ec9d3, stop: 1 #5d85ff
                );
                color: #ffffff;
                border: none;
            }
        """

        for i, (label, callback) in enumerate(actions):
            btn = QPushButton(label, card)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(callback)
            btn_grid.addWidget(btn, i // 2, i % 2)

        layout.addLayout(btn_grid)
        layout.addStretch(1)

        return card

    def _refresh_dashboard(self):
        """Update dashboard cards with live data from tool views."""
        # Only refresh when dashboard is visible (page index 0)
        if self.pages.currentIndex() != 0:
            return

        # Network Status card
        try:
            view = self.system_info_view
            net_labels = getattr(view, "_net_labels", None)
            if net_labels:
                ip_pair = net_labels.get("primary_local_ipv4")
                gw_pair = net_labels.get("default_gateway")
                pub_pair = net_labels.get("public_ip")
                ip_val = ip_pair[1].text() if ip_pair else "—"
                gw_val = gw_pair[1].text() if gw_pair else "—"
                pub_val = pub_pair[1].text() if pub_pair else "—"
                if ip_val and ip_val != "—":
                    text = f"IP: {ip_val}\nGateway: {gw_val}\nPublic: {pub_val}"
                    self._dash_net_card.property("_value_label").setText(text)
        except Exception:
            pass

        # Devices card
        try:
            table = self.scanner_view.results_table
            count = table.rowCount()
            if count > 0:
                self._dash_devices_card.property("_value_label").setText(
                    f"{count} device{'s' if count != 1 else ''} discovered"
                )
        except Exception:
            pass

        # SIP ALG card
        try:
            import re as _re
            banner_text = self.sip_alg_view.banner.text()
            if banner_text and "Click Run Detection" not in banner_text:
                plain = _re.sub(r"<[^>]+>", " ", banner_text)
                plain = _re.sub(r"\s+", " ", plain).strip()
                # Truncate if too long
                if len(plain) > 60:
                    plain = plain[:57] + "..."
                self._dash_sip_card.property("_value_label").setText(plain)
        except Exception:
            pass

        # MTR card
        try:
            engine = getattr(self.mtr_view, "_engine", None)
            if engine is not None:
                target = getattr(engine, "_target_host", "")
                hops = engine.get_all_hops()
                hop_count = len(hops)
                running = "Running" if engine.is_running else "Stopped"
                self._dash_mtr_card.property("_value_label").setText(
                    f"Target: {target}\n{hop_count} hops • {running}"
                )
        except Exception:
            pass

        # Traceroute card
        try:
            table = self.traceroute_view.results_table
            target = self.traceroute_view.target_input.text().strip()
            count = table.rowCount()
            if count > 0:
                self._dash_traceroute_card.property("_value_label").setText(
                    f"Target: {target}\n{count} hops traced"
                )
        except Exception:
            pass

    def _build_ip_scanner_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("ipScannerPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scanner_view = ScannerView()
        layout.addWidget(self.scanner_view, 1)
        return page

    def _build_mtr_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mtr_view = MTRWidget()
        layout.addWidget(self.mtr_view, 1)
        return page

    def _build_traceroute_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("traceroutePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.traceroute_view = TracerouteView()
        layout.addWidget(self.traceroute_view, 1)
        return page

    def _build_sip_alg_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("sipAlgPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.sip_alg_view = SipAlgView()
        layout.addWidget(self.sip_alg_view, 1)
        return page

    def _build_system_info_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("systemInfoPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.system_info_view = SystemInfoView()
        layout.addWidget(self.system_info_view, 1)
        return page

    def _build_full_report_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("fullReportPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.full_report_view = FullReportView()
        self.full_report_view.set_app_shell(self)
        layout.addWidget(self.full_report_view, 1)
        return page

    def _build_placeholder_page(self, page_title: str) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = QFrame(page)
        card.setObjectName("dashCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(8)

        label = QLabel(page_title, card)
        label.setObjectName("placeholderPageLabel")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        card_layout.addWidget(label)
        card_layout.addStretch(1)

        layout.addWidget(card, 1)
        return page

    def _create_card(self, title: str, subtitle: str) -> QWidget:
        card = QFrame(self)
        card.setObjectName("dashCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title_label = QLabel(title, card)
        title_label.setObjectName("cardTitle")
        subtitle_label = QLabel(subtitle, card)
        subtitle_label.setObjectName("cardSubtitle")

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addStretch(1)
        return card

    def _switch_page(self, index: int, nav: str) -> None:
        self.pages.setCurrentIndex(index)
        self._set_active_nav(nav)

    def _set_active_nav(self, nav: str) -> None:
        for nav_key, btn in self.nav_buttons.items():
            btn.setChecked(nav_key == nav)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.header_label.setText(self._PAGE_TITLES.get(nav, "Welcome"))
        # Update help dot visibility and tooltip
        help_text = self._PAGE_HELP.get(nav, "")
        if help_text:
            self._help_dot.setVisible(True)
            self._help_dot.setToolTip(help_text)
        else:
            self._help_dot.setVisible(False)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #171c3a;
            }
            #sidebar {
                background: #252c5a;
                border-right: 1px solid #2e376d;
            }
            #sidebarTitle {
                color: #f4f6ff;
                font-size: 28px;
                font-weight: 700;
                padding: 8px 0;
            }
            QPushButton[navRole="item"] {
                text-align: left;
                color: #d6dcff;
                background: #2e376d;
                border: 1px solid #39437b;
                border-radius: 20px;
                padding: 11px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton[navRole="item"]:hover {
                background: #384381;
            }
            QPushButton[navRole="item"]:checked {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3ec9d3, stop: 1 #5d85ff
                );
                color: #ffffff;
                border: none;
            }
            #contentWrap {
                background: #1d2450;
            }
            #headerBar {
                background: #212959;
                border-radius: 14px;
                border: 1px solid #2c356b;
            }
            #dashboardPage {
                background: transparent;
            }
            #dashCard {
                background: #252d61;
                border: 1px solid #313b75;
                border-radius: 14px;
            }
            #cardTitle {
                color: #eef2ff;
                font-size: 15px;
                font-weight: 700;
            }
            #cardSubtitle {
                color: #aab3de;
                font-size: 13px;
            }
            #placeholderPageLabel {
                color: #dde3ff;
                font-size: 24px;
                font-weight: 600;
            }
            #ipScannerPage {
                background: transparent;
            }
            #traceroutePage {
                background: transparent;
            }
            #sipAlgPage {
                background: transparent;
            }
            #systemInfoPage {
                background: transparent;
            }
            #fullReportPage {
                background: transparent;
            }
            """
        )


def main(argv: list[str] | None = None) -> int:
    """Launch the Advanced Network Tool shell window."""
    app = QApplication(argv if argv is not None else sys.argv)
    window = AppShellWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
