from __future__ import annotations

import os
import sys
from pathlib import Path


# PySide6 DLL 경로를 우선 등록 — 시스템 PATH 의 다른 Qt 와 충돌 회피
def _register_pyside_dll_dir() -> None:
    if not hasattr(os, "add_dll_directory"):
        return
    try:
        import PySide6  # noqa: F401
        pyside_dir = Path(PySide6.__file__).parent
        os.add_dll_directory(str(pyside_dir))
    except Exception:
        pass


_register_pyside_dll_dir()


from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from excelview.mainwindow import MainWindow  # noqa: E402


def _resource_dir() -> Path:
    # PyInstaller 으로 묶이면 sys._MEIPASS 에 unpack 됨
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).parent


def _load_stylesheet(app: QApplication) -> None:
    qss_path = _resource_dir() / "resources" / "excel.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main() -> int:
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QCoreApplication.setOrganizationName("ExcelView")
    QCoreApplication.setApplicationName("ExcelView")

    app = QApplication(sys.argv)
    app.setFont(QFont("Malgun Gothic", 9))
    _load_stylesheet(app)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
