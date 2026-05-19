from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget


class SheetTabBar(QWidget):
    sheetChanged = Signal(int)
    newSheetRequested = Signal()
    closeSheetRequested = Signal(int)

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

        self._plus = QToolButton(self)
        self._plus.setObjectName("SheetPlusBtn")
        self._plus.setText("➕")
        self._plus.setToolTip("새 시트")
        self._plus.setFixedSize(22, 22)
        self._plus.setFocusPolicy(Qt.NoFocus)
        self._plus.setCursor(QCursor(Qt.PointingHandCursor))
        self._plus.clicked.connect(self.newSheetRequested.emit)

        # 기본 탭: Sheet1 (위장) + Sheet2 (namu 작업 영역)
        for name in ["Sheet1", "Sheet2"]:
            self._make_tab(name)
        self._tabs[0].setChecked(True)

        self._lay.addWidget(self._plus)
        self._lay.addStretch()

    # ------------------------------------------------------------------ public
    def addSheet(self, name: str | None = None) -> int:
        idx = len(self._tabs)
        label = name or f"Sheet{idx + 1}"
        self._make_tab(label)
        return idx

    def closeSheet(self, idx: int) -> None:
        if idx <= 0 or idx >= len(self._tabs):
            return  # Sheet1 (idx 0) 은 닫지 못함 — 위장 시트 보호
        btn = self._tabs.pop(idx)
        btn.setParent(None)
        btn.deleteLater()

    def selectSheet(self, idx: int) -> None:
        self._select(idx)

    def sheetName(self, idx: int) -> str:
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx].text()
        return f"Sheet{idx + 1}"

    def sheetCount(self) -> int:
        return len(self._tabs)

    # ------------------------------------------------------------------ internal
    def _make_tab(self, label: str) -> None:
        btn = QToolButton(self)
        btn.setObjectName("SheetTab")
        btn.setText(label)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.setMinimumWidth(60)
        btn.setFixedHeight(22)
        # 동적 인덱스 — 닫기 후 reindex 없이도 동작
        btn.clicked.connect(lambda _c=False, b=btn: self._on_tab_clicked(b))
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=btn: self._show_tab_menu(b, pos)
        )
        # plus 버튼 직전에 삽입
        plus_idx = self._lay.indexOf(self._plus)
        if plus_idx >= 0:
            self._lay.insertWidget(plus_idx, btn)
        else:
            self._lay.addWidget(btn)
        self._tabs.append(btn)

    def _on_tab_clicked(self, btn: QToolButton) -> None:
        try:
            idx = self._tabs.index(btn)
        except ValueError:
            return
        self.sheetChanged.emit(idx)

    def _show_tab_menu(self, btn: QToolButton, pos: QPoint) -> None:
        try:
            idx = self._tabs.index(btn)
        except ValueError:
            return
        menu = QMenu(self)
        act_close = QAction("시트 닫기", menu)
        if idx == 0:
            act_close.setEnabled(False)  # 위장 시트는 닫기 차단
            act_close.setText("시트 닫기 (위장 시트는 보호됨)")
        act_close.triggered.connect(
            lambda _checked=False, i=idx: self.closeSheetRequested.emit(i)
        )
        menu.addAction(act_close)
        menu.exec(btn.mapToGlobal(pos))

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
