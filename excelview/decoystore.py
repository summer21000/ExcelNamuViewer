from __future__ import annotations

import json
import sys
from pathlib import Path


def _config_dir() -> Path:
    """프로그램과 같은 경로의 ExcelViewAPPDATA 폴더."""
    if getattr(sys, "frozen", False):
        # PyInstaller .exe — 실행 파일이 있는 폴더
        base = Path(sys.executable).resolve().parent
    else:
        # 개발 모드 — main.py 가 있는 프로젝트 루트
        base = Path(__file__).resolve().parent.parent
    p = base / "ExcelViewAPPDATA"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _decoy_file() -> Path:
    return _config_dir() / "decoy_sheet1.json"


def save(matrix: list[list[tuple]]) -> tuple[bool, str]:
    """매트릭스를 JSON 으로 저장. (성공 여부, 경로 또는 에러 메시지) 반환."""
    try:
        data = [[[t[0], bool(t[1]) if len(t) > 1 else False] for t in row] for row in matrix]
        path = _decoy_file()
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True, str(path)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def load() -> list[list[tuple]] | None:
    """저장된 매트릭스가 있으면 반환. 없으면 None."""
    path = _decoy_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    rows: list[list[tuple]] = []
    for r in data:
        rr: list[tuple] = []
        for c in r:
            text = c[0] if len(c) > 0 else ""
            bold = bool(c[1]) if len(c) > 1 else False
            rr.append((text, bold, None, None, None))
        rows.append(rr)
    return rows
