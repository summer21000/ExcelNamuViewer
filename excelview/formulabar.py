from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QWidget,
)


class FormulaBar(QWidget):
    formulaCommitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FormulaBar")
        self.setFixedHeight(26)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._name_box = QLineEdit(self)
        self._name_box.setObjectName("NameBox")
        self._name_box.setFixedWidth(90)
        self._name_box.setText("A1")
        self._name_box.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._name_box)

        sep1 = QFrame(self)
        sep1.setObjectName("FbSep")
        sep1.setFrameShape(QFrame.VLine)
        sep1.setFixedWidth(1)
        lay.addWidget(sep1)

        self._btn_x = QToolButton(self)
        self._btn_x.setObjectName("FbCancel")
        self._btn_x.setText("✕")
        self._btn_x.setFixedSize(22, 22)
        self._btn_x.setEnabled(False)
        lay.addWidget(self._btn_x)

        self._btn_ok = QToolButton(self)
        self._btn_ok.setObjectName("FbCommit")
        self._btn_ok.setText("✓")
        self._btn_ok.setFixedSize(22, 22)
        self._btn_ok.setEnabled(False)
        lay.addWidget(self._btn_ok)

        self._btn_fx = QToolButton(self)
        self._btn_fx.setObjectName("FbFx")
        self._btn_fx.setText("ƒx")
        self._btn_fx.setFixedSize(28, 22)
        lay.addWidget(self._btn_fx)

        sep2 = QFrame(self)
        sep2.setObjectName("FbSep")
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFixedWidth(1)
        lay.addWidget(sep2)

        self._formula = QLineEdit(self)
        self._formula.setObjectName("FormulaEdit")
        lay.addWidget(self._formula, 1)

        self._formula.returnPressed.connect(self._commit)
        self._btn_ok.clicked.connect(self._commit)
        self._btn_x.clicked.connect(self._cancel)
        self._formula.textEdited.connect(self._on_text_edited)

    def setCellAddress(self, addr: str) -> None:
        self._name_box.setText(addr)

    def setFormulaText(self, text: str) -> None:
        self._formula.blockSignals(True)
        self._formula.setText(text)
        self._formula.blockSignals(False)
        self._btn_ok.setEnabled(False)
        self._btn_x.setEnabled(False)

    def formulaText(self) -> str:
        return self._formula.text()

    def _on_text_edited(self, text: str) -> None:
        enabled = bool(text)
        self._btn_ok.setEnabled(enabled)
        self._btn_x.setEnabled(enabled)

    def _commit(self) -> None:
        self.formulaCommitted.emit(self._formula.text())
        self._btn_ok.setEnabled(False)
        self._btn_x.setEnabled(False)

    def _cancel(self) -> None:
        self._formula.clear()
        self._btn_ok.setEnabled(False)
        self._btn_x.setEnabled(False)
