from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeyEvent, QStandardItem, QStandardItemModel
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QMenu, QTableView, QToolTip, QWidget,
)


# 셀 모델 커스텀 데이터 슬롯
IMAGE_URL_ROLE = Qt.UserRole + 1
LINK_URL_ROLE = Qt.UserRole + 2
FOOTNOTE_ROLE = Qt.UserRole + 3


def column_letter(col: int) -> str:
    s = ""
    c = col + 1
    while c > 0:
        c, rem = divmod(c - 1, 26)
        s = chr(ord("A") + rem) + s
    return s


def cell_address(row: int, col: int) -> str:
    return f"{column_letter(col)}{row + 1}"


class SheetView(QTableView):
    cellSelected = Signal(int, int, str, str)
    imageCellActivated = Signal(str, str)   # url, alt_or_label
    linkCellActivated = Signal(str)         # href — 같은 시트에서 열기 (더블클릭 / 메뉴 "열기")
    linkOpenInNewSheet = Signal(str)        # href — 새 시트에서 열기
    visibleColsChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SheetView")
        self._frozen: QTableView | None = None
        self._frozen_enabled = False
        self._build_appearance()
        self._build_model(2000, 60)
        self._build_frozen_view()

        # 좌우 스크롤 막기 — wrap 으로 처리
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.doubleClicked.connect(self._on_double_clicked)
        self.clicked.connect(self._on_single_clicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.horizontalHeader().sectionResized.connect(self._sync_frozen_section)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self._update_frozen_geometry()
        )

    # ------------------------------------------------------------------ public
    def setCellValue(
        self,
        row: int,
        col: int,
        value: str,
        *,
        bold: bool = False,
        image_url: str | None = None,
        link_url: str | None = None,
        footnote: str | None = None,
    ) -> None:
        item = self._model.item(row, col)
        if item is None:
            item = QStandardItem(value)
            self._model.setItem(row, col, item)
        else:
            item.setText(value)

        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)

        if image_url:
            item.setData(image_url, IMAGE_URL_ROLE)
            item.setForeground(QBrush(QColor("#0563c1")))
            f = item.font()
            f.setUnderline(True)
            item.setFont(f)
            item.setToolTip("더블 클릭하면 사진이 뜹니다")
            item.setEditable(False)
        elif link_url:
            item.setData(link_url, LINK_URL_ROLE)
            item.setForeground(QBrush(QColor("#0563c1")))
            f = item.font()
            f.setUnderline(True)
            item.setFont(f)
            item.setToolTip(f"더블 클릭하면 이동: {link_url}")
            item.setEditable(False)

        if footnote:
            # 각주 — 클릭 시 즉시 toolTip 띄움. 색은 본문과 구분되는 회색.
            item.setData(footnote, FOOTNOTE_ROLE)
            item.setToolTip(footnote)
            item.setForeground(QBrush(QColor("#797775")))
            item.setEditable(False)

    def cellValue(self, row: int, col: int) -> str:
        item = self._model.item(row, col)
        return item.text() if item is not None else ""

    def fillMatrix(
        self,
        rows: list[list[tuple]],
        *,
        start_row: int = 0,
        start_col: int = 1,
    ) -> None:
        """rows[r][c] = (text, bold[, image_url[, link_url[, footnote]]])."""
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                text = cell[0]
                bold = cell[1] if len(cell) > 1 else False
                img = cell[2] if len(cell) > 2 else None
                link = cell[3] if len(cell) > 3 else None
                fn = cell[4] if len(cell) > 4 else None
                self.setCellValue(
                    start_row + r, start_col + c, text,
                    bold=bold, image_url=img, link_url=link, footnote=fn,
                )

    def clearAll(self) -> None:
        self._build_model(self._model.rowCount(), self._model.columnCount())

    def dumpMatrix(self, rows: int, cols: int) -> list[list[tuple]]:
        """모델의 (0..rows, 0..cols) 영역을 (text, bold) 매트릭스로 추출."""
        out: list[list[tuple]] = []
        for r in range(rows):
            row: list[tuple] = []
            empty_tail_start = -1
            for c in range(cols):
                item = self._model.item(r, c)
                if item is None:
                    row.append(("", False))
                else:
                    text = item.text() or ""
                    bold = item.font().bold()
                    row.append((text, bold))
            # 행 끝의 빈 셀 trim
            while row and row[-1][0] == "":
                row.pop()
            out.append(row)
        # 매트릭스 끝의 빈 행 trim
        while out and (not out[-1] or all(c[0] == "" for c in out[-1])):
            out.pop()
        return out

    @property
    def model_(self) -> QStandardItemModel:
        return self._model

    # ------------------------------------------------------------------ setup
    def _build_appearance(self) -> None:
        self.setShowGrid(True)
        self.setGridStyle(Qt.SolidLine)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.setFrameShape(QTableView.NoFrame)
        self.setCornerButtonEnabled(True)

        hh = self.horizontalHeader()
        hh.setObjectName("SheetHHeader")
        hh.setDefaultAlignment(Qt.AlignCenter)
        hh.setDefaultSectionSize(82)
        hh.setMinimumSectionSize(8)  # 컬럼 폭 8px 까지 줄일 수 있게
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setFixedHeight(20)
        hh.setHighlightSections(True)

        vh = self.verticalHeader()
        vh.setObjectName("SheetVHeader")
        vh.setDefaultAlignment(Qt.AlignCenter)
        vh.setDefaultSectionSize(20)
        vh.setMinimumSectionSize(8)
        vh.setSectionResizeMode(QHeaderView.Interactive)
        vh.setFixedWidth(38)
        vh.setHighlightSections(True)

        self.horizontalScrollBar().setSingleStep(20)
        self.verticalScrollBar().setSingleStep(20)

    def _build_model(self, rows: int, cols: int) -> None:
        self._model = QStandardItemModel(rows, cols, self)
        self._model.setHorizontalHeaderLabels([column_letter(c) for c in range(cols)])
        self._model.setVerticalHeaderLabels([str(r + 1) for r in range(rows)])
        self.setModel(self._model)
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.selectionModel().setCurrentIndex(
            self._model.index(0, 0),
            QItemSelectionModel.ClearAndSelect,
        )
        if self._frozen is not None:
            self._frozen.setModel(self._model)
            self._update_frozen_geometry()

    # ------------------------------------------------------------------ frozen pane
    def _build_frozen_view(self) -> None:
        fv = QTableView(self)
        fv.setObjectName("SheetView")
        fv.setFocusPolicy(Qt.NoFocus)
        fv.setSelectionMode(QAbstractItemView.SingleSelection)
        fv.setSelectionBehavior(QAbstractItemView.SelectItems)
        fv.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        fv.setFrameShape(QFrame.NoFrame)
        fv.setShowGrid(True)
        fv.setGridStyle(Qt.SolidLine)
        fv.verticalHeader().hide()
        fv.horizontalHeader().hide()
        fv.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fv.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 헤더 행 시각 구분 — 살짝 다른 배경
        fv.setStyleSheet(
            "QTableView { background:#fafafa; gridline-color:#d4d4d4;"
            " selection-background-color:rgba(33,115,70,30); }"
        )
        fv.setModel(self._model)
        fv.doubleClicked.connect(self._on_double_clicked)
        fv.clicked.connect(self._on_single_clicked)
        fv.hide()
        self._frozen = fv

    def setFrozenTopRow(self, enabled: bool) -> None:
        self._frozen_enabled = bool(enabled)
        if self._frozen is None:
            return
        if self._frozen_enabled:
            self._update_frozen_geometry()
            self._frozen.show()
            self._frozen.raise_()
        else:
            self._frozen.hide()

    def _sync_frozen_section(self, logical_idx: int, _old: int, new_size: int) -> None:
        if self._frozen is None:
            return
        self._frozen.setColumnWidth(logical_idx, new_size)
        self._update_frozen_geometry()

    def _update_frozen_geometry(self) -> None:
        if self._frozen is None or not self._frozen_enabled:
            return
        vh_w = self.verticalHeader().width()
        hh_h = self.horizontalHeader().height()
        row_h = self.rowHeight(0)
        if row_h <= 0:
            row_h = self.verticalHeader().defaultSectionSize()
        fw = self.frameWidth()
        self._frozen.setGeometry(
            vh_w + fw,
            hh_h + fw,
            self.viewport().width(),
            row_h,
        )
        # 모든 컬럼 폭 동기화 (한 번 더 안전장치)
        for c in range(self._model.columnCount()):
            self._frozen.setColumnWidth(c, self.columnWidth(c))
        # frozen 은 첫 row 만 — viewport 의 origin 을 (0,0) 으로 강제
        self._frozen.verticalScrollBar().setValue(0)
        self._frozen.horizontalScrollBar().setValue(0)

    # ------------------------------------------------------------------ events
    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Delete:
            for idx in self.selectionModel().selectedIndexes():
                self._model.setData(idx, "", Qt.EditRole)
            e.accept()
            return
        super().keyPressEvent(e)

    def _on_current_changed(self, cur, _prev) -> None:
        if not cur.isValid():
            return
        addr = cell_address(cur.row(), cur.column())
        val = str(cur.data(Qt.EditRole) or "")
        self.cellSelected.emit(cur.row(), cur.column(), addr, val)

    def _on_double_clicked(self, idx) -> None:
        if not idx.isValid():
            return
        img = idx.data(IMAGE_URL_ROLE)
        if img:
            label = str(idx.data(Qt.DisplayRole) or "")
            self.imageCellActivated.emit(str(img), label)
            return
        link = idx.data(LINK_URL_ROLE)
        if link:
            self.linkCellActivated.emit(str(link))

    def _show_context_menu(self, pos) -> None:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        link = idx.data(LINK_URL_ROLE)
        if not link:
            return
        link = str(link)
        menu = QMenu(self)
        act_open = QAction("열기", menu)
        act_new = QAction("새 시트로 열기", menu)
        act_open.triggered.connect(lambda: self.linkCellActivated.emit(link))
        act_new.triggered.connect(lambda: self.linkOpenInNewSheet.emit(link))
        menu.addAction(act_open)
        menu.addAction(act_new)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _on_single_clicked(self, idx) -> None:
        if not idx.isValid():
            return
        fn = idx.data(FOOTNOTE_ROLE)
        if not fn:
            return
        rect = self.visualRect(idx)
        if not rect.isValid():
            return
        pos = self.viewport().mapToGlobal(rect.bottomLeft())
        QToolTip.showText(pos, str(fn), self.viewport())

    def visible_col_count(self) -> int:
        col_w = max(1, self.horizontalHeader().defaultSectionSize())
        vp_w = max(1, self.viewport().width())
        return max(1, vp_w // col_w)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_frozen_geometry()
        self.visibleColsChanged.emit(self.visible_col_count())
