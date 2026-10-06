from __future__ import annotations

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QKeyEvent, QStandardItem, QStandardItemModel,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QMenu, QStyle, QTableView, QToolTip, QWidget,
)


# 셀 모델 커스텀 데이터 슬롯
IMAGE_URL_ROLE = Qt.UserRole + 1
LINK_URL_ROLE = Qt.UserRole + 2
FOOTNOTE_ROLE = Qt.UserRole + 3

# 나무위키 시트 글꼴 — 페이지도 이 글꼴로 렌더링해서 글자 폭을 맞춤
DOC_FONT_FAMILY = "Malgun Gothic"


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
    cellEdited = Signal()                    # 셀 편집 (모델 itemChanged) — clearAll 후에도 살아남음
    imageCellActivated = Signal(str, str)   # url, alt_or_label
    linkCellActivated = Signal(str)         # href — 같은 시트에서 열기 (더블클릭 / 메뉴 "열기")
    linkOpenInNewSheet = Signal(str)        # href — 새 시트에서 열기
    visibleColsChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SheetView")
        self._frozen: QTableView | None = None
        self._frozen_enabled = False
        self._metrics_cache: dict[tuple[int, bool], QFontMetricsF] = {}
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
        italic: bool = False,
        strike: bool = False,
    ) -> None:
        item = self._model.item(row, col)
        if item is None:
            item = QStandardItem(value)
            self._model.setItem(row, col, item)
        else:
            item.setText(value)
        self._style_item(item, bold=bold, image_url=image_url, link_url=link_url,
                         footnote=footnote, italic=italic, strike=strike)

    @staticmethod
    def _style_item(
        item: QStandardItem,
        *,
        bold: bool = False,
        image_url: str | None = None,
        link_url: str | None = None,
        footnote: str | None = None,
        italic: bool = False,
        strike: bool = False,
        base_font: QFont | None = None,
    ) -> None:
        """base_font: 글꼴을 바꾸는 셀(굵게/밑줄 등)의 기준 글꼴 — 시트 글꼴(배율 반영)을 주면
        배율을 바꿨을 때 다른 셀과 같이 커지고 작아진다."""
        if base_font is not None and (bold or italic or strike or image_url or link_url):
            item.setFont(QFont(base_font))
        if bold or italic or strike:
            f = item.font()
            f.setBold(bool(bold))
            f.setItalic(bool(italic))
            f.setStrikeOut(bool(strike))
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

    def applyLayout(self, lay) -> None:
        """namuformatter.SheetLayout 을 채운다 — 셀마다 글자 한 조각 (모든 셀 같은 너비)."""
        rows = max(2000, lay.n_rows + 50)
        cols = max(60, lay.n_cols)

        base_font = QFont(self.font())
        base_font.setFamily(DOC_FONT_FAMILY)

        def fill(model: QStandardItemModel) -> None:
            for c in lay.cells:
                item = QStandardItem(c.text)
                self._style_item(item, bold=c.bold, image_url=c.image, link_url=c.link,
                                 footnote=c.footnote, italic=c.italic, strike=c.strike,
                                 base_font=base_font)
                item.setEditable(False)
                model.setItem(c.row, c.col, item)

        self._build_model(rows, cols, fill)

    def contentWidth(self) -> int:
        """세로 스크롤바가 생겨도 넘치지 않는, 셀 영역의 가용 폭(px)."""
        sb = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        w = self.width() - self.verticalHeader().width() - 2 * self.frameWidth() - sb
        return max(100, w)

    def columnPixelWidth(self) -> int:
        """기본 열(셀) 너비 — 모든 시트 공통, 배율로만 바뀜."""
        return self.horizontalHeader().defaultSectionSize()

    def basePixelSize(self) -> int:
        f = self.font()
        if f.pixelSize() > 0:
            return f.pixelSize()
        return max(8, round(f.pointSizeF() * self.logicalDpiY() / 72))

    def measureText(self, text: str, px: int, bold: bool) -> float:
        """셀 글꼴(맑은 고딕, px 크기)로 그렸을 때의 글자 폭."""
        key = (int(px), bool(bold))
        fm = self._metrics_cache.get(key)
        if fm is None:
            f = QFont(self.font())
            f.setFamily(DOC_FONT_FAMILY)
            f.setPixelSize(max(1, int(px)))
            f.setBold(bool(bold))
            fm = QFontMetricsF(f)
            self._metrics_cache[key] = fm
        return fm.horizontalAdvance(text)

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.FontChange:
            self._metrics_cache.clear()
        super().changeEvent(e)

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

    def _build_model(self, rows: int, cols: int, fill=None) -> None:
        model = QStandardItemModel(rows, cols, self)
        model.setHorizontalHeaderLabels([column_letter(c) for c in range(cols)])
        model.setVerticalHeaderLabels([str(r + 1) for r in range(rows)])
        if fill is not None:
            # 뷰에 붙이기 전에 채운다 — 붙은 모델에 setItem 하면 셀마다 뷰가 갱신돼 수 배 느림
            fill(model)
        model.itemChanged.connect(lambda _it: self.cellEdited.emit())
        old_model = getattr(self, "_model", None)
        old_sel = self.selectionModel()
        old_frozen_sel = self._frozen.selectionModel() if self._frozen is not None else None
        self._model = model
        self.setModel(self._model)
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.selectionModel().setCurrentIndex(
            self._model.index(0, 0),
            QItemSelectionModel.ClearAndSelect,
        )
        if self._frozen is not None:
            self._frozen.setModel(self._model)
            self._update_frozen_geometry()
        # 이전 모델/선택 모델 정리 (setModel 은 이전 것을 지우지 않음)
        for old in (old_sel, old_frozen_sel, old_model):
            if old is not None:
                old.deleteLater()

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
