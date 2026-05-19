from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


class ImageDialog(QDialog):
    """이미지 셀 더블클릭 시 뜨는 미리보기 다이얼로그."""

    DIALOG_W = 520
    DIALOG_H = 400

    def __init__(self, url: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"사진 — {label}")
        # 사용자 요청 — 창 크기는 고정 (작게). 사진은 이 안에 맞춰 축소.
        self.setFixedSize(self.DIALOG_W, self.DIALOG_H)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._lbl = QLabel("로딩 중…", self)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet("background: #2b2b2b; color: #e6e6e6; font-size: 14px;")
        lay.addWidget(self._lbl, 1)

        bar = QWidget(self)
        bar.setStyleSheet("background: #1f1f1f;")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 6, 8, 6)
        self._url_lbl = QLabel(url, bar)
        self._url_lbl.setStyleSheet("color: #b9b9b9; font-size: 10px;")
        self._url_lbl.setMaximumWidth(560)
        self._url_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self._url_lbl, 1)
        btn = QPushButton("닫기", bar)
        btn.setFixedWidth(80)
        btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; color:#ffffff; border:none; padding:4px 8px; }"
            "QPushButton:hover { background:#4a4a4a; }"
        )
        btn.clicked.connect(self.accept)
        bl.addWidget(btn)
        lay.addWidget(bar)

        self._url = url
        self._mgr = QNetworkAccessManager(self)
        self._mgr.finished.connect(self._on_finished)

        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", _UA.encode())
        req.setRawHeader(b"Referer", b"https://namu.wiki/")
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        self._mgr.get(req)

    def _on_finished(self, reply: QNetworkReply) -> None:
        try:
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            ctype = reply.header(QNetworkRequest.ContentTypeHeader) or "(no content-type)"
            err = reply.error()
            url = reply.url().toString()
            data: QByteArray = reply.readAll()
            size = data.size()

            if err != QNetworkReply.NoError:
                msg = (
                    "사진 로드 실패\n"
                    f"오류: {reply.errorString()}\n"
                    f"HTTP status: {status}\n"
                    f"URL: {url}\n"
                    f"받은 바이트: {size}, content-type: {ctype}"
                )
                self._lbl.setText(msg)
                self._lbl.setWordWrap(True)
                return

            pix = QPixmap()
            if not pix.loadFromData(bytes(data)):
                self._lbl.setText(
                    "이미지 디코딩 실패\n"
                    f"HTTP {status} · {size} bytes · {ctype}\n{url}"
                )
                self._lbl.setWordWrap(True)
                return
            self._pix = pix
            self._render()
        finally:
            reply.deleteLater()

    def _render(self) -> None:
        if not hasattr(self, "_pix") or self._pix.isNull():
            return
        lbl_w = max(1, self._lbl.width())
        lbl_h = max(1, self._lbl.height())
        scaled = self._pix.scaled(lbl_w, lbl_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl.setPixmap(scaled)

    def resizeEvent(self, e) -> None:  # 창이 고정이지만 첫 layout 후 재렌더 보장
        super().resizeEvent(e)
        self._render()
