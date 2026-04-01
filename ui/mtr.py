from PySide6.QtCore import QTimer, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
)

import sys
import ctypes

from core.mtr_engine import MTREngine, MAX_HOPS


class MTRWorker(QThread):
    """Runs MTREngine.start_trace() off the UI thread."""
    finished = Signal()
    error = Signal(str)

    def __init__(self, engine: MTREngine):
        super().__init__()
        self._engine = engine

    def run(self):
        try:
            self._engine.start_trace()
            while self._engine.is_running:
                self.msleep(500)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self):
        self._engine.stop_trace()


class MTRView(QWidget):
    """WinMTR-style trace view using native Python ICMP engine."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._engine = None
        self._worker = None
        self._update_timer = QTimer()
        self._update_timer.setInterval(1000)
        self._update_timer.timeout.connect(self._update_table)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        host_label = QLabel("Host:", top_bar)
        host_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(host_label)
        self._host_input = QLineEdit(top_bar)
        self._host_input.setPlaceholderText("Enter hostname or IP address")
        self._host_input.setClearButtonEnabled(True)
        self._host_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._host_input.setMinimumWidth(260)
        self._host_input.setMinimumHeight(40)
        self._host_input.setStyleSheet("font-size: 14px; padding: 4px 8px;")
        self._host_input.returnPressed.connect(self._start_trace)
        top_layout.addWidget(self._host_input, 1)

        size_label = QLabel("Size:", top_bar)
        size_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(size_label)
        self._size_input = QSpinBox(top_bar)
        self._size_input.setRange(64, 4096)
        self._size_input.setValue(64)
        self._size_input.setSuffix(" B")
        self._size_input.setMinimumHeight(40)
        self._size_input.setFixedWidth(100)
        self._size_input.setStyleSheet("font-size: 14px; padding: 4px;")
        top_layout.addWidget(self._size_input)

        interval_label = QLabel("Interval:", top_bar)
        interval_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(interval_label)
        self._interval_input = QDoubleSpinBox(top_bar)
        self._interval_input.setRange(0.1, 10.0)
        self._interval_input.setValue(0.2)
        self._interval_input.setSingleStep(0.1)
        self._interval_input.setSuffix(" s")
        self._interval_input.setMinimumHeight(40)
        self._interval_input.setFixedWidth(100)
        self._interval_input.setStyleSheet("font-size: 14px; padding: 4px;")
        top_layout.addWidget(self._interval_input)

        self._dns_checkbox = QCheckBox("DNS", top_bar)
        self._dns_checkbox.setChecked(True)
        self._dns_checkbox.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(self._dns_checkbox)

        self._start_btn = QPushButton("Start", top_bar)
        self._start_btn.clicked.connect(self._start_trace)
        self._start_btn.setMinimumHeight(40)
        self._start_btn.setFixedWidth(80)
        self._start_btn.setStyleSheet("font-size: 14px; font-weight: 600;")
        top_layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop", top_bar)
        self._stop_btn.clicked.connect(self._stop_trace_clicked)
        self._stop_btn.setMinimumHeight(40)
        self._stop_btn.setFixedWidth(80)
        self._stop_btn.setStyleSheet("font-size: 14px; font-weight: 600;")
        self._stop_btn.setEnabled(False)
        top_layout.addWidget(self._stop_btn)

        layout.addWidget(top_bar)

        self._status_label = QLabel("Ready", self)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._table = QTableWidget(self)
        self._table.setObjectName("mtrTable")
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._table.setStyleSheet(
            """
            QTableWidget#mtrTable {
                background-color: #1f2646;
                alternate-background-color: #242d52;
                color: #e8eeff;
                border: 1px solid #334071;
                border-radius: 10px;
                gridline-color: #2c3764;
                selection-background-color: #315ea8;
                selection-color: #ffffff;
            }
            QTableWidget#mtrTable::item {
                padding: 6px 8px;
                border: none;
            }
            QTableWidget#mtrTable::item:hover {
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
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status_label)

        self._setup_table_columns()

    def _setup_table_columns(self):
        columns = ["Nr", "Hostname", "Loss %", "Sent", "Recv", "Best", "Avrg", "Worst", "Last"]
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setRowCount(0)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 35)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, len(columns)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self._table.setColumnWidth(col, 65)

    def set_host(self, hostname: str):
        """Set the target hostname. Called externally by other views/components."""
        self._host_input.setText(hostname)

    def _start_trace(self):
        if self._worker is not None and self._worker.isRunning():
            return

        target = self._host_input.text().strip()
        if not target:
            self._status_label.setText("Please enter a hostname or IP address.")
            return

        # Raw-socket privilege check is only needed on non-Windows paths.
        # Windows uses ICMP.DLL API and does not require admin elevation.
        if sys.platform != "win32":
            import os
            if os.geteuid() != 0:
                self._status_label.setText("Error: Root privileges required for raw sockets.")
                return

        # Stop any running trace first
        self._stop_trace()

        payload_size = self._size_input.value()
        interval = self._interval_input.value()
        use_dns = self._dns_checkbox.isChecked()

        self._engine = MTREngine(
            target_host=target,
            payload_size=payload_size,
            interval=interval,
            use_dns=use_dns,
        )

        if not self._engine.resolve_target():
            self._status_label.setText(f"Failed to resolve: {target}")
            self._engine = None
            return

        self._status_label.setText(f"Tracing {target} ({self._engine.target_addr})...")
        self._table.setRowCount(0)

        # Toggle buttons
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._host_input.setEnabled(False)
        self._size_input.setEnabled(False)
        self._interval_input.setEnabled(False)
        self._dns_checkbox.setEnabled(False)

        # Launch worker
        self._worker = MTRWorker(self._engine)
        self._worker.error.connect(self._on_trace_error)
        self._worker.finished.connect(self._on_trace_finished)
        self._worker.start()

        self._update_timer.start()

    def _stop_trace_clicked(self):
        """Handler for Stop button click."""
        self._stop_trace()
        self._status_label.setText("Trace stopped.")

    def _stop_trace(self):
        """Stop the current trace if running."""
        self._update_timer.stop()

        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(7000)
            self._worker = None

        # Keep self._engine alive so Full Report can read hop data.
        # It will be replaced on the next Start click.

        # Restore UI state
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._host_input.setEnabled(True)
        self._size_input.setEnabled(True)
        self._interval_input.setEnabled(True)
        self._dns_checkbox.setEnabled(True)

    def _update_table(self):
        """Refresh the table with current hop data. Called by QTimer every 1s."""
        engine = self._engine
        if engine is None:
            return

        try:
            hops = engine.get_all_hops()
        except Exception:
            return

        self._table.setRowCount(len(hops))

        for row, hop in enumerate(hops):
            display_name = hop["name"] if hop["name"] else hop["addr"] if hop["addr"] else "???"

            items = [
                str(hop["nr"]),
                display_name,
                f"{hop['loss_percent']}%",
                str(hop["xmit"]),
                str(hop["returned"]),
                str(hop["best"]),
                str(hop["avg"]),
                str(hop["worst"]),
                str(hop["last"]),
            ]

            for col, text in enumerate(items):
                existing = self._table.item(row, col)
                if existing is not None:
                    existing.setText(text)
                else:
                    item = QTableWidgetItem(text)
                    if col != 1:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self._table.setItem(row, col, item)

    def _on_trace_error(self, error_msg: str):
        """Handle errors from the worker thread."""
        self._stop_trace()
        self._status_label.setText(f"Error: {error_msg}")

    def _on_trace_finished(self):
        """Handle worker thread natural completion."""
        self._update_table()
        # Only reset UI if trace was intentionally stopped
        if not self._engine or not self._engine.is_running:
            self._update_timer.stop()
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._host_input.setEnabled(True)
            self._size_input.setEnabled(True)
            self._interval_input.setEnabled(True)
            self._dns_checkbox.setEnabled(True)
            if self._status_label.text().startswith("Tracing"):
                self._status_label.setText("Trace complete.")

    def closeEvent(self, event):
        """Ensure trace is stopped when widget is closed or destroyed."""
        self._stop_trace()
        super().closeEvent(event)


MTRWidget = MTRView
