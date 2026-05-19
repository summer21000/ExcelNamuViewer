from __future__ import annotations

"""급하게 일하는 척 할 때 보여줄 위장 시트."""

# 셀 1칸 = (text, bold, image_url|None, link_url|None, footnote|None)


def _row(values: list[str], bold: bool = False) -> list[tuple]:
    return [(v, bold, None, None, None) for v in values]


def _blank_row(n: int) -> list[tuple]:
    return [("", False, None, None, None)] * n


def decoy_sheet2() -> list[list[tuple]]:
    """주간 업무 진행 현황 — 헤더만 있는 빈 표."""
    headers = ["일자", "구분", "담당", "진행상태", "검토자", "마감", "확인", "비고"]
    rows: list[list[tuple]] = [_row(headers, bold=True)]
    # 빈 행 다수
    for _ in range(40):
        rows.append(_blank_row(len(headers)))
    return rows


def decoy_sheet3() -> list[list[tuple]]:
    """월별 자재 입출고 내역 — 빈 양식."""
    headers = ["품번", "품명", "규격", "단위", "입고수량", "출고수량", "재고", "단가", "금액"]
    rows: list[list[tuple]] = [_row(headers, bold=True)]
    for _ in range(40):
        rows.append(_blank_row(len(headers)))
    return rows
