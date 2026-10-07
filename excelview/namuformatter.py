from __future__ import annotations

"""positioned token (x/y/w/h) → 셀 레이아웃.

대원칙은 "엑셀로 보일 것". 페이지에서는 구조만 가져온다:
  - 셀 너비는 시트 기본 열 너비 하나로 고정 (배율을 바꿀 때만 변함). 글자는 셀 너비만큼
    잘라 한 셀에 하나씩 넣고, 나머지는 다음 셀에 이어 쓴다 — 셀을 병합하거나 옆 칸으로
    넘쳐 그리지 않는다. 줄 끝에 닿으면 아래 행으로 이어진다.
  - 각 텍스트 조각은 페이지상의 x 위치에 해당하는 열에서 시작 → 들여쓰기 / 표의 열 /
    정보상자 위치가 대략 유지됨.
  - 행은 "화면상의 한 줄" 단위로 묶는다 (세로 겹침 기준) — 줄 순서가 섞이지 않는다.
  - 글꼴 크기·글자색·배경색·행 높이는 페이지를 따르지 않는다. 모든 셀은 시트 기본 글꼴과
    기본 행 높이를 쓰고, 문단 사이 간격은 빈 행 한 줄로만 남긴다.
"""

from dataclasses import dataclass, field, replace
from typing import Callable

# 시트 기본 열 너비 (px, 배율 100%) — 위장 시트와 같음
COL_PX = 82
# 셀 너비 중 글자가 못 쓰는 부분 (스타일 여백 3+3 + QSS ::item padding 3+3 + 여유 2).
# 이보다 넓은 글자는 셀에 다 안 보이므로 잘라서 다음 셀로 넘긴다.
CELL_TEXT_MARGIN = 14
# 그림/동영상 자리를 줄 묶기에 쓸 때의 높이 (실제 그림 높이 대신 한 줄)
IMAGE_ROW_PX = 20
# 앞 줄과 이만큼(앞 줄 높이 대비) 이상 떨어져 있으면 빈 행 한 줄을 둔다 — 문단 구분
PARAGRAPH_GAP = 0.5
# 이어지는 줄이 시작할 열에서 오른쪽 끝까지 최소 이만큼은 있어야 함 (아니면 왼쪽부터)
MIN_WRAP_COLS = 3
# 같은 블록에서 페이지상 간격이 이 셀 수 미만이면 바로 이어지는 조각으로 본다
INLINE_GAP_CELLS = 1.5
# 셀을 자를 때 끝에서 이 글자 수 안에 띄어쓰기가 있으면 거기서 자른다
CHUNK_SPACE_SNAP = 2

MAX_ROWS = 20000

# measure(text, font_px, bold) -> 실제 셀 글꼴로 그렸을 때의 폭(px)
Measure = Callable[[str, int, bool], float]


def text_px_per_cell(col_px: int) -> int:
    """셀 하나에 넣을 수 있는 글자 폭 (px)."""
    return max(8, col_px - CELL_TEXT_MARGIN)


@dataclass
class CellSpec:
    row: int
    col: int
    text: str
    bold: bool = False
    italic: bool = False
    strike: bool = False
    image: str | None = None
    link: str | None = None
    footnote: str | None = None


@dataclass
class SheetLayout:
    cells: list[CellSpec] = field(default_factory=list)
    n_rows: int = 0
    n_cols: int = 0
    # 페이지 안 이동 대상 id → 행 (목차 숫자 등 "#id" 링크를 누르면 이 행으로)
    anchors: dict[str, int] = field(default_factory=dict)


def _default_measure(text: str, font_px: int, bold: bool) -> float:
    w = 0.0
    for ch in text:
        w += 0.55 if ord(ch) < 128 else 1.0
    return w * font_px * (1.05 if bold else 1.0)


# 앞 토큰에 무조건 붙는 부호류 (href 가 달라도 join).
_PUNCT_GLUE = set(",.;:!?)\"'》」』]·…—–-~%")
# 뒤 토큰에 붙는 여는 부호류
_PUNCT_OPEN = set("(\"'《「『[")


def _is_punct_only(v: str, chars: set[str]) -> bool:
    s = (v or "").strip()
    return bool(s) and all(ch in chars for ch in s)


class _Frag:
    __slots__ = ("kind", "text", "x0", "x1", "y0", "y1", "bottom", "blk", "style",
                 "href", "fn", "src", "ls", "ts")

    def __init__(self, **kw) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def _vertical_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    ov = min(a1, b1) - max(a0, b0)
    if ov <= 0:
        return 0.0
    return ov / max(1e-6, min(a1 - a0, b1 - b0))


def _build_frags(doc: dict, k: float) -> list[_Frag]:
    tokens = doc.get("tokens") or []
    styles = doc.get("styles") or []
    frags: list[_Frag] = []
    seen_img: set[tuple] = set()
    for tok in tokens:
        x, y = float(tok.get("x", 0)), float(tok.get("y", 0))
        w, h = float(tok.get("w", 0)), float(tok.get("h", 0))
        if tok.get("t") == "v":
            frags.append(_Frag(
                kind="v", text="", x0=x * k, x1=(x + w) * k, y0=y * k,
                y1=y * k + min(h * k, IMAGE_ROW_PX), bottom=(y + h) * k,
                blk=tok.get("b"), style=None, href=None, fn=None,
                src=(tok.get("src") or "").strip(),
            ))
            continue
        if tok.get("t") == "i":
            src = (tok.get("src") or "").strip()
            if not src:
                continue  # lazy-load placeholder — 같은 자리에 진짜 img 가 따로 있음
            key = (round(x), round(y), round(w), round(h), src)
            if key in seen_img:
                continue
            seen_img.add(key)
            frags.append(_Frag(
                kind="i", text=(tok.get("alt") or "").strip(),
                x0=x * k, x1=(x + w) * k, y0=y * k,
                y1=y * k + min(h * k, IMAGE_ROW_PX), bottom=(y + h) * k,
                blk=tok.get("b"), style=None,
                href=(tok.get("href") or None), fn=(tok.get("fn") or None), src=src,
            ))
            continue
        text = (tok.get("v") or "").strip()
        if not text:
            continue
        si = tok.get("s")
        st = styles[si] if isinstance(si, int) and 0 <= si < len(styles) else {}
        frags.append(_Frag(
            kind="x", text=text,
            x0=x * k, x1=(x + w) * k, y0=y * k, y1=(y + h) * k, bottom=(y + h) * k,
            blk=tok.get("b"), style=st,
            href=(tok.get("href") or None), fn=(tok.get("fn") or None),
            ls=bool(tok.get("ls")), ts=bool(tok.get("ts")),
        ))
    return frags


def _merge_inline(frags: list[_Frag]) -> list[_Frag]:
    """문서 순서상 이어지는, 같은 줄·같은 블록의 텍스트 조각을 합친다.

    - 링크/각주가 다르면 분리 (셀마다 링크 하나)
    - 글꼴 스타일이 다르면 분리 (굵게/색 유지) — 단, 2자 이하 짧은 조각은 합침
    - 부호만 있는 조각은 링크가 달라도 앞/뒤 조각에 붙인다
    """
    out: list[_Frag] = []
    for f in frags:
        prev = out[-1] if out else None
        if (prev is None or prev.kind != "x" or f.kind != "x" or prev.blk != f.blk
                or _vertical_overlap(prev.y0, prev.y1, f.y0, f.y1) < 0.5):
            out.append(f)
            continue
        fs = max(prev.y1 - prev.y0, 1.0) * 0.7   # 조각 높이 ≈ 글자 크기 × 1.4
        gap = f.x0 - prev.x1
        if gap < -2 or gap > max(6.0, fs):
            out.append(f)
            continue
        same_link = prev.href == f.href and prev.fn == f.fn
        same_style = prev.style == f.style
        short = len(prev.text) <= 2 or len(f.text) <= 2
        glue_back = _is_punct_only(f.text, _PUNCT_GLUE)
        glue_fwd = _is_punct_only(prev.text, _PUNCT_OPEN) and not prev.href and not prev.fn
        if not (glue_back or glue_fwd or (same_link and (same_style or short))):
            out.append(f)
            continue
        sep = " " if (prev.ts or f.ls or gap > fs * 0.2) else ""
        if glue_back and not f.ls:
            sep = ""
        if glue_fwd:
            # 여는 괄호는 뒤 조각(링크 등)의 속성을 따른다
            prev.href, prev.fn, prev.style = f.href, f.fn, f.style
            if not prev.ts:
                sep = ""
        elif len(f.text) > len(prev.text) and not same_style and not glue_back:
            prev.style = f.style
        prev.text = prev.text + sep + f.text
        prev.x1 = max(prev.x1, f.x1)
        prev.y0 = min(prev.y0, f.y0)
        prev.y1 = max(prev.y1, f.y1)
        prev.bottom = max(prev.bottom, f.bottom)
        prev.ts = f.ts
    return out


class _Row:
    __slots__ = ("top", "bot", "frags")

    def __init__(self, f: _Frag) -> None:
        self.top, self.bot, self.frags = f.y0, f.y1, [f]


def _cluster_rows(frags: list[_Frag], unit: float = 1.0) -> list[_Row]:
    """세로로 충분히 겹치는 조각끼리 한 행. 가로로 겹치는 조각은 절대 같은 행에 넣지 않는다.

    unit: x 좌표 1px 에 해당하는 값 (겹침 판정 오차)."""
    rows: list[_Row] = []
    for f in sorted(frags, key=lambda q: q.y0):
        best, best_ov = None, 0.3
        fy0, fy1 = f.y0, f.y1
        for row in reversed(rows[-12:]):
            if row.bot <= fy0:
                if row.bot < fy0 - 400:
                    break
                continue
            ov = min(row.bot, fy1) - max(row.top, fy0)
            if ov <= 0:
                continue
            ov /= max(1e-6, min(row.bot - row.top, fy1 - fy0))
            if ov < best_ov:
                continue
            if any(f.x0 < g.x1 - unit and g.x0 < f.x1 - unit for g in row.frags):
                continue
            best, best_ov = row, ov
        if best is None:
            rows.append(_Row(f))
        else:
            best.frags.append(f)
    return rows


def format_document(
    title: str,
    doc: dict,
    *,
    view_w: int,
    scale: float,
    col_px: int = COL_PX,
    font_px: int = 12,
    measure: Measure | None = None,
) -> SheetLayout:
    """페이지 → 시트 배치.

    view_w : 시트의 보이는 폭(px) — 보이는 열 수 = view_w // col_px. 넘치면 아래 행으로.
    scale  : 페이지 좌표 → 시트 px 비율. 셀 글꼴 / 페이지 글꼴 비율이어야 글자 폭이 맞는다.
    col_px : 셀(열) 너비 — 모든 셀이 같다.
    font_px: 시트 기본 글꼴 크기 — 모든 셀이 이 크기 하나로 그려진다 (폭 계산용).
    """
    measure = measure or _default_measure
    k = max(0.05, scale)
    n_cols = max(1, int(view_w // col_px))
    cell_text_px = text_px_per_cell(col_px)

    def width(t: str, bold: bool) -> float:
        return measure(t, font_px, bold)

    lay = SheetLayout(n_cols=n_cols)

    # ---- 제목 행 (1행, 스크롤과 함께 움직임) — 제목도 셀 너비만큼 잘라 이어 쓴다.
    #      본문은 바로 2행부터
    n_title_rows = 0
    if title:
        for i, piece in enumerate(_chunks(title, cell_text_px, lambda t: width(t, True))[:n_cols]):
            lay.cells.append(CellSpec(0, i, piece, bold=True))
        n_title_rows = 1

    frags = _merge_inline(_build_frags(doc, k))
    # 페이지 위치 → 셀 위치. 셀 하나에 글자가 cell_text_px 만큼 들어가므로 그 단위로 센다.
    # 본문 왼쪽 끝은 A열.
    if frags:
        dx = min(f.x0 for f in frags)
        for f in frags:
            f.x0 = (f.x0 - dx) / cell_text_px
            f.x1 = (f.x1 - dx) / cell_text_px
    rows = _cluster_rows(frags, unit=1.0 / cell_text_px)

    # ---- 화면상의 줄 → 행. 문단 사이(세로로 떨어진 곳)에는 빈 행 한 줄
    row_of: list[int] = []                  # rows[i] → 행 번호 (이어지는 행 끼우기 전)
    r_next = n_title_rows
    cursor = rows[0].top if rows else 0.0
    prev_h = 0.0
    for row in rows:
        if r_next >= MAX_ROWS:
            break
        if prev_h and row.top - cursor >= prev_h * PARAGRAPH_GAP:
            r_next += 1
        row_of.append(r_next)
        r_next += 1
        h = max(f.y1 - f.y0 for f in row.frags)
        cursor = max(cursor, row.top + h, max(f.bottom for f in row.frags))
        prev_h = h
    n_base_rows = r_next

    # ---- 셀 배치 — 조각마다 셀 너비만큼 잘라 한 셀에 하나씩. 같은 문장에서 이어지는 조각은
    #      바로 다음 셀부터. 줄 끝(보이는 마지막 열)에 닿으면 아래에 끼워 넣은 행으로 이어 쓴다.
    extra_lines: dict[int, int] = {}            # 행 → 추가로 끼워 넣은 줄 수
    placed: list[tuple[CellSpec, int, int]] = []  # (셀, 원래 행, 몇 번째 줄)
    for row, out_r in zip(rows, row_of):
        items = sorted(row.frags, key=lambda q: q.x0)
        line = 0          # 0 = 원래 행, 1.. = 이어지는 행
        cursor_col = 0    # 현재 줄에서 다음으로 쓸 수 있는 열
        # 이어지는 행은 그 문단(블록)이 이 줄에서 시작한 열부터 — 문단 왼쪽 끝 맞춤
        block_left: dict = {}
        for f in items:
            block_left.setdefault(f.blk, max(0, int(round(f.x0))))
        prev_f = None
        for f in items:
            natural = max(0, int(round(f.x0)))
            inline_next = (prev_f is not None and prev_f.blk == f.blk
                           and f.x0 - prev_f.x1 < INLINE_GAP_CELLS)
            prev_f = f
            wrap_col = min(block_left.get(f.blk, natural), natural)
            if n_cols - wrap_col < MIN_WRAP_COLS:
                wrap_col = 0
            st = f.style or {}
            if f.kind == "v":
                base = CellSpec(out_r, 0, "[동영상] " + f.src)
            elif f.kind == "i":
                label = "[사진보기]" + (f" — {f.text}" if f.text else "")
                base = CellSpec(out_r, 0, label, image=f.src, link=f.href, footnote=f.fn)
            else:
                base = CellSpec(
                    out_r, 0, f.text,
                    bold=bool(st.get("b")), italic=bool(st.get("i")), strike=bool(st.get("s")),
                    link=None if f.fn else f.href, footnote=f.fn,
                )
            if line > 0:
                c = max(cursor_col, wrap_col)
            elif inline_next:
                c = cursor_col
            else:
                c = max(natural, cursor_col)
            bold = base.bold
            for piece in _chunks(base.text, cell_text_px, lambda t: width(t, bold)):
                if c >= n_cols:
                    line += 1
                    c = wrap_col
                placed.append((replace(base, text=piece, col=c), out_r, line))
                c += 1
            cursor_col = c
        if line:
            extra_lines[out_r] = line

    # ---- 이어지는 행을 끼워 넣고 행 번호 다시 매기기
    new_index: list[int] = []
    shift = 0
    for r in range(n_base_rows):
        new_index.append(r + shift)
        shift += extra_lines.get(r, 0)
    for cell, base_r, line in placed:
        cell.row = new_index[base_r] + line
        lay.cells.append(cell)
    lay.n_rows = n_base_rows + shift

    # ---- 이동 대상 → 그 높이에서 시작하는 첫 행 (대상보다 아래쪽에 끝나는 첫 줄)
    for aid, ay in (doc.get("anchors") or {}).items():
        try:
            y = float(ay) * k
        except (TypeError, ValueError):
            continue
        for row, out_r in zip(rows, row_of):
            if row.bot > y + 0.5:
                lay.anchors[aid] = new_index[out_r]
                break
    lay.n_cols = max([n_cols] + [c.col + 1 for c in lay.cells])
    return lay


def _chunks(text: str, max_w: float, width_of) -> list[str]:
    """셀 하나(max_w)에 들어가는 만큼씩 자른 조각들.

    셀을 꽉 채운다 (단어 중간에서도 자름). 띄어쓰기에서만 자르면 셀마다 반 단어씩 비어
    페이지의 한 줄이 시트에서 두 행이 되기 쉽다. 셀 끝 바로 근처에 띄어쓰기가 있을 때만
    거기서 자른다.
    """
    out: list[str] = []
    rest = text.strip()
    while rest:
        if width_of(rest) <= max_w:
            out.append(rest)
            break
        lo, hi = 0, len(rest)
        while lo < hi:   # width_of(rest[:lo]) <= max_w 인 최대 lo
            mid = (lo + hi + 1) // 2
            if width_of(rest[:mid]) <= max_w:
                lo = mid
            else:
                hi = mid - 1
        if lo <= 0:
            lo = 1   # 셀이 한 글자보다 좁을 때
        sp = rest.rfind(" ", 0, lo + 1)
        cut = sp if sp >= max(1, lo - CHUNK_SPACE_SNAP) else lo
        out.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return out
