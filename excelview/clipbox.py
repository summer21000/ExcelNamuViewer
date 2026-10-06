from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QWidget


class ClipBox(QScrollArea):
    """창을 좁혀도 막히지 않게 감싸는 상자.

    창이 안의 위젯 최소 폭보다 넓으면 위젯이 그대로 창 폭에 맞춰 배치되고 (감싸기 전과 동일),
    최소 폭보다 좁아졌을 때만 위젯은 최소 폭을 유지한 채 오른쪽이 가려진다 (스크롤바 없음).
    """

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ClipBox")
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 폭은 직접 정한다 — 자동 맞춤(widgetResizable)은 최소 폭이 아닌 기준을 쓰기도 해서
        # 하한보다 넓은 창에서도 잘리는 경우가 있다.
        self.setWidgetResizable(False)
        self.setWidget(content)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        # 높이는 안의 위젯 그대로
        h = content.maximumHeight() if content.maximumHeight() < 10000 else content.sizeHint().height()
        self.setFixedHeight(h)
        self._fit()

    def _fit(self) -> None:
        content = self.widget()
        if content is None:
            return
        min_w = content.minimumSizeHint().width()
        if content.minimumWidth() > 0:
            min_w = content.minimumWidth()
        w = max(self.viewport().width(), min_w)
        if content.width() != w or content.height() != self.height():
            content.resize(w, self.height())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit()
