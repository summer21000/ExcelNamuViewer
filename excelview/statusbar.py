from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QWidget


class ExcelStatusBar(QWidget):
    zoomChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ExcelStatusBar")
        self.setFixedHeight(22)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(8)

        self._status = QLabel("준비", self)
        self._status.setObjectName("StatusReady")
        lay.addWidget(self._status)

        lay.addStretch()

        self._summary = QLabel("", self)
        self._summary.setObjectName("StatusSummary")
        lay.addWidget(self._summary)

        for g in ["⊞", "☰", "⊟"]:
            b = QToolButton(self)
            b.setObjectName("StatusViewBtn")
            b.setText(g)
            b.setFixedSize(22, 18)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            lay.addWidget(b)

        self._zoom = QSlider(Qt.Horizontal, self)
        self._zoom.setObjectName("StatusZoom")
        self._zoom.setRange(10, 400)
        self._zoom.setValue(100)
        self._zoom.setFixedWidth(160)
        lay.addWidget(self._zoom)

        self._zoom_lbl = QLabel("100%", self)
        self._zoom_lbl.setObjectName("StatusZoomLbl")
        self._zoom_lbl.setFixedWidth(40)
        self._zoom_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._zoom_lbl)

        self._zoom.valueChanged.connect(self._on_zoom)

    def setStatusText(self, text: str) -> None:
        self._status.setText(text)

    def setSummary(self, text: str) -> None:
        self._summary.setText(text)

    def _on_zoom(self, v: int) -> None:
        self._zoom_lbl.setText(f"{v}%")
        self.zoomChanged.emit(v)
