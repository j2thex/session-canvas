/* Session Canvas — drawing: the camera, the cards, the links, the timeline and week headers, the minimap. */
'use strict';
(function (SC) {
  const U = SC.U, L = SC.Layout, CARD = L.CARD;

  SC.THEMES = {
    dark: { bg: '#0d1117', dot: '#222b39', surface: '#171e2a', text: '#e9eef6', muted: '#93a0b4', faint: '#657287', border: '#2c3747',
      sel: '#ffffff', match: '#ffd84d', lane: 'rgba(255,255,255,0.028)', laneAlt: 'rgba(255,255,255,0.012)', weekend: 'rgba(0,0,0,0.22)',
      today: '#ff5d73', todayFill: 'rgba(255,93,115,0.07)', header: 'rgba(13,17,23,0.90)', line: 'rgba(255,255,255,0.07)', lineStrong: 'rgba(255,255,255,0.16)',
      pill: 'rgba(30,38,52,0.94)', mapBg: 'rgba(13,17,23,0.6)', mapView: '#ffffff' },
    light: { bg: '#f4f6fa', dot: '#d3dae5', surface: '#ffffff', text: '#18202e', muted: '#566375', faint: '#8f9bae', border: '#cfd7e3',
      sel: '#0f172a', match: '#e59a00', lane: 'rgba(20,40,80,0.035)', laneAlt: 'rgba(20,40,80,0.012)', weekend: 'rgba(20,40,80,0.05)',
      today: '#e11d48', todayFill: 'rgba(225,29,72,0.06)', header: 'rgba(244,246,250,0.93)', line: 'rgba(15,30,60,0.08)', lineStrong: 'rgba(15,30,60,0.2)',
      pill: 'rgba(255,255,255,0.95)', mapBg: 'rgba(255,255,255,0.6)', mapView: '#0f172a' },
  };
  SC.PALETTE = ['#4f8cff', '#ff8a3d', '#2fc98a', '#f25f7a', '#a970ff', '#19c2d1', '#f2c230', '#ff6fb5', '#7c8cff', '#8bd346', '#ff7d66', '#3fb6ff'];
  SC.KIND_COLOR = { you: '#4f8cff', helper: '#a970ff', auto: '#19c2d1', desktop: '#ff8a3d' };
  SC.EDGE_COLOR = { continued: '#2fc98a', fork: '#a970ff', handover: '#ff8a3d', helper: '#7d9cc4', worktree: '#b08968', manual: '#ff6fb5' };
  SC.NOTE_HEX = { yellow: '#ffe37a', pink: '#ffa9d0', green: '#a5eba3', blue: '#a4d6ff', purple: '#cfb2ff', orange: '#ffc07a' };

  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
  const F_TITLE = '600 13px ' + FONT, F_META = '11px ' + FONT, F_CHIP = '600 10.5px ' + FONT, F_FOOT = '10.5px ' + FONT,
    F_KIND = '700 9px ' + FONT, F_BIG1 = '700 20px ' + FONT, F_BIG2 = '700 28px ' + FONT, F_BIG3 = '500 17px ' + FONT, F_UI = '600 12px ' + FONT, F_UIS = '11px ' + FONT, F_UIB = '700 12px ' + FONT;
  const F_ZONE = '700 21px ' + FONT, F_ZHINT = '500 13.5px ' + FONT, F_ZCOUNT = '800 24px ' + FONT;
  const ZONE_WORLD_Z = 0.5;
  const TOP = 52, STATUS = 24, PANEL_W = 404, TL_HEAD = 46;
  const ZMIN = 0.035, ZMAX = 2.5;
  const LOD_FULL = 0.55, LOD_TITLE = 0.24;      // zoom levels: full card / big title only / coloured block

  const canvas = document.getElementById('board');
  const ctx = canvas.getContext('2d', { alpha: false });
  const mini = document.getElementById('minimap');
  const mctx = mini.getContext('2d');
  const measure = document.createElement('canvas').getContext('2d');
  const notesEl = document.getElementById('notes');

  SC.canvas = canvas;
  SC.cam = { x: 0, y: 0, z: 1 };
  SC.vw = 0; SC.vh = 0; SC.dpr = 1;
  SC.ui = SC.ui || { sel: null, hover: null, focus: null, family: null, drag: null, linking: null, panelOpen: false };
  SC.drawList = [];
  SC.edgeGeom = [];
  SC.perf = { last: 0, avg: 0, max: 0, frames: 0 };
  let theme = SC.THEMES.dark, themeName = 'dark';
  let raf = 0, camAnim = null, textSerial = 1, colorSerial = 1;

  SC.setTheme = function (name) {
    themeName = name === 'light' ? 'light' : 'dark';
    theme = SC.THEMES[themeName];
    document.documentElement.setAttribute('data-theme', themeName);
    colorSerial++;
    SC.requestRender();
  };
  SC.themeName = () => themeName;
  /* Card text changed (title, label, keywords) / only colours changed. */
  SC.reprep = function () { textSerial++; colorSerial++; SC.requestRender(); if (SC.warmup) SC.warmup(); };
  SC.recolor = function () { colorSerial++; SC.requestRender(); };

  SC.resize = function () {
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    const w = window.innerWidth, h = window.innerHeight;
    SC.vw = w; SC.vh = h; SC.dpr = dpr;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    mini.width = Math.round(220 * dpr);
    mini.height = Math.round(140 * dpr);
    SC.requestRender();
  };

  SC.requestRender = function () { if (!raf) raf = requestAnimationFrame(frame); };

  // ---- camera ----
  SC.viewRect = function () {
    const head = SC.state.view.layout === 'timeline' ? TL_HEAD : 0;
    const y = TOP + head;
    const left = SC.ui.waitOpen ? 338 : 0;             // the open "Your turn" list covers the left edge
    return { x: left, y: y, w: Math.max(200, SC.vw - left - (SC.ui.panelOpen ? PANEL_W : 0)), h: Math.max(120, SC.vh - y - STATUS) };
  };
  SC.toWorld = (sx, sy) => ({ x: SC.cam.x + sx / SC.cam.z, y: SC.cam.y + sy / SC.cam.z });
  SC.toScreen = (wx, wy) => ({ x: (wx - SC.cam.x) * SC.cam.z, y: (wy - SC.cam.y) * SC.cam.z });
  const camChanged = U.debounce(() => {
    const c = SC.cam;
    SC.state.view.cams[SC.state.view.layout] = { x: Math.round(c.x * 10) / 10, y: Math.round(c.y * 10) / 10, z: Math.round(c.z * 1000) / 1000 };
    SC.touch('view');
  }, 600);
  SC.camTouched = function () { camChanged(); SC.requestRender(); };
  SC.zoomAt = function (sx, sy, factor) {
    const c = SC.cam;
    const z = U.clamp(c.z * factor, ZMIN, ZMAX);
    if (z === c.z) return;
    const wx = c.x + sx / c.z, wy = c.y + sy / c.z;
    c.z = z;
    c.x = wx - sx / z;
    c.y = wy - sy / z;
    camAnim = null;
    SC.camTouched();
  };
  SC.setCam = function (x, y, z, animate) {
    z = U.clamp(z, ZMIN, ZMAX);
    if (animate === false) {
      camAnim = null;
      SC.cam.x = x; SC.cam.y = y; SC.cam.z = z;
    } else {
      camAnim = { t0: performance.now(), dur: 300, from: { x: SC.cam.x, y: SC.cam.y, z: SC.cam.z }, to: { x: x, y: y, z: z } };
    }
    SC.camTouched();
  };
  SC.fitBounds = function (b, opts) {
    opts = opts || {};
    const r = SC.viewRect(), pad = opts.pad === undefined ? 56 : opts.pad;
    const padL = pad + (opts.padL || 0);                 // extra room on the left for week / lane names
    const bw = Math.max(40, b.x1 - b.x0), bh = Math.max(40, b.y1 - b.y0);
    const z = U.clamp(Math.min((r.w - pad - padL) / bw, (r.h - pad * 2) / bh), ZMIN, opts.maxZ || 1.1);
    const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
    SC.setCam(cx - (r.x + padL + (r.w - pad - padL) / 2) / z, cy - (r.y + r.h / 2) / z, z, opts.animate);
  };
  SC.fitAll = function (animate) {
    const b = Object.assign({}, SC.lay.bounds);
    if (SC.lay.type === 'timeline') { b.x0 = 0; b.y0 = 0; b.x1 = Math.max(b.x1, SC.lay.width); b.y1 = Math.max(b.y1, SC.lay.height); }
    if (SC.lay.type === 'status') { b.x0 = -10; b.y0 = -54; b.x1 = SC.lay.width + 34; b.y1 = SC.lay.height + 10; }
    for (const note of SC.state.notes) {
      const xy = SC.noteXY.get(note.id);
      if (!xy) continue;
      b.x0 = Math.min(b.x0, xy.x); b.y0 = Math.min(b.y0, xy.y); b.x1 = Math.max(b.x1, xy.x + note.w); b.y1 = Math.max(b.y1, xy.y + note.h);
    }
    SC.fitBounds(b, { animate: animate, padL: SC.lay.type === 'free' || SC.lay.type === 'status' ? 0 : 200, pad: SC.lay.type === 'status' ? 28 : undefined });
  };
  SC.centerOn = function (n, opts) {
    opts = opts || {};
    const r = SC.viewRect();
    let z = SC.cam.z;
    if (opts.minZ && z < opts.minZ) z = opts.minZ;
    if (opts.z) z = opts.z;
    SC.setCam(n.x + n.w / 2 - (r.x + r.w / 2) / z, n.y + n.h / 2 - (r.y + r.h / 2) / z, z, opts.animate);
  };
  /* Pan just enough to bring a card fully into view. */
  SC.reveal = function (n) {
    const r = SC.viewRect(), c = SC.cam, m = 30 / c.z;
    let x = c.x, y = c.y;
    const left = c.x + r.x / c.z, top = c.y + r.y / c.z, right = left + r.w / c.z, bottom = top + r.h / c.z;
    if (n.x - m < left) x -= left - (n.x - m); else if (n.x + n.w + m > right) x += n.x + n.w + m - right;
    if (n.y - m < top) y -= top - (n.y - m); else if (n.y + n.h + m > bottom) y += n.y + n.h + m - bottom;
    if (x !== c.x || y !== c.y) SC.setCam(x, y, c.z);
  };
  /* The opening view of a layout: readable cards, newest work in sight. */
  SC.homeView = function (animate) {
    const lay = SC.lay, r = SC.viewRect();
    if (lay.type === 'status') { SC.fitAll(animate); return; }      // the whole board at a glance
    if (lay.type === 'timeline') {
      const z = 0.72;
      const day = lay.dayAt && lay.dayAt.get(lay.today);
      const right = day ? day.x1 : lay.width;
      SC.setCam(Math.max(-40 / z, right + 36 - (r.x + r.w) / z), -(r.y + 14) / z, z, animate);
    } else {
      const z = 0.75, b = lay.bounds;
      SC.setCam(b.x0 - 36 / z, b.y0 - (r.y + 70) / z, z, animate);
    }
  };

  // ---- colours and text of one card (cached until something changes) ----
  SC.accentOf = function (s) {
    const custom = SC.state.colors[s.id];
    if (U.isHex(custom)) return custom;
    const by = SC.state.view.colorBy, d = SC.data;
    if (by === 'kind') return SC.KIND_COLOR[s.kind] || SC.PALETTE[0];
    if (by === 'project') return SC.PALETTE[(d.projRank.get(s.project) || 0) % SC.PALETTE.length];
    const i = Math.max(0, d.weeks.indexOf(s.week));
    return SC.PALETTE[(i * 5) % SC.PALETTE.length];
  };
  SC.projectColor = s => SC.PALETTE[(SC.data.projRank.get(s.project) || 0) % SC.PALETTE.length];
  SC.chipColors = function (word) {
    const h = U.hash(U.norm(word)) % 360;
    return themeName === 'dark'
      ? { bg: 'hsl(' + h + ' 42% 24%)', fg: 'hsl(' + h + ' 85% 84%)' }
      : { bg: 'hsl(' + h + ' 72% 90%)', fg: 'hsl(' + h + ' 62% 27%)' };
  };

  // ---- measuring text is the slow part of drawing, so widths are remembered per word ----
  const widths = new Map();
  let measureFont = '';
  function setMeasureFont(font) { if (measureFont !== font) { measure.font = font; measureFont = font; } }
  function tw(font, text) {
    let m = widths.get(font);
    if (!m) widths.set(font, m = new Map());
    let w = m.get(text);
    if (w === undefined) {
      setMeasureFont(font);
      w = measure.measureText(text).width;
      if (m.size > 30000) m.clear();
      m.set(text, w);
    }
    return w;
  }
  function fit(font, text, maxW) {
    setMeasureFont(font);
    return U.fitText(measure, text, maxW);
  }
  function wrap(font, text, maxW, maxLines) {
    const words = String(text || '').split(/\s+/).filter(Boolean);
    const space = tw(font, ' ');
    const lines = [];
    let line = '', lw = 0;
    for (let i = 0; i < words.length; i++) {
      let w = words[i], ww = tw(font, w);
      if (ww > maxW) { w = fit(font, w, maxW); ww = maxW; }
      if (!line) { line = w; lw = ww; continue; }
      if (lw + space + ww <= maxW) { line += ' ' + w; lw += space + ww; continue; }
      if (lines.length === maxLines - 1) { lines.push(fit(font, line + ' ' + words.slice(i).join(' '), maxW)); return lines; }
      lines.push(line);
      line = w; lw = ww;
    }
    if (line) lines.push(line);
    return lines;
  }

  const chipCache = new Map();
  function chipColor(word) {
    const key = themeName + '|' + word;
    let c = chipCache.get(key);
    if (!c) { if (chipCache.size > 6000) chipCache.clear(); chipCache.set(key, c = SC.chipColors(word)); }
    return c;
  }

  /* Colours of a card: cheap, needed at every zoom level. */
  function prepColors(n) {
    const s = n.s, T = theme, dark = themeName === 'dark';
    const st = n.st || SC.stateOf(s), byState = SC.lay.type === 'status' && st.info;
    const accent = byState ? st.info.color : SC.accentOf(s);      // in the Status layout the colour IS the state
    const old = n.prep;
    const p = (old && old.text === textSerial) ? old : { text: textSerial, big: false, full: false };
    p.colors = colorSerial;
    p.accent = accent;
    p.bg = U.mix(T.surface, accent, dark ? 0.2 : 0.12);
    p.block = U.mix(T.surface, accent, dark ? 0.64 : 0.56);
    p.border = U.mix(T.surface, accent, dark ? 0.56 : 0.46);
    p.stripe = byState ? st.info.color : SC.projectColor(s);
    p.st = st;
    if (byState && st.key === 'replaced') { p.bg = U.mix(T.surface, accent, 0.08); p.block = U.mix(T.surface, accent, 0.3); p.border = U.mix(T.surface, accent, 0.3); }
    else if (byState && st.key === 'done') { p.bg = U.mix(T.surface, accent, dark ? 0.12 : 0.08); p.block = U.mix(T.surface, accent, dark ? 0.42 : 0.4); p.border = U.mix(T.surface, accent, 0.36); }
    p.kindColor = SC.KIND_COLOR[s.kind] || T.muted;
    n.prep = p;
    return p;
  }
  /* Large title used when zoomed out. */
  function prepBig(n) {
    const p = n.prep, title = SC.titleOf(n.s);
    const room = n.w - 26 - (p.st && p.st.key ? 30 : 0);          // the state badge sits in the top right corner
    p.tb1 = wrap(F_BIG1, title, room, n.compact ? 2 : 4);
    p.tb2 = wrap(F_BIG2, title, room, n.compact ? 2 : 3);
    p.day = U.fmtDay(n.s.start) + ' · ' + n.s.msgs + ' msgs';
    p.big = true;
  }
  /* Everything written on a card at reading size: title, date line, chips, footer. */
  function prepFull(n) {
    const s = n.s, p = n.prep;
    const padL = 15, padR = 10, innerW = n.w - padL - padR;
    const title = SC.titleOf(s);
    p.kindText = (s.run === 'guide' ? 'GUIDE' : SC.KIND_ONE[s.kind] || '').toUpperCase();
    p.tl = wrap(F_TITLE, title, innerW - (p.st.key ? 20 : 0) - (s.active && p.st.key !== 'running' ? 14 : 0), n.compact ? 1 : 2);
    p.meta = fit(F_META, U.fmtDay(s.start) + ' · ' + U.fmtTime(s.start) + ' · ' + s.msgs + (s.msgs === 1 ? ' msg' : ' msgs'), innerW - tw(F_KIND, p.kindText) - 8);
    // the latest: a status pill (helper report) + what it finished / what waits on you, two lines at most
    const latest = SC.latestOf(s), stInfo = SC.STATES[latest.status];
    p.stLabel = ''; p.stl = [];
    if (!n.compact && latest.text) {
      let lead = 0;
      if (stInfo) { p.stLabel = stInfo.label; p.stColor = stInfo.color; p.stInk = stInfo.ink; p.stW = Math.ceil(tw(F_KIND, stInfo.label)) + 10; lead = p.stW + 5; }
      const words = latest.text.split(/\s+/).filter(Boolean);
      const l1 = wrap(F_META, latest.text, innerW - lead, 2);
      if (l1.length < 2) p.stl = l1;
      else p.stl = [l1[0]].concat(wrap(F_META, words.slice(l1[0].split(' ').length).join(' '), innerW, 1));
    }
    const hasSt = p.stl.length > 0;
    // under a one-line title: what was asked (the outcome is on the status lines)
    p.about = (!n.compact && p.tl.length === 1 && s.about) ? fit(F_META, hasSt && s.about.indexOf(' → ') > 0 ? s.about.split(' → ')[0] : s.about.replace(/^.*?→ /, ''), innerW) : '';
    // chips: your label, commands, keywords, one Jira key
    const items = [];
    const label = SC.state.labels[s.id];
    if (label) items.push({ text: label, style: 'label' });
    for (const c of s.commands.slice(0, n.compact ? 1 : 2)) items.push({ text: c.replace(/^\/[^:]+:/, '/'), style: 'cmd' });
    for (const k of s.keywords) items.push({ text: k, style: 'kw' });
    if (s.jira.length) items.splice(Math.min(items.length, label ? 4 : 3), 0, { text: s.jira[0], style: 'jira' });
    const chips = [];
    const maxRows = n.compact || hasSt ? 1 : 2, rowY = n.compact ? 47 : (hasSt ? 88 : 65);
    let x = padL, row = 0;
    for (const it of items) {
      let text = it.text, w = Math.ceil(tw(F_CHIP, text)) + 14;
      if (w > innerW) { text = fit(F_CHIP, text, innerW - 16); w = Math.ceil(tw(F_CHIP, text)) + 14; }
      if (x + w > n.w - padR) {
        if (row + 1 >= maxRows) continue;                 // try the next (maybe shorter) chip on this row
        row++; x = padL;
      }
      chips.push({ text: text, word: it.text, x: x, y: rowY + row * 21, w: w, style: it.style });
      x += w + 5;
    }
    p.chips = chips;
    const foot = (s.worktree ? '⑂ ' + s.worktree : s.projectLabel) + (s.model ? ' · ' + s.model : '') + (s.subagents ? ' · ' + s.subagents + ' sub-agents' : '');
    p.footer = n.compact ? '' : fit(F_FOOT, foot, innerW - 54);
    p.full = true;
  }
  function ready(n, lod) {
    let p = n.prep;
    if (!p || p.text !== textSerial || p.colors !== colorSerial) p = prepColors(n);
    if (lod === 2) { if (!p.full) prepFull(n); } else if (lod === 1) { if (!p.big) prepBig(n); }
    return p;
  }
  SC.prepNode = n => ready(n, 2);

  /* Get every card ready in small slices while the Mac is idle, so zooming never has to wait. */
  let warmTimer = 0;
  SC.warmup = function () {
    clearTimeout(warmTimer);
    const list = SC.lay.shown.slice();
    let i = 0;
    const ts = textSerial;
    const step = () => {
      if (ts !== textSerial) return;
      const t0 = performance.now();
      while (i < list.length && performance.now() - t0 < 7) {
        const n = list[i++];
        const p = ready(n, 2);
        if (!p.big) prepBig(n);
      }
      if (i < list.length) warmTimer = setTimeout(step, 24);
    };
    warmTimer = setTimeout(step, 300);
  };

  function rr(c, x, y, w, h, r) {
    c.beginPath();
    if (c.roundRect) { c.roundRect(x, y, w, h, r); return; }
    const q = Math.min(typeof r === 'number' ? r : r[0], w / 2, h / 2);
    c.moveTo(x + q, y); c.arcTo(x + w, y, x + w, y + h, q); c.arcTo(x + w, y + h, x, y + h, q); c.arcTo(x, y + h, x, y, q); c.arcTo(x, y, x + w, y, q); c.closePath();
  }

  /* How strongly a card is shown: dimmed when it is not a search match / not in the focused family. */
  function alphaOf(n) {
    const ui = SC.ui, S = SC.search;
    let a = 1;
    if (S.tokens.length && !S.matches.has(n.id)) a = 0.16;
    if (ui.family && !ui.family.has(n.id)) a = Math.min(a, 0.13);
    if (n.hiddenShown) a = Math.min(a, 0.45);
    if (n.st && n.st.key === 'replaced' && !(ui.sel && ui.sel.type === 'node' && ui.sel.id === n.id) && ui.hover !== n.id) a = Math.min(a, 0.5);
    return a;
  }
  SC.alphaOf = alphaOf;

  function toggleRect(n) { return { x: n.x + n.w - 50, y: n.y + n.h - 24, w: 42, h: 17 }; }
  SC.toggleRect = toggleRect;
  SC.kidCount = id => ((SC.lay.fam && SC.lay.fam.children.get(id)) || []).length;

  // ---- one frame ----
  function frame(now) {
    raf = 0;
    const t0 = performance.now();
    let again = false;
    if (camAnim) {
      const k = Math.min(1, (now - camAnim.t0) / camAnim.dur), e = U.easeOut(Math.max(0, k));
      const a = camAnim.from, b = camAnim.to;
      // zoom changes multiply, so blend it in log space: steady on screen
      const z = Math.exp(U.lerp(Math.log(a.z), Math.log(b.z), e));
      SC.cam.z = z;
      SC.cam.x = U.lerp(a.x, b.x, e);
      SC.cam.y = U.lerp(a.y, b.y, e);
      if (k >= 1) { camAnim = null; SC.cam.x = b.x; SC.cam.y = b.y; SC.cam.z = b.z; } else again = true;
    }
    let ak = 1;
    if (SC.anim) {
      ak = U.easeOut(Math.min(1, Math.max(0, (now - SC.anim.t0) / SC.anim.dur)));
      if (now - SC.anim.t0 >= SC.anim.dur) { SC.anim = null; ak = 1; } else again = true;
    }
    spinWanted = false; pulseWanted = false;
    draw(ak);
    const dt = performance.now() - t0;
    const P = SC.perf;
    P.last = dt; P.frames++; P.avg = P.avg ? P.avg * 0.9 + dt * 0.1 : dt; if (dt > P.max) P.max = dt;
    if (SC.hooks.frame) SC.hooks.frame();
    if (again) SC.requestRender();
  }

  function draw(ak) {
    const T = theme, cam = SC.cam, z = cam.z, dpr = SC.dpr, vw = SC.vw, vh = SC.vh, lay = SC.lay, ui = SC.ui;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = T.bg;
    ctx.fillRect(0, 0, vw, vh);
    drawDots(z);

    const s = dpr * z;
    ctx.setTransform(s, 0, 0, s, -cam.x * s, -cam.y * s);
    const vx0 = cam.x, vy0 = cam.y, vx1 = cam.x + vw / z, vy1 = cam.y + vh / z;

    if (lay.type === 'timeline') drawTimelineBack(vx0, vy0, vx1, vy1, z);
    else if (lay.type === 'tree') drawBandsBack(vx0, vy0, vx1, vy1, z);
    else if (lay.type === 'status') drawZonesBack(vx0, vy0, vx1, vy1, z);

    // where each card is right now (cards slide when the layout changes)
    const list = SC.drawList;
    list.length = 0;
    let top = null, topSel = null;
    const selId = ui.sel && ui.sel.type === 'node' ? ui.sel.id : null;
    for (const n of lay.shown) {
      let x = n.x, y = n.y;
      if (ak < 1 && (n.ox || n.oy)) { x += n.ox * (1 - ak); y += n.oy * (1 - ak); }
      n.rx = x; n.ry = y;
      n.a = alphaOf(n) * (n.fresh && ak < 1 ? ak : 1);
      if (x > vx1 || y > vy1 || x + n.w < vx0 || y + n.h < vy0) { n.on = false; continue; }
      n.on = true;
      if (n.dragging) top = n; else if (n.id === selId) topSel = n; else list.push(n);
    }
    if (topSel) list.push(topSel);                 // the selected card, then the one being dragged, lie above their neighbours
    if (top) list.push(top);

    if (SC.state.view.showEdges !== false) drawEdges(vx0, vy0, vx1, vy1, z);
    drawNoteWires(z);
    drawCards(list, z);
    drawMarks(list, z);
    if (ui.drag && ui.drag.type === 'link') drawRubber(z);
    if (lay.type === 'free' && lay.inbox) drawInboxLabel(z);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    if (lay.type === 'timeline') drawTimelineHead(z);
    else if (lay.type === 'tree') drawBandLabels(z);
    else if (lay.type === 'status') drawZoneLabels(z);

    notesEl.style.transform = 'translate(' + (-cam.x * z) + 'px,' + (-cam.y * z) + 'px) scale(' + z + ')';
    drawMinimap();
  }

  function drawDots(z) {
    if (z < 0.14) return;
    const T = theme, cam = SC.cam;
    let step = 40;
    while (step * z < 22) step *= 2;
    const sx = step * z;
    const ox = ((-cam.x * z) % sx + sx) % sx, oy = ((-cam.y * z) % sx + sx) % sx;
    ctx.fillStyle = T.dot;
    ctx.beginPath();
    const r = z > 0.9 ? 1.5 : 1.2;
    for (let x = ox; x < SC.vw; x += sx) for (let y = oy; y < SC.vh; y += sx) ctx.rect(x - r / 2, y - r / 2, r, r);
    ctx.fill();
  }

  // ---- links between sessions ----
  function anchors(a, b, treeEdge) {
    const ax = a.rx, ay = a.ry, bx = b.rx, by = b.ry;
    if (treeEdge) {
      const x0 = ax + a.w / 2, y0 = ay + a.h, x1 = bx + b.w / 2, y1 = by;
      const k = Math.max(18, (y1 - y0) * 0.5);
      return [x0, y0, x0, y0 + k, x1, y1 - k, x1, y1];
    }
    const acx = ax + a.w / 2, acy = ay + a.h / 2, bcx = bx + b.w / 2, bcy = by + b.h / 2;
    const dx = bcx - acx, dy = bcy - acy;
    if (Math.abs(dx) > Math.abs(dy) * 1.15) {
      const dir = dx > 0 ? 1 : -1;
      const x0 = dir > 0 ? ax + a.w : ax, x1 = dir > 0 ? bx : bx + b.w;
      const k = Math.max(30, Math.abs(x1 - x0) * 0.45);
      return [x0, acy, x0 + dir * k, acy, x1 - dir * k, bcy, x1, bcy];
    }
    const dir = dy > 0 ? 1 : -1;
    const y0 = dir > 0 ? ay + a.h : ay, y1 = dir > 0 ? by : by + b.h;
    const k = Math.max(26, Math.abs(y1 - y0) * 0.45);
    return [acx, y0, acx, y0 + dir * k, bcx, y1 - dir * k, bcx, y1];
  }

  function drawEdges(vx0, vy0, vx1, vy1, z) {
    const lay = SC.lay, ui = SC.ui, geom = SC.edgeGeom;
    geom.length = 0;
    const treeEdges = lay.type === 'tree' ? lay.fam.treeEdges : null;
    const lw = Math.max(1.7, 1.25 / z);
    const edgeAlpha = lay.type === 'timeline' ? 0.5 : 0.8;
    ctx.lineCap = 'round';
    for (const e of lay.edges) {
      const a = SC.nodes.get(e.from), b = SC.nodes.get(e.to);
      if (!a || !b || !a.vis || !b.vis) continue;
      if (!a.on && !b.on) {
        // both ends off screen: only draw when the line itself crosses the view
        const minx = Math.min(a.rx, b.rx), maxx = Math.max(a.rx + a.w, b.rx + b.w), miny = Math.min(a.ry, b.ry), maxy = Math.max(a.ry + a.h, b.ry + b.h);
        if (maxx < vx0 || minx > vx1 || maxy < vy0 || miny > vy1) continue;
      }
      const g = anchors(a, b, treeEdges && treeEdges.has(e.id));
      const selected = ui.sel && ui.sel.type === 'edge' && ui.sel.id === e.id;
      const col = SC.EDGE_COLOR[e.kind] || theme.muted;
      ctx.globalAlpha = Math.min(a.a, b.a) * (selected ? 1 : edgeAlpha);
      ctx.strokeStyle = col;
      ctx.lineWidth = selected ? lw * 2.2 : lw;
      if (e.guess) ctx.setLineDash([7 * Math.max(1, 0.7 / z), 6 * Math.max(1, 0.7 / z)]);
      ctx.beginPath();
      ctx.moveTo(g[0], g[1]);
      ctx.bezierCurveTo(g[2], g[3], g[4], g[5], g[6], g[7]);
      ctx.stroke();
      if (e.guess) ctx.setLineDash([]);
      // arrow head at the child
      const ang = Math.atan2(g[7] - g[5], g[6] - g[4]), ah = Math.max(7, 5 / z);
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(g[6], g[7]);
      ctx.lineTo(g[6] - ah * Math.cos(ang - 0.42), g[7] - ah * Math.sin(ang - 0.42));
      ctx.lineTo(g[6] - ah * Math.cos(ang + 0.42), g[7] - ah * Math.sin(ang + 0.42));
      ctx.closePath();
      ctx.fill();
      geom.push({ e: e, g: g });
    }
    ctx.globalAlpha = 1;
  }

  /* Dashed wire from a sticky note to the session it is connected to. */
  function drawNoteWires(z) {
    const notes = SC.state.notes;
    if (!notes.length) return;
    ctx.lineWidth = Math.max(1.6, 1.2 / z);
    ctx.setLineDash([5 * Math.max(1, 0.7 / z), 5 * Math.max(1, 0.7 / z)]);
    for (const note of notes) {
      const xy = note.attach ? SC.noteXY.get(note.id) : null;
      if (!xy) continue;
      const n = SC.nodes.get(note.attach);
      if (!n || !n.vis) continue;
      const nx = xy.x + note.w / 2, ny = xy.y + note.h / 2;
      const cx = U.clamp(nx, n.rx, n.rx + n.w), cy = U.clamp(ny, n.ry, n.ry + n.h);
      ctx.strokeStyle = SC.NOTE_HEX[note.color] || '#ffe37a';
      ctx.globalAlpha = 0.9;
      ctx.beginPath();
      ctx.moveTo(nx, ny);
      ctx.lineTo(cx, cy);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  function drawRubber(z) {
    const d = SC.ui.drag;
    ctx.strokeStyle = SC.EDGE_COLOR.manual;
    ctx.lineWidth = Math.max(2.2, 1.8 / z);
    ctx.setLineDash([8 * Math.max(1, 0.7 / z), 6 * Math.max(1, 0.7 / z)]);
    ctx.beginPath();
    ctx.moveTo(d.x0, d.y0);
    ctx.lineTo(d.x, d.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = SC.EDGE_COLOR.manual;
    ctx.beginPath();
    ctx.arc(d.x, d.y, Math.max(5, 4 / z), 0, 6.283);
    ctx.fill();
  }

  // ---- where a card stands: one shape per state (so it also reads without colour) ----
  /* question = diamond with "?", your turn = disc with a "go" triangle, running = ring with a moving arc,
     not done = square with a cross, done = disc with a tick, replaced = hollow disc with a forward arrow. */
  SC.glyph = function (c, key, cx, cy, r, breath) {
    const info = SC.STATES[key];
    if (!info) return;
    const col = info.color, ink = info.ink;
    c.lineCap = 'round'; c.lineJoin = 'round';
    if (key === 'question') {
      c.fillStyle = col;
      c.beginPath(); c.moveTo(cx, cy - r * 1.18); c.lineTo(cx + r * 1.18, cy); c.lineTo(cx, cy + r * 1.18); c.lineTo(cx - r * 1.18, cy); c.closePath(); c.fill();
      c.fillStyle = ink; c.font = '800 ' + (r * 1.35).toFixed(1) + 'px ' + FONT;
      const ta = c.textAlign, tb = c.textBaseline;
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('?', cx, cy + r * 0.06);
      c.textAlign = ta; c.textBaseline = tb;
    } else if (key === 'your-turn') {
      c.fillStyle = col;
      c.beginPath(); c.arc(cx, cy, r, 0, 6.283); c.fill();
      c.fillStyle = ink;
      c.beginPath(); c.moveTo(cx - r * 0.3, cy - r * 0.5); c.lineTo(cx + r * 0.55, cy); c.lineTo(cx - r * 0.3, cy + r * 0.5); c.closePath(); c.fill();
    } else if (key === 'running') {
      c.strokeStyle = col; c.lineWidth = r * 0.34;
      const a0 = c.globalAlpha;
      c.globalAlpha = a0 * 0.3;
      c.beginPath(); c.arc(cx, cy, r * 0.8, 0, 6.283); c.stroke();
      c.globalAlpha = a0;
      const t = pulseOff ? 0.6 : (performance.now() % 1600) / 1600 * 6.283;
      c.beginPath(); c.arc(cx, cy, r * 0.8, t, t + 2.2); c.stroke();
      c.fillStyle = col;
      c.beginPath(); c.arc(cx, cy, r * 0.26, 0, 6.283); c.fill();
      spinWanted = true;
    } else if (key === 'not-done') {
      c.fillStyle = col;
      rr(c, cx - r * 0.92, cy - r * 0.92, r * 1.84, r * 1.84, r * 0.4); c.fill();
      c.strokeStyle = ink; c.lineWidth = r * 0.3;
      c.beginPath(); c.moveTo(cx - r * 0.38, cy - r * 0.38); c.lineTo(cx + r * 0.38, cy + r * 0.38); c.moveTo(cx + r * 0.38, cy - r * 0.38); c.lineTo(cx - r * 0.38, cy + r * 0.38); c.stroke();
    } else if (key === 'done') {
      c.fillStyle = col;
      c.beginPath(); c.arc(cx, cy, r, 0, 6.283); c.fill();
      c.strokeStyle = ink; c.lineWidth = r * 0.3;
      c.beginPath(); c.moveTo(cx - r * 0.45, cy + r * 0.02); c.lineTo(cx - r * 0.12, cy + r * 0.36); c.lineTo(cx + r * 0.48, cy - r * 0.32); c.stroke();
    } else {
      c.strokeStyle = col; c.lineWidth = r * 0.24;
      c.beginPath(); c.arc(cx, cy, r * 0.88, 0, 6.283); c.stroke();
      c.beginPath(); c.moveTo(cx - r * 0.42, cy); c.lineTo(cx + r * 0.4, cy); c.moveTo(cx + r * 0.08, cy - r * 0.34); c.lineTo(cx + r * 0.42, cy); c.lineTo(cx + r * 0.08, cy + r * 0.34); c.stroke();
    }
  };

  /* A slow breath (0..1) for the cards that wait on you. Off when the Mac asks for less motion. */
  const pulseOff = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) || SC.params.has('still');
  let pulseWanted = false, spinWanted = false;
  function pulseLevel() { return pulseOff ? 0.55 : 0.5 + 0.5 * Math.sin(performance.now() / 2600 * 6.283); }
  setInterval(() => {
    if (pulseOff || document.hidden || !(pulseWanted || spinWanted) || SC.benching) return;
    SC.requestRender();
  }, 70);

  // ---- status layout: one zone per state ----
  function drawZonesBack(vx0, vy0, vx1, vy1, z) {
    const T = theme, dark = themeName === 'dark', lay = SC.lay, ZS = L.ST;
    const breath = pulseLevel();
    const world = z >= ZONE_WORLD_Z;                   // close enough to read the zone's own heading
    for (const zn of lay.zones) {
      if (zn.x1 + 40 < vx0 || zn.x0 - 40 > vx1) continue;
      const col = zn.info.color, calm = zn.key === 'done' || zn.key === 'replaced';
      const w = zn.x1 - zn.x0, h = zn.y1 - zn.y0;
      // the lane
      ctx.globalAlpha = (dark ? 0.075 : 0.085) * (calm ? 0.75 : 1);
      ctx.fillStyle = col;
      rr(ctx, zn.x0, zn.y0, w, h, 22);
      ctx.fill();
      // its heading band
      ctx.globalAlpha = (dark ? 0.17 : 0.2) * (zn.count ? 1 : 0.6);
      rr(ctx, zn.x0, zn.y0, w, ZS.HEAD - 22, [22, 22, 0, 0]);
      ctx.fill();
      ctx.globalAlpha = zn.count ? (calm ? 0.45 : 0.8) : 0.3;
      ctx.strokeStyle = col;
      ctx.lineWidth = Math.max(calm ? 1.2 : 2, (calm ? 1.2 : 2) / z);
      rr(ctx, zn.x0, zn.y0, w, h, 22);
      ctx.stroke();
      if (zn.info.wait && zn.count) {                  // the lanes that wait on you glow gently
        ctx.globalAlpha = 0.08 + 0.2 * breath;
        ctx.lineWidth = Math.max(10, 9 / z);
        rr(ctx, zn.x0 - 4, zn.y0 - 4, w + 8, h + 8, 26);
        ctx.stroke();
        pulseWanted = true;
      }
      ctx.globalAlpha = 1;
      if (world) {
        SC.glyph(ctx, zn.key, zn.x0 + ZS.PAD + 15, zn.y0 + 33, 15, breath);
        ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
        ctx.font = F_ZONE;
        ctx.fillStyle = T.text;
        ctx.fillText(fit(F_ZONE, zn.info.zone, w - ZS.PAD - 40 - 14), zn.x0 + ZS.PAD + 40, zn.y0 + 40);
        ctx.font = F_ZHINT;
        ctx.fillStyle = T.muted;
        const hint = zn.key === 'done' || zn.key === 'replaced' || zn.key === 'not-done' ? zn.info.hint + ' · last ' + lay.days + ' days' : zn.info.hint;
        ctx.fillText(fit(F_ZHINT, hint, w - ZS.PAD * 2), zn.x0 + ZS.PAD, zn.y0 + 66);
        // how many: a badge on the corner, like the red dot on an app
        const txt = String(zn.count);
        ctx.font = F_ZCOUNT;
        const bw = Math.max(44, ctx.measureText(txt).width + 26);
        ctx.fillStyle = zn.count ? col : (dark ? '#2a3443' : '#d5dce7');
        rr(ctx, zn.x1 - bw + 14, zn.y0 - 16, bw, 44, 22);
        ctx.fill();
        ctx.fillStyle = zn.count ? zn.info.ink : T.muted;
        ctx.textAlign = 'center';
        ctx.fillText(txt, zn.x1 - bw / 2 + 14, zn.y0 + 15);
        ctx.textAlign = 'left';
      }
      if (!zn.count && z > 0.3) {
        ctx.font = F_ZHINT;
        ctx.fillStyle = T.faint;
        ctx.textAlign = 'center';
        ctx.fillText(zn.info.wait ? 'All clear' : 'Nothing here', (zn.x0 + zn.x1) / 2, zn.y0 + ZS.HEAD + 50);
        ctx.textAlign = 'left';
      }
    }
  }
  /* Far away (or scrolled past the heading): the zone names stay readable as pills pinned to the top of each zone. */
  function drawZoneLabels(z) {
    const T = theme, cam = SC.cam, lay = SC.lay;
    ctx.textBaseline = 'alphabetic';
    for (const zn of lay.zones) {
      const sx0 = (zn.x0 - cam.x) * z, sx1 = (zn.x1 - cam.x) * z;
      const sy0 = (zn.y0 - cam.y) * z, sy1 = (zn.y1 - cam.y) * z;
      const headGone = sy0 + (L.ST.HEAD - 30) * z < TOP;
      if (z >= ZONE_WORLD_Z && !headGone) continue;
      if (sx1 < 0 || sx0 > SC.vw || sy1 < TOP + 30 || sy0 > SC.vh) continue;
      const wide = sx1 - sx0;
      ctx.font = F_UIB;
      const count = String(zn.count);
      let label = zn.info.zone;
      let tw0 = ctx.measureText(label).width, cw = ctx.measureText(count).width + 14;
      let pw = 30 + tw0 + 8 + cw + 6;
      if (pw > wide + 6) { label = ''; pw = 26 + cw + 6; }          // a narrow zone far away: shape + count only
      const x = U.clamp(sx0 + (wide - pw) / 2, Math.min(8, sx1 - pw), Math.max(sx1 - pw, 8));
      const y = U.clamp(sy0 - 34, TOP + 6, Math.max(TOP + 6, sy1 - 30));
      ctx.globalAlpha = zn.count ? 1 : 0.6;
      ctx.fillStyle = T.pill;
      rr(ctx, x, y, pw, 26, 13);
      ctx.fill();
      ctx.strokeStyle = zn.info.color; ctx.lineWidth = zn.count && zn.info.wait ? 2 : 1.2; ctx.stroke();
      SC.glyph(ctx, zn.key, x + 14, y + 13, 7.5, 0.5);
      ctx.font = F_UIB;
      ctx.textAlign = 'left';
      ctx.fillStyle = T.text;
      if (label) ctx.fillText(label, x + 27, y + 17.5);
      const cx = x + pw - cw - 5;
      ctx.fillStyle = zn.count ? zn.info.color : T.border;
      rr(ctx, cx, y + 4, cw, 18, 9);
      ctx.fill();
      ctx.fillStyle = zn.count ? zn.info.ink : T.muted;
      ctx.textAlign = 'center';
      ctx.fillText(count, cx + cw / 2, y + 17.5);
      ctx.textAlign = 'left';
      ctx.globalAlpha = 1;
    }
  }

  // ---- cards ----
  function drawCards(list, z) {
    const T = theme, dark = themeName === 'dark';
    const lod = z >= LOD_FULL ? 2 : (z >= LOD_TITLE ? 1 : 0);
    const isTree = SC.lay.type === 'tree';
    const collapsed = isTree ? new Set(SC.state.collapsed) : null;
    const lw = Math.max(1, 1 / z);
    for (const n of list) ready(n, lod);

    // 1. bodies
    for (const n of list) {
      const p = n.prep, x = n.rx, y = n.ry;
      ctx.globalAlpha = n.a;
      if (lod === 0) {
        ctx.fillStyle = p.block;
        if (z < 0.1) ctx.fillRect(x, y, n.w, n.h);
        else { rr(ctx, x, y, n.w, n.h, 12); ctx.fill(); }
        continue;
      }
      ctx.fillStyle = p.stripe;
      rr(ctx, x, y, 14, n.h, [10, 0, 0, 10]);
      ctx.fill();
      ctx.fillStyle = p.bg;
      rr(ctx, x + 5, y, n.w - 5, n.h, [0, 10, 10, 0]);
      ctx.fill();
      ctx.strokeStyle = p.border;
      ctx.lineWidth = lw;
      rr(ctx, x + lw / 2, y + lw / 2, n.w - lw, n.h - lw, 10);
      ctx.stroke();
    }
    // where each card stands, readable at every zoom level:
    //   waiting on you = a frame in the state's colour with a soft breathing glow; stopped = a dashed red frame;
    //   far away the waiting ones also get a filled corner. Done and replaced stay calm.
    const breath = pulseLevel();
    let waitingOn = 0;
    for (const n of list) {
      const st = n.prep.st;
      if (!st.key || st.key === 'done' || st.key === 'replaced' || st.key === 'running') continue;
      const col = st.info.color;
      ctx.strokeStyle = col;
      if (st.info.wait) {
        waitingOn++;
        ctx.globalAlpha = n.a * (0.10 + 0.30 * breath);
        ctx.lineWidth = Math.max(9, 8 / z);
        rr(ctx, n.rx - 3, n.ry - 3, n.w + 6, n.h + 6, 13);
        ctx.stroke();
        ctx.globalAlpha = n.a;
        ctx.lineWidth = Math.max(2.5, 2.5 / z);
        rr(ctx, n.rx - 1, n.ry - 1, n.w + 2, n.h + 2, 11);
        ctx.stroke();
        if (lod === 0) {                                  // a far-away block: a filled corner says "this one"
          ctx.fillStyle = col;
          ctx.beginPath();
          ctx.moveTo(n.rx + n.w - 96, n.ry); ctx.lineTo(n.rx + n.w, n.ry); ctx.lineTo(n.rx + n.w, n.ry + 96);
          ctx.closePath();
          ctx.fill();
        }
      } else {
        ctx.globalAlpha = n.a * 0.9;
        ctx.lineWidth = Math.max(1.6, 1.6 / z);
        ctx.setLineDash([7 * Math.max(1, 0.6 / z), 5 * Math.max(1, 0.6 / z)]);
        rr(ctx, n.rx - 1, n.ry - 1, n.w + 2, n.h + 2, 11);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (waitingOn) pulseWanted = true;
    if (lod === 0) { ctx.globalAlpha = 1; return; }

    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    if (lod === 1) {
      // far away: only big titles
      const big = z < 0.37;
      ctx.font = big ? F_BIG2 : F_BIG1;
      ctx.fillStyle = T.text;
      const lh = big ? 32 : 24;
      for (const n of list) {
        const lines = big ? n.prep.tb2 : n.prep.tb1;
        ctx.globalAlpha = n.a;
        for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i], n.rx + 15, n.ry + lh + i * lh - 3);
      }
      // the day, where the card has room for it
      ctx.font = F_BIG3;
      ctx.fillStyle = T.muted;
      for (const n of list) {
        if (n.compact || (big ? n.prep.tb2.length > 2 : n.prep.tb1.length > 3)) continue;
        ctx.globalAlpha = n.a;
        ctx.fillText(n.prep.day, n.rx + 15, n.ry + n.h - 13);
      }
      for (const n of list) {
        if (!n.prep.st.key) continue;
        ctx.globalAlpha = n.a;
        SC.glyph(ctx, n.prep.st.key, n.rx + n.w - 24, n.ry + 24, 15, breath);
      }
      ctx.globalAlpha = 1;
      return;
    }

    // 2. titles
    ctx.font = F_TITLE;
    ctx.fillStyle = T.text;
    for (const n of list) {
      const tl = n.prep.tl;
      ctx.globalAlpha = n.a;
      for (let i = 0; i < tl.length; i++) ctx.fillText(tl[i], n.rx + 15, n.ry + 22 + i * 17);
    }
    // 3. date line (+ one line of "about" under short titles)
    ctx.font = F_META;
    ctx.fillStyle = T.muted;
    for (const n of list) {
      ctx.globalAlpha = n.a;
      ctx.fillText(n.prep.meta, n.rx + 15, n.ry + (n.compact ? 38 : 56));
      if (n.prep.about) ctx.fillText(n.prep.about, n.rx + 15, n.ry + 39);
    }
    // 3b. the latest: status pill + text
    for (const n of list) {
      const p = n.prep;
      if (!p.stl.length) continue;
      ctx.globalAlpha = n.a;
      let x = n.rx + 15;
      if (p.stLabel) {
        ctx.fillStyle = p.stColor;
        rr(ctx, x, n.ry + 61, p.stW, 12, 6);
        ctx.fill();
        ctx.font = F_KIND;
        ctx.fillStyle = p.stInk || '#10151d';
        ctx.fillText(p.stLabel, x + 5, n.ry + 70.5);
        x += p.stW + 5;
      }
      ctx.font = F_META;
      ctx.fillStyle = p.stLabel ? T.text : T.muted;
      ctx.fillText(p.stl[0], x, n.ry + 70.5);
      if (p.stl[1]) ctx.fillText(p.stl[1], n.rx + 15, n.ry + 83.5);
    }
    // 4. type of session
    ctx.font = F_KIND;
    ctx.textAlign = 'right';
    for (const n of list) {
      ctx.globalAlpha = n.a;
      ctx.fillStyle = n.prep.kindColor;
      ctx.fillText(n.prep.kindText, n.rx + n.w - 10, n.ry + (n.compact ? 38 : 56));
    }
    ctx.textAlign = 'left';
    // 5. chips
    const cmdBg = dark ? 'rgba(255,255,255,0.06)' : 'rgba(15,30,60,0.05)';
    const jiraBg = dark ? '#16335f' : '#dbe8ff', jiraFg = dark ? '#9cc2ff' : '#1d4ed8';
    for (const n of list) {
      ctx.globalAlpha = n.a;
      for (const c of n.prep.chips) {
        if (c.style === 'kw') { const cc = chipColor(c.word); c.bg = cc.bg; c.fg = cc.fg; }
        else if (c.style === 'cmd') { c.bg = cmdBg; c.fg = T.text; }
        else if (c.style === 'jira') { c.bg = jiraBg; c.fg = jiraFg; }
        else { c.bg = n.prep.accent; c.fg = '#10151d'; }
        ctx.fillStyle = c.bg;
        rr(ctx, n.rx + c.x, n.ry + c.y, c.w, 18, 9);
        ctx.fill();
        if (c.style === 'cmd') { ctx.strokeStyle = T.faint; ctx.lineWidth = 1; ctx.stroke(); }
      }
    }
    ctx.font = F_CHIP;
    for (const n of list) {
      ctx.globalAlpha = n.a;
      for (const c of n.prep.chips) { ctx.fillStyle = c.fg; ctx.fillText(c.text, n.rx + c.x + 7, n.ry + c.y + 12.5); }
    }
    // 6. footer, "running now" dot, children toggle
    ctx.font = F_FOOT;
    for (const n of list) {
      ctx.globalAlpha = n.a;
      if (n.prep.footer) { ctx.fillStyle = T.faint; ctx.fillText(n.prep.footer, n.rx + 15, n.ry + n.h - 10); }
      const sk = n.prep.st.key;
      if (sk) SC.glyph(ctx, sk, n.rx + n.w - 16, n.ry + 16, 8.5, breath);
      if (n.s.active && sk !== 'running') {               // open in a window right now (and not simply "running")
        const lx = n.rx + n.w - (sk ? 33 : 13);
        ctx.fillStyle = '#2fc98a';
        ctx.beginPath(); ctx.arc(lx, n.ry + 16, 4, 0, 6.283); ctx.fill();
        ctx.strokeStyle = 'rgba(47,201,138,0.35)'; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(lx, n.ry + 16, 6.5, 0, 6.283); ctx.stroke();
      }
      if (isTree) {
        const k = SC.kidCount(n.id);
        if (k) {
          const r = toggleRect(n), shut = collapsed.has(n.id);
          const dx = n.rx - n.x, dy = n.ry - n.y;
          ctx.fillStyle = shut ? n.prep.accent : (themeName === 'dark' ? 'rgba(255,255,255,0.10)' : 'rgba(15,30,60,0.08)');
          rr(ctx, r.x + dx, r.y + dy, r.w, r.h, 8.5);
          ctx.fill();
          ctx.fillStyle = shut ? '#10151d' : T.muted;
          const tx = r.x + dx + 11, ty = r.y + dy + 8.5;        // small triangle: right = folded, down = open
          ctx.beginPath();
          if (shut) { ctx.moveTo(tx - 2.5, ty - 4); ctx.lineTo(tx + 3, ty); ctx.lineTo(tx - 2.5, ty + 4); }
          else { ctx.moveTo(tx - 4, ty - 2.5); ctx.lineTo(tx + 4, ty - 2.5); ctx.lineTo(tx, ty + 3); }
          ctx.closePath();
          ctx.fill();
          ctx.font = F_CHIP;
          ctx.fillText(String(k), r.x + dx + 19, r.y + dy + 12.5);
          ctx.font = F_FOOT;
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  /* Outlines: search matches, hover, selection, and the little handle used to draw a link. */
  function drawMarks(list, z) {
    const T = theme, ui = SC.ui, S = SC.search;
    const px = 1 / z;
    const searching = S.tokens.length > 0;
    const cur = searching && S.index >= 0 ? S.order[S.index] : null;
    for (const n of list) {
      const x = n.rx, y = n.ry;
      if (searching && S.matches.has(n.id)) {
        ctx.strokeStyle = T.match;
        ctx.globalAlpha = n.id === cur ? 0.45 : 0.22;
        ctx.lineWidth = (n.id === cur ? 11 : 7) * px;
        rr(ctx, x - 2 * px, y - 2 * px, n.w + 4 * px, n.h + 4 * px, 12);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 2.5 * px;
        ctx.stroke();
      }
      if (ui.hover === n.id && !(ui.sel && ui.sel.type === 'node' && ui.sel.id === n.id)) {
        ctx.strokeStyle = T.muted;
        ctx.lineWidth = 1.5 * px;
        rr(ctx, x - 1.5 * px, y - 1.5 * px, n.w + 3 * px, n.h + 3 * px, 11);
        ctx.stroke();
      }
      if (ui.focus === n.id) {
        ctx.strokeStyle = n.prep ? n.prep.accent : T.sel;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 9 * px;
        rr(ctx, x - 4 * px, y - 4 * px, n.w + 8 * px, n.h + 8 * px, 13);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (ui.sel && ui.sel.type === 'node' && ui.sel.id === n.id) {
        ctx.strokeStyle = T.sel;
        ctx.lineWidth = 2.5 * px;
        rr(ctx, x - 3 * px, y - 3 * px, n.w + 6 * px, n.h + 6 * px, 12);
        ctx.stroke();
      }
      if (ui.drag && ui.drag.type === 'link' && ui.drag.over === n.id) {
        ctx.strokeStyle = SC.EDGE_COLOR.manual;
        ctx.lineWidth = 3.5 * px;
        rr(ctx, x - 4 * px, y - 4 * px, n.w + 8 * px, n.h + 8 * px, 13);
        ctx.stroke();
      }
    }
    // link handle on the hovered / selected card
    const hid = ui.hover || (ui.sel && ui.sel.type === 'node' ? ui.sel.id : null);
    if (hid && z > 0.2 && !(ui.drag && ui.drag.type !== 'link')) {
      const n = SC.nodes.get(hid);
      if (n && n.on) {
        const r = Math.max(6.5, 6 / z);
        ctx.fillStyle = '#ffffff';
        ctx.strokeStyle = SC.EDGE_COLOR.manual;
        ctx.lineWidth = Math.max(2.5, 2.2 / z);
        ctx.beginPath();
        ctx.arc(n.rx + n.w, n.ry + n.h / 2, r, 0, 6.283);
        ctx.fill();
        ctx.stroke();
      }
    }
  }
  SC.handleOf = n => ({ x: n.x + n.w, y: n.y + n.h / 2, r: Math.max(11, 10 / SC.cam.z) });

  // ---- timeline background and sticky header ----
  function drawTimelineBack(vx0, vy0, vx1, vy1, z) {
    const T = theme, lay = SC.lay;
    const y0 = -14, y1 = lay.height + 14;
    lay.lanes.forEach((lane, i) => {
      if (lane.y1 < vy0 || lane.y0 > vy1) return;
      ctx.fillStyle = i % 2 ? T.laneAlt : T.lane;
      const a = Math.max(vx0, 0), b = Math.min(vx1, lay.width);
      if (b > a) ctx.fillRect(a, lane.y0, b - a, lane.y1 - lane.y0);
    });
    for (const d of lay.days) {
      if (d.x1 < vx0 || d.x0 > vx1) continue;
      if (d.weekend) { ctx.fillStyle = T.weekend; ctx.fillRect(d.x0, y0, d.w, y1 - y0); }
      if (d.today) { ctx.fillStyle = T.todayFill; ctx.fillRect(d.x0, y0, d.w, y1 - y0); }
      ctx.fillStyle = d.monday ? T.lineStrong : T.line;
      const w = (d.monday ? 2 : 1) / z;
      ctx.fillRect(d.x0 - w / 2, y0, w, y1 - y0);
    }
    const t = lay.dayAt.get(lay.today);
    if (t) {
      // "now" inside today's column: a line that moves across the day
      const frac = U.clamp((Date.now() - lay.today) / 86400000, 0, 1);
      const x = t.x0 + t.w * frac, w = 2.5 / z;
      ctx.fillStyle = T.today;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(x - w / 2, y0, w, y1 - y0);
      ctx.globalAlpha = 1;
    }
  }

  function drawTimelineHead(z) {
    const T = theme, lay = SC.lay, cam = SC.cam, vw = SC.vw;
    ctx.fillStyle = T.header;
    ctx.fillRect(0, TOP, vw, TL_HEAD);
    ctx.fillStyle = T.line;
    ctx.fillRect(0, TOP + TL_HEAD - 1, vw, 1);
    ctx.textBaseline = 'alphabetic';
    // days
    for (const d of lay.days) {
      const sx0 = (d.x0 - cam.x) * z, sw = d.w * z;
      if (sx0 + sw < 0 || sx0 > vw) continue;
      if (d.today) { ctx.fillStyle = T.todayFill; ctx.fillRect(sx0, TOP, sw, TL_HEAD); }
      if (sw >= 17) {
        ctx.textAlign = 'center';
        ctx.font = d.today ? F_UIB : (d.count ? F_UI : F_UIS);
        ctx.fillStyle = d.today ? T.today : (d.count ? T.text : T.faint);
        const txt = sw >= 54 ? U.fmtDayShort(d.t) : String(d.dom);
        ctx.fillText(txt, sx0 + sw / 2, TOP + 37);
        if (d.count && sw >= 96) {
          ctx.font = F_UIS; ctx.fillStyle = T.faint; ctx.textAlign = 'right';
          ctx.fillText(d.count + (d.count === 1 ? ' session' : ' sessions'), sx0 + sw - 8, TOP + 37);
        }
      }
      if (d.monday || d === lay.days[0]) {
        ctx.fillStyle = T.lineStrong;
        ctx.fillRect(sx0 - 1, TOP, 2, TL_HEAD);
      }
    }
    // weeks (label stays in view while its week is on screen)
    ctx.textAlign = 'left';
    ctx.font = F_UIB;
    let i = 0;
    while (i < lay.days.length) {
      let j = i + 1;
      while (j < lay.days.length && !lay.days[j].monday) j++;
      const wx0 = (lay.days[i].x0 - cam.x) * z, wx1 = (lay.days[j - 1].x1 - cam.x) * z;
      if (wx1 > 0 && wx0 < vw) {
        const label = 'Week of ' + U.fmtDate(U.weekStart(lay.days[i].t));
        const tw = ctx.measureText(label).width;
        const x = Math.min(Math.max(wx0 + 8, 10), wx1 - tw - 8);
        if (wx1 - wx0 > tw + 14) { ctx.fillStyle = T.muted; ctx.fillText(label, x, TOP + 17); }
      }
      i = j;
    }
    const t = lay.dayAt.get(lay.today);
    if (t) {
      const sx = (t.x0 + t.w / 2 - cam.x) * z;
      if (sx > -40 && sx < vw + 40 && t.w * z >= 54) {
        ctx.font = F_KIND; ctx.textAlign = 'center'; ctx.fillStyle = T.today;
        ctx.fillText('TODAY', sx, TOP + 22);
      }
    }
    // lane names, pinned to the left edge
    ctx.textAlign = 'left';
    for (const lane of lay.lanes) {
      const sy0 = (lane.y0 - cam.y) * z, sy1 = (lane.y1 - cam.y) * z;
      if (sy1 < TOP + TL_HEAD || sy0 > SC.vh) continue;
      const label = lane.label + '  ·  ' + lane.count;
      ctx.font = F_UIB;
      const lw = ctx.measureText(label).width + 20;
      const y = U.clamp(sy0 + 6, TOP + TL_HEAD + 6, Math.max(TOP + TL_HEAD + 6, sy1 - 28));
      if (sy1 - Math.max(sy0, TOP + TL_HEAD) < 26) continue;
      const edge = (0 - cam.x) * z;                      // where the timeline starts on screen
      const x = edge >= lw + 18 ? edge - lw - 10 : 10;   // beside it when there is room, else pinned on top
      ctx.fillStyle = T.pill;
      rr(ctx, x, y, lw, 22, 11);
      ctx.fill();
      ctx.strokeStyle = T.border; ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = T.text;
      ctx.fillText(label, x + 10, y + 15.5);
    }
  }

  // ---- tree: week bands ----
  function drawBandsBack(vx0, vy0, vx1, vy1, z) {
    const T = theme;
    for (const b of SC.lay.bands) {
      const top = b.y0 - 34;
      if (top > vy1 || b.y1 < vy0) continue;
      ctx.fillStyle = T.lineStrong;
      const h = 1.5 / z;
      ctx.fillRect(b.x0, top, Math.max(b.x1 - b.x0, 900), h);
    }
  }
  function drawBandLabels(z) {
    const T = theme, cam = SC.cam;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    for (const b of SC.lay.bands) {
      const sy0 = (b.y0 - 34 - cam.y) * z, sy1 = (b.y1 - cam.y) * z;
      if (sy1 < TOP || sy0 > SC.vh) continue;
      const label = b.label + '  ·  ' + b.count + (b.count === 1 ? ' session' : ' sessions');
      ctx.font = F_UIB;
      const lw = ctx.measureText(label).width + 20;
      const edge = (b.x0 - cam.x) * z;
      let x, y;
      if (z < 0.42 && edge >= lw + 18) {                 // zoomed out: names sit beside their band
        x = edge - lw - 12;
        y = U.clamp((b.y0 - cam.y) * z - 2, TOP + 6, Math.max(TOP + 6, sy1 - 24));
      } else {                                           // zoomed in: name above the band, stays in view
        x = Math.max(10, edge);
        y = U.clamp(sy0 - 26, TOP + 6, Math.max(TOP + 6, sy1 - 30));
      }
      ctx.fillStyle = T.pill;
      rr(ctx, x, y, lw, 22, 11);
      ctx.fill();
      ctx.strokeStyle = T.border; ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = T.text;
      ctx.fillText(label, x + 10, y + 15.5);
    }
  }
  function drawInboxLabel(z) {
    const T = theme, ib = SC.lay.inbox;
    ctx.font = '700 ' + Math.max(15, 13 / z) + 'px ' + FONT;
    ctx.fillStyle = T.muted;
    ctx.textAlign = 'left';
    ctx.fillText('New here (' + ib.count + '): drag them where you like', ib.x, ib.y - 16);
  }

  // ---- minimap ----
  function drawMinimap() {
    const T = theme, dpr = SC.dpr, W = 220, H = 140, lay = SC.lay, cam = SC.cam;
    mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    mctx.clearRect(0, 0, W, H);
    mctx.fillStyle = T.mapBg;
    mctx.fillRect(0, 0, W, H);
    const b = Object.assign({}, lay.bounds);
    if (lay.type === 'timeline') { b.x0 = 0; b.y0 = 0; b.x1 = Math.max(b.x1, lay.width); b.y1 = Math.max(b.y1, lay.height); }
    if (lay.type === 'status') { b.x0 = 0; b.y0 = 0; b.x1 = lay.width; b.y1 = lay.height; }
    // always include what the person is looking at, so the view box never leaves the map
    const vx0 = cam.x, vy0 = cam.y, vx1 = cam.x + SC.vw / cam.z, vy1 = cam.y + SC.vh / cam.z;
    const bw = Math.max(1, b.x1 - b.x0), bh = Math.max(1, b.y1 - b.y0);
    const k = Math.min((W - 12) / bw, (H - 12) / bh);
    const ox = (W - bw * k) / 2 - b.x0 * k, oy = (H - bh * k) / 2 - b.y0 * k;
    SC.mini = { k: k, ox: ox, oy: oy };
    const S = SC.search, searching = S.tokens.length > 0;
    if (lay.type === 'status') {
      for (const zn of lay.zones) {
        mctx.globalAlpha = 0.2;
        mctx.fillStyle = zn.info.color;
        mctx.fillRect(ox + zn.x0 * k, oy + zn.y0 * k, (zn.x1 - zn.x0) * k, (zn.y1 - zn.y0) * k);
      }
    }
    for (const n of lay.shown) {
      const p = ready(n, 0);
      const hit = searching && S.matches.has(n.id);
      mctx.globalAlpha = searching ? (hit ? 1 : 0.25) : (SC.ui.family && !SC.ui.family.has(n.id) ? 0.25 : 0.95);
      mctx.fillStyle = hit ? T.match : p.block;
      mctx.fillRect(ox + n.x * k, oy + n.y * k, Math.max(1.6, n.w * k), Math.max(1.3, n.h * k));
    }
    mctx.globalAlpha = 1;
    for (const note of SC.state.notes) {
      const xy = SC.noteXY.get(note.id);
      if (!xy) continue;
      mctx.fillStyle = SC.NOTE_HEX[note.color] || '#ffe37a';
      mctx.fillRect(ox + xy.x * k, oy + xy.y * k, Math.max(2.5, note.w * k), Math.max(2.5, note.h * k));
    }
    const rx = U.clamp(ox + vx0 * k, 1, W - 3), ry = U.clamp(oy + vy0 * k, 1, H - 3);
    const rx1 = U.clamp(ox + vx1 * k, 3, W - 1), ry1 = U.clamp(oy + vy1 * k, 3, H - 1);
    mctx.strokeStyle = T.mapView;
    mctx.lineWidth = 1.5;
    mctx.fillStyle = themeName === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(15,23,42,0.07)';
    mctx.fillRect(rx, ry, Math.max(3, rx1 - rx), Math.max(3, ry1 - ry));
    mctx.strokeRect(rx, ry, Math.max(3, rx1 - rx), Math.max(3, ry1 - ry));
  }
  SC.miniToWorld = function (mx, my) {
    const m = SC.mini;
    return m ? { x: (mx - m.ox) / m.k, y: (my - m.oy) / m.k } : { x: 0, y: 0 };
  };

  // ---- what is under the pointer ----
  SC.hit = function (wx, wy) {
    const ui = SC.ui, z = SC.cam.z;
    const hid = ui.hover || (ui.sel && ui.sel.type === 'node' ? ui.sel.id : null);
    if (hid && z > 0.2) {
      const n = SC.nodes.get(hid);
      if (n && n.vis) {
        const h = SC.handleOf(n);
        if ((wx - h.x) * (wx - h.x) + (wy - h.y) * (wy - h.y) <= h.r * h.r) return { type: 'handle', n: n };
      }
    }
    const list = SC.drawList;
    for (let i = list.length - 1; i >= 0; i--) {
      const n = list[i];
      if (wx >= n.x && wx <= n.x + n.w && wy >= n.y && wy <= n.y + n.h) {
        if (SC.lay.type === 'tree' && z >= LOD_FULL && SC.kidCount(n.id)) {
          const r = toggleRect(n);
          if (wx >= r.x - 3 && wx <= r.x + r.w + 3 && wy >= r.y - 3 && wy <= r.y + r.h + 3) return { type: 'toggle', n: n };
        }
        return { type: 'node', n: n };
      }
    }
    return null;
  };
  SC.hitEdge = function (wx, wy) {
    const tol = 8 / SC.cam.z, tol2 = tol * tol;
    let best = null, bd = tol2;
    for (const it of SC.edgeGeom) {
      const g = it.g;
      for (let i = 0; i <= 24; i++) {
        const t = i / 24, u = 1 - t;
        const x = u * u * u * g[0] + 3 * u * u * t * g[2] + 3 * u * t * t * g[4] + t * t * t * g[6];
        const y = u * u * u * g[1] + 3 * u * u * t * g[3] + 3 * u * t * t * g[5] + t * t * t * g[7];
        const d = (x - wx) * (x - wx) + (y - wy) * (y - wy);
        if (d < bd) { bd = d; best = it.e; }
      }
    }
    return best;
  };

  SC.drawNow = function () { if (raf) { cancelAnimationFrame(raf); raf = 0; } frame(performance.now()); };
  SC.camBusy = () => !!camAnim;
  SC.CONST = { TOP: TOP, STATUS: STATUS, PANEL_W: PANEL_W, TL_HEAD: TL_HEAD, ZMIN: ZMIN, ZMAX: ZMAX };
})(window.SC);
