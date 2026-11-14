/* Session Canvas — what happens when you click, drag, type: board gestures, toolbar, search, filters, keyboard, start-up. */
'use strict';
(function (SC) {
  const U = SC.U, L = SC.Layout, E = U.esc;
  const $ = id => document.getElementById(id);
  const ui = SC.ui, canvas = SC.canvas, cam = SC.cam, stage = $('stage');
  const st = () => SC.state, view = () => SC.state.view;
  const undoAction = { label: 'Undo', fn: () => SC.doUndo() };

  // ---- selection, focus, jumping ----
  SC.select = function (sel, opts) {
    ui.sel = sel || null;
    if (!sel || sel.type !== 'edge') ui.edgeAt = null;
    SC.renderPanel();
    SC.syncNoteSelection();
    SC.renderEdgeBar();
    if (sel && sel.type === 'node' && !(opts && opts.noReveal)) {
      const n = SC.nodes.get(sel.id);
      if (n && n.vis) SC.reveal(n);
    }
    SC.requestRender();
  };

  const hist = [];
  let hi = -1;
  function familyOf(id) {
    const fam = SC.lay.fam, set = new Set([id]);
    let p = fam.parent.get(id), guard = 0;
    while (p !== undefined && guard++ < 2000) { set.add(p); p = fam.parent.get(p); }
    for (const c of L.descendants(fam, id)) set.add(c);
    for (const e of SC.edges()) { if (e.from === id) set.add(e.to); else if (e.to === id) set.add(e.from); }
    return set;
  }
  function updateNav() {
    $('btnBack').disabled = !(ui.focus ? hi > 0 : hi >= 0);
    $('btnFwd').disabled = !(hi < hist.length - 1);
  }
  SC.focusNode = function (id, fromHistory) {
    const n = SC.nodes.get(id);
    if (!n || !n.vis) return false;
    ui.focus = id;
    ui.family = familyOf(id);
    if (!fromHistory) {
      hist.length = hi + 1;
      if (hist[hist.length - 1] !== id) hist.push(id);
      hi = hist.length - 1;
    }
    SC.select({ type: 'node', id: id }, { noReveal: true });
    SC.centerOn(n, { minZ: 0.62 });
    SC.positionNotes();
    updateNav();
    return true;
  };
  SC.clearFocus = function () {
    if (!ui.focus) return;
    ui.focus = null;
    ui.family = null;
    SC.positionNotes();
    SC.renderPanel(true);
    updateNav();
    SC.requestRender();
  };
  function navFocus(dir) {
    if (!ui.focus && dir < 0 && hi >= 0 && SC.focusNode(hist[hi], true)) return;
    let i = hi + dir;
    while (i >= 0 && i < hist.length) {
      hi = i;
      if (SC.focusNode(hist[i], true)) return;
      i += dir;
    }
    updateNav();
  }

  /* Go to a card: unfold or un-filter it if needed, select it, bring it to the middle. */
  SC.jumpToNode = function (id, opts) {
    const n = SC.nodes.get(id);
    if (!n) return;
    if (!n.vis) {
      const fam = SC.lay.fam;
      if (SC.lay.nodes.indexOf(n) >= 0 && view().layout === 'tree') {
        let p = fam.parent.get(id), changed = false, guard = 0;
        while (p !== undefined && guard++ < 2000) {
          const i = st().collapsed.indexOf(p);
          if (i >= 0) { st().collapsed.splice(i, 1); changed = true; }
          p = fam.parent.get(p);
        }
        if (changed) { SC.touch('collapsed'); SC.afterStateChange(false); }
      }
      if (!n.vis) {
        if (st().hidden.includes(id)) {
          SC.toast('You hid that session.', { action: { label: 'Unhide it', fn: () => {
            SC.checkpoint('unhide');
            st().hidden = st().hidden.filter(x => x !== id);
            SC.touch('hidden');
            SC.afterStateChange(false);
            SC.jumpToNode(id);
          } } });
        } else {
          SC.toast('That session is hidden by your filters.', { action: { label: 'Show everything', fn: () => { clearFilters(); SC.jumpToNode(id); } } });
        }
        return;
      }
    }
    SC.select({ type: 'node', id: id }, { noReveal: true });
    SC.centerOn(n, { minZ: (opts && opts.minZ) || 0.62 });
  };

  SC.toggleCollapse = function (id) {
    if (view().layout !== 'tree' || !SC.kidCount(id)) return;
    SC.checkpoint('fold');
    const c = st().collapsed, i = c.indexOf(id);
    if (i >= 0) c.splice(i, 1); else c.push(id);
    SC.touch('collapsed');
    const n = SC.nodes.get(id), before = SC.toScreen(n.x, n.y);
    SC.afterStateChange(false);
    const after = SC.toScreen(n.x, n.y);         // keep the card you clicked under the pointer
    cam.x += (after.x - before.x) / cam.z;
    cam.y += (after.y - before.y) / cam.z;
    SC.camTouched();
  };

  /* Something the person can change has changed: lay out again and refresh every part of the screen. */
  SC.afterStateChange = function (animate) {
    SC.invalidate();
    SC.relayout({ animate: !!animate });
    SC.renderNotes();
    SC.rebuildSearchOrder();
    const sel = ui.sel;
    if (sel) {
      if (sel.type === 'node') { const n = SC.nodes.get(sel.id); if (!n || !n.vis) ui.sel = null; }
      else if (sel.type === 'note') { if (!SC.noteById(sel.id)) ui.sel = null; }
      else if (sel.type === 'edge') { if (!SC.edges().some(e => e.id === sel.id)) ui.sel = null; }
    }
    SC.renderPanel(true);
    SC.syncNoteSelection();
    SC.renderEdgeBar();
    renderSearchUi();
    renderStatus();
    renderLegend();
    renderFilterBadge();
    updateUndo();
    SC.requestRender();
  };
  SC.hooks.layout = function (opt) {
    if (ui.focus) {
      const n = SC.nodes.get(ui.focus);
      if (n && n.vis) ui.family = familyOf(ui.focus); else { ui.focus = null; ui.family = null; }
    }
    SC.positionNotes(opt && opt.animate);
    SC.warmup();
  };
  SC.hooks.saved = () => renderStatus();
  SC.hooks.undo = () => updateUndo();
  function updateUndo() {
    const b = $('btnUndo');
    b.disabled = !SC.canUndo();
    b.title = SC.canUndo() ? 'Undo: ' + SC.undoLabel() + ' (Cmd+Z)' : 'Nothing to undo yet';
  }
  SC.doUndo = function () {
    const label = SC.undo();
    if (label === null) { SC.toast('Nothing to undo'); return; }
    SC.prepSearch(); SC.reprep(); SC.afterStateChange(true);
    SC.toast('Undone: ' + label);
  };
  SC.doRedo = function () {
    const label = SC.redo();
    if (label === null) { SC.toast('Nothing to redo'); return; }
    SC.prepSearch(); SC.reprep(); SC.afterStateChange(true);
    SC.toast('Redone: ' + label);
  };

  // ---- drawing links by hand ----
  function banner(text) { const b = $('banner'); if (text) { b.textContent = text; b.hidden = false; } else b.hidden = true; }
  SC.startLinking = function (from) {
    ui.linking = { from: from };
    canvas.classList.add('linking');
    banner(from.type === 'note' ? 'Click the session this note belongs to  ·  Esc to cancel' : 'Click the session to link to  ·  Esc to cancel');
  };
  SC.cancelLinking = function () {
    if (!ui.linking) return;
    ui.linking = null;
    canvas.classList.remove('linking');
    banner('');
  };
  function completeLink(from, toId) {
    if (from.type === 'note') { SC.attachNote(from.id, toId); return; }
    const r = SC.addLink(from.id, toId);
    if (r === 'ok') { SC.afterStateChange(true); SC.toast('Linked', { action: undoAction }); }
    else if (r === 'exists') SC.toast('Those two are already linked');
  }
  SC.deleteSelection = function () {
    const sel = ui.sel;
    if (!sel) return;
    if (sel.type === 'note') SC.deleteNote(sel.id);
    else if (sel.type === 'edge') {
      SC.removeLink(sel.id);
      SC.select(null);
      SC.afterStateChange(true);
      SC.toast('Link removed', { action: undoAction });
    }
  };
  function hideSelected() {
    const sel = ui.sel;
    if (!sel || sel.type !== 'node') return;
    SC.checkpoint('hide');
    if (!st().hidden.includes(sel.id)) st().hidden.push(sel.id);
    SC.touch('hidden');
    SC.select(null);
    SC.afterStateChange(true);
    SC.toast('Hidden. Bring it back from Filters.', { action: undoAction });
  }

  // ---- layouts ----
  SC.setLayout = function (name, force) {
    const v = view();
    if (!['tree', 'timeline', 'free'].includes(name) || (v.layout === name && !force)) return;
    v.cams[v.layout] = { x: cam.x, y: cam.y, z: cam.z };
    const changed = v.layout !== name;
    v.layout = name;
    SC.touch('view');
    if (ui.sel && ui.sel.type === 'edge') ui.sel = null;
    SC.afterStateChange(true);
    syncToolbar();
    const selNode = ui.sel && ui.sel.type === 'node' ? SC.nodes.get(ui.sel.id) : null;
    if (selNode && selNode.vis) SC.centerOn(selNode, { minZ: 0.5 });
    else if (changed) restoreCam(true);
  };
  function restoreCam(animate) {
    const c = view().cams[view().layout];
    if (c && isFinite(c.x) && isFinite(c.y) && c.z > 0) SC.setCam(c.x, c.y, c.z, animate); else SC.homeView(animate);
  }
  function syncToolbar() {
    const v = view();
    document.querySelectorAll('#layouts button').forEach(b => b.classList.toggle('on', b.dataset.layout === v.layout));
    $('colorBy').value = v.colorBy;
    renderFilterBadge();
  }
  function goToday() {
    if (view().layout === 'timeline') { SC.homeView(true); return; }
    let newest = null;
    for (const n of SC.lay.shown) if (!newest || n.s.start > newest.s.start) newest = n;
    if (newest) SC.jumpToNode(newest.id);
  }
  function zoomBy(f) { const r = SC.viewRect(); SC.zoomAt(r.x + r.w / 2, r.y + r.h / 2, f); }
  function newNoteAt(wx, wy) {
    const note = SC.addNote(wx, wy, '');
    SC.renderNotes();
    SC.select({ type: 'note', id: note.id });
    SC.editNote(note.id);
  }
  function newNoteCentered() {
    const r = SC.viewRect(), k = st().notes.length % 6;
    const w = SC.toWorld(r.x + r.w / 2, r.y + r.h / 2);
    newNoteAt(w.x - 110 + k * 26, w.y - 75 + k * 26);
  }

  // ---- gestures on the board ----
  function setHover(id) {
    if (id === ui.hover) return;
    ui.hover = id;
    if (id) SC.showHover(id); else SC.hideHover();
    SC.requestRender();
  }
  function hoverAt(sx, sy) {
    const w = SC.toWorld(sx, sy), h = SC.hit(w.x, w.y);
    canvas.classList.toggle('pointing', !!h && h.type !== 'handle' && !ui.linking);
    canvas.classList.toggle('linking', !!ui.linking || (!!h && h.type === 'handle'));
    setHover(h ? h.n.id : null);
  }

  canvas.addEventListener('pointerdown', e => {
    if (e.button !== 0 && e.button !== 1) return;
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    $('results').hidden = true;
    SC.hideHover(true);
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events have no capture */ }
    const w = SC.toWorld(e.clientX, e.clientY);
    const h = e.button === 0 ? SC.hit(w.x, w.y) : null;
    if (ui.linking && e.button === 0) {
      const from = ui.linking.from;
      SC.cancelLinking();
      if (h && h.type !== 'handle' && !(from.type === 'node' && from.id === h.n.id)) completeLink(from, h.n.id);
      e.preventDefault();
      return;
    }
    if (h && h.type === 'handle') {
      ui.drag = { type: 'link', from: { type: 'node', id: h.n.id }, x0: h.n.x + h.n.w, y0: h.n.y + h.n.h / 2, x: w.x, y: w.y, over: null };
      canvas.classList.add('linking');
    } else if (h && h.type === 'toggle') {
      ui.drag = { type: 'toggle', id: h.n.id };
    } else if (h && h.type === 'node') {
      ui.drag = { type: 'node', id: h.n.id, sx: e.clientX, sy: e.clientY, wx: w.x, wy: w.y, ox: h.n.x, oy: h.n.y, moved: false, shift: e.shiftKey };
    } else {
      ui.drag = { type: 'pan', sx: e.clientX, sy: e.clientY, cx: cam.x, cy: cam.y, moved: false };
      canvas.classList.add('panning');
    }
    e.preventDefault();
  });

  function beginNodeDrag(d) {
    const n = SC.nodes.get(d.id), layout = view().layout;
    d.mode = 'pan'; d.cx = cam.x; d.cy = cam.y;
    if (!n) return;
    if (layout === 'free') {
      d.mode = 'free';
      SC.checkpoint('move');
      const ids = [d.id].concat(d.shift ? L.descendants(SC.lay.fam, d.id) : []);
      d.group = ids.map(id => SC.nodes.get(id)).filter(m => m && m.vis).map(m => ({ n: m, x: m.x, y: m.y }));
      n.dragging = true;
      canvas.classList.add('moving');
    } else if (layout === 'timeline') {
      const lane = SC.lay.lanes.find(l => l.key === n.lane), day = SC.lay.dayAt.get(n.day);
      const list = lane && lane.cells.get(n.day);
      if (lane && day && list && list.length > 1) {
        d.mode = 'reorder'; d.lane = lane; d.day = day; d.list = list.slice(); d.index = d.list.indexOf(n); d.changed = false;
        n.dragging = true;
        canvas.classList.add('moving');
      }
    }
    if (d.mode === 'pan') canvas.classList.add('panning');
  }

  function onMove(e) {
    const d = ui.drag;
    if (!d) { if (e.target === canvas) hoverAt(e.clientX, e.clientY); return; }
    const w = SC.toWorld(e.clientX, e.clientY);
    if (d.type === 'pan') {
      if (!d.moved && Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) < 4) return;
      d.moved = true;
      cam.x = d.cx - (e.clientX - d.sx) / cam.z;
      cam.y = d.cy - (e.clientY - d.sy) / cam.z;
      SC.camTouched();
    } else if (d.type === 'node') {
      if (!d.moved) {
        if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) < 5) return;
        d.moved = true;
        beginNodeDrag(d);
      }
      const n = SC.nodes.get(d.id);
      if (d.mode === 'pan') {
        cam.x = d.cx - (e.clientX - d.sx) / cam.z;
        cam.y = d.cy - (e.clientY - d.sy) / cam.z;
        SC.camTouched();
      } else if (d.mode === 'free') {
        const dx = w.x - d.wx, dy = w.y - d.wy;
        for (const g of d.group) { g.n.x = Math.round((g.x + dx) / 4) * 4; g.n.y = Math.round((g.y + dy) / 4) * 4; }
        SC.positionNotes();
      } else if (d.mode === 'reorder' && n) {
        n.x = d.ox + (w.x - d.wx);
        n.y = d.oy + (w.y - d.wy);
        const idx = L.slotIndexAt(d.lane, d.day, n.x + n.w / 2, n.y + n.h / 2, d.list.length);
        if (idx !== d.index) {
          d.list.splice(d.index, 1);
          d.list.splice(idx, 0, n);
          d.index = idx;
          d.changed = true;
          d.list.forEach((m, i) => { if (m !== n) { const p = L.slot(d.lane, d.day, i); m.x = p.x; m.y = p.y; } });
        }
        SC.positionNotes();
      }
    } else if (d.type === 'link') {
      d.x = w.x; d.y = w.y;
      const h = SC.hit(w.x, w.y);
      d.over = (h && h.type !== 'handle' && !(d.from.type === 'node' && d.from.id === h.n.id)) ? h.n.id : null;
      SC.requestRender();
    } else if (d.type === 'note' || d.type === 'noteResize') {
      SC.dragNote(d, e);
    } else if (d.type === 'minimap') {
      miniMove(e);
    }
  }

  function onUp(e) {
    const d = ui.drag;
    if (!d) return;
    ui.drag = null;
    canvas.classList.remove('panning', 'moving');
    if (!ui.linking) canvas.classList.remove('linking');
    const w = SC.toWorld(e.clientX, e.clientY);
    if (d.type === 'pan') {
      if (!d.moved) {
        const edge = view().showEdges !== false ? SC.hitEdge(w.x, w.y) : null;
        if (edge) { ui.edgeAt = { x: w.x, y: w.y }; SC.select({ type: 'edge', id: edge.id }); ui.edgeAt = { x: w.x, y: w.y }; SC.renderEdgeBar(); }
        else SC.select(null);
      }
    } else if (d.type === 'toggle') {
      SC.toggleCollapse(d.id);
    } else if (d.type === 'node') {
      const n = SC.nodes.get(d.id);
      if (!d.moved) { SC.select({ type: 'node', id: d.id }); return; }
      if (n) n.dragging = false;
      if (d.mode === 'free') {
        const stamp = Date.now();
        for (const g of d.group) st().positions[g.n.id] = { x: g.n.x, y: g.n.y, t: stamp };
        SC.touch('positions');
        SC.relayout();
        updateUndo();
      } else if (d.mode === 'reorder') {
        if (d.changed && n) {
          SC.checkpoint('reorder');
          st().order[n.cell] = d.list.map(m => m.id);
          SC.touch('order');
        }
        SC.relayout();
        updateUndo();
      }
      SC.requestRender();
    } else if (d.type === 'link') {
      if (d.over) completeLink(d.from, d.over);
      SC.requestRender();
    } else if (d.type === 'note' || d.type === 'noteResize') {
      SC.dropNote(d);
    }
  }
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
  window.addEventListener('pointercancel', onUp);
  canvas.addEventListener('pointerleave', () => { if (!ui.drag) { setHover(null); canvas.classList.remove('pointing'); } });

  canvas.addEventListener('dblclick', e => {
    const w = SC.toWorld(e.clientX, e.clientY), h = SC.hit(w.x, w.y);
    if (h && h.type === 'node') { if (ui.focus === h.n.id) SC.clearFocus(); else SC.focusNode(h.n.id); }
    else if (!h) newNoteAt(w.x - 20, w.y - 20);
  });

  /* Wheel: a mouse wheel zooms, two fingers on the trackpad move the board, pinch (or Ctrl/Cmd + wheel) zooms. */
  let wheelMode = 'pan', wheelAt = 0;
  stage.addEventListener('wheel', e => {
    if (e.target.tagName === 'TEXTAREA') return;
    e.preventDefault();
    const now = performance.now();
    if (now - wheelAt > 220) {
      const trackpad = e.wheelDeltaY ? (e.wheelDeltaY === -3 * e.deltaY) : (e.deltaMode === 0 && (e.deltaX !== 0 || Math.abs(e.deltaY) < 40));
      wheelMode = trackpad ? 'pan' : 'zoom';
    }
    wheelAt = now;
    SC.hideHover(true);
    if (e.ctrlKey || e.metaKey) {
      SC.zoomAt(e.clientX, e.clientY, Math.exp(-U.clamp(e.deltaY, -80, 80) * (wheelMode === 'zoom' ? 0.004 : 0.012)));
    } else if (wheelMode === 'zoom') {
      const notches = e.wheelDeltaY ? U.clamp(e.wheelDeltaY / 120, -3, 3) : -U.clamp(e.deltaY, -80, 80) / 40;
      SC.zoomAt(e.clientX, e.clientY, Math.exp(notches * 0.16));
    } else {
      const dx = e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX, dy = e.shiftKey && !e.deltaX ? 0 : e.deltaY;
      cam.x += dx / cam.z;
      cam.y += dy / cam.z;
      SC.camTouched();
    }
  }, { passive: false });

  // Safari reports a trackpad pinch as "gesture" events instead of Ctrl+wheel.
  let pinch = 1;
  stage.addEventListener('gesturestart', e => { e.preventDefault(); pinch = 1; });
  stage.addEventListener('gesturechange', e => { e.preventDefault(); if (e.scale > 0) { SC.zoomAt(e.clientX, e.clientY, e.scale / pinch); pinch = e.scale; } });
  stage.addEventListener('gestureend', e => e.preventDefault());

  // ---- minimap and zoom buttons ----
  const mini = $('minimap');
  function miniMove(e) {
    const r = mini.getBoundingClientRect();
    const w = SC.miniToWorld(e.clientX - r.left, e.clientY - r.top), vr = SC.viewRect();
    SC.setCam(w.x - (vr.x + vr.w / 2) / cam.z, w.y - (vr.y + vr.h / 2) / cam.z, cam.z, false);
  }
  mini.addEventListener('pointerdown', e => {
    e.preventDefault();
    try { mini.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
    ui.drag = { type: 'minimap' };
    miniMove(e);
  });
  $('zoomIn').onclick = () => zoomBy(1.25);
  $('zoomOut').onclick = () => zoomBy(0.8);
  $('zoomPct').onclick = () => zoomBy(1 / cam.z);
  let shownPct = '';
  SC.hooks.frame = function () {
    const pct = Math.round(cam.z * 100) + '%';
    if (pct !== shownPct) { shownPct = pct; $('zoomPct').textContent = pct; }
    SC.positionBars();
  };

  // ---- search ----
  const q = $('q'), results = $('results');
  function marks(text, tokens) {
    const raw = String(text || ''), low = raw.toLowerCase();
    const spans = [];
    for (const t of tokens) {
      if (t.length < 2) continue;
      let i = 0;
      while ((i = low.indexOf(t, i)) >= 0) { spans.push([i, i + t.length]); i += t.length; }
    }
    if (!spans.length) return E(raw);
    spans.sort((a, b) => a[0] - b[0]);
    let out = '', pos = 0;
    for (const sp of spans) {
      if (sp[0] < pos) continue;
      out += E(raw.slice(pos, sp[0])) + '<mark>' + E(raw.slice(sp[0], sp[1])) + '</mark>';
      pos = sp[1];
    }
    return out + E(raw.slice(pos));
  }
  function renderResults() {
    const S = SC.search;
    if (!S.tokens.length) { results.hidden = true; return; }
    const rows = [];
    S.order.slice(0, 50).forEach((id, i) => {
      const s = SC.data.byId.get(id), m = S.matches.get(id);
      rows.push('<button class="res' + (i === S.index ? ' cur' : '') + '" data-id="' + id + '" data-i="' + i + '"><div class="t"><span class="tt">' + marks(SC.titleOf(s), S.tokens) +
        '</span><span class="when">' + E(U.fmtDay(s.start)) + '</span></div><div class="s">' + (m.snippet ? marks(m.snippet, S.tokens) : marks(U.short(s.about, 170), S.tokens)) + '</div></button>');
    });
    let foot = '';
    if (!S.order.length) foot = '<div class="hint">' + (S.loading ? 'Searching everything that was said…' : 'Nothing found. Try another word; small typos are fine.') + '</div>';
    else if (S.order.length > 50) foot = '<div class="hint">' + (S.order.length - 50) + ' more: keep typing to narrow it down</div>';
    if (S.hiddenHits) foot += '<div class="hint">' + S.hiddenHits + ' more hidden by filters or folded away · <button class="linkbtn" data-a="showall">Show everything</button></div>';
    results.innerHTML = rows.join('') + foot;
    const curEl = results.querySelector('.res.cur');
    if (curEl) curEl.scrollIntoView({ block: 'nearest' });
  }
  function renderSearchUi() {
    const S = SC.search, n = S.order.length;
    $('qcount').textContent = S.tokens.length ? (n ? ((S.index >= 0 ? (S.index + 1) + ' / ' : '') + n + (n === 1 ? ' match' : ' matches')) : (S.loading ? '…' : 'no match')) : '';
    $('qprev').hidden = $('qnext').hidden = !n;
    if (!results.hidden) renderResults();
  }
  SC.hooks.search = function () { renderSearchUi(); SC.positionNotes(); SC.requestRender(); };
  function showResults() { if (SC.search.tokens.length) { results.hidden = false; renderResults(); } else results.hidden = true; }
  function jumpMatch(dir) {
    const S = SC.search;
    if (!S.order.length) return;
    S.index = S.index < 0 ? (dir > 0 ? 0 : S.order.length - 1) : (S.index + dir + S.order.length) % S.order.length;
    results.hidden = true;                 // get the list out of the way of the card we jump to
    SC.jumpToNode(S.order[S.index]);
    renderSearchUi();
  }
  /* Up / Down move the highlight in the list without leaving it. */
  function moveInList(dir) {
    const S = SC.search;
    if (!S.order.length) return;
    if (results.hidden) { showResults(); return; }
    const max = Math.min(S.order.length, 50) - 1;
    S.index = U.clamp(S.index < 0 ? (dir > 0 ? 0 : max) : S.index + dir, 0, max);
    renderSearchUi();
    SC.requestRender();
  }
  function clearSearch() { q.value = ''; SC.setQuery(''); results.hidden = true; }
  SC.setSearchText = function (text) { q.value = text; SC.setQuery(text); q.focus(); showResults(); };
  q.addEventListener('input', () => { SC.setQuery(q.value); showResults(); });
  q.addEventListener('focus', showResults);
  q.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const S = SC.search;
      if (!results.hidden && S.index >= 0 && S.order.length) { results.hidden = true; SC.jumpToNode(S.order[S.index]); renderSearchUi(); }
      else jumpMatch(e.shiftKey ? -1 : 1);
    }
    else if (e.key === 'ArrowDown') { e.preventDefault(); moveInList(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveInList(-1); }
  });
  $('qnext').onclick = () => jumpMatch(1);
  $('qprev').onclick = () => jumpMatch(-1);
  results.addEventListener('pointerdown', e => e.preventDefault());       // keep the typing cursor in the box
  results.addEventListener('click', e => {
    if (e.target.dataset.a === 'showall') { clearFilters(); st().collapsed = []; SC.touch('collapsed'); SC.afterStateChange(true); return; }
    const b = e.target.closest('.res');
    if (!b) return;
    SC.search.index = +b.dataset.i;
    results.hidden = true;
    SC.jumpToNode(b.dataset.id);
    renderSearchUi();
  });

  // ---- filters ----
  const filtersEl = $('filters');
  function tog(kind, value, label, count, on) {
    return '<button class="tog' + (on ? ' on' : '') + '" data-f="' + kind + '" data-v="' + E(value) + '">' + E(label) + (count !== null ? '<span class="n">' + count + '</span>' : '') + '</button>';
  }
  function renderFilters() {
    const f = view().filters, d = SC.data;
    const kc = {};
    for (const s of d.sessions) kc[s.kind] = (kc[s.kind] || 0) + 1;
    const hiddenIds = st().hidden.filter(id => d.byId.has(id));
    let h = '<h4>Type of session</h4><div class="row">' + ['you', 'helper', 'auto', 'desktop'].filter(k => kc[k]).map(k => tog('kind', k, SC.KIND_LABEL[k], kc[k], f.kinds[k] !== false)).join('') + '</div>';
    if (d.projects.length > 1) h += '<h4>Project <span style="text-transform:none;letter-spacing:0;font-weight:400">(none picked = all)</span></h4><div class="row">' + d.projects.map(p => tog('project', p.key, p.label, p.count, f.projects.includes(p.key))).join('') + '</div>';
    h += '<h4>Dates</h4><div class="row"><input type="date" id="fFrom" value="' + (f.from != null ? U.dateInputValue(f.from) : '') + '"><span>to</span><input type="date" id="fTo" value="' + (f.to != null ? U.dateInputValue(f.to) : '') + '"></div>' +
      '<div class="row" style="margin-top:6px">' + [['today', 'Today'], ['week', 'This week'], ['7', 'Last 7 days'], ['30', 'Last 30 days'], ['all', 'All time']].map(p => '<button class="tog" data-f="preset" data-v="' + p[0] + '">' + p[1] + '</button>').join('') + '</div>';
    if (d.commands.length) h += '<h4>Command used</h4><div class="row">' + d.commands.slice(0, 20).map(c => tog('command', c[0], c[0].replace(/^\/[^:]+:/, '/'), c[1], f.commands.includes(c[0]))).join('') + '</div>';
    h += '<h4>Hidden sessions</h4>';
    if (hiddenIds.length) {
      h += '<div class="row">' + tog('showHidden', '1', 'Show them faded', hiddenIds.length, f.showHidden) + '<button class="linkbtn" data-f="unhideAll">Unhide all</button></div><div class="hiddenlist">' +
        hiddenIds.slice(0, 40).map(id => '<div><span>' + E(SC.titleOf(d.byId.get(id))) + '</span><button class="linkbtn" data-f="unhide" data-v="' + id + '">Unhide</button></div>').join('') + '</div>';
    } else h += '<div style="color:var(--muted)">None. Use “Hide” on a card to tidy the board.</div>';
    h += '<div class="foot"><span style="color:var(--muted)">Showing ' + SC.lay.shown.length + ' of ' + d.sessions.length + '</span><button class="linkbtn" data-f="clear">Clear filters</button></div>';
    filtersEl.innerHTML = h;
  }
  function renderFilterBadge() {
    const n = SC.filterCount(), b = $('filterCount');
    b.hidden = !n;
    b.textContent = n;
    $('btnFilters').classList.toggle('on', n > 0);
  }
  function filtersChanged() {
    SC.touch('view');
    SC.afterStateChange(true);
    if (!filtersEl.hidden) renderFilters();
  }
  function clearFilters() {
    view().filters = SC.defaultFilters();
    filtersChanged();
  }
  SC.toggleCommandFilter = function (cmd) {
    const f = view().filters, i = f.commands.indexOf(cmd);
    if (i >= 0) f.commands.splice(i, 1); else f.commands.push(cmd);
    filtersChanged();
    if (i < 0) SC.toast('Showing only sessions that used ' + cmd, { action: { label: 'Show all again', fn: () => { view().filters.commands = []; filtersChanged(); } } });
  };
  filtersEl.addEventListener('click', e => {
    const b = e.target.closest('[data-f]');
    if (!b) return;
    const f = view().filters, v = b.dataset.v, now = Date.now();
    switch (b.dataset.f) {
      case 'kind': f.kinds[v] = f.kinds[v] === false; break;
      case 'project': { const i = f.projects.indexOf(v); if (i >= 0) f.projects.splice(i, 1); else f.projects.push(v); break; }
      case 'command': { const i = f.commands.indexOf(v); if (i >= 0) f.commands.splice(i, 1); else f.commands.push(v); break; }
      case 'showHidden': f.showHidden = !f.showHidden; break;
      case 'preset':
        if (v === 'all') { f.from = null; f.to = null; }
        else if (v === 'today') { f.from = U.startOfDay(now); f.to = U.startOfDay(now); }
        else if (v === 'week') { f.from = U.weekStart(now); f.to = U.startOfDay(now); }
        else { f.from = U.addDays(U.startOfDay(now), -(+v - 1)); f.to = U.startOfDay(now); }
        break;
      case 'unhide': SC.checkpoint('unhide'); st().hidden = st().hidden.filter(x => x !== v); SC.touch('hidden'); break;
      case 'unhideAll': SC.checkpoint('unhide all'); st().hidden = []; f.showHidden = false; SC.touch('hidden'); break;
      case 'clear': view().filters = SC.defaultFilters(); break;
      default: return;
    }
    filtersChanged();
  });
  filtersEl.addEventListener('change', e => {
    const f = view().filters;
    if (e.target.id === 'fFrom') f.from = U.parseDateInput(e.target.value);
    else if (e.target.id === 'fTo') f.to = U.parseDateInput(e.target.value);
    else return;
    filtersChanged();
  });
  $('btnFilters').onclick = () => {
    if (filtersEl.hidden) {
      renderFilters();
      filtersEl.style.left = Math.max(8, Math.min($('btnFilters').getBoundingClientRect().left, window.innerWidth - 356)) + 'px';
      filtersEl.hidden = false;
    } else filtersEl.hidden = true;
  };
  document.addEventListener('pointerdown', e => {
    if (!filtersEl.hidden && !filtersEl.contains(e.target) && !$('btnFilters').contains(e.target)) filtersEl.hidden = true;
    if (!results.hidden && !$('search').contains(e.target)) results.hidden = true;
  }, true);

  // ---- legend and status line ----
  function renderLegend() {
    const v = view(), d = SC.data, rows = [];
    let items = [];
    if (v.colorBy === 'kind') items = ['you', 'helper', 'auto', 'desktop'].filter(k => d.sessions.some(s => s.kind === k)).map(k => [SC.KIND_COLOR[k], SC.KIND_LABEL[k]]);
    else if (v.colorBy === 'project') items = d.projects.map((p, i) => [SC.PALETTE[i % SC.PALETTE.length], p.label]);
    else items = d.weeks.slice(-8).map(w => [SC.PALETTE[(d.weeks.indexOf(w) * 5) % SC.PALETTE.length], U.fmtDate(w)]);
    if (items.length) rows.push('<div class="lrow"><span>' + (v.colorBy === 'week' ? 'Week of' : 'Colour') + '</span>' + items.map(it => '<span><i style="background:' + it[0] + '"></i>' + E(it[1]) + '</span>').join('') + '</div>');
    const kinds = Array.from(new Set((SC.lay.edges || []).map(e => e.kind)));
    if (kinds.length && v.showEdges !== false) {
      rows.push('<div class="lrow"><span>Links</span>' + ['continued', 'fork', 'handover', 'helper', 'worktree', 'manual'].filter(k => kinds.includes(k)).map(k => '<span><i class="ln" style="border-color:' + SC.EDGE_COLOR[k] + '"></i>' + SC.EDGE_LABEL[k] + '</span>').join('') +
        ((SC.lay.edges || []).some(e => e.guess) ? '<span><i class="ln dash" style="border-color:var(--muted)"></i>a guess</span>' : '') + '</div>');
    }
    $('legend').innerHTML = rows.join('');
  }
  function renderStatus() {
    const d = SC.data, lay = SC.lay;
    let links = 0;
    for (const e of (lay.edges || [])) { const a = SC.nodes.get(e.from), b = SC.nodes.get(e.to); if (a && b && a.vis && b.vis) links++; }
    const save = SC.noSave ? 'Preview: changes are not saved' : SC.saveState === 'saving' ? 'Saving…' : SC.saveState === 'failed' ? '<span class="bad">Not saved. Is the Canvas still running? (scripts/canvas.sh)</span>' : 'All changes saved';
    $('status').innerHTML = '<span><b>' + lay.shown.length + '</b> of ' + d.sessions.length + ' sessions</span><span>' + links + ' links</span>' +
      (st().notes.length ? '<span>' + st().notes.length + (st().notes.length === 1 ? ' note' : ' notes') + '</span>' : '') +
      (st().hidden.length ? '<span>' + st().hidden.length + ' hidden</span>' : '') +
      '<span>' + save + '</span><span>Looked for new sessions ' + E(U.ago(d.indexedAt)) + '</span>' +
      (serverDown ? '<span class="bad">The Canvas server is not answering</span>' : '') +
      '<span class="sp"></span>' +
      (SC.dryRun ? '<span class="bad">TEST MODE: buttons show the command instead of opening Terminal</span>' : '') +
      (SC.params.has('debug') ? '<span>draw ' + SC.perf.avg.toFixed(1) + ' ms (max ' + SC.perf.max.toFixed(1) + ')</span>' : '');
  }

  // ---- new sessions appear by themselves ----
  let refreshing = false, serverDown = false, lastRefresh = Date.now();
  function applyNewData(p, manual) {
    const fresh = SC.applyData(p);
    SC.clearDetails();
    SC.reprep();
    SC.afterStateChange(false);
    if (fresh.length) SC.toast(fresh.length + (fresh.length === 1 ? ' new session' : ' new sessions'), { action: { label: 'Show', fn: () => SC.jumpToNode(fresh[fresh.length - 1]) } });
    else if (manual) SC.toast('Up to date');
  }
  async function refresh(manual) {
    if (refreshing) return;
    refreshing = true;
    $('btnRescan').classList.add('busy');
    try {
      if (manual) await SC.api.post('/api/rescan', {});
      const p = await SC.api.get('/api/sessions?gen=' + SC.data.generation + (manual ? '' : '&rescan=1'));
      serverDown = false;
      if (p.ready && !p.unchanged) applyNewData(p, manual);
      else if (manual) SC.toast('Nothing new');
      if (p.indexedAt) SC.data.indexedAt = p.indexedAt;
    } catch (e) {
      serverDown = true;
      if (manual) SC.toast('The Canvas server is not answering. Start it again with scripts/canvas.sh', { error: true });
    }
    lastRefresh = Date.now();
    refreshing = false;
    $('btnRescan').classList.remove('busy');
    renderStatus();
  }
  SC.refresh = refresh;
  setInterval(() => { if (document.visibilityState === 'visible') refresh(false); }, 60000);
  setInterval(renderStatus, 15000);
  SC.refreshLive();
  setInterval(() => { if (document.visibilityState === 'visible') SC.refreshLive(); }, 20000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && Date.now() - lastRefresh > 20000) refresh(false); });

  // ---- toolbar ----
  $('layouts').addEventListener('click', e => { const b = e.target.closest('button[data-layout]'); if (b) SC.setLayout(b.dataset.layout); });
  $('colorBy').addEventListener('change', e => { view().colorBy = e.target.value; SC.touch('view'); SC.recolor(); renderLegend(); if (ui.sel) SC.renderPanel(true); e.target.blur(); });
  $('btnNote').onclick = newNoteCentered;
  $('btnSession').onclick = () => SC.openNewSessionDialog();
  $('btnBack').onclick = () => navFocus(-1);
  $('btnFwd').onclick = () => navFocus(1);
  $('btnUndo').onclick = () => SC.doUndo();
  $('btnFit').onclick = () => SC.fitAll();
  $('btnToday').onclick = goToday;
  $('btnRescan').onclick = () => refresh(true);
  $('btnHelp').onclick = () => SC.openHelp();
  $('btnTheme').onclick = () => {
    const next = SC.themeName() === 'dark' ? 'light' : 'dark';
    view().theme = next;
    SC.touch('view');
    SC.setTheme(next);
    renderLegend();
    if (ui.sel) SC.renderPanel(true);
  };

  // ---- keyboard ----
  function arrow(dx, dy) {
    const sel = ui.sel && ui.sel.type === 'node' ? SC.nodes.get(ui.sel.id) : null;
    if (!sel || !sel.vis) { cam.x += dx * 110 / cam.z; cam.y += dy * 110 / cam.z; SC.camTouched(); return; }
    const cx = sel.x + sel.w / 2, cy = sel.y + sel.h / 2;
    let best = null, bs = Infinity;
    for (const n of SC.lay.shown) {
      if (n === sel) continue;
      const ox = n.x + n.w / 2 - cx, oy = n.y + n.h / 2 - cy;
      const along = ox * dx + oy * dy;
      if (along <= 1) continue;
      const across = Math.abs(ox * dy) + Math.abs(oy * dx);
      if (across > along * 2.4 + 70) continue;
      const score = along + across * 2.6;
      if (score < bs) { bs = score; best = n; }
    }
    if (best) SC.select({ type: 'node', id: best.id });
  }
  function onEsc() {
    if (ui.modal) { SC.closeModal(); return; }
    if (ui.linking) { SC.cancelLinking(); return; }
    if (ui.drag && ui.drag.type === 'link') { ui.drag = null; canvas.classList.remove('linking'); SC.requestRender(); return; }
    if (!filtersEl.hidden) { filtersEl.hidden = true; return; }
    if (document.activeElement === q) { if (q.value) clearSearch(); else q.blur(); results.hidden = true; return; }
    if (ui.sel) { SC.select(null); return; }
    if (ui.focus) { SC.clearFocus(); return; }
    if (SC.search.tokens.length) { clearSearch(); return; }
    SC.hideHover(true);
  }
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); onEsc(); return; }      // Esc is ours: close / clear / cancel
    if (ui.modal) return;
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && (e.key === 'z' || e.key === 'Z')) { if (typing) return; e.preventDefault(); if (e.shiftKey) SC.doRedo(); else SC.doUndo(); return; }
    if (mod && (e.key === 'k' || e.key === 'f')) { e.preventDefault(); q.focus(); q.select(); return; }
    if (typing || mod || e.altKey) return;
    const sel = ui.sel;
    let used = true;
    switch (e.key) {
      case '/': q.focus(); q.select(); break;
      case 'f': case 'F': SC.fitAll(); break;
      case 't': case 'T': goToday(); break;
      case '1': SC.setLayout('tree'); break;
      case '2': SC.setLayout('timeline'); break;
      case '3': SC.setLayout('free'); break;
      case 'n': case 'N': newNoteCentered(); break;
      case 's': case 'S': SC.openNewSessionDialog(); break;
      case 'r': case 'R': refresh(true); break;
      case '0': zoomBy(1 / cam.z); break;
      case '+': case '=': zoomBy(1.25); break;
      case '-': case '_': zoomBy(0.8); break;
      case '[': navFocus(-1); break;
      case ']': navFocus(1); break;
      case '?': SC.openHelp(); break;
      case 'Enter':
        if (sel && sel.type === 'node') { if (ui.focus === sel.id) SC.clearFocus(); else SC.focusNode(sel.id); }
        else if (sel && sel.type === 'note') SC.editNote(sel.id);
        else used = false;
        break;
      case 'l': case 'L': if (sel && sel.type === 'node') SC.startLinking({ type: 'node', id: sel.id }); else SC.toast('Click a card first, then press L and click the card to link to.'); break;
      case 'c': case 'C': if (sel && sel.type === 'node') SC.toggleCollapse(sel.id); break;
      case 'h': case 'H': hideSelected(); break;
      case 'Delete': case 'Backspace': SC.deleteSelection(); break;
      case 'ArrowLeft': arrow(-1, 0); break;
      case 'ArrowRight': arrow(1, 0); break;
      case 'ArrowUp': arrow(0, -1); break;
      case 'ArrowDown': arrow(0, 1); break;
      default: used = false;
    }
    if (used) e.preventDefault();
  });

  // ---- start ----
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function showProgress(p, err) {
    if (err) { $('loadMsg').textContent = 'Could not read the sessions: ' + err; return; }
    const total = (p && p.total) || 0, done = (p && p.done) || 0;
    $('loadMsg').textContent = total ? 'Reading your sessions… ' + done + ' of ' + total : 'Reading your sessions…';
    $('loadBar').style.width = (total ? Math.max(8, Math.round(done / total * 100)) : 8) + '%';
  }
  async function boot() {
    SC.resize();
    window.addEventListener('resize', () => { SC.resize(); SC.positionBars(); });
    let saved = {};
    try { saved = await SC.api.get('/api/state'); } catch (e) { SC.toast('Could not read your saved board. Starting fresh.', { error: true }); }
    SC.loadState(saved);
    const P = SC.params, v = view();
    if (['tree', 'timeline', 'free'].includes(P.get('layout'))) v.layout = P.get('layout');
    if (['week', 'project', 'kind'].includes(P.get('color'))) v.colorBy = P.get('color');
    const sysLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
    SC.setTheme(P.get('theme') || v.theme || (sysLight ? 'light' : 'dark'));
    let p = await SC.api.get('/api/sessions');
    while (!p.ready) { showProgress(p.progress, p.error); await sleep(250); p = await SC.api.get('/api/sessions'); }
    $('loadBar').style.width = '100%';
    SC.applyData(p);
    syncToolbar();
    SC.afterStateChange(false);
    if (P.has('fit')) SC.fitAll(false); else if (P.has('home')) SC.homeView(false); else restoreCam(false);
    if (P.get('q')) { q.value = P.get('q'); SC.setQuery(q.value); if (P.has('results')) showResults(); }
    if (P.get('select')) {
      const id = P.get('select') === 'newest' ? (SC.lay.shown.slice().sort((a, b) => b.s.start - a.s.start)[0] || {}).id : P.get('select');
      if (id && SC.nodes.has(id)) SC.jumpToNode(id);
    }
    if (P.get('focus') && SC.nodes.has(P.get('focus'))) SC.focusNode(P.get('focus'));
    $('loading').classList.add('done');
    setTimeout(() => { $('loading').hidden = true; }, 300);
    if (saved.recovered) SC.toast('Your saved board was damaged, so the backup was used.', { error: true });
    if (p.errors && p.errors.length) SC.report('warn', 'index: ' + p.errors.join(' | '));
    updateNav();
    SC.drawNow();
    window.__canvasReady = true;
    if (P.has('setup') || (!(SC.state.settings || {}).setupDone && !P.has('nosetup') && !P.has('nosave'))) setTimeout(() => SC.openSetup(0), 350);   // after the loading screen is gone
  }

  /* Handles for the automatic checks (tests/browser_check.py); harmless in normal use. */
  SC.debug = {
    rect(id) { const n = SC.nodes.get(id); if (!n) return null; const a = SC.toScreen(n.x, n.y); return { x: a.x, y: a.y, w: n.w * cam.z, h: n.h * cam.z, vis: !!n.vis, on: !!n.on }; },
    summary() {
      return { layout: view().layout, shown: SC.lay.shown.length, total: SC.data.sessions.length, edges: (SC.lay.edges || []).length, zoom: cam.z, cam: { x: cam.x, y: cam.y },
        sel: ui.sel, focus: ui.focus, matches: SC.search.order.length, notes: st().notes.length, hidden: st().hidden.length, saveState: SC.saveState,
        drawn: SC.drawList.length, perf: SC.perf, panelOpen: !!ui.panelOpen, linking: !!ui.linking };
    },
    /* Draw `frames` frames while panning and zooming; reports how long drawing takes. */
    async bench(frames, zoom) {
      frames = frames || 120;
      const times = [], gaps = [];
      const c0 = { x: cam.x, y: cam.y, z: cam.z };
      const b = SC.lay.bounds, bw = b.x1 - b.x0, bh = b.y1 - b.y0;
      let last = performance.now(), cards = 0, cardsMax = 0;
      for (let i = 0; i < frames; i++) {
        const t = i / frames;
        const z = zoom || (0.3 + 0.6 * (0.5 + 0.5 * Math.sin(t * Math.PI * 4)));
        // wander over the part of the board that has cards, so every frame has real work to do
        const wx = b.x0 + bw * (0.5 + 0.32 * Math.sin(t * 6.283)), wy = b.y0 + bh * (0.5 + 0.4 * Math.sin(t * 6.283 * 2 + 1));
        SC.setCam(wx - SC.vw / 2 / z, wy - SC.vh / 2 / z, z, false);
        const t0 = performance.now();
        SC.drawNow();
        times.push(performance.now() - t0);
        cards += SC.drawList.length;
        cardsMax = Math.max(cardsMax, SC.drawList.length);
        await new Promise(r => requestAnimationFrame(r));
        const now = performance.now();
        gaps.push(now - last);
        last = now;
      }
      SC.setCam(c0.x, c0.y, c0.z, false);
      times.sort((a, b2) => a - b2);
      gaps.sort((a, b2) => a - b2);
      const avg = a => a.reduce((s, x) => s + x, 0) / a.length;
      return { frames: frames, drawAvg: +avg(times).toFixed(2), drawP95: +times[Math.floor(times.length * 0.95)].toFixed(2), drawMax: +times[times.length - 1].toFixed(2),
        frameAvg: +avg(gaps).toFixed(2), frameP95: +gaps[Math.floor(gaps.length * 0.95)].toFixed(2), fps: +(1000 / avg(gaps)).toFixed(1),
        cards: Math.round(cards / frames), cardsMax: cardsMax };
    },
  };

  boot().catch(e => {
    SC.report('error', 'boot: ' + (e && e.message ? e.message : e), { stack: e && e.stack ? String(e.stack) : '' });
    $('loadMsg').textContent = 'Something went wrong while starting: ' + (e && e.message ? e.message : e);
  });
})(window.SC);
