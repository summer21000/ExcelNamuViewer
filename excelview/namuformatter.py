from __future__ import annotations

"""positioned token (x/y/w/h) → 셀 매트릭스.

같은 행에서 가까이 붙어있는 토큰은 한 셀에 자동 join,
멀리 떨어진 토큰 사이는 빈 셀로 두어 페이지 좌우 구조 유지.
"""

# 한 토큰을 자기 시작 좌표에 둘 때 사용하는 그리드 분해능
COL_WIDTH = 90       # px / cell  (셀 한 칸 가로폭의 명목값)
ROW_HEIGHT = 24      # px / cell  (셀 한 칸 세로폭)

# 같은 행에서 인접 토큰 사이의 가로 간격이 이 값 미만이면 같은 셀로 join.
JOIN_GAP_PX = 30

# 한 셀의 텍스트 폭 한도. 한글 1자 = 2 단위, 영문 1자 = 1 단위.
# 한글 6자 (= 12 단위) 기준. 사용자 선호.
CELL_WIDTH_UNITS = 12

# 한 row 에 들어갈 셀 수의 최대치. 이를 넘는 텍스트는 다음 row 로 줄바꿈 (브라우저처럼).
MAX_COLS_VISIBLE = 18

MAX_COLS = 80
MAX_ROWS = 5000


def _char_w(ch: str) -> int:
    """대략적인 폭 — ASCII 1, 그 외 (한글/한자/이모지) 2."""
    return 1 if ord(ch) < 128 else 2


def _text_w(text: str) -> int:
    return sum(_char_w(c) for c in text)


def _split_text_to_cells(text: str, max_w: int) -> list[str]:
    """띄어쓰기(단어) 경계 우선으로 잘라 옆 셀로 흘림.

    여러 단어가 셀 폭에 들어가면 한 셀에 합치고, 한 단어가 폭을 넘으면 강제 분할.
    """
    text = text.strip()
    if not text:
        return []
    if _text_w(text) <= max_w:
        return [text]

    def cut_by_width(s: str, w: int) -> tuple[str, str]:
        acc = 0
        for i, ch in enumerate(s):
            cw = _char_w(ch)
            if acc + cw > w:
                return s[:i], s[i:]
            acc += cw
        return s, ""

    out: list[str] = []
    words = text.split(" ")
    cur = ""
    cur_w = 0
    for w in words:
        ww = _text_w(w)
        sep = 1 if cur else 0
        if cur_w + sep + ww <= max_w:
            cur = (cur + " " + w) if cur else w
            cur_w += sep + ww
            continue
        if cur:
            out.append(cur)
            cur, cur_w = "", 0
        # 단어 자체가 셀 폭 보다 큰 경우 강제 분할
        while _text_w(w) > max_w:
            head, w = cut_by_width(w, max_w)
            if head:
                out.append(head)
            else:
                break
        cur = w
        cur_w = _text_w(w)
    if cur:
        out.append(cur)
    return out


def _is_text(tok: dict) -> bool:
    return tok.get("t") == "x"


# 앞 토큰에 무조건 붙는 부호류 (href 가 달라도 join).
_PUNCT_GLUE = set(",.;:!?)\"'》」』]·…—–-")


def _is_punct_only(v: str) -> bool:
    s = (v or "").strip()
    if not s:
        return False
    return all(ch in _PUNCT_GLUE for ch in s)


def _dedup_images_in_row(row_tokens: list[dict]) -> list[dict]:
    """같은 행 안에서 동일 src 이미지가 여러 번 잡히면 (thumb+full 등) 한 번만 남김."""
    seen: set[str] = set()
    out: list[dict] = []
    for tok in row_tokens:
        if tok.get("t") == "i":
            src = (tok.get("src") or "").strip()
            if src and src in seen:
                continue
            if src:
                seen.add(src)
        out.append(tok)
    return out


def _merge_inline(row_tokens: list[dict]) -> list[dict]:
    """같은 행 안에서 가까이 있는 텍스트 토큰들을 한 토큰으로 합친다.

    - 링크(href) / 각주(fn) 가 다르면 분리 유지
    - 단, 토큰 내용이 부호류 ( , . ; : 등) 만 있으면 href 가 달라도 앞에 붙임
      (단어 사이 punctuation 이 별도 셀에 떨어지는 것 방지)
    """
    merged: list[dict] = []
    for tok in sorted(row_tokens, key=lambda t: int(t.get("x", 0))):
        if not _is_text(tok) or not merged or not _is_text(merged[-1]):
            merged.append(dict(tok))
            continue
        prev = merged[-1]
        punct = _is_punct_only(tok.get("v", ""))
        same_link = (prev.get("href") == tok.get("href")
                     and prev.get("fn") == tok.get("fn"))
        if not punct and not same_link:
            merged.append(dict(tok))
            continue
        prev_right = int(prev.get("x", 0)) + int(prev.get("w", 0))
        gap = int(tok.get("x", 0)) - prev_right
        if gap < JOIN_GAP_PX:
            sep = "" if punct else " "
            prev["v"] = (prev.get("v") or "") + sep + (tok.get("v") or "")
            prev["w"] = int(prev.get("w", 0)) + max(0, gap) + int(tok.get("w", 0))
        else:
            merged.append(dict(tok))
    return merged


def format_positioned(
    title: str,
    tokens: list[dict],
    page_w: int = 1280,
    page_h: int = 0,
    max_cols: int | None = None,
) -> list[list[tuple]]:
    if not tokens:
        return []

    # 좌상단을 (0, 0) 기준으로 맞춤 (페이지가 (0,0) 부터 시작 안 할 수도)
    xs = [int(t.get("x", 0)) for t in tokens]
    ys = [int(t.get("y", 0)) for t in tokens]
    min_x = max(0, min(xs))
    min_y = max(0, min(ys))

    # row 그룹
    by_row: dict[int, list[dict]] = {}
    for tok in tokens:
        y = int(tok.get("y", 0)) - min_y
        if y < 0:
            continue
        r = y // ROW_HEIGHT
        if r >= MAX_ROWS:
            continue
        adj = dict(tok)
        adj["x"] = int(tok.get("x", 0)) - min_x
        adj["y"] = y
        by_row.setdefault(r, []).append(adj)

    rows_out: list[list[tuple]] = []
    max_r = max(by_row.keys()) if by_row else 0

    # 셀 1칸 = (text, bold, image_url|None, link_url|None, footnote|None)
    def commit_row(cells: list[tuple]) -> None:
        if not cells:
            cells = [("", False, None, None, None)]
        rows_out.append(cells)

    # 연속 빈 row 는 1개로 압축 (문단 간격 과도하게 벌어지지 않게)
    empty_streak = 0
    for r in range(max_r + 1):
        group = by_row.get(r, [])
        if not group:
            empty_streak += 1
            if empty_streak <= 1:
                rows_out.append([("", False, None, None, None)])
            continue
        empty_streak = 0
        group = _dedup_images_in_row(group)
        merged = _merge_inline(group)
        row_cells: list[tuple] = []
        col = 0

        def append_cell(
            text: str,
            img: str | None,
            link: str | None,
            fn: str | None,
        ) -> None:
            nonlocal row_cells, col
            limit = max_cols if (max_cols and max_cols > 0) else MAX_COLS_VISIBLE
            if col >= limit:
                commit_row(row_cells)
                row_cells = []
                col = 0
            row_cells.append((text, False, img, link, fn))
            col += 1

        for tok in merged:
            href = (tok.get("href") or "").strip() or None
            fn = (tok.get("fn") or "").strip() or None
            if _is_text(tok):
                text = (tok.get("v") or "").strip()
                if not text:
                    continue
                chunks = _split_text_to_cells(text, CELL_WIDTH_UNITS)
                for ch in chunks:
                    append_cell(ch, None, href, fn)
            else:  # image
                src = (tok.get("src") or "").strip()
                alt = (tok.get("alt") or "").strip()
                text = "[사진보기]" + (f" — {alt}" if alt else "")
                append_cell(text, src, href, fn)

        commit_row(row_cells)

    if title:
        rows_out = [
            [(title, True, None, None, None)],
            [("", False, None, None, None)],
        ] + rows_out

    return rows_out


# legacy text-only fallback
def format_for_cells(title: str, body: str, **_kw) -> list[list[tuple]]:
    rows: list[list[tuple]] = []
    if title:
        rows.append([(title, True, None, None, None)])
        rows.append([("", False, None, None, None)])
    for line in body.split("\n"):
        line = line.rstrip()
        if not line.strip():
            rows.append([("", False, None, None, None)])
            continue
        rows.append([(line, False, None, None, None)])
    return rows
