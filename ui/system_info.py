from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.system_info import collect_full_snapshot, snapshot_to_dict


class _SystemInfoRefreshThread(QThread):
    """Runs blocking collection off the GUI thread."""

    finished_ok = Signal(dict)

    def run(self) -> None:
        try:
            snap = collect_full_snapshot(include_speedtests=True)
            self.finished_ok.emit(snapshot_to_dict(snap))
        except Exception as e:
            self.finished_ok.emit(
                {
                    "hostname": "Unavailable",
                    "primary_local_ipv4": "Unavailable",
                    "subnet_mask": "Unavailable",
                    "default_gateway": "Unavailable",
                    "mac_address": "Unavailable",
                    "public_ip": "Unavailable",
                    "adapter_name": "Unavailable",
                    "adapter_ipv4": "Unavailable",
                    "cloudflare": {
                        "download": "Unavailable",
                        "upload": "Unavailable",
                        "latency": "Unavailable",
                        "jitter": "Unavailable",
                        "status": "Failed",
                    },
                    "google": {
                        "download": "Unavailable",
                        "upload": "Unavailable",
                        "latency": "Unavailable",
                        "jitter": "Unavailable",
                        "status": "Failed",
                    },
                    "error": str(e),
                }
            )


class SystemInfoView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _SystemInfoRefreshThread | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        title = QLabel("System Info", top_bar)
        title.setObjectName("systemInfoTitle")
        self.refresh_btn = QPushButton("Refresh", top_bar)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.setMinimumWidth(100)
        self.status_lbl = QLabel("", top_bar)
        self.status_lbl.setObjectName("systemInfoStatus")

        top_layout.addWidget(title)
        top_layout.addStretch(1)
        top_layout.addWidget(self.status_lbl)
        top_layout.addWidget(self.refresh_btn)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setObjectName("systemInfoScroll")

        inner = QWidget()
        inner.setObjectName("systemInfoInner")
        scroll.setWidget(inner)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 8, 0)
        inner_layout.setSpacing(14)

        self.network_card = self._make_card("Network details")
        net_grid = QGridLayout()
        net_grid.setHorizontalSpacing(24)
        net_grid.setVerticalSpacing(10)
        self._net_labels: dict[str, tuple[QLabel, QLabel]] = {}
        rows = [
            ("Hostname", "hostname"),
            ("Primary local IPv4", "primary_local_ipv4"),
            ("Subnet mask", "subnet_mask"),
            ("Default gateway", "default_gateway"),
            ("MAC address", "mac_address"),
            ("Public IP", "public_ip"),
            ("Adapter name", "adapter_name"),
            ("Adapter IPv4", "adapter_ipv4"),
        ]
        for i, (title, key) in enumerate(rows):
            tl = QLabel(title + ":")
            tl.setObjectName("systemInfoFieldTitle")
            vl = QLabel("—")
            vl.setObjectName("systemInfoFieldValue")
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            net_grid.addWidget(tl, i, 0, Qt.AlignRight | Qt.AlignTop)
            net_grid.addWidget(vl, i, 1)
            self._net_labels[key] = (tl, vl)
        net_grid.setColumnStretch(1, 1)
        self.network_card.layout().addLayout(net_grid)

        self.cf_card, self._cf_labels, self._cf_status = self._make_speed_card(
            "Cloudflare (speed.cloudflare.com endpoints)"
        )
        self.google_card, self._google_labels, self._google_status = self._make_speed_card(
            "Google (dl.google.com CDN)"
        )

        inner_layout.addWidget(self.network_card)
        inner_layout.addWidget(self.cf_card)
        inner_layout.addWidget(self.google_card)
        inner_layout.addStretch(1)

        root.addWidget(top_bar)
        root.addWidget(scroll, 1)

        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.setStyleSheet(
            """
            #systemInfoTitle {
                color: #eef2ff;
                font-size: 18px;
                font-weight: 700;
            }
            #systemInfoStatus {
                color: #9aa7d4;
                font-size: 13px;
            }
            #systemInfoScroll {
                background: transparent;
            }
            #systemInfoInner {
                background: transparent;
            }
            QPushButton {
                background-color: #2f6fed;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 18px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #4a82ff;
            }
            QPushButton:disabled {
                background-color: #3a4581;
                color: #aab3de;
            }
            QFrame#systemInfoCard {
                background-color: #1f2646;
                border: 1px solid #334071;
                border-radius: 12px;
            }
            QLabel#systemInfoCardTitle {
                color: #dbe5ff;
                font-size: 15px;
                font-weight: 700;
                padding-bottom: 4px;
            }
            QLabel#systemInfoFieldTitle {
                color: #8b97c9;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#systemInfoFieldValue {
                color: #e8eeff;
                font-size: 13px;
            }
            QLabel#systemInfoSpeedStatus {
                color: #9aa7d4;
                font-size: 12px;
                font-style: italic;
            }
            """
        )

        self._apply_card_shell(self.network_card)
        self._apply_card_shell(self.cf_card)
        self._apply_card_shell(self.google_card)

        self._start_refresh()

    def _apply_card_shell(self, card: QFrame) -> None:
        card.setObjectName("systemInfoCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def _make_card(self, title: str) -> QFrame:
        card = QFrame(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        t = QLabel(title, card)
        t.setObjectName("systemInfoCardTitle")
        lay.addWidget(t)
        return card

    def _make_speed_card(self, title: str) -> tuple[QFrame, dict[str, QLabel], QLabel]:
        card = self._make_card(title)
        lay = card.layout()
        status = QLabel("", card)
        status.setObjectName("systemInfoSpeedStatus")
        lay.addWidget(status)
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(8)
        keys = [
            ("Download", "download"),
            ("Upload", "upload"),
            ("Ping / latency", "latency"),
            ("Jitter", "jitter"),
        ]
        labels: dict[str, QLabel] = {}
        for i, (lt, k) in enumerate(keys):
            a = QLabel(lt + ":")
            a.setObjectName("systemInfoFieldTitle")
            b = QLabel("—")
            b.setObjectName("systemInfoFieldValue")
            b.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(a, i, 0, Qt.AlignRight | Qt.AlignTop)
            grid.addWidget(b, i, 1)
            labels[k] = b
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        return card, labels, status

    def _on_refresh_clicked(self) -> None:
        self._start_refresh()

    def _start_refresh(self) -> None:
        if self._worker is not None:
            return
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText("Loading…")
        self._worker = _SystemInfoRefreshThread(self)
        self._worker.finished_ok.connect(self._on_refresh_done)
        self._worker.finished.connect(self._on_thread_finished)
        self._worker.start()

    def _on_thread_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self.refresh_btn.setEnabled(True)

    def _on_refresh_done(self, data: dict) -> None:
        err = (data.get("error") or "").strip()
        if err:
            self.status_lbl.setText(f"Issue: {err}")
        else:
            self.status_lbl.setText("Updated")

        for key, (_, vl) in self._net_labels.items():
            vl.setText(str(data.get(key, "Unavailable")))

        cf = data.get("cloudflare") or {}
        goog = data.get("google") or {}
        self._apply_speed_panel(self._cf_labels, self._cf_status, cf, ookla=False)
        self._apply_speed_panel(self._google_labels, self._google_status, goog, ookla=False)

    def _apply_speed_panel(
        self,
        labels: dict[str, QLabel],
        status: QLabel,
        panel: dict,
        *,
        ookla: bool,
    ) -> None:
        st = str(panel.get("status") or "Unavailable")
        if st in ("ok", "Completed"):
            status.setText("Completed")
        elif st == "Not Installed":
            if ookla:
                status.setText(
                    "Not installed — add Ookla Speedtest CLI or speedtest-cli to PATH"
                )
            else:
                status.setText("Not installed")
        elif st == "Failed":
            status.setText("Failed")
        elif st == "Unavailable":
            status.setText("Unavailable")
        else:
            status.setText(st)

        for k, lbl in labels.items():
            v = panel.get(k)
            if v is None or str(v).strip() == "":
                lbl.setText("Unavailable")
            else:
                lbl.setText(str(v))
