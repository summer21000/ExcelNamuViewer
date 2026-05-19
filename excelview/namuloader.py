from __future__ import annotations

import json
from urllib.parse import quote, unquote

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


# 각 텍스트/이미지 노드의 화면 좌표를 같이 수집한다.
# 그래야 페이지의 시각적 구조 (좌측 사이드바/본문/우측 등) 를 셀 그리드로 매핑할 수 있다.
_EXTRACT_JS = r"""
JSON.stringify((function() {
  var SKIP = {
    SCRIPT:1, STYLE:1, NOSCRIPT:1,
    SVG:1, svg:1, PATH:1, path:1,
    IFRAME:1, LINK:1, META:1,
    INS:1   // AdSense 등 광고 ins 태그
  };

  function isHidden(el) {
    try {
      var s = window.getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden') return true;
    } catch (e) {}
    return false;
  }

  // id / class 에 광고성 키워드가 들어간 컨테이너 검출.
  // 단어 경계(\b)로 false positive (address, headline 등) 회피.
  var AD_RE = /(^|[\s_-])(ad|ads|adv|advert|adunit|adsense|adsbygoogle|sponsor|sponsored|promo|partnerpixel)([\s_-]|$)/i;
  function isAd(el) {
    var id = el.id || '';
    var cls = el.className;
    if (typeof cls !== 'string') cls = (cls && cls.baseVal) || '';
    if (AD_RE.test(id)) return true;
    if (AD_RE.test(cls)) return true;
    if (id.indexOf('google_ads') >= 0) return true;
    if (cls.indexOf('google_ads') >= 0) return true;
    return false;
  }

  var tokens = [];
  var range = document.createRange();

  // 각주 anchor: href 가 in-page #anchor 이면 그 target 또는 부모 컨테이너의 텍스트 추출.
  // namu.wiki 는 <span id="fn-N"></span> 빈 anchor + 부모 span 에 각주 본문 텍스트.
  // rfn-N / fn-N 도 비슷한 패턴 → 부모 1~3 단계 올라가며 짧은 본문 찾기.
  function resolveFootnote(href) {
    if (!href) return null;
    var hashIdx = href.indexOf('#');
    if (hashIdx < 0) return null;
    var id;
    try { id = decodeURIComponent(href.substring(hashIdx + 1)); }
    catch (e) { id = href.substring(hashIdx + 1); }
    if (!id) return null;
    var target = document.getElementById(id);
    if (!target) return null;
    var txt = (target.innerText || '').replace(/\s+/g, ' ').trim();
    if (txt.length >= 3) return txt.substring(0, 600);
    var cur = target.parentElement;
    for (var i = 0; i < 4 && cur; i++) {
      var t = (cur.innerText || '').replace(/\s+/g, ' ').trim();
      // 너무 큰 컨테이너(섹션 전체) 는 각주 본문이 아님
      if (t.length >= 3 && t.length <= 2000) {
        return t.substring(0, 600);
      }
      cur = cur.parentElement;
    }
    return null;
  }

  function pushText(node, href, fn) {
    var t = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
    if (!t) return;
    try { range.selectNodeContents(node); }
    catch (e) { return; }
    var rects = range.getClientRects();
    if (!rects || rects.length === 0) return;
    var r = rects[0];
    if (!r || (r.width === 0 && r.height === 0)) return;
    var tok = {
      t: 'x', v: t,
      x: Math.round(r.left + window.scrollX),
      y: Math.round(r.top + window.scrollY),
      w: Math.round(r.width),
      h: Math.round(r.height)
    };
    if (fn) tok.fn = fn;
    else if (href) tok.href = href;
    tokens.push(tok);
  }

  // lazy-load 대응 — placeholder 가 아닌 진짜 이미지 URL 찾기.
  // 절대 URL 로 정규화 (protocol-relative, 상대 경로 모두 처리).
  function absolutize(url) {
    if (!url) return '';
    url = url.trim();
    if (!url) return '';
    if (url.startsWith('data:')) return '';
    if (url.startsWith('//')) return location.protocol + url;
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    try {
      return new URL(url, location.href).href;
    } catch (e) {
      return url;
    }
  }

  function realImgSrc(img) {
    try {
      // img.currentSrc 가 가장 신뢰성 높음 (브라우저가 srcset 평가 후 선택한 URL)
      if (img.currentSrc && !img.currentSrc.startsWith('data:')) {
        return absolutize(img.currentSrc);
      }
      var sets = img.srcset || img.getAttribute('srcset') || '';
      if (sets) {
        var parts = sets.split(',');
        for (var i = parts.length - 1; i >= 0; i--) {
          var url = parts[i].trim().split(/\s+/)[0];
          var abs = absolutize(url);
          if (abs) return abs;
        }
      }
      var attrs = ['data-src', 'data-original', 'data-lazy-src', 'data-srcset'];
      for (var k = 0; k < attrs.length; k++) {
        var v = img.getAttribute(attrs[k]);
        if (v) {
          var first = v.split(',')[0].trim().split(/\s+/)[0];
          var abs2 = absolutize(first);
          if (abs2) return abs2;
        }
      }
      return absolutize(img.src || '');
    } catch (e) {
      return absolutize(img.src || '');
    }
  }

  function pushImage(el, href, fn) {
    var r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    var tok = {
      t: 'i',
      src: realImgSrc(el),
      alt: el.alt || '',
      x: Math.round(r.left + window.scrollX),
      y: Math.round(r.top + window.scrollY),
      w: Math.round(r.width),
      h: Math.round(r.height)
    };
    if (fn) tok.fn = fn;
    else if (href) tok.href = href;
    tokens.push(tok);
  }

  function walk(el, parentHref, parentFn) {
    if (!el) return;
    if (el.nodeType === 1 && (SKIP[el.nodeName] || isHidden(el) || isAd(el))) return;
    var ch = el.childNodes;
    for (var i = 0; i < ch.length; i++) {
      var c = ch[i];
      if (c.nodeType === 3) {
        pushText(c, parentHref, parentFn);
      } else if (c.nodeType === 1) {
        if (c.nodeName === 'IMG') {
          pushImage(c, parentHref, parentFn);
        } else if (c.nodeName === 'A') {
          var h = c.getAttribute('href') || '';
          try { if (h && c.href) h = c.href; } catch (e) {}
          var fn = resolveFootnote(h);
          walk(c, fn ? null : (h || parentHref), fn || parentFn);
        } else {
          walk(c, parentHref, parentFn);
        }
      }
    }
  }

  // lazy-load 트리거
  try {
    window.scrollTo(0, document.body ? document.body.scrollHeight : 0);
    window.scrollTo(0, 0);
  } catch (e) {}

  try {
    var root = document.body;
    if (!root) {
      return { ok: false, sel: 'no-body',
               title: document.title, url: location.href,
               readyState: document.readyState };
    }
    walk(root);
    return {
      ok: true,
      sel: 'positioned',
      tokens: tokens,
      pageW: document.documentElement.scrollWidth,
      pageH: document.documentElement.scrollHeight,
      title: document.title,
      url: location.href
    };
  } catch (e) {
    return { ok: false, sel: 'error', error: String(e) };
  }
})());
"""


class NamuLoader(QObject):
    """Hidden QWebEnginePage that loads namu.wiki and extracts positioned tokens."""

    loadStarted = Signal(str)
    loadProgress = Signal(int)
    # title, tokens (list[dict] — 각 토큰은 x/y/w/h 포함), source_url, page_w, page_h
    bodyExtracted = Signal(str, list, str, int, int)
    fetchFailed = Signal(str, str)
    diagnostics = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        profile = QWebEngineProfile("ExcelViewNamu", self)
        profile.setHttpUserAgent(_UA_CHROME)
        s = profile.settings()
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        s.setAttribute(QWebEngineSettings.AutoLoadImages, True)  # 이미지 보여야 layout이 정확
        s.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)

        self._page = QWebEnginePage(profile, self)
        self._page.loadStarted.connect(lambda: self.loadProgress.emit(0))
        self._page.loadProgress.connect(self.loadProgress.emit)
        self._page.loadFinished.connect(self._on_loaded)

        # hidden view 로 viewport 확보 — layout 계산 (getBoundingClientRect) 이 동작하려면
        # page 가 실제 렌더 사이즈를 가져야 한다. WA_DontShowOnScreen 으로 화면엔 안 뜸.
        self._hidden_view = QWebEngineView()
        self._hidden_view.setPage(self._page)
        self._hidden_view.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._hidden_view.resize(1280, 900)
        self._hidden_view.show()

        self._current_title = ""
        self._current_url = ""
        self._extract_attempts = 0
        self._max_attempts = 4
        self._extract_delay_ms = 5000

        self._debug_view: QWebEngineView | None = None

    def cleanup(self) -> None:
        """앱 종료 시 명시적으로 호출 — QtWebEngine helper 프로세스가 좀비로 남지 않게.

        QWebEngineView/Page 가 GC 에 맡겨지면 Qt event loop 종료 후 정리되어
        WebEngine helper 가 떨어져나가는 일이 있다. closeEvent 에서 명시 정리.
        """
        try:
            if self._debug_view is not None:
                self._debug_view.setPage(None)
                self._debug_view.close()
                self._debug_view.deleteLater()
                self._debug_view = None
        except Exception:
            pass
        try:
            if self._hidden_view is not None:
                self._hidden_view.setPage(None)
                self._hidden_view.close()
                self._hidden_view.deleteLater()
                self._hidden_view = None
        except Exception:
            pass
        try:
            if self._page is not None:
                self._page.setUrl(QUrl("about:blank"))
                self._page.deleteLater()
                self._page = None
        except Exception:
            pass

    def showDebugView(self) -> None:
        if self._debug_view is None:
            self._debug_view = QWebEngineView()
            self._debug_view.setPage(self._page)
            self._debug_view.setWindowTitle("[디버그] namu.wiki 직접 보기")
            self._debug_view.resize(1280, 900)
        self._debug_view.show()
        self._debug_view.raise_()
        self._debug_view.activateWindow()

    @staticmethod
    def _title_from_path(s: str) -> str:
        """URL/경로에서 문서 제목만 추출 — fragment/query 제거 + %xx 디코드."""
        t = s
        if "#" in t:
            t = t.split("#", 1)[0]
        if "?" in t:
            t = t.split("?", 1)[0]
        t = t.rsplit("/", 1)[-1] or t
        try:
            t = unquote(t)
        except Exception:
            pass
        return t

    def fetch(self, title_or_url: str) -> None:
        s = title_or_url.strip()
        if s.lower().startswith(("file:", "http://", "https://")):
            qurl = QUrl(s)
            self._current_title = self._title_from_path(s)
            self._current_url = s
        elif s.startswith("/"):
            # namu.wiki 상대 경로 — 절대 URL 로 보정
            self._current_url = "https://namu.wiki" + s
            qurl = QUrl(self._current_url)
            self._current_title = self._title_from_path(s)
        else:
            try:
                from pathlib import Path as _P
                p = _P(s)
                if p.exists() and p.is_file():
                    qurl = QUrl.fromLocalFile(str(p.resolve()))
                    self._current_title = p.name
                    self._current_url = qurl.toString()
                else:
                    raise FileNotFoundError
            except Exception:
                self._current_title = s
                self._current_url = f"https://namu.wiki/w/{quote(s, safe='')}"
                qurl = QUrl(self._current_url)

        self._extract_attempts = 0
        self.loadStarted.emit(self._current_title)
        self._page.load(qurl)

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            self.fetchFailed.emit(self._current_title, "페이지 로드 실패")
            return
        QTimer.singleShot(self._extract_delay_ms, self._run_extract)

    def _run_extract(self) -> None:
        self._extract_attempts += 1
        self._page.runJavaScript(_EXTRACT_JS, self._on_extracted)

    def _on_extracted(self, result) -> None:
        info: dict = {}
        if isinstance(result, str) and result:
            try:
                info = json.loads(result)
            except Exception as e:
                info = {"ok": False, "sel": "json-parse-error",
                        "error": f"JSON.parse 실패: {e}", "raw_head": result[:300]}
        elif isinstance(result, dict):
            info = result
        else:
            info = {"ok": False, "sel": "no-result",
                    "error": f"runJavaScript 결과가 빈 값 (type={type(result).__name__})"}

        ok = bool(info.get("ok"))
        tokens = info.get("tokens") or []

        if ok and tokens:
            page_w = int(info.get("pageW") or 1280)
            page_h = int(info.get("pageH") or 800)
            self.bodyExtracted.emit(
                self._current_title, tokens, self._current_url, page_w, page_h
            )
            return

        if self._extract_attempts < self._max_attempts:
            QTimer.singleShot(1500, self._run_extract)
            return

        self.diagnostics.emit(info)
        self.fetchFailed.emit(self._current_title, "본문을 찾지 못했습니다 (selector 미스)")
