import sys

from PySide6.QtCore import Qt, QTimer, QMimeData
from PySide6.QtGui import QCloseEvent, QDrag
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
from ui.settings_view import SettingsView
from core.logger import logger
from core.settings_manager import SettingsManager
from core.version import __version__


class AppShellWindow(QMainWindow):
    _PAGE_TITLES: dict[str, str] = {
        "dashboard": "Welcome to Advanced Network Tool",
        "ip_scanner": "Welcome to IP Scanner",
        "mtr": "Welcome to MTR",
        "traceroute": "Welcome to Traceroute",
        "sip_alg_detector": "Welcome to SIP ALG Detector",
        "system_info": "Welcome to System Info",
        "full_report": "Welcome to Full Report",
        "settings": "Application Settings",
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
        "settings": (
            "Adjust app-level preferences and defaults.\n\n"
            "• Save theme, density, and startup page behavior\n"
            "• Control window restore/maximize behavior\n"
            "• Configure MTR defaults and runtime toggles"
        ),
    }
    _DASHBOARD_CARDS: list[tuple[str, str, str]] = [
        ("network_status", "Network Status", "🌐"),
        ("devices_found", "Devices Found", "💻"),
        ("sip_alg", "SIP ALG Status", "📞"),
        ("mtr_trace", "MTR Trace", "📡"),
        ("traceroute", "Traceroute", "🔗"),
        ("quick_actions", "Quick Actions", "⚡"),
    ]

    _PAGE_INDEX: dict[str, int] = {
        "dashboard": 0,
        "ip_scanner": 1,
        "mtr": 2,
        "traceroute": 3,
        "sip_alg_detector": 4,
        "system_info": 5,
        "full_report": 6,
        "settings": 7,
    }
    _THEMES: dict[str, dict[str, str]] = {
        "blue": {
            "main_bg": "#171c3a",
            "sidebar_bg": "#252c5a",
            "sidebar_border": "#2e376d",
            "nav_text": "#d6dcff",
            "nav_bg": "#2e376d",
            "nav_border": "#39437b",
            "nav_hover": "#384381",
            "content_bg": "#1d2450",
            "header_bg": "#212959",
            "header_border": "#2c356b",
            "card_bg": "#252d61",
            "card_border": "#313b75",
            "accent_1": "#3ec9d3",
            "accent_2": "#5d85ff",
            "logo_color": "#6b9eff",
            "logo_dot": "#4a5a8a",
            "subtitle_color": "#6b7aaa",
            "version_text": "#5b9bd5",
            "version_bg": "#2e376d",
            "version_border": "#39437b",
            "header_info": "#8b97c9",
            "card_title": "#eef2ff",
            "card_subtitle": "#aab3de",
            "card_value": "#9aaad4",
            "tooltip_bg": "#1a2040",
            "tooltip_text": "#e0e6ff",
            "tooltip_border": "#3a4581",
        },
        "dark": {
            "main_bg": "#10131f",
            "sidebar_bg": "#151b2d",
            "sidebar_border": "#232b44",
            "nav_text": "#d7def7",
            "nav_bg": "#1c243b",
            "nav_border": "#2c385a",
            "nav_hover": "#293455",
            "content_bg": "#0f1426",
            "header_bg": "#171f38",
            "header_border": "#2a3558",
            "card_bg": "#161e37",
            "card_border": "#2a3558",
            "accent_1": "#3ec9d3",
            "accent_2": "#5d85ff",
            "logo_color": "#6b9eff",
            "logo_dot": "#3a4868",
            "subtitle_color": "#5a6a8a",
            "version_text": "#5b9bd5",
            "version_bg": "#1c243b",
            "version_border": "#2c385a",
            "header_info": "#7a88b0",
            "card_title": "#e0e8ff",
            "card_subtitle": "#8a96c0",
            "card_value": "#8090b8",
            "tooltip_bg": "#141828",
            "tooltip_text": "#d0d8f0",
            "tooltip_border": "#2a3558",
        },
        "midnight": {
            "main_bg": "#0d0b1a",
            "sidebar_bg": "#16102e",
            "sidebar_border": "#2a1f50",
            "nav_text": "#d4ccf0",
            "nav_bg": "#1e1540",
            "nav_border": "#302360",
            "nav_hover": "#2a1d55",
            "content_bg": "#110e22",
            "header_bg": "#1a1435",
            "header_border": "#2d2258",
            "card_bg": "#1a1438",
            "card_border": "#2d2258",
            "accent_1": "#a855f7",
            "accent_2": "#6d28d9",
            "logo_color": "#b07aff",
            "logo_dot": "#5a3d8a",
            "subtitle_color": "#7a6aaa",
            "version_text": "#b07aff",
            "version_bg": "#1e1540",
            "version_border": "#302360",
            "header_info": "#8a7ab8",
            "card_title": "#ede5ff",
            "card_subtitle": "#a899d0",
            "card_value": "#9585c0",
            "tooltip_bg": "#16102e",
            "tooltip_text": "#e0d8f8",
            "tooltip_border": "#3a2d68",
        },
        "green": {
            "main_bg": "#0a120a",
            "sidebar_bg": "#0f1e10",
            "sidebar_border": "#1a3518",
            "nav_text": "#c8f0c8",
            "nav_bg": "#142a14",
            "nav_border": "#1e4020",
            "nav_hover": "#1a3a1a",
            "content_bg": "#0c160c",
            "header_bg": "#122012",
            "header_border": "#1e3820",
            "card_bg": "#122012",
            "card_border": "#1e3820",
            "accent_1": "#22c55e",
            "accent_2": "#16a34a",
            "logo_color": "#4ade80",
            "logo_dot": "#2d6a3e",
            "subtitle_color": "#5a8a5a",
            "version_text": "#4ade80",
            "version_bg": "#142a14",
            "version_border": "#1e4020",
            "header_info": "#78aa78",
            "card_title": "#e0ffe0",
            "card_subtitle": "#88c088",
            "card_value": "#78b078",
            "tooltip_bg": "#0f1e10",
            "tooltip_text": "#d0f0d0",
            "tooltip_border": "#2a5030",
        },
        "teal": {
            "main_bg": "#0a1518",
            "sidebar_bg": "#0f2028",
            "sidebar_border": "#183540",
            "nav_text": "#c8ecf0",
            "nav_bg": "#142830",
            "nav_border": "#1e4048",
            "nav_hover": "#1a3840",
            "content_bg": "#0c1820",
            "header_bg": "#122028",
            "header_border": "#1e3840",
            "card_bg": "#122028",
            "card_border": "#1e3840",
            "accent_1": "#2dd4bf",
            "accent_2": "#0891b2",
            "logo_color": "#5eead4",
            "logo_dot": "#2d6a6a",
            "subtitle_color": "#5a8a90",
            "version_text": "#5eead4",
            "version_bg": "#142830",
            "version_border": "#1e4048",
            "header_info": "#78aab0",
            "card_title": "#e0fffa",
            "card_subtitle": "#88c0c0",
            "card_value": "#78b0b0",
            "tooltip_bg": "#0f2028",
            "tooltip_text": "#d0f0f0",
            "tooltip_border": "#2a5058",
        },
        "light": {
            "main_bg": "#f0f2f5",
            "sidebar_bg": "#ffffff",
            "sidebar_border": "#e0e4ea",
            "nav_text": "#3a4260",
            "nav_bg": "#f0f2f8",
            "nav_border": "#dce0ec",
            "nav_hover": "#e4e8f4",
            "content_bg": "#f5f7fa",
            "header_bg": "#ffffff",
            "header_border": "#e0e4ea",
            "card_bg": "#ffffff",
            "card_border": "#e0e4ea",
            "accent_1": "#0ea5e9",
            "accent_2": "#3b82f6",
            "logo_color": "#2563eb",
            "logo_dot": "#94a3b8",
            "subtitle_color": "#64748b",
            "version_text": "#2563eb",
            "version_bg": "#eff6ff",
            "version_border": "#bfdbfe",
            "header_info": "#64748b",
            "card_title": "#1e293b",
            "card_subtitle": "#64748b",
            "card_value": "#475569",
            "tooltip_bg": "#1e293b",
            "tooltip_text": "#f1f5f9",
            "tooltip_border": "#334155",
        },
        "rose": {
            "main_bg": "#1a0f14",
            "sidebar_bg": "#28141e",
            "sidebar_border": "#40202e",
            "nav_text": "#f0d0dc",
            "nav_bg": "#301828",
            "nav_border": "#4a2838",
            "nav_hover": "#3a2030",
            "content_bg": "#1e1018",
            "header_bg": "#261420",
            "header_border": "#3e2030",
            "card_bg": "#261420",
            "card_border": "#3e2030",
            "accent_1": "#f43f5e",
            "accent_2": "#e11d48",
            "logo_color": "#fb7185",
            "logo_dot": "#8a3a50",
            "subtitle_color": "#aa6a7a",
            "version_text": "#fb7185",
            "version_bg": "#301828",
            "version_border": "#4a2838",
            "header_info": "#b87888",
            "card_title": "#ffe0e8",
            "card_subtitle": "#c08898",
            "card_value": "#b07888",
            "tooltip_bg": "#28141e",
            "tooltip_text": "#f8e0e8",
            "tooltip_border": "#582838",
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.load()
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
        self._apply_settings_to_views(self.settings)
        self._restore_window_behavior()
        self._apply_runtime_behavior(self.settings)
        self._open_startup_page()

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

        self._logo_text = QLabel("A\u2009•\u2009N\u2009•\u2009T", logo_container)
        logo_text = self._logo_text
        logo_text.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_text)

        self._logo_subtitle = QLabel("ADVANCED NETWORK TOOL", logo_container)
        subtitle = self._logo_subtitle
        subtitle.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(subtitle)

        self._version_label = QLabel(f"v{__version__}", logo_container)
        version_label = self._version_label
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setFixedWidth(56)
        version_label.setFixedHeight(18)
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
        settings_btn = QPushButton("Settings", sidebar)
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setCheckable(True)
        settings_btn.setMinimumHeight(44)
        settings_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        settings_btn.setProperty("navRole", "item")
        layout.addWidget(settings_btn)
        self.nav_buttons["settings"] = settings_btn

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
        self.nav_buttons["settings"].clicked.connect(
            lambda: self._switch_page(7, "settings")
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
        settings_page = self._build_settings_page()
        self.pages.addWidget(dashboard_page)
        self.pages.addWidget(ip_scanner_page)
        self.pages.addWidget(mtr_page)
        self.pages.addWidget(traceroute_page)
        self.pages.addWidget(sip_alg_page)
        self.pages.addWidget(system_info_page)
        self.pages.addWidget(full_report_page)
        self.pages.addWidget(settings_page)
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

        # Help info dot — shows tooltip with tool usage help
        self._help_dot = QLabel("ⓘ", self.header_bar)
        self._help_dot.setFixedSize(36, 36)
        self._help_dot.setAlignment(Qt.AlignCenter)
        self._help_dot.setCursor(Qt.PointingHandCursor)
        self._help_dot.setVisible(False)  # hidden on dashboard
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

        # 3x2 grid of status cards — order comes from settings
        self._dash_grid_widget = QWidget(page)
        self._dash_grid = QGridLayout(self._dash_grid_widget)
        self._dash_grid.setContentsMargins(0, 0, 0, 0)
        self._dash_grid.setHorizontalSpacing(16)
        self._dash_grid.setVerticalSpacing(16)

        # Build all cards and store by key
        self._dash_cards: dict[str, QFrame] = {}
        self._dash_net_card = self._create_dash_card("Network Status", "Click Refresh or run System Info", icon="🌐")
        self._dash_devices_card = self._create_dash_card("Devices Found", "Run IP Scanner to discover", icon="💻")
        self._dash_sip_card = self._create_dash_card("SIP ALG Status", "Not tested yet", icon="📞")
        self._dash_mtr_card = self._create_dash_card("MTR Trace", "No trace run yet", icon="📡")
        self._dash_traceroute_card = self._create_dash_card("Traceroute", "No trace run yet", icon="🔗")
        self._dash_actions_card = self._create_actions_card()

        self._dash_cards["network_status"] = self._dash_net_card
        self._dash_cards["devices_found"] = self._dash_devices_card
        self._dash_cards["sip_alg"] = self._dash_sip_card
        self._dash_cards["mtr_trace"] = self._dash_mtr_card
        self._dash_cards["traceroute"] = self._dash_traceroute_card
        self._dash_cards["quick_actions"] = self._dash_actions_card

        # Enable drag-and-drop reordering
        for key, card in self._dash_cards.items():
            card.setProperty("_card_key", key)
            card.setAcceptDrops(True)
            card.installEventFilter(self)

        self._arrange_dashboard_cards()

        outer.addWidget(self._dash_grid_widget, 1)

        # Timer to refresh dashboard cards
        from PySide6.QtCore import QTimer
        self._dash_timer = QTimer(self)
        self._dash_timer.setInterval(2000)
        self._dash_timer.timeout.connect(self._refresh_dashboard)
        self._dash_timer.start()

        return page

    def _arrange_dashboard_cards(self) -> None:
        """Place dashboard cards into the grid according to saved order."""
        # Remove all cards from grid first
        while self._dash_grid.count():
            item = self._dash_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        order = self.settings.get("dashboard", {}).get("card_order", [
            "network_status", "devices_found", "sip_alg",
            "mtr_trace", "traceroute", "quick_actions",
        ])

        # Ensure all keys are present (in case settings are stale)
        all_keys = [k for k, _, _ in self._DASHBOARD_CARDS]
        for key in all_keys:
            if key not in order:
                order.append(key)

        for idx, key in enumerate(order):
            card = self._dash_cards.get(key)
            if card is None:
                continue
            row, col = divmod(idx, 3)
            card.setParent(self._dash_grid_widget)
            self._dash_grid.addWidget(card, row, col)

        for col in range(3):
            self._dash_grid.setColumnStretch(col, 1)
        rows = (len(order) + 2) // 3
        for row in range(rows):
            self._dash_grid.setRowStretch(row, 1)

    def eventFilter(self, obj, event):
        """Handle drag-and-drop reordering of dashboard cards."""
        from PySide6.QtCore import QEvent

        if not hasattr(obj, 'property') or not obj.property("_card_key"):
            return super().eventFilter(obj, event)

        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_source_key = obj.property("_card_key")
            self._drag_start_pos = event.pos()
            return False

        if event.type() == QEvent.MouseMove and hasattr(self, '_drag_start_pos'):
            if (event.pos() - self._drag_start_pos).manhattanLength() < 30:
                return False
            drag = QDrag(obj)
            mime = QMimeData()
            mime.setText(self._drag_source_key)
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction)
            self._drag_start_pos = None
            return True

        if event.type() == QEvent.DragEnter:
            if event.mimeData().hasText():
                event.acceptProposedAction()
            return True

        if event.type() == QEvent.Drop:
            source_key = event.mimeData().text()
            target_key = obj.property("_card_key")
            if source_key and target_key and source_key != target_key:
                order = self.settings.get("dashboard", {}).get("card_order", [
                    "network_status", "devices_found", "sip_alg",
                    "mtr_trace", "traceroute", "quick_actions",
                ])
                if source_key in order and target_key in order:
                    si = order.index(source_key)
                    ti = order.index(target_key)
                    order.insert(ti, order.pop(si))
                    self.settings = self.settings_manager.update(
                        {"dashboard": {"card_order": order}}, save=True
                    )
                    self._arrange_dashboard_cards()
            event.acceptProposedAction()
            return True

        return super().eventFilter(obj, event)

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

    def _build_settings_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.settings_view = SettingsView(self.settings_manager)
        self.settings_view.settings_applied.connect(self._on_settings_applied)
        layout.addWidget(self.settings_view, 1)
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
        if nav == "system_info":
            auto_refresh = bool(
                self.settings.get("app_behavior", {}).get("auto_refresh_system_info", True)
            )
            if auto_refresh:
                self.system_info_view._start_refresh()

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
        theme = self.settings.get("appearance", {}).get("theme", "blue")
        palette = self._palette_for_theme(theme)
        self.setStyleSheet(
            """
            QMainWindow {
                background: %(main_bg)s;
            }
            #sidebar {
                background: %(sidebar_bg)s;
                border-right: 1px solid %(sidebar_border)s;
            }
            #sidebarTitle {
                color: #f4f6ff;
                font-size: 28px;
                font-weight: 700;
                padding: 8px 0;
            }
            QPushButton[navRole="item"] {
                text-align: left;
                color: %(nav_text)s;
                background: %(nav_bg)s;
                border: 1px solid %(nav_border)s;
                border-radius: 20px;
                padding: 11px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton[navRole="item"]:hover {
                background: %(nav_hover)s;
            }
            QPushButton[navRole="item"]:checked {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 %(accent_1)s, stop: 1 %(accent_2)s
                );
                color: #ffffff;
                border: none;
            }
            #contentWrap {
                background: %(content_bg)s;
            }
            #headerBar {
                background: %(header_bg)s;
                border-radius: 14px;
                border: 1px solid %(header_border)s;
            }
            #dashboardPage {
                background: transparent;
            }
            #dashCard {
                background: %(card_bg)s;
                border: 1px solid %(card_border)s;
                border-radius: 14px;
            }
            #cardTitle {
                color: %(card_title)s;
                font-size: 15px;
                font-weight: 700;
            }
            #cardSubtitle {
                color: %(card_subtitle)s;
                font-size: 13px;
            }
            #placeholderPageLabel {
                color: %(card_title)s;
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
            #settingsPage {
                background: transparent;
            }
            """
            % palette
        )
        self._apply_accent_colors(palette)

    def _apply_accent_colors(self, palette: dict[str, str]) -> None:
        """Re-apply inline styles that depend on the current theme accent colors."""
        # Logo text
        self._logo_text.setTextFormat(Qt.RichText)
        self._logo_text.setText(
            '<span style="font-size:42px; font-weight:300; color:%(logo_color)s; letter-spacing:4px;">'
            'A<span style="font-size:10px; color:%(logo_dot)s; vertical-align:super;">•</span>'
            'N<span style="font-size:10px; color:%(logo_dot)s; vertical-align:super;">•</span>'
            'T</span>' % palette
        )
        # Subtitle
        self._logo_subtitle.setStyleSheet(
            "QLabel { color: %(subtitle_color)s; font-size: 8px; font-weight: 400; "
            "letter-spacing: 4px; background: transparent; border: none; }" % palette
        )
        # Version pill
        self._version_label.setStyleSheet(
            "QLabel { color: %(version_text)s; font-size: 9px; font-weight: 600; "
            "background-color: %(version_bg)s; border: 1px solid %(version_border)s; "
            "border-radius: 9px; }" % palette
        )
        # Header pill gradient
        self.header_label.setStyleSheet(
            "QLabel { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 %(accent_1)s, stop:1 %(accent_2)s); "
            "color: white; border-radius: 16px; padding: 6px 18px; "
            "font-size: 13px; font-weight: 600; }" % palette
        )
        # Header info text
        self._header_info.setStyleSheet(
            "QLabel { color: %(header_info)s; font-size: 12px; font-weight: 500; "
            "padding-right: 4px; }" % palette
        )
        # Help dot tooltip
        self._help_dot.setStyleSheet(
            "QLabel { color: #ff4d4d; font-size: 22px; font-weight: 700; "
            "background: transparent; border: none; } "
            "QLabel:hover { color: #ff6b6b; } "
            "QToolTip { background-color: %(tooltip_bg)s; color: %(tooltip_text)s; "
            "border: 1px solid %(tooltip_border)s; border-radius: 8px; "
            "padding: 12px 16px; font-size: 13px; font-family: 'Segoe UI', sans-serif; }" % palette
        )

    def _palette_for_theme(self, theme: str) -> dict[str, str]:
        return self._THEMES.get(theme, self._THEMES["blue"])

    def _apply_settings_to_views(self, settings: dict) -> None:
        self._apply_mtr_defaults(settings)
        self._apply_density(settings)

    def _apply_mtr_defaults(self, settings: dict) -> None:
        defaults = settings.get("mtr_defaults", {})
        try:
            self.mtr_view._interval_input.setValue(float(defaults.get("interval", 0.2)))
            self.mtr_view._size_input.setValue(int(defaults.get("packet_size", 64)))
            self.mtr_view._dns_checkbox.setChecked(bool(defaults.get("dns_enabled", True)))
        except Exception:
            pass

    def _apply_density(self, settings: dict) -> None:
        density = settings.get("appearance", {}).get("density", "comfortable")
        button_height = {"compact": 38, "comfortable": 44, "wide": 50}.get(density, 44)
        sidebar_spacing = {"compact": 8, "comfortable": 12, "wide": 16}.get(density, 12)
        for btn in self.nav_buttons.values():
            btn.setMinimumHeight(button_height)
        parent_layout = self.nav_buttons["dashboard"].parentWidget().layout()
        if isinstance(parent_layout, QVBoxLayout):
            parent_layout.setSpacing(sidebar_spacing)

    def _open_startup_page(self) -> None:
        page_key = self.settings.get("startup", {}).get("default_page", "dashboard")
        page_index = self._PAGE_INDEX.get(page_key, 0)
        self._switch_page(page_index, page_key if page_key in self.nav_buttons else "dashboard")

    def _restore_window_behavior(self) -> None:
        window_cfg = self.settings.get("window", {})
        remember_geometry = bool(window_cfg.get("remember_geometry", True))
        geometry_hex = str(window_cfg.get("geometry", ""))
        if remember_geometry and geometry_hex:
            try:
                self.restoreGeometry(bytes.fromhex(geometry_hex))
            except Exception:
                pass
        if bool(window_cfg.get("start_maximized", False)):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def _apply_runtime_behavior(self, settings: dict) -> None:
        debug_enabled = bool(settings.get("app_behavior", {}).get("debug_console_output", True))
        console_level = logger.level if debug_enabled else 100
        for handler in logger.handlers:
            if handler.__class__.__name__ == "StreamHandler":
                handler.setLevel(console_level)

    def _on_settings_applied(self, updated: dict) -> None:
        self.settings = updated
        self._apply_styles()
        self._apply_settings_to_views(updated)
        self._apply_runtime_behavior(updated)
        self._arrange_dashboard_cards()

    def closeEvent(self, event: QCloseEvent) -> None:
        window_cfg = self.settings.get("window", {})
        payload: dict[str, dict] = {"window": {}}
        if bool(window_cfg.get("remember_geometry", True)):
            payload["window"]["geometry"] = bytes(self.saveGeometry()).hex()
        else:
            payload["window"]["geometry"] = ""
        self.settings = self.settings_manager.update(payload, save=True)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    """Launch the Advanced Network Tool shell window."""
    app = QApplication(argv if argv is not None else sys.argv)
    window = AppShellWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
