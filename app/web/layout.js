/* Session Canvas — where every card goes. Pure functions: nodes in, positions out. */
'use strict';
(function (SC) {
  const U = SC.U;
  const L = {};
  SC.Layout = L;

  const CARD = L.CARD = { W: 252, H: 126, HC: 78, GX: 22, GY: 16 };
  const PRI = { manual: 0, continued: 1, fork: 2, handover: 3, helper: 4, worktree: 5 };
  const byStart = (a, b) => a.start - b.start || (a.id < b.id ? -1 : 1);

  /* One parent per session (the strongest link wins), never a loop. */
  L.family = function (nodes, edges) {
    const byId = new Map();
    for (const n of nodes) byId.set(n.id, n);
    const cand = new Map();
    for (const e of edges) {
      if (e.from === e.to || !byId.has(e.from) || !byId.has(e.to)) continue;
      let a = cand.get(e.to);
      if (!a) cand.set(e.to, a = []);
      a.push(e);
    }
    const rank = e => (PRI[e.kind] === undefined ? 9 : PRI[e.kind]) + (e.guess ? 0.5 : 0);
    const parent = new Map(), children = new Map(), treeEdges = new Set();
    const loops = (child, from) => {
      let p = from, guard = 0;
      while (p !== undefined && guard++ < 100000) { if (p === child) return true; p = parent.get(p); }
      return false;
    };
    for (const n of nodes.slice().sort(byStart)) {
      const cs = cand.get(n.id);
      if (!cs) continue;
      cs.sort((a, b) => rank(a) - rank(b));
      for (const e of cs) {
        if (loops(n.id, e.from)) continue;
        parent.set(n.id, e.from);
        treeEdges.add(e.id);
        let ch = children.get(e.from);
        if (!ch) children.set(e.from, ch = []);
        ch.push(n.id);
        break;
      }
    }
    for (const ch of children.values()) ch.sort((a, b) => byStart(byId.get(a), byId.get(b)));
    return { parent, children, treeEdges, byId };
  };

  L.descendants = function (fam, id) {
    const out = [];
    const walk = x => { for (const c of (fam.children.get(x) || [])) { out.push(c); walk(c); } };
    walk(id);
    return out;
  };

  /* TREE: one band per week (newest on top). In a band: families (parent above its children), then
     single sessions in a grid, then the small automatic ones. */
  L.tree = function (nodes, edges, opts) {
    opts = opts || {};
    const collapsed = opts.collapsed || new Set();
    const fam = L.family(nodes, edges);
    const parent = fam.parent, children = fam.children, byId = fam.byId;
    const VGAP = 58, FAM_GAP = 70, SHELF_GAP = 40, BAND_GAP = 110;
    const kids = id => (collapsed.has(id) ? [] : (children.get(id) || []));

    for (const n of nodes) { n.vis = true; n.depth = 0; n.unplaced = false; }
    const hide = id => { for (const c of (children.get(id) || [])) { byId.get(c).vis = false; hide(c); } };
    for (const id of collapsed) if (byId.has(id)) hide(id);

    let area = 0;
    for (const n of nodes) if (n.vis) area += (n.w + CARD.GX) * (n.h + CARD.GY + 24);
    const maxW = opts.maxW || U.clamp(Math.sqrt(area * 1.9), 2700, 6600);

    const sw = new Map();
    const subW = id => {
      const n = byId.get(id), ch = kids(id);
      let w = n.w;
      if (ch.length) {
        let sum = -CARD.GX;
        for (const c of ch) sum += subW(c) + CARD.GX;
        w = Math.max(n.w, sum);
      }
      sw.set(id, w);
      return w;
    };
    const levels = (id, d, arr) => { arr[d] = Math.max(arr[d] || 0, byId.get(id).h); for (const c of kids(id)) levels(c, d + 1, arr); };
    const place = (id, x0, d, ys) => {
      const n = byId.get(id), ch = kids(id), w = sw.get(id);
      n.x = Math.round(x0 + (w - n.w) / 2);
      n.y = ys[d];
      n.depth = d;
      if (ch.length) {
        let sum = -CARD.GX;
        for (const c of ch) sum += sw.get(c) + CARD.GX;
        let cx = x0 + (w - sum) / 2;
        for (const c of ch) { place(c, cx, d + 1, ys); cx += sw.get(c) + CARD.GX; }
      }
    };

    const bandMap = new Map();
    for (const n of nodes) {
      if (parent.has(n.id)) continue;
      const wk = U.weekStart(n.start);
      let b = bandMap.get(wk);
      if (!b) bandMap.set(wk, b = { week: wk, fams: [], singles: [], compact: [] });
      if ((children.get(n.id) || []).length) b.fams.push(n);
      else if (n.h < CARD.H) b.compact.push(n);
      else b.singles.push(n);
    }
    const weeks = Array.from(bandMap.keys()).sort((a, b) => b - a);
    const bands = [];
    let y = 0;
    for (const wk of weeks) {
      const b = bandMap.get(wk);
      const y0 = y;
      let maxX = 0;
      if (b.fams.length) {
        b.fams.sort(byStart);
        let x = 0, shelfH = 0;
        for (const r of b.fams) {
          const w = subW(r.id);
          const lv = [];
          levels(r.id, 0, lv);
          const ys = [];
          let yy = 0;
          for (let d = 0; d < lv.length; d++) { ys[d] = yy; yy += lv[d] + VGAP; }
          const h = yy - VGAP;
          if (x > 0 && x + w > maxW) { y += shelfH + SHELF_GAP; x = 0; shelfH = 0; }
          place(r.id, x, 0, ys.map(v => v + y));
          x += w + FAM_GAP;
          shelfH = Math.max(shelfH, h);
          maxX = Math.max(maxX, x - FAM_GAP);
        }
        y += shelfH + SHELF_GAP;
      }
      for (const group of [b.singles, b.compact]) {
        if (!group.length) continue;
        group.sort(byStart);
        const colW = CARD.W + CARD.GX;
        const cols = Math.max(1, Math.floor((maxW + CARD.GX) / colW));
        const rowH = group[0].h + CARD.GY;
        for (let i = 0; i < group.length; i++) {
          group[i].x = (i % cols) * colW;
          group[i].y = y + Math.floor(i / cols) * rowH;
        }
        maxX = Math.max(maxX, Math.min(group.length, cols) * colW - CARD.GX);
        y += Math.ceil(group.length / cols) * rowH - CARD.GY + SHELF_GAP;
      }
      y -= SHELF_GAP;
      bands.push({ key: wk, y0: y0, y1: y, x0: 0, x1: maxX, label: 'Week of ' + U.fmtDate(wk), count: 0 });
      y += BAND_GAP;
    }
    for (const n of nodes) {
      if (!n.vis) continue;
      for (const b of bands) if (n.y >= b.y0 && n.y < b.y1 + 1) { b.count++; break; }
    }
    return { type: 'tree', fam: fam, bands: bands };
  };

  /* TIMELINE: one column per day (time runs left to right), one lane per project and kind of session. */
  L.TL = { PADX: 16, PADT: 46, PADB: 18, EMPTY_W: 52, LANE_GAP: 26 };   // PADT leaves room for the lane's name
  L.timeline = function (nodes, opts) {
    opts = opts || {};
    const T = L.TL;
    const now = opts.now || Date.now();
    const today = U.startOfDay(now);
    for (const n of nodes) { n.vis = true; n.depth = 0; n.unplaced = false; }
    const laneMap = new Map();
    let minDay = Infinity, maxDay = today;
    for (const n of nodes) {
      n.day = U.startOfDay(n.start);
      if (n.day < minDay) minDay = n.day;
      if (n.day > maxDay) maxDay = n.day;
      const l = opts.laneOf(n);
      let lane = laneMap.get(l.key);
      if (!lane) laneMap.set(l.key, lane = { key: l.key, label: l.label, rank: l.rank, cells: new Map(), count: 0, h: 0 });
      lane.count++;
      lane.h = Math.max(lane.h, n.h);
      n.lane = l.key;
      let c = lane.cells.get(n.day);
      if (!c) lane.cells.set(n.day, c = []);
      c.push(n);
    }
    if (!isFinite(minDay)) minDay = today;
    const lanes = Array.from(laneMap.values()).sort((a, b) => a.rank - b.rank || (a.label < b.label ? -1 : 1));
    for (const lane of lanes) lane.maxRows = lane.h < CARD.H ? 8 : 5;

    const days = [];
    const dayAt = new Map();
    let x = 0, guard = 0;
    for (let d = minDay; d <= maxDay && guard++ < 4000; d = U.addDays(d, 1)) {
      let cols = 0, count = 0;
      for (const lane of lanes) {
        const c = lane.cells.get(d);
        if (c) { count += c.length; cols = Math.max(cols, Math.ceil(c.length / lane.maxRows)); }
      }
      const w = count ? cols * (CARD.W + CARD.GX) - CARD.GX + 2 * T.PADX : T.EMPTY_W;
      const dt = new Date(d);
      const day = { t: d, key: U.dayKey(d), x0: x, x1: x + w, w: w, count: count, weekend: U.isWeekend(d),
        today: d === today, monday: dt.getDay() === 1, dom: dt.getDate() };
      days.push(day);
      dayAt.set(d, day);
      x += w;
    }
    let y = 0;
    for (const lane of lanes) {
      let rows = 1;
      for (const c of lane.cells.values()) rows = Math.max(rows, Math.min(c.length, lane.maxRows));
      lane.y0 = y;
      lane.y1 = y + T.PADT + T.PADB + rows * (lane.h + CARD.GY) - CARD.GY;
      y = lane.y1 + T.LANE_GAP;
      for (const entry of lane.cells) {
        const day = dayAt.get(entry[0]), list = entry[1];
        const key = lane.key + '|' + day.key;
        const ord = opts.order && opts.order[key];
        list.sort((a, b) => {
          if (ord) {
            const ia = ord.indexOf(a.id), ib = ord.indexOf(b.id);
            if (ia >= 0 || ib >= 0) { if (ia < 0) return 1; if (ib < 0) return -1; return ia - ib; }
          }
          return byStart(a, b);
        });
        for (let i = 0; i < list.length; i++) {
          const p = L.slot(lane, day, i);
          list[i].x = p.x; list[i].y = p.y; list[i].cell = key; list[i].cellIndex = i;
        }
      }
    }
    return { type: 'timeline', lanes: lanes, days: days, dayAt: dayAt, width: x, height: Math.max(0, y - T.LANE_GAP), today: today };
  };

  L.slot = function (lane, day, i) {
    const col = Math.floor(i / lane.maxRows), row = i % lane.maxRows;
    return { x: day.x0 + L.TL.PADX + col * (CARD.W + CARD.GX), y: lane.y0 + L.TL.PADT + row * (lane.h + CARD.GY) };
  };

  /* Which slot of a timeline cell is under a point (used while dragging a card to reorder it). */
  L.slotIndexAt = function (lane, day, wx, wy, count) {
    const col = Math.max(0, Math.floor((wx - day.x0 - L.TL.PADX + CARD.GX / 2) / (CARD.W + CARD.GX)));
    const row = U.clamp(Math.round((wy - lane.y0 - L.TL.PADT - lane.h / 2) / (lane.h + CARD.GY)), 0, lane.maxRows - 1);
    return U.clamp(col * lane.maxRows + row, 0, Math.max(0, count - 1));
  };

  /* FREE: wherever the person put each card. Cards with no saved place wait in a column on the left. */
  L.free = function (nodes, positions) {
    let minX = Infinity, minY = Infinity;
    const missing = [];
    for (const n of nodes) {
      n.vis = true; n.depth = 0; n.unplaced = false;
      const p = positions && positions[n.id];
      if (p && isFinite(p.x) && isFinite(p.y)) {
        n.x = p.x; n.y = p.y;
        if (n.x < minX) minX = n.x;
        if (n.y < minY) minY = n.y;
      } else missing.push(n);
    }
    if (missing.length) {
      if (!isFinite(minX)) { minX = 0; minY = 0; }
      missing.sort((a, b) => byStart(b, a));
      const x = minX - CARD.W - 150;
      let y = minY;
      for (const n of missing) { n.x = x; n.y = y; n.unplaced = true; y += n.h + CARD.GY; }
    }
    return { type: 'free', inbox: missing.length ? { x: minX - CARD.W - 150, y: minY, count: missing.length } : null };
  };

  L.bounds = function (nodes) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) {
      if (!n.vis) continue;
      if (n.x < x0) x0 = n.x;
      if (n.y < y0) y0 = n.y;
      if (n.x + n.w > x1) x1 = n.x + n.w;
      if (n.y + n.h > y1) y1 = n.y + n.h;
    }
    if (!isFinite(x0)) return { x0: 0, y0: 0, x1: 1000, y1: 600, empty: true };
    return { x0: x0, y0: y0, x1: x1, y1: y1 };
  };
})(window.SC);
