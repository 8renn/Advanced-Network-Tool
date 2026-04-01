from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.sip_alg_detector import SipAlgDetector

_COLOR_GREEN = "#35c46b"
_COLOR_RED = "#e74c3c"
_COLOR_ORANGE = "#f39c12"
_COLOR_IDLE_BG = "#2e376d"
_COLOR_IDLE_FG = "#d6dcff"
_COLOR_IDLE_BORDER = "#39437b"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _html_banner(title: str, headline: str, subtext: str, fg: str) -> str:
    return (
        f'<div style="text-align:center;color:{fg};">'
        f'<span style="font-weight:700;font-size:15px;">{_esc(title)}</span><br/>'
        f'<span style="font-weight:700;font-size:13px;">{_esc(headline)}</span><br/>'
        f'<span style="font-size:11px;font-weight:400;">{_esc(subtext)}</span>'
        "</div>"
    )


def _idle_banner() -> str:
    return _html_banner(
        "SIP ALG Detection",
        "—",
        "Click Run Detection",
        _COLOR_IDLE_FG,
    )


def _idle_stylesheet() -> str:
    return (
        f"QLabel {{ background-color: {_COLOR_IDLE_BG}; color: {_COLOR_IDLE_FG}; "
        f"border: 1px solid {_COLOR_IDLE_BORDER}; border-radius: 12px; "
        "padding: 14px 18px; }}"
    )


def _state_stylesheet(state: str) -> str:
    if state == "green":
        bg = _COLOR_GREEN
    elif state == "red":
        bg = _COLOR_RED
    else:
        bg = _COLOR_ORANGE
    return f"QLabel {{ background-color: {bg}; border-radius: 12px; padding: 14px 18px; border: none; }}"


class SipAlgView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top = QWidget(self)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.run_button = QPushButton("Run Detection", top)
        self.run_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.run_button.setMinimumHeight(40)
        self.run_button.setMinimumWidth(140)
        self.run_button.setStyleSheet("font-size: 14px; font-weight: 600; padding: 6px 16px;")
        top_layout.addWidget(self.run_button)
        top_layout.addStretch(1)

        root.addWidget(top)

        self.banner = QLabel(self)
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setMinimumHeight(88)
        self.banner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.banner.setTextFormat(Qt.RichText)
        self.banner.setWordWrap(True)
        self._reset_banner_idle()

        root.addWidget(self.banner)
        root.addStretch(1)

        self._detector: SipAlgDetector | None = None
        self.run_button.clicked.connect(self._on_run_clicked)

    def _reset_banner_idle(self) -> None:
        self.banner.setText(_idle_banner())
        self.banner.setStyleSheet(_idle_stylesheet())

    def _apply_banner(self, payload: dict) -> None:
        st = str(payload.get("state", "orange"))
        if st not in ("green", "red", "orange"):
            st = "orange"
        headline = str(payload.get("headline", "UNABLE TO DETERMINE"))
        subtext = str(
            payload.get("subtext", "No response from server or blocked by firewall")
        )
        self.banner.setText(
            _html_banner("SIP ALG Detection", headline, subtext, "#ffffff")
        )
        self.banner.setStyleSheet(_state_stylesheet(st))

    def _on_run_clicked(self) -> None:
        print("DEBUG: Detect button clicked")
        from core.sip_alg_detector import detect_sip_alg

        target_ip = "192.81.82.254"
        target_port = 5060

        result = detect_sip_alg(target_ip, target_port)

        # Update UI based on result
        self.banner.setText("SIP ALG\n" + result)

        if result == "SIP ALG is NOT detected":
            self.banner.setStyleSheet("background-color: green; color: white;")

        elif result == "SIP ALG detected":
            self.banner.setStyleSheet("background-color: red; color: white;")

        else:
            self.banner.setStyleSheet("background-color: orange; color: black;")

    def _on_result(self, payload: dict) -> None:
        self._apply_banner(payload)

    def _on_thread_finished(self) -> None:
        self.run_button.setEnabled(True)
        self._detector = None
