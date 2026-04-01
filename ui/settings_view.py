from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.settings_manager import DEFAULT_SETTINGS, SettingsManager


class SettingsView(QWidget):
    settings_applied = Signal(dict)

    def __init__(self, settings_manager: SettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_manager = settings_manager
        self._controls: dict[str, QWidget] = {}
        self._build_ui()
        self.load_from_settings(self._settings_manager.snapshot())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        title = QLabel("Settings", top_bar)
        title.setObjectName("settingsTitle")
        subtitle = QLabel("Configure application behavior and startup defaults.", top_bar)
        subtitle.setObjectName("settingsSubtitle")

        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(2)
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)

        top_layout.addLayout(title_wrap)
        top_layout.addStretch(1)

        self.save_btn = QPushButton("Save", top_bar)
        self.reset_btn = QPushButton("Reset to Defaults", top_bar)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setProperty("variant", "primary")
        self.reset_btn.setProperty("variant", "secondary")
        top_layout.addWidget(self.reset_btn)
        top_layout.addWidget(self.save_btn)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setObjectName("settingsScroll")

        inner = QWidget()
        inner.setObjectName("settingsInner")
        scroll.setWidget(inner)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 0)
        inner_layout.setSpacing(12)

        inner_layout.addWidget(self._build_appearance_card())
        inner_layout.addWidget(self._build_startup_card())
        inner_layout.addWidget(self._build_window_card())
        inner_layout.addWidget(self._build_mtr_card())
        inner_layout.addWidget(self._build_behavior_card())
        inner_layout.addWidget(self._build_dashboard_card())
        inner_layout.addStretch(1)

        root.addWidget(top_bar)
        root.addWidget(scroll, 1)

        self.save_btn.clicked.connect(self._on_save_clicked)
        self.reset_btn.clicked.connect(self._on_reset_clicked)

        self.setStyleSheet(
            """
            #settingsTitle {
                color: #eef2ff;
                font-size: 18px;
                font-weight: 700;
            }
            #settingsSubtitle {
                color: #9aa7d4;
                font-size: 12px;
            }
            #settingsScroll {
                background: transparent;
            }
            #settingsInner {
                background: transparent;
            }
            QFrame#settingsCard {
                background-color: #1f2646;
                border: 1px solid #334071;
                border-radius: 12px;
            }
            QLabel#settingsCardTitle {
                color: #dbe5ff;
                font-size: 15px;
                font-weight: 700;
                padding-bottom: 2px;
            }
            QLabel#settingsCardHint {
                color: #8b97c9;
                font-size: 12px;
            }
            QLabel#settingsLabel {
                color: #cfd9ff;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#settingsValueHelp {
                color: #8b97c9;
                font-size: 11px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                min-height: 34px;
                border-radius: 9px;
                border: 1px solid #3b4a7f;
                background: #252d52;
                color: #e8eeff;
                padding: 4px 10px;
                selection-background-color: #2f6fed;
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QCheckBox {
                color: #e8eeff;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid #4a5d9a;
                background: #1a2142;
            }
            QCheckBox::indicator:checked {
                background: #2f6fed;
                border: 1px solid #2f6fed;
            }
            QPushButton[variant="primary"] {
                background-color: #2f6fed;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                min-height: 36px;
                padding: 0 18px;
                font-weight: 700;
            }
            QPushButton[variant="primary"]:hover {
                background-color: #4a82ff;
            }
            QPushButton[variant="secondary"] {
                background-color: #2e376d;
                color: #d6dcff;
                border: 1px solid #39437b;
                border-radius: 10px;
                min-height: 36px;
                padding: 0 14px;
                font-weight: 600;
            }
            QPushButton[variant="secondary"]:hover {
                background-color: #384381;
            }
            """
        )

    def _build_card(self, title: str, hint: str) -> tuple[QFrame, QGridLayout]:
        card = QFrame(self)
        card.setObjectName("settingsCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_lbl = QLabel(title, card)
        title_lbl.setObjectName("settingsCardTitle")
        hint_lbl = QLabel(hint, card)
        hint_lbl.setObjectName("settingsCardHint")
        hint_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)
        layout.addWidget(hint_lbl)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card, grid

    def _row_label(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setObjectName("settingsLabel")
        return lbl

    def _build_appearance_card(self) -> QFrame:
        card, grid = self._build_card(
            "Appearance",
            "Theme and layout spacing preferences.",
        )
        theme = QComboBox(card)
        theme.addItem("Blue (default)", "blue")
        theme.addItem("Dark", "dark")
        theme.addItem("Midnight", "midnight")
        theme.addItem("Green", "green")
        theme.addItem("Teal", "teal")
        theme.addItem("Light", "light")
        theme.addItem("Rose", "rose")
        density = QComboBox(card)
        density.addItem("Compact", "compact")
        density.addItem("Comfortable", "comfortable")
        density.addItem("Wide", "wide")
        self._controls["appearance.theme"] = theme
        self._controls["appearance.density"] = density
        grid.addWidget(self._row_label("Theme"), 0, 0)
        grid.addWidget(theme, 0, 1)
        grid.addWidget(self._row_label("Layout density"), 1, 0)
        grid.addWidget(density, 1, 1)
        return card

    def _build_startup_card(self) -> QFrame:
        card, grid = self._build_card(
            "Startup",
            "Choose which page opens first when the app launches.",
        )
        startup = QComboBox(card)
        startup_items = [
            ("Dashboard", "dashboard"),
            ("IP Scanner", "ip_scanner"),
            ("MTR", "mtr"),
            ("Traceroute", "traceroute"),
            ("SIP ALG Detector", "sip_alg_detector"),
            ("System Info", "system_info"),
            ("Full Report", "full_report"),
        ]
        for label, value in startup_items:
            startup.addItem(label, value)
        self._controls["startup.default_page"] = startup
        grid.addWidget(self._row_label("Default startup page"), 0, 0)
        grid.addWidget(startup, 0, 1)
        return card

    def _build_window_card(self) -> QFrame:
        card, grid = self._build_card(
            "Window",
            "Control startup window state and geometry behavior.",
        )
        remember = QCheckBox("Remember window size and position", card)
        maximized = QCheckBox("Start maximized", card)
        self._controls["window.remember_geometry"] = remember
        self._controls["window.start_maximized"] = maximized
        grid.addWidget(remember, 0, 0, 1, 2)
        grid.addWidget(maximized, 1, 0, 1, 2)
        return card

    def _build_mtr_card(self) -> QFrame:
        card, grid = self._build_card(
            "MTR Defaults",
            "Default values used when opening the MTR page.",
        )
        interval = QDoubleSpinBox(card)
        interval.setRange(0.1, 10.0)
        interval.setDecimals(1)
        interval.setSingleStep(0.1)
        interval.setSuffix(" s")

        packet_size = QSpinBox(card)
        packet_size.setRange(64, 4096)
        packet_size.setSuffix(" B")

        dns = QCheckBox("Enable DNS by default", card)
        self._controls["mtr_defaults.interval"] = interval
        self._controls["mtr_defaults.packet_size"] = packet_size
        self._controls["mtr_defaults.dns_enabled"] = dns
        grid.addWidget(self._row_label("Default interval"), 0, 0)
        grid.addWidget(interval, 0, 1)
        grid.addWidget(self._row_label("Default packet size"), 1, 0)
        grid.addWidget(packet_size, 1, 1)
        grid.addWidget(dns, 2, 0, 1, 2)
        return card

    def _build_behavior_card(self) -> QFrame:
        card, grid = self._build_card(
            "App Behavior",
            "Runtime behavior toggles.",
        )
        debug = QCheckBox("Enable debug console output", card)
        auto_refresh = QCheckBox("Auto-refresh System Info on open", card)
        self._controls["app_behavior.debug_console_output"] = debug
        self._controls["app_behavior.auto_refresh_system_info"] = auto_refresh
        grid.addWidget(debug, 0, 0, 1, 2)
        grid.addWidget(auto_refresh, 1, 0, 1, 2)
        return card

    def _build_dashboard_card(self) -> QFrame:
        card, grid = self._build_card(
            "Dashboard Layout",
            "Drag cards on the dashboard to reorder, or use the buttons below.",
        )
        from PySide6.QtWidgets import QListWidget, QAbstractItemView

        order_list = QListWidget(card)
        order_list.setDragDropMode(QAbstractItemView.InternalMove)
        order_list.setDefaultDropAction(Qt.MoveAction)
        order_list.setMinimumHeight(180)
        order_list.setStyleSheet(
            """
            QListWidget {
                background: #252d52;
                color: #e8eeff;
                border: 1px solid #3b4a7f;
                border-radius: 9px;
                padding: 4px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background: #2f6fed;
            }
            QListWidget::item:hover {
                background: #353f6a;
            }
            """
        )
        self._controls["dashboard.card_order"] = order_list
        grid.addWidget(order_list, 0, 0, 1, 2)

        reset_order_btn = QPushButton("Reset Order", card)
        reset_order_btn.setCursor(Qt.PointingHandCursor)
        reset_order_btn.setProperty("variant", "secondary")
        reset_order_btn.clicked.connect(self._reset_dashboard_order)
        grid.addWidget(reset_order_btn, 1, 0, 1, 2)

        return card

    def _reset_dashboard_order(self) -> None:
        default_order = ["network_status", "devices_found", "sip_alg",
                         "mtr_trace", "traceroute", "quick_actions"]
        order_list = self._controls["dashboard.card_order"]
        order_list.clear()
        labels = {
            "network_status": "🌐  Network Status",
            "devices_found": "💻  Devices Found",
            "sip_alg": "📞  SIP ALG Status",
            "mtr_trace": "📡  MTR Trace",
            "traceroute": "🔗  Traceroute",
            "quick_actions": "⚡  Quick Actions",
        }
        for key in default_order:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(labels.get(key, key))
            item.setData(Qt.UserRole, key)
            order_list.addItem(item)

    def load_from_settings(self, settings: dict[str, Any]) -> None:
        self._set_combo_by_data("appearance.theme", str(settings["appearance"]["theme"]))
        self._set_combo_by_data("appearance.density", str(settings["appearance"]["density"]))
        self._set_combo_by_data("startup.default_page", str(settings["startup"]["default_page"]))

        self._controls["window.remember_geometry"].setChecked(
            bool(settings["window"]["remember_geometry"])
        )
        self._controls["window.start_maximized"].setChecked(
            bool(settings["window"]["start_maximized"])
        )
        self._controls["mtr_defaults.interval"].setValue(float(settings["mtr_defaults"]["interval"]))
        self._controls["mtr_defaults.packet_size"].setValue(int(settings["mtr_defaults"]["packet_size"]))
        self._controls["mtr_defaults.dns_enabled"].setChecked(bool(settings["mtr_defaults"]["dns_enabled"]))
        self._controls["app_behavior.debug_console_output"].setChecked(
            bool(settings["app_behavior"]["debug_console_output"])
        )
        self._controls["app_behavior.auto_refresh_system_info"].setChecked(
            bool(settings["app_behavior"]["auto_refresh_system_info"])
        )

        # Dashboard card order
        order = settings.get("dashboard", {}).get("card_order", [
            "network_status", "devices_found", "sip_alg",
            "mtr_trace", "traceroute", "quick_actions",
        ])
        labels = {
            "network_status": "🌐  Network Status",
            "devices_found": "💻  Devices Found",
            "sip_alg": "📞  SIP ALG Status",
            "mtr_trace": "📡  MTR Trace",
            "traceroute": "🔗  Traceroute",
            "quick_actions": "⚡  Quick Actions",
        }
        order_list = self._controls["dashboard.card_order"]
        order_list.clear()
        for key in order:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(labels.get(key, key))
            item.setData(Qt.UserRole, key)
            order_list.addItem(item)

    def _set_combo_by_data(self, key: str, value: str) -> None:
        combo = self._controls[key]
        if not isinstance(combo, QComboBox):
            return
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _collect_payload(self) -> dict[str, Any]:
        return {
            "appearance": {
                "theme": self._controls["appearance.theme"].currentData(),
                "density": self._controls["appearance.density"].currentData(),
            },
            "startup": {
                "default_page": self._controls["startup.default_page"].currentData(),
            },
            "window": {
                "remember_geometry": self._controls["window.remember_geometry"].isChecked(),
                "start_maximized": self._controls["window.start_maximized"].isChecked(),
            },
            "mtr_defaults": {
                "interval": self._controls["mtr_defaults.interval"].value(),
                "packet_size": self._controls["mtr_defaults.packet_size"].value(),
                "dns_enabled": self._controls["mtr_defaults.dns_enabled"].isChecked(),
            },
            "app_behavior": {
                "debug_console_output": self._controls["app_behavior.debug_console_output"].isChecked(),
                "auto_refresh_system_info": self._controls[
                    "app_behavior.auto_refresh_system_info"
                ].isChecked(),
            },
            "dashboard": {
                "card_order": [
                    self._controls["dashboard.card_order"].item(i).data(Qt.UserRole)
                    for i in range(self._controls["dashboard.card_order"].count())
                ],
            },
        }

    def _on_save_clicked(self) -> None:
        payload = self._collect_payload()
        updated = self._settings_manager.update(payload, save=True)
        self.settings_applied.emit(updated)

    def _on_reset_clicked(self) -> None:
        defaults = self._settings_manager.reset_to_defaults()
        self.load_from_settings(defaults)
        self.settings_applied.emit(defaults)
