from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.logger import logger
from core.updater import (
    DownloadWorker,
    ReleaseInfo,
    UpdateCheckWorker,
    apply_update,
    pick_update_asset,
)
from core.version import APP_NAME, DIST_CHANNEL, __version__


class LauncherWindow(QWidget):
    launch_app = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset = QPoint()
        self._release: ReleaseInfo | None = None
        self._downloaded_path: Path | None = None
        self._check_thread: QThread | None = None
        self._check_worker: UpdateCheckWorker | None = None
        self._download_thread: QThread | None = None
        self._download_worker: DownloadWorker | None = None
        self._update_asset = None

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(520, 420)
        self._build_ui()
        self._center_on_screen()
        QTimer.singleShot(600, self._start_init)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("launcherCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(26, 24, 26, 18)
        card_layout.setSpacing(14)

        logo = QLabel(card)
        logo.setAlignment(Qt.AlignCenter)
        logo.setTextFormat(Qt.RichText)
        logo.setText(
            '<span style="font-size:48px; font-weight:300; color:#6b9eff; letter-spacing:6px;">'
            'A<span style="font-size:12px; color:#4a5a8a; vertical-align:super;">•</span>'
            'N<span style="font-size:12px; color:#4a5a8a; vertical-align:super;">•</span>'
            'T</span>'
        )
        card_layout.addWidget(logo)

        subtitle = QLabel("ADVANCED NETWORK TOOL", card)
        subtitle.setObjectName("launcherSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(subtitle)

        version = QLabel(f"Version {__version__}", card)
        version.setObjectName("launcherVersion")
        version.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(version)

        self.status_lbl = QLabel("Initializing…", card)
        self.status_lbl.setObjectName("launcherStatus")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setWordWrap(True)
        card_layout.addWidget(self.status_lbl)

        self.progress = QProgressBar(card)
        self.progress.setObjectName("launcherProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        card_layout.addWidget(self.progress)

        self.update_frame = QFrame(card)
        self.update_frame.setObjectName("updateFrame")
        self.update_frame.setVisible(False)
        update_layout = QVBoxLayout(self.update_frame)
        update_layout.setContentsMargins(14, 12, 14, 12)
        update_layout.setSpacing(8)

        self.update_title = QLabel("Update available", self.update_frame)
        self.update_title.setObjectName("updateTitle")
        self.update_title.setWordWrap(True)
        update_layout.addWidget(self.update_title)

        self.update_notes = QLabel("", self.update_frame)
        self.update_notes.setObjectName("updateNotes")
        self.update_notes.setWordWrap(True)
        self.update_notes.setMaximumHeight(80)
        update_layout.addWidget(self.update_notes)

        update_btn_row = QHBoxLayout()
        update_btn_row.setSpacing(10)
        self.download_btn = QPushButton("Download Update", self.update_frame)
        self.download_btn.setObjectName("btnPrimary")
        self.skip_btn = QPushButton("Skip", self.update_frame)
        self.skip_btn.setObjectName("btnSecondary")
        update_btn_row.addWidget(self.download_btn)
        update_btn_row.addWidget(self.skip_btn)
        update_layout.addLayout(update_btn_row)
        card_layout.addWidget(self.update_frame)

        card_layout.addStretch(1)
        footer = QLabel("© 2025 Advanced Network Tool", card)
        footer.setObjectName("launcherFooter")
        footer.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(footer)

        outer.addWidget(card, 1)

        self.download_btn.clicked.connect(self._on_download_clicked)
        self.skip_btn.clicked.connect(self._show_choose_phase)

        self.setStyleSheet(
            """
            LauncherWindow {
                background: #12162b;
            }
            #launcherCard {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #1a2040, stop: 1 #141830
                );
                border: 1px solid #2a3260;
                border-radius: 16px;
            }
            #launcherSubtitle {
                color: #6b7aaa;
                font-size: 9px;
                letter-spacing: 4px;
            }
            #launcherVersion {
                color: #5b8ad5;
                font-size: 11px;
                font-weight: 700;
            }
            #launcherStatus {
                color: #c0caef;
                font-size: 13px;
            }
            #launcherProgress {
                border: none;
                border-radius: 3px;
                background: #1e2548;
            }
            #launcherProgress::chunk {
                border-radius: 3px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3ec9d3, stop: 1 #5d85ff
                );
            }
            #updateFrame {
                background: #1c2346;
                border: 1px solid #2e3768;
                border-radius: 10px;
            }
            #updateTitle {
                color: #7ecbff;
                font-size: 15px;
                font-weight: 700;
            }
            #updateNotes {
                color: #9aa7d4;
                font-size: 12px;
            }
            #btnPrimary {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3ec9d3, stop: 1 #5d85ff
                );
                color: #ffffff;
                border: none;
                border-radius: 10px;
                min-height: 38px;
                font-size: 14px;
                font-weight: 700;
                padding: 0 14px;
            }
            #btnPrimary:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #56d8e1, stop: 1 #7399ff
                );
            }
            #btnPrimary:disabled {
                background: #2e376d;
                color: #6b7aaa;
            }
            #btnSecondary {
                background: #2e376d;
                color: #d6dcff;
                border: 1px solid #39437b;
                border-radius: 10px;
                min-height: 38px;
                font-size: 14px;
                font-weight: 600;
                padding: 0 14px;
            }
            #btnSecondary:hover {
                background: #384381;
            }
            #launcherFooter {
                color: #3e4870;
                font-size: 10px;
            }
            """
        )

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            geometry.center().x() - self.width() // 2,
            geometry.center().y() - self.height() // 2,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def _start_init(self) -> None:
        if DIST_CHANNEL == "msstore":
            # Microsoft Store handles updates — skip GitHub check, just launch
            self.status_lbl.setText("Initializing…")
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            QTimer.singleShot(1500, self._auto_launch)
            return

        # GitHub channel — check for updates
        self.status_lbl.setText("Checking for updates…")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        self._check_thread = QThread(self)
        self._check_worker = UpdateCheckWorker()
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_check_finished)
        self._check_worker.error.connect(self._on_check_error)
        self._check_worker.finished.connect(self._check_thread.quit)
        self._check_worker.error.connect(self._check_thread.quit)
        self._check_thread.finished.connect(self._cleanup_check_thread)
        self._check_thread.start()

    def _cleanup_check_thread(self) -> None:
        if self._check_worker is not None:
            self._check_worker.deleteLater()
            self._check_worker = None
        if self._check_thread is not None:
            self._check_thread.deleteLater()
            self._check_thread = None

    def _on_check_finished(self, release_obj: object) -> None:
        release = release_obj if isinstance(release_obj, ReleaseInfo) else None
        if release is None:
            self._show_choose_phase()
            return
        self._release = release
        self._show_update_phase(release)

    def _on_check_error(self, message: str) -> None:
        logger.warning("Launcher update check failed: %s", message)
        self._show_choose_phase()

    def _show_update_phase(self, release: ReleaseInfo) -> None:
        self.progress.setVisible(False)
        self.update_frame.setVisible(True)
        self.status_lbl.setText("Update available.")
        self.update_title.setText(f"Version {release.version} is available")
        notes = (release.body or "").strip()
        if len(notes) > 300:
            notes = notes[:297].rstrip() + "..."
        self.update_notes.setText(notes or "Release notes unavailable.")

    def _show_choose_phase(self) -> None:
        self.update_frame.setVisible(False)
        self.progress.setVisible(False)
        self.status_lbl.setText("Launching…")
        QTimer.singleShot(500, self._auto_launch)

    def _auto_launch(self) -> None:
        self.launch_app.emit()
        self.close()

    def _on_download_clicked(self) -> None:
        if self._release is None:
            self._show_choose_phase()
            return
        self._update_asset = pick_update_asset(self._release)
        if self._update_asset is None:
            if sys.platform == "win32":
                self.status_lbl.setText("No compatible .exe update asset found.")
            elif sys.platform == "darwin":
                # macOS: in-app update not supported
                self.status_lbl.setText(
                    "Auto-update is not available on macOS. "
                    "Please download the latest version from GitHub."
                )
            else:
                self.status_lbl.setText("No compatible update asset found.")
            return

        self.download_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_lbl.setText("Downloading update…")

        self._download_thread = QThread(self)
        self._download_worker = DownloadWorker(self._update_asset)
        self._download_worker.moveToThread(self._download_thread)
        self._download_thread.started.connect(self._download_worker.run)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.finished.connect(self._download_thread.quit)
        self._download_worker.error.connect(self._download_thread.quit)
        self._download_thread.finished.connect(self._cleanup_download_thread)
        self._download_thread.start()

    def _cleanup_download_thread(self) -> None:
        if self._download_worker is not None:
            self._download_worker.deleteLater()
            self._download_worker = None
        if self._download_thread is not None:
            self._download_thread.deleteLater()
            self._download_thread = None

    def _on_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = max(0, min(100, int((done / total) * 100)))
            self.progress.setValue(pct)
            self.status_lbl.setText(
                f"Downloading update… {done / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB"
            )
        else:
            self.status_lbl.setText(f"Downloading update… {done / (1024 * 1024):.1f} MB")

    def _on_download_finished(self, downloaded_obj: object) -> None:
        downloaded = Path(downloaded_obj) if downloaded_obj is not None else None
        if downloaded is None or self._update_asset is None:
            self._on_download_error("Invalid downloaded file")
            return
        self._downloaded_path = downloaded
        self.status_lbl.setText("Applying update…")
        try:
            should_quit = apply_update(downloaded, self._update_asset)
        except Exception as e:
            self._on_download_error(str(e))
            return

        if should_quit:
            self.status_lbl.setText("Update launched. Closing…")
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(500, app.quit)
            return

        self.status_lbl.setText("Update cannot be applied in dev mode.")
        self.download_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)

    def _on_download_error(self, message: str) -> None:
        logger.warning("Launcher download failed: %s", message)
        self.status_lbl.setText(f"Download failed: {message}")
        self.download_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
