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
        # 기본 탭: Sheet1 (위장) + Sheet2 (namu 작업 영역). 추가 시트는 동적으로.
        for i, name in enumerate(["Sheet1", "Sheet2"]):
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

        self._plus = QToolButton(self)
        self._plus.setObjectName("SheetPlusBtn")
        self._plus.setText("➕")
        self._plus.setFixedSize(22, 22)
        self._plus.setFocusPolicy(Qt.NoFocus)
        self._plus.setCursor(QCursor(Qt.PointingHandCursor))
        self._lay.addWidget(self._plus)

        self._lay.addStretch()

    def addSheet(self, name: str | None = None) -> int:
        """탭 추가 → 새 탭 인덱스 반환. 자동으로 그 탭 select 하진 않음."""
        idx = len(self._tabs)
        label = name or f"Sheet{idx + 1}"
        btn = QToolButton(self)
        btn.setObjectName("SheetTab")
        btn.setText(label)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setMinimumWidth(60)
        btn.setFixedHeight(22)
        btn.clicked.connect(lambda _checked=False, i=idx: self._select(i))
        # plus 버튼 앞에 삽입
        plus_index = self._lay.indexOf(self._plus)
        self._lay.insertWidget(plus_index, btn)
        self._tabs.append(btn)
        return idx

    def selectSheet(self, idx: int) -> None:
        self._select(idx)

    def sheetName(self, idx: int) -> str:
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx].text()
        return f"Sheet{idx + 1}"

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
