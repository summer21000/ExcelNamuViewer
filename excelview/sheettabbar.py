from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget


class SheetTabBar(QWidget):
    sheetChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SheetTabBar")
        self.setFixedHeight(26)

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(2, 0, 2, 0)
        self._lay.setSpacing(0)

        self._lay.addWidget(self._nav_btn("⮜"))
        self._lay.addWidget(self._nav_btn("⮞"))
        self._lay.addSpacing(4)

        self._tabs: list[QToolButton] = []
        for i, name in enumerate(["Sheet1", "Sheet2", "Sheet3"]):
            btn = QToolButton(self)
            btn.setObjectName("SheetTab")
            btn.setText(name)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setMinimumWidth(60)
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda _checked=False, idx=i: self._select(idx))
            self._lay.addWidget(btn)
            self._tabs.append(btn)
        self._tabs[0].setChecked(True)

        plus = QToolButton(self)
        plus.setObjectName("SheetPlusBtn")
        plus.setText("➕")
        plus.setFixedSize(22, 22)
        plus.setFocusPolicy(Qt.NoFocus)
        plus.setCursor(QCursor(Qt.PointingHandCursor))
        self._lay.addWidget(plus)

        self._lay.addStretch()

    def _nav_btn(self, glyph: str) -> QToolButton:
        b = QToolButton(self)
        b.setObjectName("SheetNavBtn")
        b.setText(glyph)
        b.setFixedSize(20, 22)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        return b

    def _select(self, index: int) -> None:
        if 0 <= index < len(self._tabs):
            self._tabs[index].setChecked(True)
            self.sheetChanged.emit(index)
