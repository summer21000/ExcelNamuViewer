from __future__ import annotations

import json
from urllib.parse import parse_qs, quote, unquote, urlparse

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


# 본문 영역의 각 텍스트/이미지 조각의 화면 좌표 + 블록/서식(굵게 등) 정보를 수집한다.
# 텍스트는 "화면상의 한 줄" 단위로 쪼갠다 — 여러 줄로 감긴 문단도 줄마다 정확한 위치를 가짐.
# 그래야 본문의 구조 (줄 순서, 들여쓰기, 표의 열, 정보상자 위치) 를 셀 그리드로 옮길 수 있다.
_EXTRACT_JS = r"""
JSON.stringify((function() {
  var SKIP = {
    SCRIPT:1, STYLE:1, NOSCRIPT:1, TEMPLATE:1,
    SVG:1, svg:1, PATH:1, path:1,
    IFRAME:1, LINK:1, META:1,
    INPUT:1, TEXTAREA:1, SELECT:1,
    INS:1   // AdSense 등 광고 ins 태그
  };

  // id / class 에 광고성 키워드가 들어간 컨테이너 검출.
  // 단어 경계(\b)로 false positive (address, headline 등) 회피.
  var AD_RE = /(^|[\s_-])(ad|ads|gad|adv|advert|adunit|adsense|adsbygoogle|sponsor|sponsored|promo|partnerpixel)([\s_-]|$)/i;
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

  // 페이지를 시트와 같은 글꼴(맑은 고딕)로 다시 배치 — 브라우저가 계산한 줄바꿈 위치와
  // 글자 폭이 셀에 그릴 때와 같아져서, 셀 글자가 축소/잘림 없이 그대로 들어간다.
  try {
    if (!document.getElementById('__excelview_font')) {
      var fst = document.createElement('style');
      fst.id = '__excelview_font';
      fst.textContent = '*{font-family:"Malgun Gothic","맑은 고딕",sans-serif !important;}';
      (document.head || document.documentElement).appendChild(fst);
    }
  } catch (e) {}

  var sx = window.scrollX, sy = window.scrollY;
  var pageW = document.documentElement.scrollWidth;
  var pageH = document.documentElement.scrollHeight;

  // tokens: 문서(DOM) 순서 = 읽는 순서. 텍스트는 "화면상의 한 줄" 단위로 쪼개서 넣는다.
  // b(블록 번호): 블록 요소마다 새 번호 — 같은 블록 안의 조각만 서로 합칠 수 있다.
  // styles: 셀 서식으로 옮길 것만 (굵게/기울임/취소선). 글자 크기·색·배경은 옮기지 않는다
  //         — 엑셀처럼 보이는 것이 우선.
  var tokens = [], styles = [], styleIdx = {}, nBlocks = 0;
  // 같은 페이지 안에서 이동하는 링크(목차 숫자 ↔ 문단 제목 숫자 등)의 대상 id
  var jumpIds = {};
  var range = document.createRange();

  function num(v) { var n = parseFloat(v); return isNaN(n) ? 0 : n; }

  function styleOf(s, ctx) {
    var fw = parseInt(s.fontWeight, 10) || 400;
    var key = (fw >= 600 ? 1 : 0) + '|' + (s.fontStyle === 'italic' ? 1 : 0) + '|' + (ctx.strike ? 1 : 0);
    if (!(key in styleIdx)) {
      var a = key.split('|');
      styleIdx[key] = styles.length;
      styles.push({b: +a[0], i: +a[1], s: +a[2]});
    }
    return styleIdx[key];
  }

  // 본문 영역만 — 상단 메뉴바 / 우측 사이드바(최근 변경·인기 검색어·광고) 제외.
  // 문서 제목(h1)과 첫 문단 제목(#s-1)을 함께 품는 가장 가까운 요소가 본문 열이다.
  function contentRoot() {
    var body = document.body;
    var h1 = document.querySelector('h1');
    if (!h1) return body;
    var root = null;
    var sec = document.querySelector('[id^="s-"]');
    if (sec) {
      var seen = new Set();
      for (var a = h1; a; a = a.parentElement) seen.add(a);
      for (var b = sec; b; b = b.parentElement) { if (seen.has(b)) { root = b; break; } }
    }
    if (!root) {
      // 문단 제목이 없는 짧은 문서 — 사이드바와 나란히 놓인 열까지만 올라간다
      root = h1;
      while (root.parentElement && root.parentElement !== body &&
             root.parentElement.getBoundingClientRect().width <= pageW * 0.75) {
        root = root.parentElement;
      }
    }
    // 본문 글자가 너무 적게 잡히면 판별 실패로 보고 전체 페이지
    var bodyLen = (body.innerText || '').length;
    if (!root || root === body || (root.innerText || '').length < bodyLen * 0.3) return body;
    return root;
  }

  function inter(a, b) {
    if (!a) return b;
    return {l: Math.max(a.l, b.l), t: Math.max(a.t, b.t),
            r: Math.min(a.r, b.r), b: Math.min(a.b, b.b)};
  }
  // overflow:hidden 등으로 잘려 화면에 안 보이는 조각은 버린다.
  function visibleIn(clip, r) {
    if (!clip) return true;
    var cx = r.left + sx + r.width / 2, cy = r.top + sy + r.height / 2;
    return cx >= clip.l - 1 && cx <= clip.r + 1 && cy >= clip.t - 1 && cy <= clip.b + 1;
  }

  // 링크가 지금 페이지 안의 #id 를 가리키면 그 id, 아니면 null.
  function samePageId(a) {
    var raw = a.getAttribute('href') || '';
    var hash = null;
    if (raw.charAt(0) === '#') hash = raw.substring(1);
    else {
      try {
        var u = new URL(a.href);
        if (u.origin === location.origin && u.pathname === location.pathname &&
            u.search === location.search && u.hash.length > 1) hash = u.hash.substring(1);
      } catch (e) {}
    }
    if (!hash) return null;
    try { return decodeURIComponent(hash); } catch (e) { return hash; }
  }

  // 각주 anchor: 그 target 또는 부모 컨테이너의 텍스트 추출.
  // namu.wiki 는 <span id="fn-N"></span> 빈 anchor + 부모 span 에 각주 본문 텍스트.
  function resolveFootnote(id) {
    if (!id) return null;
    var target = document.getElementById(id);
    if (!target) return null;
    var txt = (target.innerText || '').replace(/\s+/g, ' ').trim();
    if (txt.length >= 3) return txt.substring(0, 600);
    var cur = target.parentElement;
    for (var i = 0; i < 4 && cur; i++) {
      var t = (cur.innerText || '').replace(/\s+/g, ' ').trim();
      if (t.length >= 3 && t.length <= 2000) return t.substring(0, 600);
      cur = cur.parentElement;
    }
    return null;
  }

  function rectsOf(node, a, b) {
    range.setStart(node, a);
    range.setEnd(node, b);
    var out = [];
    var rs = range.getClientRects();
    for (var i = 0; i < rs.length; i++) {
      if (rs[i].width > 0.5 && rs[i].height > 0.5) out.push(rs[i]);
    }
    return out;
  }

  function emitText(text, r, ctx, ls, ts) {
    // 아이콘 글꼴 문자(사용자 정의 영역)는 맑은 고딕에 없어서 빈 네모로 보이므로 뺀다
    text = (text || '').replace(/[\uE000-\uF8FF]/g, '').trim();
    if (!text || !visibleIn(ctx.clip, r)) return;
    var tok = {
      t: 'x', v: text,
      x: Math.round(r.left + sx), y: Math.round(r.top + sy),
      w: Math.round(r.width), h: Math.round(r.height),
      b: ctx.blk, s: ctx.st
    };
    if (ls) tok.ls = 1;
    if (ts) tok.ts = 1;
    if (ctx.fn) tok.fn = ctx.fn;
    else if (ctx.href) tok.href = ctx.href;
    tokens.push(tok);
  }

  function sameLine(a, r) {
    var h = Math.min(a.bottom - a.top, r.height);
    return Math.abs(r.top - a.top) < h * 0.5 && r.left >= a.right - 2;
  }

  // 텍스트 노드 하나를 "화면상의 줄" 단위 조각으로 분해.
  // 한 줄에 다 들어가면 그대로, 여러 줄로 감기면 단어(필요하면 글자) 단위로 위치를 재서
  // 같은 줄끼리 다시 묶는다 — 줄마다 정확한 x/y 를 가지므로 행 순서가 뒤섞이지 않는다.
  function pushText(node, ctx) {
    var raw = node.nodeValue;
    if (!raw || !/\S/.test(raw)) return;
    var ls = /^\s/.test(raw), ts = /\s$/.test(raw);
    var all = rectsOf(node, 0, raw.length);
    if (all.length === 0) return;
    if (all.length === 1) {
      emitText(raw.replace(/\s+/g, ' ').trim(), all[0], ctx, ls, ts);
      return;
    }
    var line = null, first = true;
    function flush(trailing) {
      if (!line) return;
      emitText(line.text, {
        left: line.left, top: line.top,
        width: line.right - line.left, height: line.bottom - line.top
      }, ctx, line.ls, trailing);
      line = null;
    }
    function add(text, r, spaceBefore) {
      if (line && sameLine(line, r)) {
        line.text += (spaceBefore ? ' ' : '') + text;
        line.left = Math.min(line.left, r.left);
        line.top = Math.min(line.top, r.top);
        line.right = Math.max(line.right, r.right);
        line.bottom = Math.max(line.bottom, r.bottom);
        return;
      }
      flush(spaceBefore);
      line = {text: text, left: r.left, top: r.top, right: r.right, bottom: r.bottom,
              ls: first ? ls : spaceBefore};
    }
    var re = /\S+/g, m;
    while ((m = re.exec(raw))) {
      var word = m[0], start = m.index;
      var wr = rectsOf(node, start, start + word.length);
      if (wr.length === 0) continue;
      if (wr.length === 1) {
        add(word, wr[0], !first);
      } else {
        // 단어 중간에서 줄이 바뀜 (한글은 음절 단위로 감김) → 글자 단위
        var piece = '', pr = null, sp = !first;
        for (var i = 0; i < word.length; i++) {
          var cr = rectsOf(node, start + i, start + i + 1);
          var c = cr.length ? cr[0] : null;
          if (pr && c && !(Math.abs(c.top - pr.top) < Math.min(pr.height, c.height) * 0.5)) {
            add(piece, pr, sp);
            piece = ''; pr = null; sp = false;
          }
          piece += word[i];
          if (c) {
            pr = pr ? {left: Math.min(pr.left, c.left), top: Math.min(pr.top, c.top),
                       right: Math.max(pr.right, c.right), bottom: Math.max(pr.bottom, c.bottom),
                       height: Math.max(pr.height, c.height)}
                    : {left: c.left, top: c.top, right: c.right, bottom: c.bottom, height: c.height};
          }
        }
        if (piece && pr) add(piece, pr, sp);
      }
      first = false;
    }
    flush(ts);
  }

  // lazy-load 대응 — placeholder 가 아닌 진짜 이미지 URL 찾기.
  function absolutize(url) {
    if (!url) return '';
    url = url.trim();
    if (!url) return '';
    if (url.startsWith('data:')) return '';
    if (url.startsWith('//')) return location.protocol + url;
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    try { return new URL(url, location.href).href; } catch (e) { return url; }
  }

  function realImgSrc(img) {
    try {
      if (img.currentSrc && !img.currentSrc.startsWith('data:')) return absolutize(img.currentSrc);
      var sets = img.srcset || img.getAttribute('srcset') || '';
      if (sets) {
        var parts = sets.split(',');
        for (var i = parts.length - 1; i >= 0; i--) {
          var abs = absolutize(parts[i].trim().split(/\s+/)[0]);
          if (abs) return abs;
        }
      }
      var attrs = ['data-src', 'data-original', 'data-lazy-src', 'data-srcset'];
      for (var k = 0; k < attrs.length; k++) {
        var v = img.getAttribute(attrs[k]);
        if (v) {
          var abs2 = absolutize(v.split(',')[0].trim().split(/\s+/)[0]);
          if (abs2) return abs2;
        }
      }
      return absolutize(img.src || '');
    } catch (e) {
      return absolutize(img.src || '');
    }
  }

  function pushImage(el, ctx) {
    var r = el.getBoundingClientRect();
    if (r.width < 6 && r.height < 6) return;
    if (!visibleIn(ctx.clip, r)) return;
    var tok = {
      t: 'i', src: realImgSrc(el), alt: el.alt || '',
      x: Math.round(r.left + sx), y: Math.round(r.top + sy),
      w: Math.round(r.width), h: Math.round(r.height),
      b: ctx.blk
    };
    if (ctx.fn) tok.fn = ctx.fn;
    else if (ctx.href) tok.href = ctx.href;
    tokens.push(tok);
  }

  // 본문에 끼워 넣은 동영상(YouTube 등 iframe) — 내용은 못 가져오므로 자리 + 주소만
  function pushEmbed(el, ctx) {
    var src = absolutize(el.getAttribute('src') || '');
    if (!src || !/^https?:/.test(src) || isAd(el)) return;
    if (!/youtube|youtu\.be|vimeo|kakao|naver|dailymotion|nicovideo|bilibili|twitch/i.test(src)) return;
    var r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 40 || !visibleIn(ctx.clip, r)) return;
    var s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return;
    tokens.push({t: 'v', src: src,
                 x: Math.round(r.left + sx), y: Math.round(r.top + sy),
                 w: Math.round(r.width), h: Math.round(r.height), b: ctx.blk});
  }

  var BULLET = {disc: '•', circle: '◦', square: '▪'};
  function markerText(li, type) {
    if (BULLET[type]) return BULLET[type];
    var n = 1;
    if (li.value) n = li.value;
    else {
      var par = li.parentElement;
      if (par && par.nodeName === 'OL' && par.start) n = par.start;
      for (var sib = li.previousElementSibling; sib; sib = sib.previousElementSibling) {
        if (sib.nodeName === 'LI') n++;
      }
    }
    if (type === 'lower-alpha' || type === 'lower-latin') return String.fromCharCode(96 + ((n - 1) % 26) + 1) + '.';
    if (type === 'upper-alpha' || type === 'upper-latin') return String.fromCharCode(64 + ((n - 1) % 26) + 1) + '.';
    if (type === 'lower-roman' || type === 'upper-roman') {
      var R = [[1000,'m'],[900,'cm'],[500,'d'],[400,'cd'],[100,'c'],[90,'xc'],[50,'l'],[40,'xl'],[10,'x'],[9,'ix'],[5,'v'],[4,'iv'],[1,'i']];
      var out = '', v = n;
      for (var k = 0; k < R.length; k++) while (v >= R[k][0]) { out += R[k][1]; v -= R[k][0]; }
      return (type === 'upper-roman' ? out.toUpperCase() : out) + '.';
    }
    return n + '.';
  }

  function walk(el, ctx) {
    var ch = el.childNodes;
    for (var i = 0; i < ch.length; i++) {
      var c = ch[i];
      if (c.nodeType === 3) { pushText(c, ctx); continue; }
      if (c.nodeType === 1 && c.nodeName === 'IFRAME') { pushEmbed(c, ctx); continue; }
      if (c.nodeType !== 1 || SKIP[c.nodeName]) continue;
      var s;
      try { s = window.getComputedStyle(c); } catch (e) { continue; }
      if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse') continue;
      if (num(s.opacity) === 0 && s.opacity !== '') continue;
      if (isAd(c)) continue;

      var n = {href: ctx.href, fn: ctx.fn, clip: ctx.clip, blk: ctx.blk,
               st: ctx.st, strike: ctx.strike};
      if ((s.textDecorationLine || '').indexOf('line-through') >= 0) n.strike = 1;

      var disp = s.display;
      var r = null;
      if (disp !== 'inline' && disp !== 'contents') {
        r = c.getBoundingClientRect();
        n.blk = nBlocks++;
        // overflow:auto/scroll 은 스크롤하면 볼 수 있으므로 자르지 않는다
        var ox = s.overflowX, oy = s.overflowY;
        if (ox === 'hidden' || ox === 'clip' || oy === 'hidden' || oy === 'clip') {
          n.clip = inter(ctx.clip, {
            l: (ox === 'hidden' || ox === 'clip') ? r.left + sx : -1e9,
            r: (ox === 'hidden' || ox === 'clip') ? r.right + sx : 1e9,
            t: (oy === 'hidden' || oy === 'clip') ? r.top + sy : -1e9,
            b: (oy === 'hidden' || oy === 'clip') ? r.bottom + sy : 1e9
          });
          if (n.clip.r - n.clip.l < 1 || n.clip.b - n.clip.t < 1) continue;
        }
        if (disp === 'list-item' && s.listStyleType && s.listStyleType !== 'none') {
          var fs = num(s.fontSize) || 15;
          var mt = markerText(c, s.listStyleType);
          var mw = fs * (mt.length > 1 ? mt.length * 0.6 : 0.8);
          n.st = styleOf(s, n);
          emitText(mt, {left: r.left - mw - fs * 0.4, top: r.top, width: mw,
                        height: num(s.lineHeight) || fs * 1.5}, n, false, true);
        }
      }
      n.st = styleOf(s, n);

      if (c.nodeName === 'IMG') { pushImage(c, n); continue; }
      if (c.nodeName === 'A') {
        var h = c.getAttribute('href') || '';
        try { if (h && c.href) h = c.href; } catch (e) {}
        var pid = samePageId(c);
        if (pid !== null) {
          // 각주(#fn-N)는 내용을 보여 주고, 그 밖의 페이지 안 링크(목차 #s-N, #toc,
          // 각주 목록의 #rfn-N 등)는 시트 안에서 그 위치로 이동 — href 를 "#id" 로 남김
          var fn = /^fn-/.test(pid) ? resolveFootnote(pid) : null;
          if (fn) { n.fn = fn; n.href = null; }
          else if (document.getElementById(pid)) { n.href = '#' + pid; jumpIds[pid] = 1; }
        } else if (h && !/^javascript:/i.test(h)) n.href = h;
      }
      walk(c, n);
    }
  }

  // lazy-load 트리거
  try {
    window.scrollTo(0, document.body ? document.body.scrollHeight : 0);
    window.scrollTo(0, 0);
    sx = window.scrollX; sy = window.scrollY;
  } catch (e) {}

  try {
    if (!document.body) {
      return { ok: false, sel: 'no-body', title: document.title, url: location.href,
               readyState: document.readyState };
    }
    var root = contentRoot();
    walk(root, {href: null, fn: null, clip: null, blk: -1,
                st: styleOf(window.getComputedStyle(root), {}), strike: 0});
    // 이동 대상의 페이지 y 좌표 — 시트에서는 이 높이의 행으로 이동
    var anchors = {};
    for (var jid in jumpIds) {
      var el = document.getElementById(jid);
      if (!el) continue;
      var er = el.getBoundingClientRect();
      if (er.width === 0 && er.height === 0 && el.parentElement)
        er = el.parentElement.getBoundingClientRect();
      anchors[jid] = Math.round(er.top + sy);
    }
    return {
      ok: true, sel: root === document.body ? 'body' : 'content',
      tokens: tokens, styles: styles, anchors: anchors,
      pageW: pageW, pageH: pageH,
      title: document.title, url: location.href
    };
  } catch (e) {
    return { ok: false, sel: 'error', error: String(e) + ' @ ' + (e.stack || '') };
  }
})());
"""


class NamuLoader(QObject):
    """Hidden QWebEnginePage that loads namu.wiki and extracts positioned tokens."""

    loadStarted = Signal(str)
    loadProgress = Signal(int)
    pageLoaded = Signal()  # 페이지 로드 성공 (본문 추출은 이제 시작)
    # title, doc (tokens/styles/pageW/pageH — namuformatter 입력), source_url
    bodyExtracted = Signal(str, dict, str)
    # 창 크기 변경으로 같은 페이지를 새 폭으로 다시 배치해서 읽은 결과: source_url, doc
    relayoutDone = Signal(str, dict)
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
        self._page.loadStarted.connect(self._on_page_load_started)
        self._page.loadProgress.connect(self._on_progress)
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
        self._gen = 0  # fetch 세대 — 이전 로드의 지연 추출 타이머가 새 페이지에 끼어들지 않게
        self._page_ready = False  # 현재 페이지 추출까지 끝났는지 (다시 배치 가능 여부)
        # 페이지 로드가 아직 안 끝났는지 — 끝난 뒤(실패 포함) 늦게 오는 진행률이
        # 상태 표시줄의 실패 문구를 "렌더링 완료" 로 덮지 않게 진행률은 이때만 전달
        self._loading = False
        self._relayout_gen = 0
        self._extract_attempts = 0
        self._max_attempts = 4
        self._extract_delay_ms = 5000

        self._debug_view: QWebEngineView | None = None

    def setPageWidth(self, css_px: int) -> None:
        """렌더링 폭(CSS px). 시트 폭에 맞춰 두면 줄바꿈 위치가 시트와 같아진다.

        창을 줄이면 이 폭도 줄어든다 — 좁으면 나무위키도 좁은 화면용 배치(사이드바 없음)로 바뀜.
        """
        css_px = max(360, min(3000, int(css_px)))
        if self._hidden_view is not None and self._hidden_view.width() != css_px:
            self._hidden_view.resize(css_px, 900)

    def loadedUrl(self) -> str:
        """다시 배치(relayout)할 수 있는 상태로 열려 있는 페이지 주소. 없으면 ""."""
        return self._current_url if self._page_ready else ""

    def relayout(self, css_px: int) -> bool:
        """지금 열린 페이지를 새 폭으로 다시 배치하고 다시 추출 (네트워크 없이).

        결과는 relayoutDone 으로. 페이지가 준비 안 됐으면 False.
        """
        if not self._page_ready or self._page is None:
            return False
        self.setPageWidth(css_px)
        self._relayout_gen += 1
        gen = self._relayout_gen

        def run() -> None:
            if gen != self._relayout_gen or not self._page_ready or self._page is None:
                return
            self._page.runJavaScript(
                _EXTRACT_JS, lambda res, g=gen: self._on_relayout_extracted(res, g)
            )
        # 크기 변경 후 렌더러가 다시 배치할 시간
        QTimer.singleShot(400, run)
        return True

    def _on_relayout_extracted(self, result, gen: int) -> None:
        if gen != self._relayout_gen or not self._page_ready:
            return
        info = self._parse_result(result)
        if info.get("ok") and info.get("tokens"):
            self.relayoutDone.emit(self._current_url, self._doc_from(info))

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
                # 나무위키 검색창과 같은 /Go 경로 — 띄어쓰기/대소문자가 달라도 문서를 찾아가고,
                # 없으면 검색 결과 페이지로 간다. (/w/제목 은 정확히 일치해야만 열림)
                self._current_title = s
                self._current_url = f"https://namu.wiki/Go?q={quote(s, safe='')}"
                qurl = QUrl(self._current_url)

        self._gen += 1
        self._page_ready = False
        self._relayout_gen += 1   # 진행 중이던 다시 배치는 무효
        self._extract_attempts = 0
        self._loading = True
        self.loadStarted.emit(self._current_title)
        self._page.load(qurl)

    def _on_progress(self, p: int) -> None:
        # 100% 는 보내지 않는다 — 실패해도 100% 가 오므로 성공 여부는 loadFinished 로만 판단
        if self._loading and p < 100:
            self.loadProgress.emit(p)

    def _on_page_load_started(self) -> None:
        self._loading = True
        self.loadProgress.emit(0)

    def _on_loaded(self, ok: bool) -> None:
        self._loading = False
        if not ok:
            self.fetchFailed.emit(self._current_title, "페이지를 불러오지 못했습니다")
            return
        self.pageLoaded.emit()
        gen = self._gen
        QTimer.singleShot(self._extract_delay_ms, lambda: self._run_extract(gen))

    def _run_extract(self, gen: int) -> None:
        if gen != self._gen or self._page is None:
            return
        self._extract_attempts += 1
        self._page.runJavaScript(
            _EXTRACT_JS, lambda res, g=gen: self._on_extracted(res, g)
        )

    @staticmethod
    def _page_title(doc_title: str, url: str, fallback: str) -> str:
        """document.title("악어 - 나무위키") / URL 에서 실제 문서 제목."""
        t = (doc_title or "").strip()
        for suffix in (" - 나무위키", " - namu.wiki"):
            if t.endswith(suffix):
                t = t[: -len(suffix)].strip()
        if "/Search?" in (url or ""):
            q = (parse_qs(urlparse(url).query).get("q") or [""])[0]
            return f"검색: {q}" if q else (t or fallback)
        return t or fallback

    @staticmethod
    def _parse_result(result) -> dict:
        if isinstance(result, str) and result:
            try:
                return json.loads(result)
            except Exception as e:
                return {"ok": False, "sel": "json-parse-error",
                        "error": f"JSON.parse 실패: {e}", "raw_head": result[:300]}
        if isinstance(result, dict):
            return result
        return {"ok": False, "sel": "no-result",
                "error": f"runJavaScript 결과가 빈 값 (type={type(result).__name__})"}

    def _doc_from(self, info: dict) -> dict:
        return {
            "tokens": info.get("tokens") or [],
            "styles": info.get("styles") or [],
            "anchors": info.get("anchors") or {},
            "pageW": int(info.get("pageW") or 1280),
            "pageH": int(info.get("pageH") or 800),
            # 이 문서를 렌더링한 폭 — 창 크기와 다르면 다시 배치 대상
            "renderW": self._hidden_view.width() if self._hidden_view is not None else 0,
        }

    def _on_extracted(self, result, gen: int) -> None:
        if gen != self._gen:
            return
        info = self._parse_result(result)
        ok = bool(info.get("ok"))
        tokens = info.get("tokens") or []

        if ok and tokens:
            url = info.get("url") or self._current_url
            self._current_title = self._page_title(info.get("title", ""), url, self._current_title)
            self._current_url = url
            self._page_ready = True
            self.bodyExtracted.emit(self._current_title, self._doc_from(info), self._current_url)
            return

        if self._extract_attempts < self._max_attempts:
            QTimer.singleShot(1500, lambda: self._run_extract(gen))
            return

        self.diagnostics.emit(info)
        self.fetchFailed.emit(self._current_title, "본문을 찾지 못했습니다 (selector 미스)")
