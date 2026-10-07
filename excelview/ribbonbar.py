from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_TABS: list[str] = [
    "파일",
    "홈",
    "삽입",
    "페이지 레이아웃",
    "수식",
    "데이터",
    "검토",
    "원본 보기",
]


_ACTION_TAB_NAME = "원본 보기"

_SEARCH_W = 280       # 검색창 기본 폭
_SEARCH_MIN_W = 100   # 창이 아주 좁을 때 줄어들 수 있는 최소 폭


class RibbonBar(QWidget):
    searchRequested = Signal(str)
    backRequested = Signal()
    openOriginalRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonBar")
        self.setFixedHeight(30 + 110)
        self.setMinimumWidth(0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tab_bar = QWidget(self)
        self._tab_bar.setObjectName("RibbonTabBar")
        self._tab_bar.setFixedHeight(30)
        self._tab_lay = QHBoxLayout(self._tab_bar)
        self._tab_lay.setContentsMargins(0, 0, 8, 0)
        self._tab_lay.setSpacing(0)
        root.addWidget(self._tab_bar)

        self._pages = QStackedWidget(self)
        self._pages.setObjectName("RibbonPages")
        self._pages.setMinimumWidth(0)
        root.addWidget(self._pages, 1)

        self._tab_btns: list[QToolButton] = []
        self._search_edit: QLineEdit | None = None

        self._build_tab_bar()
        self._build_all_pages()

        # Default = 홈
        self._tab_btns[1].setChecked(True)
        self._pages.setCurrentIndex(1)

    # ------------------------------------------------------------------ helpers
    @property
    def search_edit(self) -> QLineEdit:
        assert self._search_edit is not None
        return self._search_edit

    def setBackEnabled(self, enabled: bool) -> None:
        if self._back_btn is not None:
            self._back_btn.setEnabled(enabled)

    # ------------------------------------------------------------------ tab bar
    def _build_tab_bar(self) -> None:
        for i, name in enumerate(_TABS):
            btn = QToolButton(self._tab_bar)
            btn.setText(name)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedHeight(30)
            btn.setObjectName("RibbonTabFile" if i == 0 else "RibbonTab")
            btn.clicked.connect(lambda _checked=False, idx=i: self._on_tab_clicked(idx))
            self._tab_lay.addWidget(btn)
            self._tab_btns.append(btn)

        self._tab_lay.addStretch()

        # 뒤로 가기 버튼 + 검색창 — 탭 줄 레이아웃에는 같은 폭의 빈자리만 두고, 실제 위젯은
        # 보이는 영역 오른쪽 끝에 직접 놓는다. 창이 리본 최소 폭보다 좁아져 리본 오른쪽이
        # 잘려도 검색창은 늘 보이게 (대신 그 아래 탭이 가려짐).
        self._search_box = QWidget(self._tab_bar)
        self._search_box.setObjectName("RibbonSearchBox")
        self._search_box.setAttribute(Qt.WA_StyledBackground, True)
        box_lay = QHBoxLayout(self._search_box)
        box_lay.setContentsMargins(6, 0, 0, 0)
        box_lay.setSpacing(6)

        self._back_btn = QToolButton(self._search_box)
        self._back_btn.setObjectName("RibbonBack")
        self._back_btn.setText("◀")
        self._back_btn.setToolTip("뒤로 (Alt+←)")
        self._back_btn.setFixedSize(28, 22)
        self._back_btn.setFocusPolicy(Qt.NoFocus)
        self._back_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self.backRequested.emit)
        box_lay.addWidget(self._back_btn)

        self._search_edit = QLineEdit(self._search_box)
        self._search_edit.setObjectName("RibbonSearch")
        self._search_edit.setPlaceholderText("🔍  검색하거나 사이트 찾기")
        self._search_edit.setMinimumWidth(_SEARCH_MIN_W)
        self._search_edit.setFixedHeight(22)
        self._search_edit.returnPressed.connect(self._on_search_enter)
        box_lay.addWidget(self._search_edit, 1)

        # 넓은 창에서는 예전과 같은 자리 — 탭 줄 오른쪽 여백(8) 안쪽에 뒤로 버튼 + 280px 검색창
        self._search_box_w = 6 + 28 + 6 + _SEARCH_W
        self._tab_lay.addSpacing(self._search_box_w)
        self._visible_w: int | None = None
        self._place_search_box()

    def setVisibleWidth(self, w: int) -> None:
        """ClipBox 가 알려 주는, 화면에 실제로 보이는 리본 폭."""
        self._visible_w = w
        self._place_search_box()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_search_box()

    def _place_search_box(self) -> None:
        bar_w = self._tab_bar.width() or self.width()
        vis = bar_w if self._visible_w is None else min(bar_w, self._visible_w)
        right = vis - 8
        w = max(6 + 28 + 6 + _SEARCH_MIN_W, min(self._search_box_w, right))
        self._search_box.setGeometry(right - w, 4, w, 22)
        self._search_box.raise_()

    def _on_search_enter(self) -> None:
        text = (self._search_edit.text() if self._search_edit else "").strip()
        if text:
            self.searchRequested.emit(text)

    def _on_tab_clicked(self, idx: int) -> None:
        name = _TABS[idx] if 0 <= idx < len(_TABS) else ""
        if name == _ACTION_TAB_NAME:
            # 액션 탭 — 페이지 전환하지 않고 시그널만 발생, 이전 탭 active 유지
            self.openOriginalRequested.emit()
            cur = self._pages.currentIndex()
            if 0 <= cur < len(self._tab_btns):
                self._tab_btns[cur].setChecked(True)
            return
        self._pages.setCurrentIndex(idx)

    # ------------------------------------------------------------------ pages
    def _build_all_pages(self) -> None:
        self._pages.addWidget(self._wrap_scroll(self._build_placeholder("파일")))
        self._pages.addWidget(self._wrap_scroll(self._build_home_tab()))
        for name in _TABS[2:]:
            self._pages.addWidget(self._wrap_scroll(self._build_placeholder(name)))

    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        """Ribbon 페이지를 가로 스크롤 가능하게 — 윈도우 폭 줄여도 막히지 않게."""
        sa = QScrollArea()
        sa.setObjectName("RibbonScroll")
        sa.setWidget(content)
        sa.setWidgetResizable(False)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setMinimumWidth(0)
        return sa

    def _build_placeholder(self, name: str) -> QWidget:
        page = QWidget()
        page.setObjectName("RibbonPage")
        lay = QHBoxLayout(page)
        lay.setContentsMargins(10, 6, 10, 6)
        lbl = QLabel(f"[{name}] 탭 콘텐츠 영역")
        lbl.setStyleSheet("color: #808080; font-size: 11px;")
        lay.addWidget(lbl)
        lay.addStretch()
        return page

    def _build_home_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("RibbonPage")
        lay = QHBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)

        # ------- 클립보드
        clip = QWidget()
        cl = QHBoxLayout(clip)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        cl.addWidget(self._big_btn("📋", "붙여\n넣기"))
        col = QWidget()
        vc = QVBoxLayout(col)
        vc.setContentsMargins(0, 0, 0, 0)
        vc.setSpacing(1)
        vc.addWidget(self._small_btn("✂", "잘라내기"))
        vc.addWidget(self._small_btn("⧉", "복사"))
        vc.addWidget(self._small_btn("🖌", "서식 복사"))
        cl.addWidget(col)
        lay.addWidget(self._group("클립보드", clip))

        # ------- 글꼴
        font = QWidget()
        fl = QVBoxLayout(font)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)
        row1 = QHBoxLayout()
        row1.setSpacing(2)
        font_cb = QComboBox()
        font_cb.setFixedWidth(120)
        font_cb.addItems(["맑은 고딕", "굴림", "돋움", "바탕", "Calibri", "Arial"])
        row1.addWidget(font_cb)
        size_cb = QComboBox()
        size_cb.setFixedWidth(52)
        size_cb.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "36"])
        size_cb.setCurrentText("11")
        row1.addWidget(size_cb)
        row1.addStretch()
        fl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(1)
        for g in ["𝐁", "𝑰", "U̲", "⊞", "🎨", "A"]:
            row2.addWidget(self._small_icon_btn(g))
        row2.addStretch()
        fl.addLayout(row2)
        lay.addWidget(self._group("글꼴", font))

        # ------- 맞춤
        align = QWidget()
        al = QVBoxLayout(align)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(2)
        ar1 = QHBoxLayout()
        ar1.setSpacing(1)
        for g in ["⬆", "⬌", "⬇"]:
            ar1.addWidget(self._small_icon_btn(g))
        ar1.addSpacing(4)
        for g in ["⇤", "≡", "⇥"]:
            ar1.addWidget(self._small_icon_btn(g))
        ar1.addStretch()
        al.addLayout(ar1)

        ar2 = QHBoxLayout()
        ar2.setSpacing(1)
        ar2.addWidget(self._small_btn("↵", "줄 바꿈"))
        ar2.addWidget(self._small_btn("⇔", "셀 병합"))
        ar2.addStretch()
        al.addLayout(ar2)
        lay.addWidget(self._group("맞춤", align))

        # ------- 표시 형식
        fmt = QWidget()
        fl2 = QVBoxLayout(fmt)
        fl2.setContentsMargins(0, 0, 0, 0)
        fl2.setSpacing(2)
        fmt_cb = QComboBox()
        fmt_cb.setFixedWidth(110)
        fmt_cb.addItems(["일반", "숫자", "통화", "회계", "날짜", "시간", "백분율", "분수", "과학", "텍스트"])
        fl2.addWidget(fmt_cb)
        rr = QHBoxLayout()
        rr.setSpacing(1)
        for g in ["₩", "%", ",", ".0", "0."]:
            rr.addWidget(self._small_icon_btn(g))
        rr.addStretch()
        fl2.addLayout(rr)
        lay.addWidget(self._group("표시 형식", fmt))

        # ------- 스타일
        style = QWidget()
        sl = QHBoxLayout(style)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)
        sl.addWidget(self._big_btn("⊞", "조건부\n서식"))
        sl.addWidget(self._big_btn("⊠", "표 서식"))
        sl.addWidget(self._big_btn("✦", "셀\n스타일"))
        lay.addWidget(self._group("스타일", style))

        # ------- 셀
        cells = QWidget()
        ccl = QHBoxLayout(cells)
        ccl.setContentsMargins(0, 0, 0, 0)
        ccl.setSpacing(2)
        ccl.addWidget(self._big_btn("➕", "삽입"))
        ccl.addWidget(self._big_btn("➖", "삭제"))
        ccl.addWidget(self._big_btn("⚙", "서식"))
        lay.addWidget(self._group("셀", cells))

        # ------- 편집
        edit = QWidget()
        el = QVBoxLayout(edit)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(2)
        el.addWidget(self._small_btn("Σ", "자동 합계"))
        el.addWidget(self._small_btn("⤓", "채우기"))
        el.addWidget(self._small_btn("🧽", "지우기"))
        lay.addWidget(self._group("편집", edit))

        lay.addStretch()
        return page

    # ------------------------------------------------------------------ widgets
    def _group(self, title: str, content: QWidget) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("RibbonGroup")
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(6, 2, 8, 0)
        vl.setSpacing(0)
        vl.addWidget(content, 1)
        lbl = QLabel(title)
        lbl.setObjectName("RibbonGroupTitle")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedHeight(16)
        vl.addWidget(lbl)

        outer = QWidget()
        hl = QHBoxLayout(outer)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(wrap)
        sep = QFrame()
        sep.setObjectName("RibbonGroupSep")
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        hl.addWidget(sep)
        return outer

    def _big_btn(self, glyph: str, text: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("RibbonBigBtn")
        b.setText(f"{glyph}\n{text}")
        b.setFixedSize(60, 76)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def _small_btn(self, glyph: str, text: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("RibbonSmallBtn")
        b.setText(f"{glyph}  {text}")
        b.setMinimumHeight(22)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def _small_icon_btn(self, glyph: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName("RibbonSmallBtn")
        b.setText(glyph)
        b.setFixedSize(24, 22)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        b.setFocusPolicy(Qt.NoFocus)
        return b
