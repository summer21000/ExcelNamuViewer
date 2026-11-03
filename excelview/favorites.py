"""즐겨찾기 — (제목, 주소) 목록을 ExcelViewAPPDATA/favorites.dat 에 암호화해 저장.

주소는 실제로 열린 주소 그대로 — 나무위키 문서, 문단(#s-N), 직접 입력한 외부 사이트 모두.
암호화는 securestore — 다른 방법으로 열면 알아볼 수 없음 (실행 비밀번호와는 별개).
"""
from __future__ import annotations

import json

from excelview import securestore
from excelview.decoystore import _config_dir


def _file():
    return _config_dir() / "favorites.dat"


def _legacy_file():
    # 예전 평문 저장 파일 — migrate_legacy() 가 암호화 파일로 옮기고 지움
    return _config_dir() / "favorites.json"


def _key(url: str) -> str:
    return (url or "").strip()


def _parse(data) -> list[dict]:
    out = []
    for it in data if isinstance(data, list) else []:
        if isinstance(it, dict) and it.get("url"):
            out.append({"title": str(it.get("title") or it["url"]), "url": str(it["url"])})
    return out


def load() -> list[dict]:
    try:
        raw = securestore.decrypt(_file().read_bytes())
        if raw is None:
            return []
        return _parse(json.loads(raw.decode("utf-8")))
    except Exception:
        return []


def _save(items: list[dict]) -> bool:
    try:
        data = json.dumps(items, ensure_ascii=False).encode("utf-8")
        _file().write_bytes(securestore.encrypt(data))
        return True
    except Exception:
        return False


def migrate_legacy() -> None:
    """평문 favorites.json 이 남아 있으면 암호화 파일에 합치고 지운다."""
    p = _legacy_file()
    if not p.exists():
        return
    try:
        old = _parse(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        old = []
    items = load()
    have = {_key(it["url"]) for it in items}
    items += [it for it in old if _key(it["url"]) not in have]
    if _save(items):
        try:
            p.unlink()
        except Exception:
            pass


def contains(url: str) -> bool:
    k = _key(url)
    return any(_key(it["url"]) == k for it in load())


def add(title: str, url: str) -> bool:
    """추가 (이미 있으면 제목만 갱신). 저장 성공 여부."""
    if not url:
        return False
    items = load()
    k = _key(url)
    for it in items:
        if _key(it["url"]) == k:
            it["title"] = title or it["title"]
            return _save(items)
    items.append({"title": title or url, "url": url})
    return _save(items)


def remove(url: str) -> bool:
    k = _key(url)
    return _save([it for it in load() if _key(it["url"]) != k])
