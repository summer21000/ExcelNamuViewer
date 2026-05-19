from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from excelview.decoysheets import decoy_sheet2, decoy_sheet3
from excelview.formulabar import FormulaBar
from excelview.imagedialog import ImageDialog
from excelview.namuformatter import format_positioned
from excelview.namuloader import NamuLoader
from excelview.ribbonbar import RibbonBar
from excelview.sheettabbar import SheetTabBar
from excelview.sheetview import SheetView
from excelview.statusbar import ExcelStatusBar


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

        lay.addWidget(self.ribbon)
        lay.addWidget(self.formula)
        lay.addWidget(self.sheet, 1)
        lay.addWidget(self.tabs)
        lay.addWidget(self.status)
        self.setCentralWidget(central)

        self.loader = NamuLoader(self)

        self._last_diag: dict = {}
        self._last_title: str = ""
        self._last_tokens: list[dict] = []
        self._last_url: str = ""
        self._last_page_w: int = 1280

        # 페이지 히스토리 — (title, tokens, url, page_w) 스택. 링크 이동 시 push, 뒤로 시 pop.
        self._history: list[tuple[str, list, str, int]] = []

        self._refill_timer = QTimer(self)
        self._refill_timer.setSingleShot(True)
        self._refill_timer.timeout.connect(self._refill)

        # ---- wiring
        self.ribbon.searchRequested.connect(self._on_search)
        self.ribbon.backRequested.connect(self._go_back)
        self.ribbon.openOriginalRequested.connect(self.loader.showDebugView)
        self.loader.loadStarted.connect(self._on_load_started)
        self.loader.loadProgress.connect(self._on_load_progress)
        self.loader.bodyExtracted.connect(self._on_body_extracted)
        self.loader.fetchFailed.connect(self._on_fetch_failed)
        self.loader.diagnostics.connect(self._on_diagnostics)

        self.sheet.cellSelected.connect(self._on_cell_selected)
        self.sheet.imageCellActivated.connect(self._on_image_cell)
        self.sheet.linkCellActivated.connect(self._on_link_cell)
        self.sheet.linkOpenInNewSheet.connect(self._on_link_cell_new_sheet)
        self.sheet.visibleColsChanged.connect(self._on_visible_cols)
        self.tabs.sheetChanged.connect(self._on_sheet_changed)
        self.formula.formulaCommitted.connect(self._on_formula_committed)
        self.status.zoomChanged.connect(self._on_zoom_changed)

        # Sheet1 은 위장(decoy) 고정. Sheet2~ 는 namu 작업 영역.
        self._sheets: dict[int, dict] = {
            0: {"type": "decoy2"},  # Sheet1 = 위장 시트 (주간 업무)
            1: {"type": "namu", "tokens": [], "title": "", "url": "", "page_w": 1280},
        }
        self._current_sheet = 0
        self._pending_new_sheet: int | None = None
        self.sheet.setFrozenTopRow(True)
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
        self._sheets[new_idx] = {
            "type": "namu", "tokens": [], "title": "",
            "url": "", "page_w": 1280,
        }
        self.tabs.selectSheet(new_idx)

    def _on_search(self, title: str) -> None:
        # 새 시트로 열기 진행 중이 아니라면 namu 시트가 활성 상태여야
        if self._pending_new_sheet is None:
            self._ensure_namu_sheet_active()
        self.status.setStatusText(f"'{title}' 로드 중...")
        self.status.setSummary("")
        self.loader.fetch(title)

    def _on_load_started(self, title: str) -> None:
        self.ribbon.search_edit.setText(title)
        # 윈도우 타이틀은 sheet 이름 기준 (문서 제목 노출 안 함)
        self._update_window_title()

    def _update_window_title(self) -> None:
        name = self.tabs.sheetName(self._current_sheet)
        self.setWindowTitle(f"{name} - Book1 - Excel")

    def _on_load_progress(self, p: int) -> None:
        if p < 100:
            self.status.setStatusText(f"로드 중… {p}%")
        else:
            self.status.setStatusText("렌더링 완료, 본문 추출 중…")

    def _on_body_extracted(self, title: str, tokens: list, url: str,
                           page_w: int = 1280, page_h: int = 0) -> None:
        # 새 시트로 열기 진행 중이면 그 시트에 저장 + 활성화
        if self._pending_new_sheet is not None:
            target = self._pending_new_sheet
            self._pending_new_sheet = None
            self._sheets[target] = {
                "type": "namu", "tokens": tokens, "title": title,
                "url": url, "page_w": page_w,
            }
            self.tabs.selectSheet(target)
            return

        # 현재 시트가 namu 타입이면 그것에 저장. 아니면 sheet0 에 저장 (기본 namu 시트)
        target = self._current_sheet if self._sheets.get(self._current_sheet, {}).get("type") == "namu" else 0
        self._sheets[target] = {
            "type": "namu", "tokens": tokens, "title": title,
            "url": url, "page_w": page_w,
        }
        # 현재 시트가 그 target 이면 화면 갱신
        if self._current_sheet == target:
            self._last_title = title
            self._last_tokens = tokens
            self._last_url = url
            self._last_page_w = page_w
            self._refill()
        else:
            self.tabs.selectSheet(target)

    def _refill(self) -> None:
        if not self._last_tokens:
            return
        max_cols = self.sheet.visible_col_count()
        rows = format_positioned(
            self._last_title, self._last_tokens,
            page_w=self._last_page_w, max_cols=max_cols,
        )
        self.sheet.clearAll()
        self.sheet.fillMatrix(rows, start_row=0, start_col=0)
        n_img = sum(1 for t in self._last_tokens if isinstance(t, dict) and t.get("t") == "i")
        self.status.setStatusText("준비")
        self.status.setSummary(f"{len(rows)}행 (cols={max_cols}) · 사진 {n_img}장")

    def _on_visible_cols(self, _cols: int) -> None:
        # resize debounce — 200ms 동안 추가 resize 없으면 재포맷
        if self._current_sheet == 0 and self._last_tokens:
            self._refill_timer.start(200)

    # ------------------------------------------------------------------ sheet tabs
    def _on_sheet_changed(self, idx: int) -> None:
        """sheet 인덱스별 데이터 표시. namu 타입은 저장된 tokens 로 재렌더."""
        self._current_sheet = idx
        info = self._sheets.get(idx, {"type": "namu"})
        kind = info.get("type", "namu")
        if kind == "decoy2":
            self.sheet.clearAll()
            self.sheet.fillMatrix(decoy_sheet2(), start_row=0, start_col=0)
            self.status.setSummary("주간 업무 진행 현황")
            return
        if kind == "decoy3":
            self.sheet.clearAll()
            self.sheet.fillMatrix(decoy_sheet3(), start_row=0, start_col=0)
            self.status.setSummary("자재 입출고 내역")
            return
        # namu 시트
        self._last_title = info.get("title", "")
        self._last_tokens = info.get("tokens", [])
        self._last_url = info.get("url", "")
        self._last_page_w = info.get("page_w", 1280)
        if self._last_tokens:
            self._refill()
            self.ribbon.search_edit.setText(self._last_title)
        else:
            self.sheet.clearAll()
            self.status.setSummary(f"{self.tabs.sheetName(idx)} (비어 있음)")
        self._update_window_title()

    def _on_link_cell_new_sheet(self, href: str) -> None:
        """우클릭 → '새 시트로 열기'. 새 sheet 탭 만들고 거기에 로드."""
        if not href:
            return
        new_idx = self.tabs.addSheet()
        self._sheets[new_idx] = {
            "type": "namu", "tokens": [], "title": href,
            "url": "", "page_w": 1280,
        }
        self._pending_new_sheet = new_idx
        # 현재 시트는 그대로 두고 — fetch 끝나면 _on_body_extracted 에서 새 탭 활성화
        self._on_search(href)

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

    def _on_link_cell(self, href: str) -> None:
        if not href:
            return
        if self._last_tokens:
            self._history.append((
                self._last_title, self._last_tokens,
                self._last_url, self._last_page_w,
            ))
            self.ribbon.setBackEnabled(True)
        # search_edit / 윈도우 타이틀은 loadStarted 에서 추출 title 로 반영
        self._on_search(href)

    def _go_back(self) -> None:
        if not self._history:
            self.status.setStatusText("뒤로 갈 페이지가 없습니다")
            return
        title, tokens, url, page_w = self._history.pop()
        self._last_title = title
        self._last_tokens = tokens
        self._last_url = url
        self._last_page_w = page_w
        self._refill()
        self.ribbon.search_edit.setText(title)
        self._update_window_title()
        self.ribbon.setBackEnabled(bool(self._history))

    # ------------------------------------------------------------------ shutdown
    def closeEvent(self, e) -> None:
        try:
            self.loader.cleanup()
        except Exception:
            pass
        super().closeEvent(e)

    # ------------------------------------------------------------------ zoom
    def _on_zoom_changed(self, percent: int) -> None:
        base = self._sheet_base_font.pointSizeF() if self._sheet_base_font.pointSizeF() > 0 else 9.0
        scaled = max(4.0, base * percent / 100.0)
        f = QFont(self._sheet_base_font)
        f.setPointSizeF(scaled)
        self.sheet.setFont(f)

        # 행 높이도 살짝 맞춰줌 — 표준 20px → 비율로
        self.sheet.verticalHeader().setDefaultSectionSize(max(14, int(20 * percent / 100)))
        self.sheet.horizontalHeader().setDefaultSectionSize(max(40, int(82 * percent / 100)))
