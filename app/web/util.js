/* Session Canvas — small helpers (no dependencies). */
'use strict';
window.SC = window.SC || {};
(function (SC) {
  const U = {};
  SC.U = U;

  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const pad = n => (n < 10 ? '0' : '') + n;

  U.esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  U.clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  U.lerp = (a, b, t) => a + (b - a) * t;

  // ---- dates (always the Mac's local time) ----
  U.dayKey = ms => { const d = new Date(ms); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
  U.startOfDay = ms => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };
  U.addDays = (ms, n) => { const d = new Date(ms); d.setDate(d.getDate() + n); return d.getTime(); };
  U.weekStart = ms => { const d = new Date(ms); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.getTime(); };
  U.fmtDay = ms => { const d = new Date(ms); return DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()]; };
  U.fmtDayShort = ms => { const d = new Date(ms); return DAYS[d.getDay()] + ' ' + d.getDate(); };
  U.fmtDate = ms => { const d = new Date(ms); return d.getDate() + ' ' + MONTHS[d.getMonth()]; };
  U.fmtDateYear = ms => { const d = new Date(ms); return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear(); };
  U.fmtTime = ms => { const d = new Date(ms); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  U.fmtDateTime = ms => U.fmtDay(ms) + ' · ' + U.fmtTime(ms);
  U.isWeekend = ms => { const g = new Date(ms).getDay(); return g === 0 || g === 6; };
  U.dateInputValue = ms => U.dayKey(ms);
  U.parseDateInput = v => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || ''); return m ? new Date(+m[1], +m[2] - 1, +m[3]).getTime() : null; };
  U.fmtDuration = ms => {
    const min = Math.round(ms / 60000);
    if (min < 1) return 'under a minute';
    if (min < 60) return min + ' min';
    const h = Math.floor(min / 60), m = min % 60;
    if (h < 24) return h + ' h' + (m ? ' ' + m + ' min' : '');
    const d = Math.floor(h / 24);
    return d + (d === 1 ? ' day' : ' days') + (h % 24 ? ' ' + (h % 24) + ' h' : '');
  };
  U.ago = ms => {
    const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 5) return 'just now';
    if (s < 60) return s + ' s ago';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' d ago';
  };

  // ---- colours ----
  U.hash = str => { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
  const hexToRgb = hex => {
    let h = hex.replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  U.hexToRgb = hexToRgb;
  U.mix = (a, b, t) => {
    const A = hexToRgb(a), B = hexToRgb(b);
    const c = i => Math.round(A[i] + (B[i] - A[i]) * t);
    return '#' + ((1 << 24) + (c(0) << 16) + (c(1) << 8) + c(2)).toString(16).slice(1);
  };
  U.rgba = (hex, a) => { const c = hexToRgb(hex); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; };
  U.isHex = s => typeof s === 'string' && /^#[0-9a-fA-F]{6}$/.test(s);

  // ---- text ----
  U.norm = s => String(s == null ? '' : s).toLowerCase().normalize('NFD').replace(/\p{M}+/gu, '');
  U.words = s => U.norm(s).split(/[^a-z0-9]+/).filter(w => w.length > 1);
  U.short = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
  U.homePath = (p, home) => (home && p && p.indexOf(home) === 0) ? '~' + p.slice(home.length) : (p || '');

  /* True when a and b are at most k edits apart (insert, delete, replace, swap of neighbours). */
  U.within = (a, b, k) => {
    const la = a.length, lb = b.length;
    if (Math.abs(la - lb) > k) return false;
    if (a === b) return true;
    let prev2 = null, prev = new Array(lb + 1), cur = new Array(lb + 1);
    for (let j = 0; j <= lb; j++) prev[j] = j;
    for (let i = 1; i <= la; i++) {
      cur[0] = i;
      let rowMin = cur[0];
      const ca = a.charCodeAt(i - 1);
      for (let j = 1; j <= lb; j++) {
        const cost = ca === b.charCodeAt(j - 1) ? 0 : 1;
        let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (prev2 && i > 1 && j > 1 && ca === b.charCodeAt(j - 2) && a.charCodeAt(i - 2) === b.charCodeAt(j - 1)) v = Math.min(v, prev2[j - 2] + 1);
        cur[j] = v;
        if (v < rowMin) rowMin = v;
      }
      if (rowMin > k) return false;
      prev2 = prev; prev = cur; cur = new Array(lb + 1);
    }
    return prev[lb] <= k;
  };

  /* Does word w start with something close to the typed token t? (typo-tolerant prefix match) */
  U.fuzzyPrefix = (t, w) => {
    const k = t.length >= 8 ? 2 : 1;
    if (w.length < t.length - k) return false;
    if (w[0] !== t[0] && w[1] !== t[1] && w[0] !== t[1]) return false;
    for (let L = t.length - 1; L <= t.length + 1; L++) {
      if (L < 2 || L > w.length) continue;
      if (U.within(t, w.slice(0, L), k)) return true;
    }
    return false;
  };

  /* Sticky-note formatting: # heading, - bullets, [ ] / [x] boxes, **bold**, *italic*, `code`, links. Output is safe HTML. */
  U.mdLite = text => {
    const inline = raw => {
      let s = U.esc(raw);
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
      s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,!?:;]|$)/g, '$1<i>$2</i>');
      s = s.replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s).,!?:;]|$)/g, '$1<i>$2</i>');
      s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
      return s;
    };
    const out = [];
    const lines = String(text || '').split('\n');
    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      let m;
      if ((m = /^\s*#{1,3}\s+(.*)$/.exec(ln))) out.push('<div class="md-h">' + inline(m[1]) + '</div>');
      else if ((m = /^\s*(?:[-*]\s+)?\[( |x|X)\]\s+(.*)$/.exec(ln))) out.push('<div class="md-li md-box' + (m[1] !== ' ' ? ' done' : '') + '" data-line="' + i + '"><span class="box">' + (m[1] !== ' ' ? '✓' : '') + '</span><span>' + inline(m[2]) + '</span></div>');
      else if ((m = /^\s*[-*•]\s+(.*)$/.exec(ln))) out.push('<div class="md-li"><span class="dot">•</span><span>' + inline(m[1]) + '</span></div>');
      else if (!ln.trim()) out.push('<div class="md-gap"></div>');
      else out.push('<div>' + inline(ln) + '</div>');
    }
    return out.join('');
  };

  /* Break text into lines that fit maxWidth (canvas measuring); the last line gets an ellipsis when cut. */
  U.wrapText = (ctx, text, maxWidth, maxLines) => {
    const words = String(text || '').split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    const fitWord = w => {                       // a single word wider than the line: cut it
      if (ctx.measureText(w).width <= maxWidth) return w;
      let lo = 1, hi = w.length;
      while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (ctx.measureText(w.slice(0, mid) + '…').width <= maxWidth) lo = mid; else hi = mid - 1; }
      return w.slice(0, lo) + '…';
    };
    for (let i = 0; i < words.length; i++) {
      const w = words[i];
      const test = line ? line + ' ' + w : w;
      if (ctx.measureText(test).width <= maxWidth) { line = test; continue; }
      if (lines.length === maxLines - 1) {       // no room for another line: finish this one with "…"
        let cut = line ? line + ' ' + w : w;
        while (cut.length > 1 && ctx.measureText(cut + '…').width > maxWidth) cut = cut.slice(0, -1);
        lines.push(cut.trimEnd() + '…');
        return lines;
      }
      if (line) lines.push(line);
      line = fitWord(w);
    }
    if (line) lines.push(line);
    return lines;
  };

  U.fitText = (ctx, text, maxWidth) => {
    text = String(text || '');
    if (ctx.measureText(text).width <= maxWidth) return text;
    let lo = 0, hi = text.length;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (ctx.measureText(text.slice(0, mid) + '…').width <= maxWidth) lo = mid; else hi = mid - 1; }
    return lo > 0 ? text.slice(0, lo).trimEnd() + '…' : '';
  };

  U.debounce = (fn, ms) => { let t = 0; const d = function () { const a = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, a), ms); }; d.cancel = () => clearTimeout(t); return d; };
  U.uid = p => (p || '') + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  U.clone = o => JSON.parse(JSON.stringify(o));
  U.easeOut = t => 1 - Math.pow(1 - t, 3);

  U.copy = async text => {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall through */ }
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch (e) { return false; }
  };
})(window.SC);
