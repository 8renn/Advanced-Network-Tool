from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.traceroute import TracerouteWorker


class TracerouteView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(10)

        top_bar = QWidget(self)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.target_input = QLineEdit(top_bar)
        self.target_input.setPlaceholderText("Enter hostname or IP")
        self.target_input.setClearButtonEnabled(True)
        self.target_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.target_input.setMinimumWidth(260)
        self.target_input.setMinimumHeight(40)
        self.target_input.setStyleSheet("font-size: 14px; padding: 4px 8px;")

        self.start_button = QPushButton("Start", top_bar)
        self.start_button.setMinimumHeight(40)
        self.start_button.setMinimumWidth(80)
        self.start_button.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 12px;")
        self.stop_button = QPushButton("Stop", top_bar)
        self.stop_button.setMinimumHeight(40)
        self.stop_button.setMinimumWidth(80)
        self.stop_button.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 12px;")
        self.stop_button.setEnabled(False)

        top_layout.addWidget(self.target_input, 1)
        top_layout.addWidget(self.start_button)
        top_layout.addWidget(self.stop_button)

        self.results_table = QTableWidget(0, 6, self)
        self.results_table.setObjectName("tracerouteTable")
        self.results_table.setHorizontalHeaderLabels(
            ["Hop", "Hostname", "IP", "Time 1", "Time 2", "Time 3"]
        )
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setShowGrid(False)
        hdr = self.results_table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_table.setStyleSheet(
            """
            QTableWidget#tracerouteTable {
                background-color: #1f2646;
                alternate-background-color: #242d52;
                color: #e8eeff;
                border: 1px solid #334071;
                border-radius: 10px;
                gridline-color: #2c3764;
                selection-background-color: #315ea8;
                selection-color: #ffffff;
            }
            QTableWidget#tracerouteTable::item {
                padding: 6px 8px;
                border: none;
            }
            QTableWidget#tracerouteTable::item:hover {
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

        self._worker: TracerouteWorker | None = None

        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.target_input.returnPressed.connect(self._trigger_start)

    def _trigger_start(self) -> None:
        if self.start_button.isEnabled():
            self.start_button.click()

    def _on_start_clicked(self) -> None:
        target = self.target_input.text().strip()
        if not target:
            self.status_label.setText("Ready")
            return
        if self._worker is not None:
            return

        self.results_table.setRowCount(0)
        self.status_label.setText("Tracing route...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        worker = TracerouteWorker(target, self)
        worker.hop_signal.connect(self._on_hop)
        worker.finished_signal.connect(self._on_worker_finished_signal)
        worker.finished.connect(self._on_thread_finished)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_stop_clicked(self) -> None:
        if self._worker is None:
            return
        self.status_label.setText("Stopping...")
        self.stop_button.setEnabled(False)
        self._worker.request_stop()

    def _on_hop(self, hop: dict) -> None:
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(str(hop.get("hop", ""))))
        self.results_table.setItem(row, 1, QTableWidgetItem(str(hop.get("hostname", ""))))
        self.results_table.setItem(row, 2, QTableWidgetItem(str(hop.get("ip", ""))))
        for col, key in ((3, "latency_1"), (4, "latency_2"), (5, "latency_3")):
            t_item = QTableWidgetItem(str(hop.get(key, "")))
            t_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(row, col, t_item)

    def _on_worker_finished_signal(self, message: str) -> None:
        if message:
            self.status_label.setText(message)

    def _on_thread_finished(self) -> None:
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._worker = None
