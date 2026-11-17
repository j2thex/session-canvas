/* Session Canvas — data and saved state: talking to the server, filters, links, layout, search, undo. */
'use strict';
(function (SC) {
  const U = SC.U, L = SC.Layout;

  const meta = name => { const m = document.querySelector('meta[name="' + name + '"]'); return m ? m.getAttribute('content') : ''; };
  SC.token = meta('canvas-token');
  SC.dryRun = meta('canvas-dry-run') === '1';
  SC.version = meta('canvas-version') || '';
  SC.params = new URLSearchParams(location.search);
  SC.noSave = SC.params.has('nosave');
  SC.hooks = { layout: () => {}, data: () => {}, search: () => {}, saved: () => {}, undo: () => {} };

  SC.LAYOUTS = ['tree', 'timeline', 'free', 'status'];
  SC.KIND_LABEL = { you: 'You', helper: 'Helpers', auto: 'Automatic', desktop: 'Desktop app' };
  SC.KIND_ONE = { you: 'you', helper: 'helper', auto: 'automatic', desktop: 'desktop app' };
  const KIND_RANK = { you: 0, helper: 1, auto: 2, desktop: 3 };
  SC.EDGE_LABEL = { continued: 'Continued', fork: 'Fork (copy)', handover: 'Handover', helper: 'Helper', worktree: 'Worktree', manual: 'Your link' };

  // ---- server ----
  SC.api = {
    async get(path) {
      const r = await fetch(path, { cache: 'no-store' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || ('The server answered ' + r.status));
      return j;
    },
    async post(path, body) {
      const send = () => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Canvas-Token': SC.token }, body: JSON.stringify(body || {}) });
      let r = await send();
      if (r.status === 403 && await SC.api.renewToken()) r = await send();     // the Canvas was restarted: carry on without a reload
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || ('The server answered ' + r.status));
      return j;
    },
    /* After the Canvas server restarts it expects a new token; the page reads it from a fresh copy of itself. */
    async renewToken() {
      try {
        const html = await (await fetch('/', { cache: 'no-store' })).text();
        const m = /name="canvas-token" content="([^"]+)"/.exec(html);
        const d = /name="canvas-dry-run" content="([01])"/.exec(html);
        if (!m || m[1] === SC.token) return false;
        SC.token = m[1];
        if (d) SC.dryRun = d[1] === '1';
        return true;
      } catch (e) { return false; }
    },
  };
  SC.report = function (level, msg, extra) {
    try {
      fetch('/api/clientlog', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Canvas-Token': SC.token },
        body: JSON.stringify(Object.assign({ level: level, msg: String(msg).slice(0, 2000) }, extra || {})) }).catch(() => {});
    } catch (e) { /* nothing more to do */ }
  };
  window.addEventListener('error', e => SC.report('error', e.message, { where: (e.filename || '') + ':' + (e.lineno || 0), stack: e.error && e.error.stack ? String(e.error.stack) : '' }));
  window.addEventListener('unhandledrejection', e => SC.report('error', 'unhandled promise: ' + (e.reason && e.reason.message ? e.reason.message : e.reason), { stack: e.reason && e.reason.stack ? String(e.reason.stack) : '' }));

  // ---- saved state (lives in state.json on the server) ----
  const defaultFilters = () => ({ kinds: { you: true, helper: true, auto: true, desktop: true }, projects: [], from: null, to: null, commands: [], showHidden: false });
  const defaultView = () => ({ layout: 'tree', colorBy: 'week', theme: '', showEdges: true, cams: {}, filters: defaultFilters() });
  SC.defaultFilters = defaultFilters;
  SC.state = { rev: 0, view: defaultView(), positions: {}, order: {}, edges: [], removedEdges: [], notes: [], titles: {}, labels: {}, colors: {}, hidden: [], collapsed: [], settings: {}, marks: {} };

  SC.loadState = function (s) {
    const st = SC.state;
    for (const k of ['positions', 'order', 'titles', 'labels', 'colors', 'settings', 'marks']) if (s[k] && typeof s[k] === 'object' && !Array.isArray(s[k])) st[k] = s[k];
    for (const k of ['edges', 'removedEdges', 'notes', 'hidden', 'collapsed']) if (Array.isArray(s[k])) st[k] = s[k];
    st.rev = s.rev || 0;
    const v = defaultView(), sv = (s.view && typeof s.view === 'object') ? s.view : {};
    if (SC.LAYOUTS.includes(sv.layout)) v.layout = sv.layout;
    if (['week', 'project', 'kind'].includes(sv.colorBy)) v.colorBy = sv.colorBy;
    if (sv.theme === 'dark' || sv.theme === 'light') v.theme = sv.theme;
    if (typeof sv.showEdges === 'boolean') v.showEdges = sv.showEdges;
    if (sv.cams && typeof sv.cams === 'object') v.cams = sv.cams;
    if (sv.filters && typeof sv.filters === 'object') {
      const f = sv.filters;
      if (f.kinds && typeof f.kinds === 'object') for (const k of Object.keys(v.filters.kinds)) if (f.kinds[k] === false) v.filters.kinds[k] = false;
      if (Array.isArray(f.projects)) v.filters.projects = f.projects.filter(x => typeof x === 'string');
      if (Array.isArray(f.commands)) v.filters.commands = f.commands.filter(x => typeof x === 'string');
      if (typeof f.from === 'number') v.filters.from = f.from;
      if (typeof f.to === 'number') v.filters.to = f.to;
      v.filters.showHidden = !!f.showHidden;
    }
    st.view = v;
    st.notes = st.notes.filter(n => n && typeof n === 'object' && typeof n.id === 'string');
    st.edges = st.edges.filter(e => e && typeof e.from === 'string' && typeof e.to === 'string' && typeof e.id === 'string');
  };

  const dirty = new Set();
  let saving = false;
  SC.saveState = 'saved';
  async function flush() {
    if (!dirty.size || saving || SC.noSave) return;
    const keys = Array.from(dirty);
    dirty.clear();
    const patch = {};
    for (const k of keys) patch[k] = SC.state[k];
    saving = true;
    try {
      const r = await SC.api.post('/api/state', { patch: patch });
      SC.state.rev = r.rev;
      SC.saveState = 'saved';
    } catch (e) {
      for (const k of keys) dirty.add(k);
      SC.saveState = 'failed';
      setTimeout(saveSoon, 4000);
    } finally {
      saving = false;
      SC.hooks.saved();
      if (dirty.size && SC.saveState !== 'failed') saveSoon();
    }
  }
  const saveSoon = U.debounce(flush, 450);
  /* Write pending changes now (used when the very next request depends on them). */
  SC.flush = async function () { saveSoon.cancel(); await flush(); };
  /* Mark parts of the state as changed; they are written to state.json shortly after. */
  SC.touch = function () {
    for (let i = 0; i < arguments.length; i++) dirty.add(arguments[i]);
    if (SC.noSave) return;
    SC.saveState = 'saving';
    saveSoon();
  };
  window.addEventListener('pagehide', () => {
    if (!dirty.size || SC.noSave) return;
    const patch = {};
    dirty.forEach(k => { patch[k] = SC.state[k]; });
    try { navigator.sendBeacon('/api/state', new Blob([JSON.stringify({ token: SC.token, patch: patch })], { type: 'application/json' })); } catch (e) { /* closing anyway */ }
  });

  // ---- undo / redo: snapshots of what the person can change ----
  const UNDO_KEYS = ['positions', 'order', 'edges', 'removedEdges', 'notes', 'titles', 'labels', 'colors', 'hidden', 'collapsed', 'marks'];
  const undoStack = [], redoStack = [];
  const snap = () => { const o = {}; for (const k of UNDO_KEYS) o[k] = SC.state[k]; return JSON.stringify(o); };
  SC.checkpoint = function (label) {
    undoStack.push({ label: label, snap: snap() });
    if (undoStack.length > 80) undoStack.shift();
    redoStack.length = 0;
    SC.hooks.undo();
  };
  const restore = (from, to) => {
    const u = from.pop();
    if (!u) return null;
    to.push({ label: u.label, snap: snap() });
    Object.assign(SC.state, JSON.parse(u.snap));
    SC.touch.apply(null, UNDO_KEYS);
    SC.invalidate();
    SC.hooks.undo();
    return u.label;
  };
  SC.undo = () => restore(undoStack, redoStack);
  SC.redo = () => restore(redoStack, undoStack);
  SC.canUndo = () => undoStack.length > 0;
  SC.canRedo = () => redoStack.length > 0;
  SC.undoLabel = () => (undoStack.length ? undoStack[undoStack.length - 1].label : '');

  // ---- sessions ----
  SC.data = { sessions: [], byId: new Map(), edges: [], projects: [], generation: 0, home: '', defaultCwd: '', indexedAt: 0, commands: [] };
  SC.nodes = new Map();
  SC.lay = { type: 'tree', nodes: [], shown: [], edges: [], bands: [], bounds: { x0: 0, y0: 0, x1: 1000, y1: 600 }, fam: { parent: new Map(), children: new Map(), treeEdges: new Set() } };
  let edgeCache = null;
  SC.invalidate = function () { edgeCache = null; };

  /* The name on a card: yours if you renamed it, else the helper's intended name (no "W16·" tag), else Claude's title. */
  SC.baseName = s => s.name || s.title || '(untitled)';
  SC.titleOf = s => SC.state.titles[s.id] || SC.baseName(s);
  /* Where a card stands. Order = how much it needs you. `zone` is the name of its group in the Status layout. */
  SC.STATES = {
    'question': { label: 'ANSWER NEEDED', zone: 'Needs your answer', hint: 'you must answer or decide', color: '#b98cff', ink: '#1b1030', wait: true },
    'your-turn': { label: 'YOUR TURN', zone: 'Your turn', hint: 'ready for you: send, review or approve', color: '#f5a524', ink: '#231503', wait: true },
    'running': { label: 'RUNNING', zone: 'Running', hint: 'Claude is working on it now', color: '#38b6ff', ink: '#04202f' },
    'not-done': { label: 'NOT DONE', zone: 'Stopped, not done', hint: 'ended early', color: '#ef5b5b', ink: '#2a0707' },
    'done': { label: 'DONE', zone: 'Done', hint: 'nothing left for you', color: '#2fc98a', ink: '#04231a' },
    'replaced': { label: 'REPLACED', zone: 'Replaced', hint: 'a newer session took over', color: '#8792a6', ink: '#12161d' },
  };
  SC.STATE_ORDER = ['question', 'your-turn', 'running', 'not-done', 'done', 'replaced'];
  SC.STATUS = SC.STATES;        // the name used before v1.2
  const NO_STATE = { key: '', info: null, since: 0, by: null, mark: null, note: '' };
  /* The same rule as card_state() in indexer.py: a mark you made on the board wins while the report's header is
     the one it was made on; then `replaced-by` / `replaces`; then the report; else "running" while it is open. */
  SC.stateOf = function (s) {
    if (!SC.data.statusOn) return s.active ? Object.assign({}, NO_STATE, { key: 'running', info: SC.STATES.running, since: s.start }) : NO_STATE;
    const r = s.report || null, m = SC.state.marks[s.id];
    const mk = (key, extra) => Object.assign({ key: key, info: SC.STATES[key], since: (r && r.at) || s.end || s.start, by: null, mark: null, note: '' }, extra);
    if (m && (m.kind === 'done' || m.kind === 'sent' || m.kind === 'replaced') && (!m.sig || !r || m.sig === r.sig)) {
      if (m.kind === 'replaced') {
        const o = m.by ? SC.data.byId.get(m.by) : null;
        return mk('replaced', { mark: m, since: m.at || 0, by: o ? { id: o.id, name: SC.titleOf(o) } : null, note: 'you said so' });
      }
      return mk('done', { mark: m, since: m.at || 0, note: m.kind === 'sent' ? 'sent (you said so)' : 'marked done by you' });
    }
    if (s.replacedBy) {
      const o = s.replacedBy.id ? SC.data.byId.get(s.replacedBy.id) : null;
      return mk('replaced', { by: { id: o ? o.id : null, name: o ? SC.titleOf(o) : s.replacedBy.name }, note: 'its report says so' });
    }
    if (r) {
      if (r.status === 'your-turn' || r.status === 'question') {
        if (r.sent) return mk('done', { note: 'sent', sent: r.sent });
        return mk(r.status === 'question' || r.ask ? 'question' : 'your-turn');
      }
      if (r.status === 'not-done') return mk(s.active ? 'running' : 'not-done');
      return mk('done');
    }
    return s.active ? mk('running', { since: s.start }) : NO_STATE;
  };
  SC.stateKey = s => SC.stateOf(s).key;
  /* Mark a card by hand: 'done' | 'sent' | 'replaced' (by = the newer session's id). null = take the mark off. */
  SC.setMark = function (id, kind, by) {
    const s = SC.data.byId.get(id);
    if (!s) return false;
    SC.checkpoint(kind ? 'mark ' + (kind === 'replaced' ? 'replaced' : kind) : 'reopen');
    const marks = Object.assign({}, SC.state.marks);
    if (!kind) delete marks[id];
    else marks[id] = { kind: kind, by: kind === 'replaced' ? (by || null) : null, at: Date.now(), sig: (s.report && s.report.sig) || '' };
    SC.state.marks = marks;
    SC.touch('marks');
    return true;
  };
  /* Everything that waits on you, the one that has waited longest first. */
  SC.waiting = function () {
    const out = [], seen = new Set();
    for (const s of SC.data.sessions.slice().sort((a, b) => b.start - a.start || (a.id < b.id ? 1 : -1))) {
      const st = SC.stateOf(s);
      if (!(st.info && st.info.wait)) continue;
      const f = s.report && s.report.file;           // two sessions with the same report are one thing to do: the newer one
      if (f) { if (seen.has(f)) continue; seen.add(f); }
      out.push({ s: s, st: st });
    }
    out.sort((a, b) => a.st.since - b.st.since || (a.s.id < b.s.id ? -1 : 1));
    return out;
  };
  /* The latest from a session: where it stands, what is done, what is left; else the end of its last message. */
  SC.latestOf = function (s) {
    const r = s.report, st = SC.stateOf(s);
    if (st.key === 'replaced') return { status: 'replaced', text: 'Replaced by ' + (st.by ? st.by.name : 'a newer session') + (r && r.outcome ? ' · ' + r.outcome : '') };
    if (!r) return { status: st.key, text: (st.mark ? 'Marked done by you' + (s.last ? ' · ' : '') : '') + (s.last || '') };
    if (st.mark || st.sent) return { status: 'done', text: (st.mark && st.mark.kind === 'done' ? 'Marked done by you' : 'Sent') + (r.outcome ? ' · ' + r.outcome : '') };
    const nothing = !r.left || /^(nothing|none|no|nobody|n\/a|-)\b/i.test(r.left);
    const text = st.info && st.info.wait
      ? [r.left, r.outcome].filter(Boolean).join(' · Done so far: ')
      : [r.outcome, nothing ? '' : 'Left: ' + r.left].filter(Boolean).join(' · ');
    return { status: st.key, text: text || s.last || '' };
  };

  SC.applyData = function (p) {
    const d = SC.data;
    const before = new Set(d.byId.keys());
    const firstTime = d.generation === 0;
    d.sessions = p.sessions || [];
    d.edges = p.edges || [];
    d.projects = p.projects || [];
    d.generation = p.generation || 0;
    d.home = p.home || '';
    d.defaultCwd = p.defaultCwd || '';
    d.statusOn = !!p.statusOn;          // status reports are optional: off until a report folder is set (Advanced)
    if (!d.statusOn && SC.state.view.layout === 'status') SC.state.view.layout = 'tree';
    d.indexedAt = p.indexedAt || Date.now();
    d.errors = p.errors || [];
    d.byId = new Map();
    const now = p.now || Date.now();
    const cmd = new Map();
    const projKinds = new Map();
    const fresh = [];
    for (const s of d.sessions) {
      d.byId.set(s.id, s);
      s.week = U.weekStart(s.start);
      s.active = SC.isOpen(s, now);
      for (const c of s.commands) cmd.set(c, (cmd.get(c) || 0) + 1);
      let ks = projKinds.get(s.project);
      if (!ks) projKinds.set(s.project, ks = new Set());
      ks.add(s.kind);
      let n = SC.nodes.get(s.id);
      if (!n) {
        n = { id: s.id, x: 0, y: 0, vis: false, placed: false };
        SC.nodes.set(s.id, n);
        if (!firstTime && !before.has(s.id)) fresh.push(s.id);
      }
      n.s = s;
      n.start = s.start;
      n.compact = s.kind === 'auto';
      n.w = L.CARD.W;
      n.h = n.compact ? L.CARD.HC : L.CARD.H;
      n.prep = null;
    }
    for (const id of Array.from(SC.nodes.keys())) if (!d.byId.has(id)) SC.nodes.delete(id);
    d.commands = Array.from(cmd.entries()).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
    d.projKinds = projKinds;
    d.projRank = new Map(d.projects.map((pr, i) => [pr.key, i]));
    d.weeks = Array.from(new Set(d.sessions.map(s => s.week))).sort((a, b) => a - b);
    SC.invalidate();
    SC.prepSearch();
    return fresh;
  };

  SC.visibleSessions = function () {
    const f = SC.state.view.filters;
    const hidden = new Set(SC.state.hidden);
    const projects = f.projects.length ? new Set(f.projects) : null;
    const commands = f.commands.length ? new Set(f.commands) : null;
    const to = f.to != null ? U.addDays(f.to, 1) : null;
    return SC.data.sessions.filter(s => {
      if (!f.showHidden && hidden.has(s.id)) return false;
      if (f.kinds[s.kind] === false) return false;
      if (projects && !projects.has(s.project)) return false;
      if (f.from != null && s.end < f.from) return false;
      if (to != null && s.start >= to) return false;
      if (commands && !s.commands.some(c => commands.has(c))) return false;
      return true;
    });
  };
  SC.filterCount = function () {
    const f = SC.state.view.filters;
    let n = 0;
    for (const k of Object.keys(f.kinds)) if (f.kinds[k] === false) n++;
    if (f.projects.length) n++;
    if (f.from != null || f.to != null) n++;
    if (f.commands.length) n++;
    if (f.showHidden) n++;
    return n;
  };

  /* All links to draw: the ones found in the transcripts (minus those the person removed) plus the person's own. */
  SC.edges = function () {
    if (edgeCache) return edgeCache;
    const removed = new Set(SC.state.removedEdges);
    const out = [];
    for (const e of SC.data.edges) if (!removed.has(e.id)) out.push(e);
    for (const e of SC.state.edges) {
      if (SC.data.byId.has(e.from) && SC.data.byId.has(e.to)) out.push({ id: e.id, from: e.from, to: e.to, kind: 'manual', guess: false, why: 'Linked by you' });
    }
    edgeCache = out;
    return out;
  };
  SC.addLink = function (from, to) {
    if (from === to) return 'same';
    if (SC.edges().some(e => (e.from === from && e.to === to) || (e.from === to && e.to === from))) return 'exists';
    SC.checkpoint('link');
    SC.state.edges.push({ id: 'm:' + from + ':' + to, from: from, to: to, kind: 'manual' });
    SC.state.removedEdges = SC.state.removedEdges.filter(id => id !== 'a:' + from + ':' + to);
    SC.touch('edges', 'removedEdges');
    SC.invalidate();
    return 'ok';
  };
  SC.removeLink = function (edgeId) {
    SC.checkpoint('remove link');
    if (edgeId.indexOf('m:') === 0) {
      SC.state.edges = SC.state.edges.filter(e => e.id !== edgeId);
      SC.touch('edges');
    } else if (!SC.state.removedEdges.includes(edgeId)) {
      SC.state.removedEdges.push(edgeId);
      SC.touch('removedEdges');
    }
    SC.invalidate();
  };

  SC.laneOf = function (n) {
    const s = n.s, d = SC.data;
    const kinds = d.projKinds.get(s.project);
    const multi = kinds && kinds.size > 1;
    return { key: s.project + '|' + s.kind,
      label: s.projectLabel + (multi ? ' · ' + SC.KIND_LABEL[s.kind] : ''),
      rank: (d.projRank.get(s.project) || 0) * 10 + (KIND_RANK[s.kind] || 0) };
  };

  /* Work out where every card goes for the current layout and filters. */
  SC.relayout = function (opt) {
    opt = opt || {};
    const st = SC.state, layout = st.view.layout;
    const vis = SC.visibleSessions();
    const old = new Map();
    for (const n of SC.nodes.values()) {
      if (n.vis && n.placed) old.set(n.id, { x: n.x, y: n.y });
      n.vis = false;
    }
    const nodes = vis.map(s => SC.nodes.get(s.id));
    for (const n of nodes) n.st = SC.stateOf(n.s);          // where each card stands, worked out once per layout pass
    const hiddenIds = st.hidden.length ? new Set(st.hidden) : null;
    for (const n of nodes) n.hiddenShown = !!(hiddenIds && hiddenIds.has(n.id));      // shown faded via Filters
    const edges = SC.edges();
    let lay;
    if (layout === 'timeline') {
      lay = L.timeline(nodes, { order: st.order, laneOf: SC.laneOf });
      lay.fam = L.family(nodes, edges);
    } else if (layout === 'status') {
      lay = L.status(nodes, { order: SC.STATE_ORDER, states: SC.STATES });
      lay.fam = L.family(nodes, edges);
    } else if (layout === 'free') {
      if (!Object.keys(st.positions).length && nodes.length) SC.seedFree(nodes, edges);
      lay = L.free(nodes, st.positions);
      lay.fam = L.family(nodes, edges);
    } else {
      lay = L.tree(nodes, edges, { collapsed: new Set(st.collapsed) });
    }
    lay.nodes = nodes;
    lay.shown = nodes.filter(n => n.vis);
    if (layout === 'free') {                       // the card moved last lies on top of the ones it overlaps
      const pos = st.positions;
      lay.shown.sort((a, b) => ((pos[a.id] && pos[a.id].t) || 0) - ((pos[b.id] && pos[b.id].t) || 0));
    }
    lay.bounds = L.bounds(lay.shown);
    lay.edges = edges;
    SC.lay = lay;
    let moved = false;
    for (const n of lay.shown) {
      const o = old.get(n.id);
      if (opt.animate && o && (Math.abs(o.x - n.x) > 0.5 || Math.abs(o.y - n.y) > 0.5)) { n.ox = o.x - n.x; n.oy = o.y - n.y; moved = true; } else { n.ox = 0; n.oy = 0; }
      n.fresh = opt.animate && !o;
      n.placed = true;
    }
    SC.anim = (opt.animate && (moved || lay.shown.some(n => n.fresh))) ? { t0: performance.now(), dur: 360 } : null;
    SC.hooks.layout(opt);
    return lay;
  };

  /* First visit to the Free layout: start from the Tree arrangement so nothing is in a heap. */
  SC.seedFree = function (nodes, edges, from) {
    const pos = {};
    if (from === 'timeline') L.timeline(nodes, { order: SC.state.order, laneOf: SC.laneOf });
    else L.tree(nodes, edges, { collapsed: new Set() });
    for (const n of nodes) pos[n.id] = { x: Math.round(n.x), y: Math.round(n.y) };
    SC.state.positions = Object.assign({}, SC.state.positions, pos);
    SC.touch('positions');
  };

  // ---- search ----
  SC.search = { q: '', tokens: [], matches: new Map(), order: [], hiddenHits: 0, index: -1, seq: 0, loading: false, serverMs: null };
  SC.prepSearch = function () {
    const st = SC.state;
    for (const s of SC.data.sessions) {
      s._t = U.norm(SC.titleOf(s));
      s._k = U.norm(s.keywords.join(' '));
      s._x = U.norm([s.commands.join(' '), s.jira.join(' '), st.labels[s.id] || '', s.projectLabel, s.worktree || '', s.id, s.model || '', SC.KIND_LABEL[s.kind]].join(' '));
      s._a = U.norm(s.about);
      s._w = Array.from(new Set(U.words(s._t + ' ' + s._k)));
    }
  };
  const tokenize = q => {
    const out = [];
    const re = /"([^"]+)"|(\S+)/g;
    let m;
    while ((m = re.exec(U.norm(q)))) { const t = (m[1] || m[2] || '').trim(); if (t && !out.includes(t)) out.push(t); }
    return out.slice(0, 8);
  };
  SC.tokenize = tokenize;
  const localScore = (s, tokens) => {
    let total = 0;
    for (const t of tokens) {
      let sc = 0;
      const i = s._t.indexOf(t);
      if (i >= 0) sc = 10 + ((i === 0 || /[^a-z0-9]/.test(s._t[i - 1])) ? 4 : 0);
      if (sc < 8 && s._k.indexOf(t) >= 0) sc = 8;
      if (sc < 6 && s._x.indexOf(t) >= 0) sc = 6;
      if (sc < 3 && s._a.indexOf(t) >= 0) sc = 3;
      if (!sc && t.length >= 4) { for (const w of s._w) if (U.fuzzyPrefix(t, w)) { sc = 2.5; break; } }
      if (!sc) return 0;
      total += sc;
    }
    return total;
  };
  const rebuildOrder = () => {
    const S = SC.search;
    const visible = new Set(SC.visibleSessions().map(s => s.id));
    const all = Array.from(S.matches.entries()).sort((a, b) => b[1].score - a[1].score || SC.data.byId.get(b[0]).start - SC.data.byId.get(a[0]).start);
    S.order = all.filter(e => visible.has(e[0]) && SC.nodes.get(e[0]) && SC.nodes.get(e[0]).vis).map(e => e[0]);
    S.hiddenHits = all.length - S.order.length;
    if (S.index >= S.order.length) S.index = S.order.length - 1;
  };
  SC.rebuildSearchOrder = rebuildOrder;
  const fetchFull = U.debounce(async function (q, seq) {
    const S = SC.search;
    try {
      const r = await SC.api.get('/api/search?q=' + encodeURIComponent(q));
      if (seq !== S.seq) return;                       // the person typed something newer
      S.serverMs = r.ms;
      for (const hit of r.results) {
        if (!SC.data.byId.has(hit.id)) continue;
        const m = S.matches.get(hit.id);
        const bonus = 1 + Math.min(hit.score, 25) / 5;
        if (m) { m.score += bonus; m.snippet = hit.snippet; m.said = true; } else S.matches.set(hit.id, { score: bonus, snippet: hit.snippet, said: true, local: false });
      }
    } catch (e) { /* the instant results still stand */ }
    if (seq !== S.seq) return;
    S.loading = false;
    rebuildOrder();
    SC.hooks.search();
  }, 140);
  SC.setQuery = function (q) {
    const S = SC.search;
    S.q = q;
    S.seq++;
    S.tokens = tokenize(q);
    S.matches = new Map();
    S.index = -1;
    S.serverMs = null;
    if (!S.tokens.length) { S.order = []; S.hiddenHits = 0; S.loading = false; fetchFull.cancel(); SC.hooks.search(); return; }
    for (const s of SC.data.sessions) {
      const sc = localScore(s, S.tokens);
      if (sc > 0) S.matches.set(s.id, { score: sc * 3, snippet: '', said: false, local: true });
    }
    S.loading = true;
    rebuildOrder();
    SC.hooks.search();
    fetchFull(q, S.seq);
  };

  // ---- sticky notes ----
  SC.NOTE_COLORS = ['yellow', 'pink', 'green', 'blue', 'purple', 'orange'];
  SC.noteById = id => SC.state.notes.find(n => n.id === id);
  /* Where a note sits: beside its session when connected, otherwise where it was left in this layout. */
  SC.notePos = function (note, idx) {
    if (note.attach) {
      const n = SC.nodes.get(note.attach);
      if (n && n.vis) return { x: n.x + (typeof note.dx === 'number' ? note.dx : n.w + 34), y: n.y + (typeof note.dy === 'number' ? note.dy : -10), anchored: true };
    }
    const p = note.pos && note.pos[SC.state.view.layout];
    if (p && isFinite(p.x) && isFinite(p.y)) return { x: p.x, y: p.y, anchored: false };
    const b = SC.lay.bounds;
    return { x: b.x0 + (idx || 0) * 250, y: b.y0 - (note.h || 150) - 70, anchored: false, shelf: true };
  };
  SC.addNote = function (x, y, text) {
    SC.checkpoint('add note');
    const used = SC.state.notes.length;
    const note = { id: U.uid('n'), text: text || '', color: SC.NOTE_COLORS[used % SC.NOTE_COLORS.length], w: 220, h: 150, attach: null, pos: {}, created: Date.now(), updated: Date.now() };
    note.pos[SC.state.view.layout] = { x: Math.round(x), y: Math.round(y) };
    SC.state.notes.push(note);
    SC.touch('notes');
    return note;
  };

  // ---- opening sessions ----
  SC.APP_NAME = (document.querySelector('meta[name="canvas-name"]') || {}).content || 'Session Canvas';
  SC.spawn = body => SC.api.post('/api/spawn', body);

  /* Which sessions are open in a window right now (from Claude Code's own list, ~/.claude/sessions/).
     A session that changed in the last 3 minutes also counts, in case that list is missing. */
  SC.live = new Map();
  SC.liveKnown = false;      // true once the server has read Claude Code's list; until then "changed in the last 3 minutes" is the guess
  SC.isOpen = (s, now) => !!s && (SC.live.has(s.id) || ((!SC.liveKnown || s.kind === 'desktop') && (now || Date.now()) - s.mtime < 180000));
  SC.refreshLive = async function () {
    try {
      const r = await SC.api.get('/api/live');
      SC.live = new Map(Object.entries(r.live || {}));
      SC.liveKnown = !!r.available;
    } catch (e) { SC.liveKnown = false; return SC.live; }
    let changed = false;
    for (const s of SC.data.sessions) { const a = SC.isOpen(s); if (a !== s.active) { s.active = a; changed = true; } }
    if (changed && SC.invalidate) {          // a session started or stopped: its card may change group
      if (SC.afterStateChange && !SC.ui.drag && !SC.ui.editing) { SC.reprep(); SC.afterStateChange(true); }
      else { SC.invalidate(); if (SC.renderPanel) SC.renderPanel(true); }
    }
    return SC.live;
  };
})(window.SC);
