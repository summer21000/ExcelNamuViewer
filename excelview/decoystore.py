from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def _config_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base:
        base = str(Path.home() / ".excelview")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _decoy_file() -> Path:
    return _config_dir() / "decoy_sheet1.json"


def save(matrix: list[list[tuple]]) -> None:
    """매트릭스를 JSON 으로 저장. tuple = (text, bold)."""
    data = [[[t[0], bool(t[1]) if len(t) > 1 else False] for t in row] for row in matrix]
    path = _decoy_file()
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


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
