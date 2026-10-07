from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QMainWindow, QVBoxLayout, QWidget

from excelview import decoystore
from excelview.clipbox import ClipBox
from excelview.decoysheets import decoy_sheet2, decoy_sheet3
from excelview.formulabar import FormulaBar
from excelview.imagedialog import ImageDialog
from excelview.namuformatter import format_document, text_px_per_cell
from excelview.namuloader import NamuLoader
from excelview.ribbonbar import RibbonBar
from excelview.sheettabbar import SheetTabBar
from excelview.sheetview import SheetView
from excelview.statusbar import ExcelStatusBar


# 나무위키 본문 글꼴 크기 (px) — 렌더 폭 계산용
NAMU_BODY_FONT_PX = 15
# 렌더 폭 여유 비율 — 셀 경계에서 자를 때 셀마다 조금씩 남는 폭, 글꼴 크기별 글자 폭 오차 흡수
PAGE_WIDTH_MARGIN = 0.93
# 읽던 위치를 찾을 때 쓰는 글자열 길이 (공백 제외)
ANCHOR_CHARS = 16


def _text_stream(lay) -> tuple[str, list[tuple[int, int]]]:
    """레이아웃의 글자를 읽는 순서(행, 열)대로 공백 없이 이어 붙인 문자열 + 셀별 (행, 시작 위치)."""
    parts: list[str] = []
    starts: list[tuple[int, int]] = []
    n = 0
    for c in sorted((c for c in lay.cells if c.row > 0), key=lambda c: (c.row, c.col)):
        t = "".join(c.text.split())
        starts.append((c.row, n))
        parts.append(t)
        n += len(t)
    return "".join(parts), starts


def _find_anchor_row(lay, snippet: str, frac: float) -> int:
    """snippet 이 나오는 곳 중 문서 안 비율이 frac 에 가장 가까운 곳의 행. 없으면 비율로."""
    stream, starts = _text_stream(lay)
    if not starts:
        return -1
    target = frac * len(stream)
    best = -1
    for size in (len(snippet), 8):
        part = snippet[:size]
        i = stream.find(part)
        while i >= 0:
            if best < 0 or abs(i - target) < abs(best - target):
                best = i
            i = stream.find(part, i + 1)
        if best >= 0:
            break
    off = best if best >= 0 else int(target)
    # off 를 품는 셀의 행
    row = starts[0][0]
    for r, start in starts:
        if start > off:
            break
        row = r
    return row


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sheet1 - Book1 - Excel")
        self.resize(1280, 800)

        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.ribbon = RibbonBar(self)
        self.formula = FormulaBar(self)
        self.sheet = SheetView(self)
        self.tabs = SheetTabBar(self)
        self.status = ExcelStatusBar(self)

        # 창 폭에 하한이 없도록 — 각 줄은 평소엔 지금처럼 창 폭에 맞춰 배치되고,
        # 자기 최소 폭보다 창이 좁아질 때만 오른쪽이 잘려 보인다 (시트는 계속 창 폭을 따름)
        lay.addWidget(ClipBox(self.ribbon))
        lay.addWidget(ClipBox(self.formula))
        lay.addWidget(self.sheet, 1)
        lay.addWidget(ClipBox(self.tabs))
        lay.addWidget(ClipBox(self.status))
        self.setCentralWidget(central)

        self.loader = NamuLoader(self)

        self._last_diag: dict = {}
        self._last_title: str = ""
        # 추출된 페이지 (tokens/styles/pageW/pageH/renderW) — namuformatter 입력
        self._last_doc: dict = {}
        self._last_url: str = ""
        self._last_layout_w: int = 0
        self._last_layout_rows: int = 0
        self._cur_layout = None   # 지금 그려진 SheetLayout (읽던 위치 찾기용)
        self._zoom: int = 100
        # 다음 _show_namu 에서 읽던 위치를 유지할지 (창 크기 때문에 다시 불러온 경우)
        self._keep_scroll_next = False
        # 계산한 셀 레이아웃 캐시 — 시트를 오갈 때 큰 문서도 다시 계산하지 않게.
        # (id(doc), 폭, 줌, 제목) -> (doc, layout)
        self._layout_cache: dict[tuple, tuple[dict, object]] = {}

        # 페이지 히스토리 — (title, doc, url, 읽던 위치) 스택. 링크 이동 시 push, 뒤로 시 pop.
        # 읽던 위치는 _top_anchor() 의 (글자열, 비율) — 문서 안 이동(목차 등)도 한 칸씩 쌓인다.
        self._history: list[tuple[str, dict, str, tuple[str, float] | None]] = []

        # 창 크기 변경 대응: ① 즉시 새 폭으로 다시 그림 (_refill_timer)
        #                  ② 잠시 뒤 페이지 자체를 새 폭으로 다시 배치해서 줄바꿈까지 맞춤
        self._refill_timer = QTimer(self)
        self._refill_timer.setSingleShot(True)
        self._refill_timer.timeout.connect(lambda: self._refill(keep_scroll=True))
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout_current)

        # ---- wiring
        self.ribbon.searchRequested.connect(self._on_search)
        self.ribbon.backRequested.connect(self._go_back)
        self.ribbon.openOriginalRequested.connect(self.loader.showDebugView)
        self.loader.loadStarted.connect(self._on_load_started)
        self.loader.loadProgress.connect(self._on_load_progress)
        self.loader.pageLoaded.connect(self._on_page_loaded)
        self.loader.bodyExtracted.connect(self._on_body_extracted)
        self.loader.relayoutDone.connect(self._on_relayout_done)
        self.loader.fetchFailed.connect(self._on_fetch_failed)
        self.loader.diagnostics.connect(self._on_diagnostics)

        self.sheet.cellSelected.connect(self._on_cell_selected)
        self.sheet.imageCellActivated.connect(self._on_image_cell)
        self.sheet.linkCellActivated.connect(self._on_link_cell)
        self.sheet.linkOpenInNewSheet.connect(self._on_link_cell_new_sheet)
        self.sheet.visibleColsChanged.connect(self._on_visible_cols)
        self.tabs.sheetChanged.connect(self._on_sheet_changed)
        self.tabs.newSheetRequested.connect(self._on_new_sheet)
        self.tabs.closeSheetRequested.connect(self._on_close_sheet)
        self.formula.formulaCommitted.connect(self._on_formula_committed)
        self.status.zoomChanged.connect(self._on_zoom_changed)

        # Sheet1 은 위장(decoy) 고정. Sheet2~ 는 namu 작업 영역.
        self._sheets: dict[int, dict] = {
            0: {"type": "decoy2"},  # Sheet1 = 위장 시트 (주간 업무)
            1: {"type": "namu", "doc": {}, "title": "", "url": ""},
        }
        self._current_sheet = 0
        self._pending_new_sheet: int | None = None
        # 로드를 시작한 namu 시트 — 비동기 추출 도중 다른 시트(위장 포함)로
        # 이동해도 결과는 항상 이 시트에 들어간다.
        self._loading_sheet: int | None = None
        self._decoy_dirty = False  # 사용자 편집 후만 True — 빈 모델로 저장 덮어쓰는 사고 방지
        self.sheet.setFrozenTopRow(True)
        # 셀 편집 추적 — sheet 자체 signal 이라 clearAll 후에도 살아남음
        self.sheet.cellEdited.connect(self._on_decoy_item_changed)
        # 시작 시 Sheet1 (위장) 표시
        self._on_sheet_changed(0)

        self.status.setSummary("준비")
        self._sheet_base_font: QFont = self.sheet.font()

        # Ctrl+D — namu.wiki 디버그 뷰 (실제 페이지를 별창에 visible 으로)
        sc = QShortcut(QKeySequence("Ctrl+D"), self)
        sc.activated.connect(self.loader.showDebugView)

        # Alt+Left / Backspace — 뒤로 가기
        for seq in ("Alt+Left", "Backspace"):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(self._go_back)

        # Ctrl+Z — 어느 시트에서든 즉시 Sheet1 (위장) 으로 전환
        panic = QShortcut(QKeySequence("Ctrl+Z"), self)
        panic.activated.connect(lambda: self.tabs.selectSheet(0))

        # Ctrl+S — 위장 시트 저장 (명시)
        save_sc = QShortcut(QKeySequence("Ctrl+S"), self)
        save_sc.activated.connect(self._on_save_shortcut)

    # ------------------------------------------------------------------ search
    def _ensure_namu_sheet_active(self) -> None:
        """현재 시트가 위장(decoy) 이면 namu 시트로 전환. 없으면 새로 만듦."""
        cur = self._sheets.get(self._current_sheet, {})
        if cur.get("type") == "namu":
            return
        for idx, info in self._sheets.items():
            if info.get("type") == "namu":
                self.tabs.selectSheet(idx)
                return
        new_idx = self.tabs.addSheet()
        self._sheets[new_idx] = {"type": "namu", "doc": {}, "title": "", "url": ""}
        self.tabs.selectSheet(new_idx)

    def _on_search(self, title: str) -> None:
        # 검색창/링크로 현재 시트에 여는 로드 — 진행 중이던 "새 시트로 열기" 로드는
        # (로더가 하나라) 여기서 취소된다. 결과가 엉뚱한 새 시트로 가지 않게 해제.
        self._pending_new_sheet = None
        self._ensure_namu_sheet_active()
        # 로드를 시작한 시트를 고정 — 추출 완료 시 현재 시트가 아니라
        # 이 시트가 결과를 받는다 (다른 시트로 이동해도 / 위장으로 숨어도).
        self._loading_sheet = self._current_sheet
        self._fetch(title)

    def _fetch(self, title: str) -> None:
        self.status.setStatusText(f"'{title}' 로드 중...")
        if self._pending_new_sheet is None:
            self.status.setSummary("")
        self.loader.setPageWidth(self._page_css_width())
        self.loader.fetch(title)

    def _page_scale(self) -> float:
        """페이지 px → 시트 px. 셀 글꼴 / 페이지 본문 글꼴 — 이래야 글자 폭이 맞는다 (줌 포함)."""
        return self.sheet.basePixelSize() / NAMU_BODY_FONT_PX

    def _page_css_width(self) -> int:
        """보이는 셀들에 들어갈 글자 폭을 페이지 px 로 — 이 폭으로 렌더링하면 페이지의
        한 줄이 시트의 한 행(보이는 셀들)에 들어간다.

        셀 하나에는 셀 너비에서 여백을 뺀 만큼만 글자가 들어가고, 본문은 A열부터 놓으며
        링크 등 조각마다 새 셀에서 시작하므로 한 셀을 빼고 7% 여유를 둔다.
        """
        col_px = self.sheet.columnPixelWidth()
        n_cols = self.sheet.contentWidth() // max(1, col_px)
        usable = max(1, n_cols - 1) * text_px_per_cell(col_px)
        return int(usable / self._page_scale() * PAGE_WIDTH_MARGIN)

    def _on_load_started(self, title: str) -> None:
        if self._pending_new_sheet is not None:
            return  # 백그라운드 새 시트 로드 — 지금 보고 있는 시트의 검색창은 그대로
        self.ribbon.search_edit.setText(title)
        # 윈도우 타이틀은 sheet 이름 기준 (문서 제목 노출 안 함)
        self._update_window_title()

    def _update_window_title(self) -> None:
        name = self.tabs.sheetName(self._current_sheet)
        self.setWindowTitle(f"{name} - Book1 - Excel")

    def _on_load_progress(self, p: int) -> None:
        self.status.setStatusText(f"로드 중… {p}%")

    def _on_page_loaded(self) -> None:
        # 성공했을 때만 — 실패면 _on_fetch_failed 가 실패 문구를 띄운다
        self.status.setStatusText("렌더링 완료, 본문 추출 중…")

    def _on_body_extracted(self, title: str, doc: dict, url: str) -> None:
        # 새 시트로 열기 — 결과는 그 시트에 저장만 하고, 보고 있던 시트는 그대로 둔다.
        # (사용자가 직접 그 탭을 눌러야 이동. 이미 그 탭을 보고 있으면 바로 그림)
        if self._pending_new_sheet is not None:
            target = self._pending_new_sheet
            self._pending_new_sheet = None
            if self._sheets.get(target, {}).get("type") != "namu":
                return
            self._sheets[target] = {"type": "namu", "doc": doc, "title": title, "url": url}
            if self._current_sheet == target:
                self._show_namu(title, doc, url)
            else:
                self.status.setStatusText(f"{self.tabs.sheetName(target)} 준비됨")
            return

        # 로드를 시작한 시트(= 브라우저 탭)에 저장 — 도중 다른 시트로 이동했어도
        # 그 시트가 받는다. 시작 시트가 닫혔으면(로딩 중 탭 닫기 = 취소) 결과 폐기.
        target = self._loading_sheet
        self._loading_sheet = None
        if target is None or self._sheets.get(target, {}).get("type") != "namu":
            self.status.setStatusText("준비")
            return
        self._sheets[target] = {"type": "namu", "doc": doc, "title": title, "url": url}
        # 현재 보고 있는 시트가 target 일 때만 화면 갱신. 아니면 조용히 저장만 —
        # 사용자가 이동한 시트/위장 시트를 함부로 전환하지 않는다(위장 보호).
        if self._current_sheet == target:
            self._show_namu(title, doc, url)
        else:
            # 백그라운드 시트에 저장 완료 — "로드 중…" 상태 문구만 정리.
            self.status.setStatusText("준비")

    def _show_namu(self, title: str, doc: dict, url: str) -> None:
        keep = self._keep_scroll_next and url == self._last_url
        self._keep_scroll_next = False
        self._last_title = title
        self._last_doc = doc
        self._last_url = url
        self._refill(keep_scroll=keep)
        self.ribbon.search_edit.setText(title)
        # 다른 폭에서 렌더링된 문서(창 크기를 바꾼 뒤 시트 전환/뒤로 가기 등)면 다시 배치
        self._schedule_relayout_if_needed()

    def _refill(self, keep_scroll: bool = False) -> None:
        if not self._last_doc:
            return
        # 읽던 위치 — 맨 위에 보이던 글자열 + 문서 안 위치 비율.
        # 다시 배치하면 줄바꿈이 달라지므로 행 번호가 아니라 글자열로 같은 곳을 찾는다.
        anchor = self._top_anchor() if keep_scroll else None
        view_w = self.sheet.contentWidth()
        font_px = self.sheet.basePixelSize()
        key = (id(self._last_doc), view_w, font_px, self.sheet.columnPixelWidth(), self._last_title)
        hit = self._layout_cache.get(key)
        if hit is not None and hit[0] is self._last_doc:
            lay = hit[1]
        else:
            lay = format_document(
                self._last_title, self._last_doc,
                view_w=view_w, scale=self._page_scale(),
                col_px=self.sheet.columnPixelWidth(),
                font_px=font_px, measure=self.sheet.measureText,
            )
            if len(self._layout_cache) >= 8:
                self._layout_cache.pop(next(iter(self._layout_cache)))
            self._layout_cache[key] = (self._last_doc, lay)
        self.sheet.applyLayout(lay)
        self._last_layout_w = view_w
        self._last_layout_rows = lay.n_rows
        self._cur_layout = lay
        if anchor is not None:
            row = _find_anchor_row(lay, *anchor)
            if row > 0:
                self.sheet.scrollTo(self.sheet.model().index(row, 0),
                                    QAbstractItemView.ScrollHint.PositionAtTop)
        tokens = self._last_doc.get("tokens") or []
        n_img = sum(1 for t in tokens if isinstance(t, dict) and t.get("t") == "i" and t.get("src"))
        self.status.setStatusText("준비")
        self.status.setSummary(f"{lay.n_rows}행 · 사진 {n_img}장")

    def _top_anchor(self) -> tuple[str, float] | None:
        """맨 위에 보이는 줄부터의 글자열(공백 제외 앞부분)과, 그 지점의 문서 안 비율."""
        lay = self._cur_layout
        if lay is None:
            return None
        first = max(0, self.sheet.rowAt(0))
        stream, starts = _text_stream(lay)
        for i, (row, _off) in enumerate(starts):
            if row >= first:
                off = starts[i][1]
                snippet = stream[off:off + ANCHOR_CHARS]
                if snippet:
                    return snippet, off / max(1, len(stream))
                break
        return None

    def _on_visible_cols(self, _cols: int) -> None:
        # 창 크기 변경 — namu 시트를 볼 때만, 그리고 폭이 실제로 바뀌었을 때만.
        if (self._sheets.get(self._current_sheet, {}).get("type") == "namu"
                and self._last_doc
                and self.sheet.contentWidth() != self._last_layout_w):
            self._refill_timer.start(150)      # ① 바로: 새 폭으로 다시 그림
            self._relayout_timer.start(600)    # ② 크기 조절이 멈추면: 페이지 다시 배치

    def _schedule_relayout_if_needed(self) -> None:
        render_w = int(self._last_doc.get("renderW") or 0) if self._last_doc else 0
        if self._last_doc and abs(render_w - self._page_css_width()) > 16:
            self._relayout_timer.start(300)

    def _relayout_current(self) -> None:
        """현재 시트의 문서를 지금 창 폭으로 페이지에서 다시 배치해서 읽어 온다."""
        info = self._sheets.get(self._current_sheet, {})
        if info.get("type") != "namu" or not self._last_doc or not self._last_url:
            return
        if self._loading_sheet is not None or self._pending_new_sheet is not None:
            return  # 다른 로드 진행 중 — 끝나고 보여줄 때 다시 확인됨
        want = self._page_css_width()
        if abs(int(self._last_doc.get("renderW") or 0) - want) <= 16:
            return
        if self.loader.loadedUrl() == self._last_url:
            # 같은 페이지가 열려 있음 — 네트워크 없이 폭만 바꿔서 다시 읽음 (1초 이내)
            if self.loader.relayout(want):
                self.status.setStatusText("창 크기에 맞춰 다시 배치 중…")
            return
        # 다른 문서가 열려 있음 — 이 문서를 새 폭으로 다시 불러온다 (읽던 위치 유지)
        self._loading_sheet = self._current_sheet
        self._keep_scroll_next = True
        self.status.setStatusText("창 크기에 맞춰 다시 불러오는 중…")
        self.loader.setPageWidth(want)
        self.loader.fetch(self._last_url)

    def _on_relayout_done(self, url: str, doc: dict) -> None:
        # 같은 주소를 보여주는 시트들의 문서를 새 배치로 교체
        for info in self._sheets.values():
            if info.get("type") == "namu" and info.get("url") == url:
                info["doc"] = doc
        if (self._sheets.get(self._current_sheet, {}).get("type") == "namu"
                and self._last_url == url):
            self._last_doc = doc
            self._refill(keep_scroll=True)

    # ------------------------------------------------------------------ sheet tabs
    def _commit_active_editor(self) -> None:
        """편집 중인 셀의 editor 를 강제 commit (편집 도중 저장 시 손실 방지)."""
        try:
            idx = self.sheet.currentIndex()
            if idx.isValid():
                w = self.sheet.indexWidget(idx)
                if w is not None:
                    self.sheet.commitData(w)
        except Exception:
            pass

    def _save_decoy_if_current(self, verbose: bool = False) -> None:
        """현재 시트가 위장 시트 (decoy2) 면 매트릭스 dump → 파일 저장.

        verbose=False (자동 저장) 일 땐 dirty 플래그 있을 때만 저장.
        verbose=True (Ctrl+S) 는 dirty 무시하고 강제 저장.
        """
        cur = self._sheets.get(self._current_sheet, {})
        if cur.get("type") != "decoy2":
            if verbose:
                self.status.setStatusText("저장은 Sheet1 (위장 시트) 에서만 동작합니다")
            return
        if not verbose and not self._decoy_dirty:
            return  # 사용자 편집 없음 → 빈 모델로 덮어쓰지 않음
        self._commit_active_editor()
        matrix = self.sheet.dumpMatrix(rows=80, cols=20)
        ok, info = decoystore.save(matrix)
        if ok:
            self._decoy_dirty = False
            if verbose:
                self.status.setStatusText(f"저장됨: {info}")
        else:
            self.status.setStatusText(f"저장 실패: {info}")

    def _on_decoy_item_changed(self) -> None:
        """sheet.cellEdited 시 dirty 플래그 set."""
        if self._sheets.get(self._current_sheet, {}).get("type") == "decoy2":
            self._decoy_dirty = True

    def _on_save_shortcut(self) -> None:
        """Ctrl+S — 위장 시트 명시 저장."""
        self._save_decoy_if_current(verbose=True)

    def _on_sheet_changed(self, idx: int) -> None:
        """sheet 전환 — 떠나는 시트 스크롤 저장, 도착 시트 스크롤 복원."""
        # 떠나는 시트가 위장 시트면 편집 내용 저장
        self._save_decoy_if_current()
        # 떠나는 시트의 스크롤 위치 저장
        prev = self._sheets.get(self._current_sheet)
        if prev is not None:
            prev["scroll_v"] = self.sheet.verticalScrollBar().value()
            prev["scroll_h"] = self.sheet.horizontalScrollBar().value()
            # 나무위키 시트는 글자열로도 — 돌아왔을 때 창 크기가 바뀌어 배치가 달라져도
            # 같은 곳을 찾도록 (픽셀 스크롤 값은 배치가 같을 때만 맞음)
            prev["anchor"] = self._top_anchor() if prev.get("type") == "namu" else None
            prev["anchor_w"] = self._last_layout_w

        self._current_sheet = idx
        info = self._sheets.get(idx, {"type": "namu"})
        kind = info.get("type", "namu")
        # 위장 시트만 머리글 행 고정 — 나무위키 시트의 제목 행은 스크롤과 함께 움직인다
        self.sheet.setFrozenTopRow(kind != "namu")

        if kind == "decoy2":
            saved = decoystore.load()
            data = saved if saved else decoy_sheet2()
            self.sheet.clearAll()
            self.sheet.fillMatrix(data, start_row=0, start_col=0)
            self._decoy_dirty = False  # 로드 직후 — 빈 모델 사고 방지
            self.status.setSummary("주간 업무 진행 현황")
        elif kind == "decoy3":
            self.sheet.clearAll()
            self.sheet.fillMatrix(decoy_sheet3(), start_row=0, start_col=0)
            self.status.setSummary("자재 입출고 내역")
        else:
            # namu 시트
            self._last_title = info.get("title", "")
            self._last_doc = info.get("doc") or {}
            self._last_url = info.get("url", "")
            if self._last_doc:
                self._refill()
                self.ribbon.search_edit.setText(self._last_title)
                # 이 시트를 연 뒤 창 크기가 바뀌었으면 지금 폭으로 다시 배치
                self._schedule_relayout_if_needed()
            else:
                self.sheet.clearAll()
                self.status.setSummary(f"{self.tabs.sheetName(idx)} (비어 있음)")

        # 도착 시트의 저장된 스크롤 복원 — fillMatrix 끝난 뒤
        sv = info.get("scroll_v", 0)
        sh = info.get("scroll_h", 0)
        anchor = info.get("anchor")
        if (kind == "namu" and anchor and self._cur_layout is not None
                and info.get("anchor_w") != self._last_layout_w):
            # 떠난 뒤 창 크기가 바뀌어 배치가 달라짐 — 글자열로 읽던 곳 찾기
            row = _find_anchor_row(self._cur_layout, *anchor)
            if row > 0:
                self.sheet.scrollTo(self.sheet.model().index(row, 0),
                                    QAbstractItemView.ScrollHint.PositionAtTop)
        else:
            self.sheet.verticalScrollBar().setValue(sv)
        self.sheet.horizontalScrollBar().setValue(sh)
        self._update_window_title()

    def _on_new_sheet(self) -> None:
        """+ 버튼 → 빈 namu 작업 시트 추가."""
        new_idx = self.tabs.addSheet()
        self._sheets[new_idx] = {"type": "namu", "doc": {}, "title": "", "url": ""}
        self.tabs.selectSheet(new_idx)

    def _on_close_sheet(self, idx: int) -> None:
        """우클릭 → 시트 닫기. Sheet1 (idx 0) 은 차단."""
        if idx <= 0 or idx >= self.tabs.sheetCount():
            return

        # 1) TabBar 에서 위젯 제거
        self.tabs.closeSheet(idx)

        # 2) _sheets dict reindex — idx 이후 키를 -1 씩 이동
        new_sheets: dict[int, dict] = {}
        for k, v in self._sheets.items():
            if k == idx:
                continue
            new_sheets[k if k < idx else k - 1] = v
        self._sheets = new_sheets

        # 3) pending / loading 인덱스 갱신
        if self._pending_new_sheet is not None:
            if self._pending_new_sheet == idx:
                self._pending_new_sheet = None
            elif self._pending_new_sheet > idx:
                self._pending_new_sheet -= 1
        if self._loading_sheet is not None:
            if self._loading_sheet == idx:
                self._loading_sheet = None  # 시작 시트가 닫힘 → fallback 처리됨
            elif self._loading_sheet > idx:
                self._loading_sheet -= 1

        # 4) current_sheet 갱신 / 활성 탭 전환
        if self._current_sheet == idx:
            new_active = max(0, idx - 1)
            self._current_sheet = new_active
            self.tabs.selectSheet(new_active)
        elif self._current_sheet > idx:
            self._current_sheet -= 1

    def _on_link_cell_new_sheet(self, href: str) -> None:
        """우클릭 → '새 시트로 열기'. 새 sheet 탭 만들고 거기에 로드."""
        if not href:
            return
        if href.startswith("#"):
            # 페이지 안 링크 — 새 시트에는 이 문서를 불러온다
            if not self._last_url:
                return
            href = self._last_url.split("#", 1)[0] + href
        new_idx = self.tabs.addSheet()
        self._sheets[new_idx] = {"type": "namu", "doc": {}, "title": href, "url": ""}
        # 진행 중이던 현재 시트 로드는 취소됨 (로더가 하나)
        self._loading_sheet = None
        self._pending_new_sheet = new_idx
        # 현재 시트는 그대로 두고 — 로드가 끝나도 탭 전환 없이 그 시트에 저장만 함
        self._fetch(href)

    def _on_fetch_failed(self, title: str, msg: str) -> None:
        self.status.setStatusText(f"실패: {msg}")
        self.status.setSummary("")
        self._dump_diagnostics(title, msg)

    def _on_diagnostics(self, info: dict) -> None:
        self._last_diag = info or {}

    def _dump_diagnostics(self, title: str, err_msg: str) -> None:
        d = self._last_diag or {}
        lines: list[tuple[str, bool]] = []
        lines.append((f"[selector 진단] {title}", True))
        lines.append(("", False))
        lines.append((f"실패 사유: {err_msg}", False))
        lines.append(("(Ctrl+D 누르면 namu.wiki 페이지를 별창에 직접 띄움 — Cloudflare 차단인지 확인용)", False))
        lines.append(("", False))
        lines.append((f"진단 dict 키: {list(d.keys()) if d else '(빈 dict — JS 결과 자체가 안 옴)'}", False))
        lines.append((f"sel: {d.get('sel', '(missing)')}", False))
        lines.append((f"error: {d.get('error', '(none)')}", False))
        lines.append((f"URL: {d.get('url', '(no url)')}", False))
        lines.append((f"document.title: {d.get('title', '(no title)')}", False))
        lines.append((f"readyState: {d.get('readyState', '(unknown)')}", False))
        lines.append((f"body innerText length: {d.get('bodyTextLen', 0)}", False))
        lines.append((f"body innerHTML length: {d.get('bodyHtmlLen', 0)}", False))
        if d.get("raw_head"):
            lines.append((f"raw_head: {d.get('raw_head')}", False))
        lines.append(("", False))
        lines.append(("== 본문 후보 top 8 (휴리스틱) ==", True))
        for cand in d.get("top", []) or []:
            if isinstance(cand, dict):
                lines.append((
                    f"  [{cand.get('src','?')}] <{cand.get('tag','?')}>"
                    f" textLen={cand.get('textLen',0)}"
                    f" p={cand.get('pCount',0)}"
                    f" score={cand.get('score',0)}"
                    f" id={cand.get('id','')!r}"
                    f" cls={cand.get('cls','')!r}",
                    False,
                ))
        lines.append(("", False))
        lines.append(("== selector 시도 결과 (구버전) ==", True))
        for h in d.get("hits", []) or []:
            lines.append((str(h), False))
        lines.append(("", False))
        lines.append(("== 페이지에서 발견된 class 이름 (앞 40개) ==", True))
        for cn in d.get("classes", []) or []:
            lines.append((str(cn), False))
        lines.append(("", False))
        lines.append(("== body.innerText 앞 800자 ==", True))
        snippet = (d.get("bodySnippet") or "").splitlines()
        for ln in snippet:
            lines.append((ln, False))
        lines.append(("", False))
        lines.append(("== body.innerHTML 앞 2000자 ==", True))
        html = (d.get("htmlSnippet") or "")
        # HTML 한 줄이 너무 길면 80자씩 잘라서
        i = 0
        while i < len(html):
            lines.append((html[i:i + 80], False))
            i += 80

        rows = [[line] for line in lines]
        self.sheet.clearAll()
        self.sheet.fillMatrix(rows)
        self.status.setSummary(f"진단 {len(rows)}행")

    # ------------------------------------------------------------------ cell
    def _on_cell_selected(self, _row: int, _col: int, addr: str, value: str) -> None:
        self.formula.setCellAddress(addr)
        self.formula.setFormulaText(value)

    def _on_formula_committed(self, text: str) -> None:
        cur = self.sheet.selectionModel().currentIndex()
        if cur.isValid():
            self.sheet.setCellValue(cur.row(), cur.column(), text)

    def _on_image_cell(self, url: str, label: str) -> None:
        if not url:
            return
        dlg = ImageDialog(url, label, self)
        dlg.exec()

    def _push_history(self) -> None:
        if self._last_doc:
            at_top = self.sheet.verticalScrollBar().value() == 0
            self._history.append((self._last_title, self._last_doc, self._last_url,
                                  None if at_top else self._top_anchor()))
            self.ribbon.setBackEnabled(True)

    def _scroll_to_row(self, row: int) -> None:
        self.sheet.scrollTo(self.sheet.model().index(row, 0),
                            QAbstractItemView.ScrollHint.PositionAtTop)

    def _jump_in_page(self, anchor_id: str) -> None:
        """목차 숫자 등 페이지 안 링크 — 다시 불러오지 않고 그 위치의 행으로 스크롤."""
        lay = self._cur_layout
        row = lay.anchors.get(anchor_id) if lay is not None else None
        if row is None:
            self.status.setStatusText("이동할 위치를 찾지 못했습니다")
            return
        self._push_history()
        self._scroll_to_row(row)

    def _on_link_cell(self, href: str) -> None:
        if not href:
            return
        if href.startswith("#"):
            self._jump_in_page(href[1:])
            return
        self._push_history()
        # search_edit / 윈도우 타이틀은 loadStarted 에서 추출 title 로 반영
        self._on_search(href)

    def _go_back(self) -> None:
        if not self._history:
            self.status.setStatusText("뒤로 갈 페이지가 없습니다")
            return
        title, doc, url, anchor = self._history.pop()
        if url != self._last_url or not self._last_doc:
            self._show_namu(title, doc, url)
        # 이동하기 전에 보던 곳으로 (맨 위였으면 맨 위로)
        if anchor is None:
            self.sheet.verticalScrollBar().setValue(0)
        elif self._cur_layout is not None:
            row = _find_anchor_row(self._cur_layout, *anchor)
            if row >= 0:
                self._scroll_to_row(row)
        # 뒤로 간 결과도 현재 시트에 보존 (시트 전환 후 돌아와도 유지)
        cur = self._sheets.get(self._current_sheet)
        if cur is not None and cur.get("type") == "namu":
            cur.update({"doc": self._last_doc, "title": self._last_title, "url": self._last_url})
        self._update_window_title()
        self.ribbon.setBackEnabled(bool(self._history))

    # ------------------------------------------------------------------ shutdown
    def closeEvent(self, e) -> None:
        # 위장 시트 편집 내용 저장 (프로그램 다음 실행 시 유지)
        try:
            self._save_decoy_if_current()
        except Exception:
            pass
        try:
            self.loader.cleanup()
        except Exception:
            pass
        super().closeEvent(e)

    # ------------------------------------------------------------------ zoom
    def _on_zoom_changed(self, percent: int) -> None:
        self._zoom = percent
        base = self._sheet_base_font.pointSizeF() if self._sheet_base_font.pointSizeF() > 0 else 9.0
        scaled = max(4.0, base * percent / 100.0)
        f = QFont(self._sheet_base_font)
        f.setPointSizeF(scaled)
        self.sheet.setFont(f)

        # 행 높이도 살짝 맞춰줌 — 표준 20px → 비율로
        self.sheet.verticalHeader().setDefaultSectionSize(max(14, int(20 * percent / 100)))
        self.sheet.horizontalHeader().setDefaultSectionSize(max(40, int(82 * percent / 100)))
        if self._sheets.get(self._current_sheet, {}).get("type") == "namu" and self._last_doc:
            # 나무위키 시트: 셀 너비/글꼴이 바뀌었으니 다시 배치 (읽던 위치 유지) → 페이지도 새 폭으로
            self._refill(keep_scroll=True)
            self._schedule_relayout_if_needed()
