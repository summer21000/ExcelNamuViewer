from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEngineLoadingInfo, QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView


# 광고·추적 요청 차단 목록 (호스트가 이 도메인이거나 그 하위 도메인이면 차단).
# 본문 배치와 상관없는 요청이라 막으면 페이지 로드가 빨라진다. 문서 주소(메인 프레임)는 막지 않음.
_BLOCK_DOMAINS = (
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "googletagservices.com", "googletagmanager.com", "google-analytics.com",
    "adservice.google.com", "adservice.google.co.kr", "pagead2.googlesyndication.com",
    "fundingchoicesmessages.google.com", "imasdk.googleapis.com",
    "amazon-adsystem.com", "adnxs.com", "criteo.com", "criteo.net", "taboola.com",
    "outbrain.com", "pubmatic.com", "rubiconproject.com", "openx.net", "casalemedia.com",
    "scorecardresearch.com", "quantserve.com", "moatads.com", "adsrvr.org",
    "smartadserver.com", "teads.tv", "yieldmo.com", "3lift.com", "sharethrough.com",
    "connect.facebook.net", "analytics.tiktok.com", "ads-twitter.com",
    "dable.io", "mobon.net", "realclick.co.kr", "tenping.kr", "adpnut.com",
    "clarity.ms", "hotjar.com", "newrelic.com", "nr-data.net",
)


def _blocked_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    for d in _BLOCK_DOMAINS:
        if host == d or host.endswith("." + d):
            return True
    return False


class _AdBlocker(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info) -> None:  # noqa: N802 (Qt 이름)
        try:
            if info.resourceType() == QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame:
                return
            if _blocked_host(info.requestUrl().host()):
                info.block(True)
        except Exception:
            pass


# 본문이 준비되면 페이지가 직접 알려 준다 (시간을 정해 두고 기다리지 않음).
# 준비 조건: 문서 로드 완료 + 본문 글자 + (나무위키면) 문서 제목 h1.
# 이미 준비됐으면 바로, 아니면 DOM 이 바뀔 때마다(MutationObserver) 다시 확인해서
# 조건이 맞는 순간 console 로 신호(tag)를 보낸다 → _Page.javaScriptConsoleMessage 가 받음.
# afterChange: 추출 재시도용 — 지금 상태는 건너뛰고 다음 DOM 변화부터 확인.
_WAIT_JS = r"""
(function(tag, needH1, afterChange) {
  var done = false;
  function ok() {
    var b = document.body;
    // 글자가 없어도 iframe 이 있으면 준비된 것 — 본문이 iframe 안에 있는 사이트는
    // 추출 단계에서 그 iframe 주소를 직접 연다
    return document.readyState === 'complete' && !!b &&
           ((b.innerText || '').length > 0 || !!document.querySelector('iframe')) &&
           (!needH1 || !!document.querySelector('h1'));
  }
  function check() {
    if (done || !ok()) return;
    done = true;
    try { mo.disconnect(); } catch (e) {}
    document.removeEventListener('readystatechange', check);
    console.log(tag);
  }
  var mo = new MutationObserver(check);
  mo.observe(document.documentElement, {childList: true, subtree: true, characterData: true});
  document.addEventListener('readystatechange', check);
  if (!afterChange) check();
})(%s, %s, %s);
"""

_READY_TAG = "__excelview_ready__"


# 시트의 검색 셀에 쓴 검색어로 페이지의 검색을 실행 — 입력칸에 넣고, 그 양식의 검색 버튼을
# 누른다 (버튼이 없으면 Enter 키 / 양식 제출). 사이트가 만드는 검색 주소로 이동하려는 순간
# _Page 가 그 이동을 가로채서 앱이 그 주소를 평소 링크처럼 연다.
# 인자: 입력칸 순번(추출 때의 fi), 검색어
_FIELD_SUBMIT_JS = r"""
(function(fi, text) {
  var el = document.querySelectorAll(
    'input[type="text"],input[type="search"],input:not([type])')[fi];
  if (!el) return 'nofield';
  try { el.focus(); } catch (e) {}
  var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, text);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  var f = el.form;
  var btn = f && f.querySelector(
    'button[type="submit"],input[type="submit"],input[type="image"],button:not([type])');
  if (btn) { btn.click(); return 'click'; }
  var o = {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true};
  var go = el.dispatchEvent(new KeyboardEvent('keydown', o));
  el.dispatchEvent(new KeyboardEvent('keypress', o));
  el.dispatchEvent(new KeyboardEvent('keyup', o));
  if (f && go) {
    if (f.requestSubmit) f.requestSubmit(); else f.submit();
    return 'submit';
  }
  return 'key';
})(%s, %s);
"""


class _Page(QWebEnginePage):
    """페이지 안 JS 가 보낸 준비 신호(console 메시지)를 시그널로 바꿔 주는 페이지."""

    readySignal = Signal(int)   # 대기 세대
    # 검색 실행 중 페이지가 다른 주소로 가려 함 — 이동은 막고 주소만 알린다
    navCaptured = Signal(QUrl)
    capture_nav = False

    def acceptNavigationRequest(self, url, nav_type, is_main_frame) -> bool:  # noqa: N802
        if self.capture_nav and is_main_frame:
            self.capture_nav = False
            self.navCaptured.emit(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    # 숨은 페이지는 대화상자를 띄우지 않는다 — 기본 동작은 보이지 않는 모달 창을 띄우고
    # 응답을 기다려서 다른 시트의 로드까지 멈춘다 (네이버 블로그 "게시물이 삭제…" alert 등).
    # 위장 면에서도 숨은 페이지가 창을 띄우면 안 됨.
    def javaScriptAlert(self, origin, msg) -> None:  # noqa: N802
        pass

    def javaScriptConfirm(self, origin, msg) -> bool:  # noqa: N802
        return False

    def javaScriptPrompt(self, origin, msg, default):  # noqa: N802
        return False, ""

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:  # noqa: N802
        if message.startswith(_READY_TAG):
            try:
                self.readySignal.emit(int(message[len(_READY_TAG):]))
            except ValueError:
                pass


# https:// 없이 입력한 웹 주소로 볼 입력 — 소문자 + 공백 없음 + 알려진 도메인 끝자리 (+ 경로)
_DOMAIN_INPUT_RE = re.compile(
    r"^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*"
    r"\.(?:com|net|org|kr|co\.kr|or\.kr|go\.kr|ac\.kr|re\.kr|ne\.kr|io|me|tv|jp|co\.jp|"
    r"cn|uk|co\.uk|de|fr|edu|gov|info|biz|dev|app|ai|xyz|wiki|gg)"
    r"(?::\d+)?(?:[/?#]\S*)?$",
)   # 대소문자 구분 — 주소는 보통 소문자로 입력. "ASP.NET" 같은 대문자 제목은 나무위키로


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
    // el.id / el.className 은 <form> 안에 name="id" 입력칸이 있으면 그 요소가 됨 — 속성으로 읽음
    var id = (el.getAttribute && el.getAttribute('id')) || '';
    var cls = (el.getAttribute && el.getAttribute('class')) || '';
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

  // 지원 사이트 B 판별 (도메인은 인코딩해 둠)
  var SITE_B = atob('ZGNpbnNpZGUuY29t');
  function isSiteB() {
    var h = location.hostname || '';
    return h === SITE_B || h.slice(-(SITE_B.length + 1)) === '.' + SITE_B;
  }

  // 본문 영역만 — 상단 메뉴바 / 우측 사이드바(최근 변경·인기 검색어·광고) 제외.
  // 문서 제목(h1)과 첫 문단 제목(#s-1)을 함께 품는 가장 가까운 요소가 본문 열이다.
  function contentRoot() {
    var body = document.body;
    // 지원 사이트 B — 제목·글·댓글·목록이 든 main#container 만.
    // 상단 메뉴, 옆 광고, 하단 분류·약관은 그 바깥에 있다
    if (isSiteB()) {
      var sb = document.querySelector('main#container') || document.getElementById('container');
      if (sb && (sb.innerText || '').trim()) return sb;
    }
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

  // 본문이 통째로 iframe 안에 있는 사이트(네이버 블로그 등) — 화면 대부분을 차지하는
  // 가장 큰 iframe 의 주소. 바깥 페이지에 글자가 거의 없으면 이 주소를 직접 열어서 읽는다.
  function mainFrame() {
    var best = null, bestArea = 0;
    var vw = document.documentElement.clientWidth || window.innerWidth;
    var fr = document.querySelectorAll('iframe');
    for (var i = 0; i < fr.length; i++) {
      var f = fr[i];
      var src = f.src || '';
      if (!/^https?:/.test(src) || isAd(f)) continue;
      var s = window.getComputedStyle(f);
      if (s.display === 'none' || s.visibility === 'hidden') continue;
      var r = f.getBoundingClientRect();
      if (r.width < vw * 0.5 || r.height < 300) continue;
      if (r.width * r.height > bestArea) { bestArea = r.width * r.height; best = src; }
    }
    return best;
  }

  // 본문 사이에 끼워 넣은 텍스트 광고 (파워링크 등). 클래스 이름은 무작위라 쓸 수 없고,
  // 링크를 문단 이동(#s-N)으로 위장한다 — 그런데 링크 글자가 목차 숫자도, 가리키는 문단의
  // 제목도 아니고, 광고 문구에 도메인(www.○○.com 등)이 들어 있다. 이런 표와 그 표만
  // 감싼 상위 요소를 통째로 뺀다.
  var textAds = new Set();
  var DOMAIN_RE = /(^|[\s(])(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|net|kr|co\.kr|org|biz|info|shop|io)(\/\S*)?(\s|$|\))/i;
  function markTextAds(root) {
    // 나무위키의 위장 광고만 — 다른 사이트 내용은 건드리지 않는다
    var host = location.hostname || '';
    if (host !== 'namu.wiki' && !/\.namu\.wiki$/.test(host)) return;
    var tables = root.querySelectorAll('table');
    for (var i = 0; i < tables.length; i++) {
      var t = tables[i];
      var links = t.querySelectorAll('a[href]');
      if (links.length < 2) continue;
      var fake = 0, genuine = false;
      for (var j = 0; j < links.length; j++) {
        var href = links[j].getAttribute('href') || '';
        if (!/^#s-/.test(href)) { genuine = true; break; }
        var txt = (links[j].innerText || '').replace(/\s+/g, ' ').trim();
        if (!txt) continue;
        var tgt = document.getElementById(href.substring(1));
        var tt = tgt ? (tgt.innerText || '').replace(/\s+/g, ' ').trim() : '';
        // 진짜 문단 링크: 목차 숫자이거나, 가리키는 문단 제목에 링크 글자가 들어 있음
        if (/^[\d.]+$/.test(txt) || (tt && tt.indexOf(txt) >= 0)) { genuine = true; break; }
        fake++;
      }
      if (genuine || fake < 2) continue;
      var all = (t.innerText || '').replace(/\s+/g, ' ').trim();
      if (!DOMAIN_RE.test(all)) continue;
      // 이 표만 감싼 상위 요소(글자가 같음)까지 올라가 통째로
      var top = t;
      while (top.parentElement && top.parentElement !== root &&
             (top.parentElement.innerText || '').replace(/\s+/g, ' ').trim() === all) {
        top = top.parentElement;
      }
      textAds.add(top);
    }
  }

  function inter(a, b) {
    if (!a) return b;
    return {l: Math.max(a.l, b.l), t: Math.max(a.t, b.t),
            r: Math.min(a.r, b.r), b: Math.min(a.b, b.b)};
  }
  // overflow:hidden 등으로 잘려 화면에 안 보이는 조각은 버린다.
  function visibleIn(clip, r) {
    // 페이지 바깥(음수 좌표)에 숨겨 둔 스크린리더용 글자("본문영역 바로가기" 등)
    if (r.top + r.height + sy <= 0 || r.left + r.width + sx <= 0) return false;
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
    // 지원 사이트 B 글쓴이 닉네임 옆 작은 아이콘 — 대체 글자("…로 이동합니다")가 셀에 찍히므로 제외
    if (isSiteB() && el.closest && el.closest('.writer_nikcon')) return;
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

  // 검색 입력칸 — 시트에는 입력할 수 있는 빈 셀로. 검색어를 넣고 Enter 를 누르면 앱이
  // 숨은 페이지의 같은 입력칸(fi = 문서 안 입력칸 순번)에 넣고 그 양식의 검색 버튼을 누른다.
  // 로그인·댓글 입력칸 등은 빼고 검색용으로 보이는 것만.
  var FIELD_SEL = 'input[type="text"],input[type="search"],input:not([type])';
  var allFields = Array.prototype.slice.call(document.querySelectorAll(FIELD_SEL));
  function pushField(el, ctx) {
    if (el.disabled || el.readOnly || isAd(el)) return;
    var hint = [el.name, el.getAttribute('id'), el.getAttribute('class'), el.placeholder,
                el.getAttribute('aria-label'), el.getAttribute('title')].join(' ');
    var isSearch = el.type === 'search' || /search|keyword|query|sch|검색/i.test(hint) ||
                   /^(q|s|k|kw)$/i.test(el.name || '') ||
                   !!(el.closest && el.closest('[role="search"]'));
    if (!isSearch) return;
    var s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || num(s.opacity) === 0) return;
    var r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 8 || !visibleIn(ctx.clip, r)) return;
    var fi = allFields.indexOf(el);
    if (fi < 0) return;
    tokens.push({t: 'f', fi: fi, ph: (el.placeholder || el.getAttribute('title') || '').trim(),
                 x: Math.round(r.left + sx), y: Math.round(r.top + sy),
                 w: Math.round(r.width), h: Math.round(r.height), b: ctx.blk});
  }

  var BULLET = {disc: '•', circle: '◦', square: '▪',
                'disclosure-closed': '▸', 'disclosure-open': '▾'};
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
    // 접힌 <details>(나무위키 틀의 탭/접기 상자)는 제목(summary)만 — 접힌 내용은 화면에
    // 안 그려지는데, 위치를 물으면 브라우저가 억지로 배치해 여러 탭 내용이 겹쳐 들어온다
    var closedDetails = el.nodeName === 'DETAILS' && !el.open;
    for (var i = 0; i < ch.length; i++) {
      var c = ch[i];
      if (closedDetails && !(c.nodeType === 1 && c.nodeName === 'SUMMARY')) continue;
      if (c.nodeType === 3) { pushText(c, ctx); continue; }
      if (c.nodeType === 1 && c.nodeName === 'IFRAME') { pushEmbed(c, ctx); continue; }
      if (c.nodeType === 1 && c.nodeName === 'INPUT') { pushField(c, ctx); continue; }
      if (c.nodeType !== 1 || SKIP[c.nodeName]) continue;
      var s;
      try { s = window.getComputedStyle(c); } catch (e) { continue; }
      if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse') continue;
      if (num(s.opacity) === 0 && s.opacity !== '') continue;
      if (isAd(c) || textAds.has(c)) continue;

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
    markTextAds(root);
    // 지원 사이트 B 글 목록 옆 홍보 영역 — 글 목록은 유지
    if (isSiteB()) {
      var side = root.querySelectorAll('.right_content');
      for (var si = 0; si < side.length; si++) textAds.add(side[si]);
    }
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
      title: document.title, url: location.href,
      textLen: (document.body.innerText || '').replace(/\s+/g, '').length,
      frame: mainFrame()
    };
  } catch (e) {
    return { ok: false, sel: 'error', error: String(e) + ' @ ' + (e.stack || '') };
  }
})());
"""


class _Job:
    """로드 요청 하나 = 숨은 브라우저 탭 하나 (페이지 + 렌더 크기용 숨은 뷰)."""

    def __init__(self, rid: int, page: QWebEnginePage, view: QWebEngineView,
                 title: str, url: str) -> None:
        self.rid = rid
        self.page = page
        self.view = view
        self.title = title
        self.url = url
        self.loading = True
        self.gen = 0        # loadFinished 세대 — JS 리다이렉트로 다시 로드되면 최신 것만 추출
        self.attempts = 0
        self.frame_hops = 0   # 본문 iframe 을 따라 들어간 횟수 (무한 반복 방지)
        # 서버가 오류 코드(404 등)로 응답했을 때 그 코드 — 브라우저처럼 서버가 보낸 안내
        # 페이지를 그대로 보여 준다. 접속 자체 실패(연결 끊김 등)와 구분하는 용도
        self.http_status: int | None = None
        self.net_error: int | None = None
        self.watchdog: QTimer | None = None   # 준비 신호가 끝내 안 올 때만 쓰는 안전장치


class NamuLoader(QObject):
    """namu.wiki 를 숨은 QWebEnginePage 로 불러와 위치 정보가 붙은 조각을 추출한다.

    요청(fetch)마다 페이지를 따로 만든다 — 브라우저 탭처럼 여러 로드가 동시에 진행돼도
    서로 끊거나 결과를 가로채지 않는다. 모든 시그널의 첫 인자는 요청 번호(rid).
    """

    loadProgress = Signal(int, int)          # rid, %
    pageLoaded = Signal(int)                 # rid — 페이지 로드 성공 (본문 추출은 이제 시작)
    # rid, title, doc (tokens/styles/pageW/pageH — namuformatter 입력), source_url
    bodyExtracted = Signal(int, str, dict, str)
    # 창 크기 변경으로 같은 페이지를 새 폭으로 다시 배치해서 읽은 결과: source_url, doc
    relayoutDone = Signal(str, dict)
    fetchFailed = Signal(int, str, str)      # rid, title, 사유
    diagnostics = Signal(int, dict)          # rid, 진단 정보
    # 시트의 검색 셀로 페이지 검색 실행 → 이동할 검색 결과 주소: 검색한 문서 주소, 결과 주소
    fieldNavigation = Signal(str, str)
    fieldFailed = Signal(str)                # 사유

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        profile = QWebEngineProfile("ExcelViewNamu", self)
        profile.setHttpUserAgent(_UA_CHROME)
        self._adblock = _AdBlocker(self)   # 참조 유지 필수 (프로필은 소유하지 않음)
        profile.setUrlRequestInterceptor(self._adblock)
        s = profile.settings()
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        # 이미지는 내려받지 않는다 — 시트에는 "[사진보기]" 로만 나오고, 누르면 사진 창이
        # 주소로 직접 받아 온다. 주소·자리(크기)는 태그 속성만으로 추출됨 (켬/끔 비교로 확인)
        s.setAttribute(QWebEngineSettings.AutoLoadImages, False)
        s.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self._profile = profile

        self._jobs: dict[int, _Job] = {}   # 진행 중인 요청
        # 마지막으로 추출까지 끝난 페이지 — 창 크기 변경 시 네트워크 없이 다시 배치할 때 사용
        self._ready: _Job | None = None
        self._next_rid = 0
        self._page_w = 1280
        self._relayout_gen = 0
        self._max_attempts = 4
        # 정상 흐름은 페이지의 준비 신호로만 진행한다. 이 값은 신호가 끝내 오지 않을 때
        # (Cloudflare 확인 화면에 멈춤 등) 무한정 "로드 중" 에 머물지 않게 하는 실패 처리용.
        self._watchdog_ms = 15000

        self._debug_view: QWebEngineView | None = None

        # 진행 중인 검색 (submitField) — page, url(검색한 문서), seq, temp(따로 연 페이지인지)
        self._submit: dict | None = None
        self._submit_seq = 0

    # ------------------------------------------------------------------ search field
    def submitField(self, page_url: str, field: int, text: str) -> None:
        """page_url 문서의 검색 입력칸(field 번)에 text 로 검색 → fieldNavigation / fieldFailed."""
        self._end_submit()
        job = self._ready if (self._ready is not None and self._ready.url == page_url) else None
        if job is not None:
            self._submit_on(job.page, page_url, field, text, temp=False)
            return
        # 다른 문서가 열려 있음 — 이 문서를 숨은 페이지로 다시 열어서 검색
        page = _Page(self._profile, self)
        page.navCaptured.connect(lambda u, p=page: self._on_nav_captured(p, u))
        started = {"done": False}

        def on_loaded(ok: bool) -> None:
            if started["done"] or self._submit is None or self._submit["page"] is not page:
                return
            started["done"] = True
            if not ok:
                self._fail_submit("검색할 페이지를 다시 불러오지 못했습니다")
                return
            self._submit_on(page, page_url, field, text, temp=True)

        self._submit_seq += 1
        self._submit = {"page": page, "url": page_url, "seq": self._submit_seq, "temp": True}
        page.loadFinished.connect(on_loaded)
        page.load(QUrl(page_url))
        seq = self._submit_seq
        QTimer.singleShot(20000, lambda: self._submit_timeout(seq))

    def _submit_on(self, page: QWebEnginePage, page_url: str, field: int, text: str,
                   temp: bool) -> None:
        self._submit_seq += 1
        seq = self._submit_seq
        self._submit = {"page": page, "url": page_url, "seq": seq, "temp": temp}
        page.capture_nav = True
        js = _FIELD_SUBMIT_JS % (int(field), json.dumps(text))
        page.runJavaScript(js, lambda res, s=seq: self._on_submit_js(s, res))
        QTimer.singleShot(5000, lambda: self._submit_timeout(seq))

    def _on_submit_js(self, seq: int, res) -> None:
        if self._submit is not None and self._submit["seq"] == seq and res == "nofield":
            self._fail_submit("페이지에서 검색창을 찾지 못했습니다")

    def _on_nav_captured(self, page: QWebEnginePage, url: QUrl) -> None:
        sub = self._submit
        if sub is None or sub["page"] is not page:
            return
        self._end_submit()
        self.fieldNavigation.emit(sub["url"], url.toString())

    def _submit_timeout(self, seq: int) -> None:
        if self._submit is not None and self._submit["seq"] == seq:
            self._fail_submit("검색 결과로 이동하지 못했습니다")

    def _fail_submit(self, msg: str) -> None:
        self._end_submit()
        self.fieldFailed.emit(msg)

    def _end_submit(self) -> None:
        sub, self._submit = self._submit, None
        if sub is None:
            return
        page = sub["page"]
        try:
            page.capture_nav = False
        except Exception:
            pass
        if sub["temp"]:
            try:
                page.triggerAction(QWebEnginePage.WebAction.Stop)
                page.deleteLater()
            except Exception:
                pass

    # ------------------------------------------------------------------ pages
    def _new_job(self, title: str, url: str) -> _Job:
        self._next_rid += 1
        rid = self._next_rid
        page = _Page(self._profile, self)
        page.readySignal.connect(lambda g, r=rid: self._on_ready(r, g))
        page.navCaptured.connect(lambda u, p=page: self._on_nav_captured(p, u))
        page.loadStarted.connect(lambda r=rid: self._on_page_load_started(r))
        page.loadProgress.connect(lambda p, r=rid: self._on_progress(r, p))
        # 로드 결과는 loadingChanged 로만 판단 (성공/서버 오류 응답/접속 실패/중단 구분)
        page.loadingChanged.connect(lambda li, r=rid: self._on_loading_changed(r, li))
        # hidden view 로 viewport 확보 — layout 계산 (getBoundingClientRect) 이 동작하려면
        # page 가 실제 렌더 사이즈를 가져야 한다. WA_DontShowOnScreen 으로 화면엔 안 뜸.
        view = QWebEngineView()
        view.setPage(page)
        view.setAttribute(Qt.WA_DontShowOnScreen, True)
        view.resize(self._page_w, 900)
        view.show()
        job = _Job(rid, page, view, title, url)
        self._jobs[rid] = job
        return job

    def _destroy(self, job: _Job | None) -> None:
        if job is None:
            return
        if job.watchdog is not None:
            job.watchdog.stop()
            job.watchdog.deleteLater()
            job.watchdog = None
        try:
            if self._debug_view is not None and self._debug_view.page() == job.page:
                self._debug_view.setPage(QWebEnginePage(self._profile, self._debug_view))
        except Exception:
            pass
        try:
            job.page.triggerAction(QWebEnginePage.WebAction.Stop)
        except Exception:
            pass
        # 뷰를 먼저 지우고 페이지를 지운다 (deleteLater 는 넣은 순서대로 처리됨)
        try:
            job.view.close()
            job.view.deleteLater()
        except Exception:
            pass
        try:
            job.page.deleteLater()
        except Exception:
            pass

    def setPageWidth(self, css_px: int) -> None:
        """다음에 여는 페이지의 렌더링 폭(CSS px). 시트 폭에 맞춰 두면 줄바꿈 위치가 시트와 같아진다.

        창을 줄이면 이 폭도 줄어든다 — 좁으면 나무위키도 좁은 화면용 배치(사이드바 없음)로 바뀜.
        """
        self._page_w = max(360, min(3000, int(css_px)))

    def loadedUrl(self) -> str:
        """다시 배치(relayout)할 수 있는 상태로 열려 있는 페이지 주소. 없으면 ""."""
        return self._ready.url if self._ready is not None else ""

    def relayout(self, css_px: int) -> bool:
        """마지막으로 연 페이지를 새 폭으로 다시 배치하고 다시 추출 (네트워크 없이).

        결과는 relayoutDone 으로. 페이지가 준비 안 됐으면 False.
        """
        job = self._ready
        if job is None:
            return False
        self.setPageWidth(css_px)
        if job.view.width() != self._page_w:
            job.view.resize(self._page_w, 900)
        self._relayout_gen += 1
        gen = self._relayout_gen

        def run() -> None:
            if gen != self._relayout_gen or self._ready is not job:
                return
            job.page.runJavaScript(
                _EXTRACT_JS, lambda res, g=gen, j=job: self._on_relayout_extracted(res, g, j)
            )
        # 크기 변경 후 렌더러가 다시 배치할 시간
        QTimer.singleShot(400, run)
        return True

    def _on_relayout_extracted(self, result, gen: int, job: _Job) -> None:
        if gen != self._relayout_gen or self._ready is not job:
            return
        info = self._parse_result(result)
        if info.get("ok") and info.get("tokens"):
            self.relayoutDone.emit(job.url, self._doc_from(info, job))

    def cleanup(self) -> None:
        """앱 종료 시 명시적으로 호출 — QtWebEngine helper 프로세스가 좀비로 남지 않게.

        QWebEngineView/Page 가 GC 에 맡겨지면 Qt event loop 종료 후 정리되어
        WebEngine helper 가 떨어져나가는 일이 있다. closeEvent 에서 명시 정리.
        """
        try:
            if self._debug_view is not None:
                self._debug_view.close()
                self._debug_view.deleteLater()
                self._debug_view = None
        except Exception:
            pass
        self._end_submit()
        for job in list(self._jobs.values()):
            self._destroy(job)
        self._jobs.clear()
        self._destroy(self._ready)
        self._ready = None

    def showDebugView(self) -> None:
        job = self._ready
        if job is None and self._jobs:
            job = self._jobs[max(self._jobs)]   # 가장 최근에 시작한 로드
        if job is None:
            return
        if self._debug_view is None:
            self._debug_view = QWebEngineView()
            self._debug_view.setWindowTitle("[디버그] namu.wiki 직접 보기")
            self._debug_view.resize(1280, 900)
        if self._debug_view.page() != job.page:
            self._debug_view.setPage(job.page)
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

    def _resolve(self, s: str) -> tuple[QUrl, str, str]:
        """입력(제목/주소/파일 경로) → (QUrl, 제목, 주소 문자열)."""
        if s.lower().startswith(("file:", "http://", "https://")):
            return QUrl(s), self._title_from_path(s), s
        if s.startswith("/"):
            # namu.wiki 상대 경로 — 절대 URL 로 보정
            url = "https://namu.wiki" + s
            return QUrl(url), self._title_from_path(s), url
        try:
            from pathlib import Path as _P
            p = _P(s)
            if p.exists() and p.is_file():
                qurl = QUrl.fromLocalFile(str(p.resolve()))
                return qurl, p.name, qurl.toString()
        except Exception:
            pass
        # https:// 없이 입력한 웹 주소 (naver.com, www.google.com/search?q=…) — 알려진
        # 도메인 끝자리일 때만. "Node.js" 같은 문서 제목은 그대로 나무위키에서 찾는다.
        if _DOMAIN_INPUT_RE.match(s):
            url = "https://" + s
            return QUrl(url), self._title_from_path(url) or s, url
        # 나무위키 검색창과 같은 /Go 경로 — 띄어쓰기/대소문자가 달라도 문서를 찾아가고,
        # 없으면 검색 결과 페이지로 간다. (/w/제목 은 정확히 일치해야만 열림)
        url = f"https://namu.wiki/Go?q={quote(s, safe='')}"
        return QUrl(url), s, url

    def fetch(self, title_or_url: str) -> tuple[int, str]:
        """새 페이지(탭)에서 로드 시작. (요청 번호, 표시용 제목) 반환.

        진행 중인 다른 요청에는 영향이 없다 — 그만두려면 cancel(rid).
        """
        qurl, title, url = self._resolve(title_or_url.strip())
        job = self._new_job(title, url)
        job.page.load(qurl)
        return job.rid, title

    def cancel(self, rid: int) -> None:
        """진행 중인 요청을 취소 — 이후 그 요청의 시그널은 오지 않는다."""
        job = self._jobs.pop(rid, None)
        if job is not None:
            self._destroy(job)

    def _on_progress(self, rid: int, p: int) -> None:
        job = self._jobs.get(rid)
        # 100% 는 보내지 않는다 — 실패해도 100% 가 오므로 성공 여부는 loadFinished 로만 판단.
        # 로드가 끝난 뒤(실패 포함) 늦게 오는 진행률이 실패 문구를 덮지 않게 로딩 중에만.
        if job is not None and job.loading and p < 100:
            self.loadProgress.emit(rid, p)

    def _on_page_load_started(self, rid: int) -> None:
        job = self._jobs.get(rid)
        if job is None:
            return
        job.loading = True
        self.loadProgress.emit(rid, 0)

    def _on_loading_changed(self, rid: int, li) -> None:
        """로드 결과 판단 — loadFinished 는 오류 종류를 몰라서 이 신호로 한다.

        (loadFinished 가 이 신호보다 먼저 와서, 거기서는 404 와 접속 실패를 구분할 수 없음)
        """
        job = self._jobs.get(rid)
        if job is None:
            return
        S = QWebEngineLoadingInfo.LoadStatus
        st = li.status()
        if st == S.LoadStartedStatus:
            job.http_status = None
            return
        if st == S.LoadSucceededStatus:
            self._on_loaded(rid, True)
        elif st == S.LoadFailedStatus:
            if li.errorDomain() == QWebEngineLoadingInfo.ErrorDomain.HttpStatusCodeDomain:
                # 서버가 오류 코드로 응답했지만 안내 페이지는 왔음 (404 등) — 브라우저처럼 보여 줌
                job.http_status = li.errorCode()
                self._on_loaded(rid, True)
            elif li.errorCode() == -3:
                # ERR_ABORTED — 페이지가 다른 주소로 넘어가느라 앞 로드가 끊김. 새 로드를 기다림
                return
            else:
                self._on_loaded(rid, False, li.errorCode())
        # LoadStoppedStatus — 로드 중지(다른 로드로 대체 등). 결과는 이어지는 로드가 알려 줌

    def _on_loaded(self, rid: int, ok: bool, net_error: int | None = None) -> None:
        job = self._jobs.get(rid)
        if job is None:
            return
        job.net_error = net_error
        job.loading = False
        job.gen += 1   # 이전에 걸어 둔 추출 타이머는 무효
        if not ok:
            code = f" (오류 코드 {job.net_error})" if job.net_error else ""
            self._fail(job, f"페이지를 불러오지 못했습니다{code}")
            return
        self.pageLoaded.emit(rid)
        self._wait_ready(job, after_change=False)
        # 안전장치 — 준비 신호가 끝내 안 오면 그 상태로 추출해 보고, 안 되면 실패 처리
        if job.watchdog is None:
            job.watchdog = QTimer(self)
            job.watchdog.setSingleShot(True)
            job.watchdog.timeout.connect(lambda r=rid: self._on_watchdog(r))
        job.watchdog.start(self._watchdog_ms)

    def _wait_ready(self, job: _Job, after_change: bool) -> None:
        """페이지 안에 준비 감시를 건다 — 준비되는 순간 _on_ready 가 불린다."""
        host = (QUrl(job.url).host() or "").lower()
        need_h1 = host == "namu.wiki" or host.endswith(".namu.wiki")
        js = _WAIT_JS % (json.dumps(f"{_READY_TAG}{job.gen}"),
                         "true" if need_h1 else "false",
                         "true" if after_change else "false")
        job.page.runJavaScript(js)

    def _on_ready(self, rid: int, gen: int) -> None:
        job = self._jobs.get(rid)
        if job is None or gen != job.gen or job.loading:
            return
        self._run_extract(rid, gen)

    def _on_watchdog(self, rid: int) -> None:
        job = self._jobs.get(rid)
        if job is None or job.loading:
            return
        job.attempts = self._max_attempts - 1   # 마지막 한 번만 시도하고 안 되면 실패
        self._run_extract(rid, job.gen)

    def _run_extract(self, rid: int, gen: int) -> None:
        job = self._jobs.get(rid)
        if job is None or gen != job.gen or job.loading:
            return
        job.attempts += 1
        job.page.runJavaScript(
            _EXTRACT_JS, lambda res, r=rid, g=gen: self._on_extracted(r, g, res)
        )

    def _fail(self, job: _Job, msg: str, info: dict | None = None) -> None:
        self._jobs.pop(job.rid, None)
        if info is not None:
            self.diagnostics.emit(job.rid, info)
        self.fetchFailed.emit(job.rid, job.title, msg)
        self._destroy(job)

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

    @staticmethod
    def _doc_from(info: dict, job: _Job) -> dict:
        return {
            "tokens": info.get("tokens") or [],
            "styles": info.get("styles") or [],
            "anchors": info.get("anchors") or {},
            "pageW": int(info.get("pageW") or 1280),
            "pageH": int(info.get("pageH") or 800),
            # 이 문서를 렌더링한 폭 — 창 크기와 다르면 다시 배치 대상
            "renderW": job.view.width(),
            # 서버가 오류 코드(404 등)로 응답한 페이지면 그 코드 — 상태 표시줄에 알림
            "httpStatus": job.http_status,
        }

    def _on_extracted(self, rid: int, gen: int, result) -> None:
        job = self._jobs.get(rid)
        if job is None or gen != job.gen:
            return
        info = self._parse_result(result)
        ok = bool(info.get("ok"))
        tokens = info.get("tokens") or []

        # 본문이 iframe 안에 있는 사이트 — 바깥 페이지 글자가 거의 없으면 그 iframe 을 직접 연다
        frame = info.get("frame")
        if (ok and frame and job.frame_hops < 2 and frame != job.url
                and int(info.get("textLen") or 0) < 200):
            job.frame_hops += 1
            job.attempts = 0
            job.url = frame
            job.page.load(QUrl(frame))   # loadFinished → 준비 감시 → 추출 (같은 흐름)
            return

        if ok and tokens:
            url = info.get("url") or job.url
            job.title = self._page_title(info.get("title", ""), url, job.title)
            job.url = url
            doc = self._doc_from(info, job)
            # 이 페이지를 다시 배치용으로 남기고, 전에 남겨 둔 페이지는 정리
            self._jobs.pop(rid, None)
            if job.watchdog is not None:
                job.watchdog.stop()
            old, self._ready = self._ready, job
            self._relayout_gen += 1   # 이전 페이지에 걸린 다시 배치는 무효
            self._destroy(old)
            self.bodyExtracted.emit(rid, job.title, doc, job.url)
            return

        if job.attempts < self._max_attempts:
            # 아직 본문이 덜 그려짐 — 다음 DOM 변화가 오면 다시 시도
            self._wait_ready(job, after_change=True)
            return

        self._fail(job, "본문을 찾지 못했습니다 (selector 미스)", info)
