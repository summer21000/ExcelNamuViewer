"""실행 비밀번호 창 — 엑셀이 보호된 통합 문서를 열 때 띄우는 "암호" 창 모양 (위장 유지)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from excelview import favorites, securestore


class _PasswordDialog(QDialog):
    def __init__(self, setup: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup = setup
        self.setWindowTitle("암호")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setFixedWidth(320)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(6)

        if setup:
            msg = "통합 문서를 보호할 암호를 지정하세요."
        else:
            msg = "'Book1'은(는) 보호되어 있습니다."
        lay.addWidget(QLabel(msg, self))

        lay.addWidget(QLabel("암호(P):", self))
        self._pw = QLineEdit(self)
        self._pw.setEchoMode(QLineEdit.Password)
        lay.addWidget(self._pw)

        self._pw2: QLineEdit | None = None
        if setup:
            lay.addWidget(QLabel("암호 확인(R):", self))
            self._pw2 = QLineEdit(self)
            self._pw2.setEchoMode(QLineEdit.Password)
            lay.addWidget(self._pw2)

        self._err = QLabel("", self)
        self._err.setStyleSheet("color: #c00000;")
        self._err.hide()
        lay.addWidget(self._err)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        btns.button(QDialogButtonBox.Ok).setText("확인")
        btns.button(QDialogButtonBox.Cancel).setText("취소")
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._pw.setFocus()

    def _fail(self, text: str) -> None:
        self._err.setText(text)
        self._err.show()
        self._pw.selectAll()
        self._pw.setFocus()

    def _on_ok(self) -> None:
        pw = self._pw.text()
        if self._setup:
            if not pw:
                self._fail("암호를 입력하세요.")
                return
            if self._pw2 is not None and pw != self._pw2.text():
                self._pw2.clear()
                self._fail("암호 확인이 일치하지 않습니다.")
                return
            if not securestore.set_password(pw):
                self._fail("암호를 저장하지 못했습니다.")
                return
        elif not securestore.check_password(pw):
            self._fail("암호가 잘못되었습니다.")
            return
        self.accept()


def ask_password() -> bool:
    """실행 시 비밀번호 확인 (확인 용도만 — 즐겨찾기 암호화와는 별개). 처음이면 설정. 취소하면 False."""
    dlg = _PasswordDialog(setup=not securestore.has_password())
    if dlg.exec() != QDialog.Accepted:
        return False
    favorites.migrate_legacy()   # 예전 평문 즐겨찾기 → 암호화 파일
    return True
