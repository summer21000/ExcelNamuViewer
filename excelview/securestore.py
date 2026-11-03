"""실행 비밀번호 확인 + 로컬 파일(즐겨찾기) 암호화 — 서로 별개.

- 비밀번호: 실행할 때 확인하는 용도만. 원문은 저장하지 않고 PBKDF2 해시만 저장.
- 파일 암호화: 비밀번호와 무관하게 프로그램에 든 키로 암호화 — 다른 방법(메모장 등)으로
  열면 내용을 알아볼 수 없다. Windows 계정에 묶이지 않아 폴더째 다른 PC 로 옮겨도 읽힌다.
  (SHA-256 기반 스트림 암호 + HMAC 위변조 확인, 표준 라이브러리만 사용)

파일 (ExcelViewAPPDATA):
  auth.json — {"salt": base64, "hash": base64}
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from excelview.decoystore import _config_dir

_ITER = 200_000
_MAGIC = b"XVF1"
# 프로그램에 든 파일 암호화 키 (암호화용 / 위변조 확인용)
_FILE_KEY = hashlib.sha256(b"ExcelView/local-file/enc/7f3a9c1e5b2d4086").digest()
_MAC_KEY = hashlib.sha256(b"ExcelView/local-file/mac/c2e8a4170f9b6d35").digest()


# ------------------------------------------------------------------ 실행 비밀번호
def _auth_file():
    return _config_dir() / "auth.json"


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)


def has_password() -> bool:
    try:
        d = json.loads(_auth_file().read_text(encoding="utf-8"))
        return bool(d.get("salt") and d.get("hash"))
    except Exception:
        return False


def set_password(password: str) -> bool:
    """처음 비밀번호 설정."""
    salt = os.urandom(16)
    try:
        _auth_file().write_text(json.dumps({
            "salt": base64.b64encode(salt).decode(),
            "hash": base64.b64encode(_derive(password, salt)).decode(),
        }), encoding="utf-8")
        return True
    except Exception:
        return False


def check_password(password: str) -> bool:
    try:
        d = json.loads(_auth_file().read_text(encoding="utf-8"))
        salt = base64.b64decode(d["salt"])
        want = base64.b64decode(d["hash"])
    except Exception:
        return False
    return hmac.compare_digest(_derive(password, salt), want)


# ------------------------------------------------------------------ 파일 암호화
def _keystream(nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(_FILE_KEY + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:n])


def encrypt(data: bytes) -> bytes:
    nonce = os.urandom(16)
    body = bytes(a ^ b for a, b in zip(data, _keystream(nonce, len(data))))
    tag = hmac.new(_MAC_KEY, _MAGIC + nonce + body, hashlib.sha256).digest()
    return _MAGIC + nonce + tag + body


def decrypt(blob: bytes) -> bytes | None:
    """복호화. 형식이 다르거나 위변조됐으면 None."""
    if len(blob) < 4 + 16 + 32 or blob[:4] != _MAGIC:
        return None
    nonce, tag, body = blob[4:20], blob[20:52], blob[52:]
    want = hmac.new(_MAC_KEY, _MAGIC + nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, want):
        return None
    return bytes(a ^ b for a, b in zip(body, _keystream(nonce, len(body))))
