"""시스템의 한/영 입력 상태를 이 프로그램에 그대로 반영 (Windows 전용, 다른 OS 는 아무것도 안 함).

Windows 한글 IME 는 창마다 한/영 상태를 따로 갖기 때문에, 다른 프로그램에서 한글로 쓰다가
이 프로그램으로 와도 영문으로 시작한다. 그래서
- 이 프로그램이 비활성일 때: 앞에 떠 있는 다른 창의 한/영 상태를 주기적으로 읽어 두고
- 이 프로그램이 활성화될 때: 그 상태를 우리 창에 적용한다 (한글 고정이 아니라 따라가기).
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _imm = ctypes.windll.imm32

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    _user32.SendMessageTimeoutW.restype = ctypes.c_size_t
    _imm.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
    _imm.ImmGetDefaultIMEWnd.restype = wintypes.HWND
    _imm.ImmGetContext.argtypes = [wintypes.HWND]
    _imm.ImmGetContext.restype = wintypes.HANDLE
    _imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    _imm.ImmGetConversionStatus.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    _imm.ImmSetConversionStatus.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]

_WM_IME_CONTROL = 0x0283
_IMC_GETCONVERSIONMODE = 0x0001
_IME_CMODE_HANGUL = 0x0001          # = IME_CMODE_NATIVE
_SMTO_ABORTIFHUNG = 0x0002


def _foreign_foreground_hangul() -> bool | None:
    """앞에 떠 있는 다른 프로그램 창이 한글 모드인지. 알 수 없거나 우리 창이면 None."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None
    ime_wnd = _imm.ImmGetDefaultIMEWnd(hwnd)
    if not ime_wnd:
        return None
    out = ctypes.c_size_t(0)
    ok = _user32.SendMessageTimeoutW(ime_wnd, _WM_IME_CONTROL, _IMC_GETCONVERSIONMODE, 0,
                                     _SMTO_ABORTIFHUNG, 200, ctypes.byref(out))
    if not ok:
        return None
    return bool(out.value & _IME_CMODE_HANGUL)


def _apply_hangul(widget: QWidget, hangul: bool) -> None:
    hwnd = int(widget.window().winId())
    himc = _imm.ImmGetContext(hwnd)
    if not himc:
        return
    try:
        conv, sent = wintypes.DWORD(0), wintypes.DWORD(0)
        if not _imm.ImmGetConversionStatus(himc, ctypes.byref(conv), ctypes.byref(sent)):
            return
        new = (conv.value | _IME_CMODE_HANGUL) if hangul else (conv.value & ~_IME_CMODE_HANGUL)
        if new != conv.value:
            _imm.ImmSetConversionStatus(himc, new, sent.value)
    finally:
        _imm.ImmReleaseContext(hwnd, himc)


class ImeStateSync(QObject):
    """window 의 한/영 상태를 시스템(직전에 쓰던 다른 프로그램)의 상태에 맞춘다."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._hangul: bool | None = None
        if not _WIN:
            return
        # 시작 시 — 아직 우리 창이 뜨기 전, 실행한 쪽(탐색기 등)의 상태
        self._sample()
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._sample)
        app = QApplication.instance()
        app.applicationStateChanged.connect(self._on_app_state)
        if app.applicationState() != Qt.ApplicationActive:
            self._timer.start()
        QTimer.singleShot(0, self._apply)

    def _sample(self) -> None:
        try:
            v = _foreign_foreground_hangul()
        except Exception:
            v = None
        if v is not None:
            self._hangul = v

    def _on_app_state(self, state) -> None:
        if state == Qt.ApplicationActive:
            self._timer.stop()
            # Qt 가 활성화 처리 중에 IME 컨텍스트를 다시 연결하므로 그 뒤에 적용
            QTimer.singleShot(0, self._apply)
        else:
            self._timer.start()

    def _apply(self) -> None:
        if self._hangul is None:
            return
        try:
            _apply_hangul(self._window, self._hangul)
        except Exception:
            pass
