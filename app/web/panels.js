/* Session Canvas — the parts made of normal page elements: details panel, hover card, sticky notes, dialogs, toasts. */
'use strict';
(function (SC) {
  const U = SC.U, E = U.esc;
  const $ = id => document.getElementById(id);
  const ui = SC.ui;
  const panel = $('panel'), hover = $('hovercard'), notesEl = $('notes'), notebar = $('notebar'), edgebar = $('edgebar');
  const cardbar = $('cardbar'), waitEl = $('waitlist');
  SC.noteXY = new Map();

  // ---- toasts and dialogs ----
  SC.toast = function (msg, opt) {
    opt = opt || {};
    const el = document.createElement('div');
    el.className = 'toast' + (opt.error ? ' err' : '');
    el.textContent = msg;
    if (opt.action) {
      const b = document.createElement('button');
      b.textContent = opt.action.label;
      b.onclick = () => { el.remove(); opt.action.fn(); };
      el.appendChild(b);
    }
    const box = $('toasts');
    box.appendChild(el);
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(() => el.remove(), opt.ms || (opt.error ? 7000 : (opt.action ? 6000 : 3200)));
  };
  SC.modal = function (html, opt) {
    const m = $('modal');
    m.innerHTML = '<div class="dlg' + (opt && opt.wide ? ' wide' : '') + '" role="dialog" aria-modal="true">' + html + '</div>';
    m.hidden = false;
    ui.modal = true;
    SC.hideHover(true);
    const first = m.querySelector('[data-autofocus]') || m.querySelector('.btn.accent') || m.querySelector('button');
    if (first) first.focus();
    return m.firstChild;
  };
  SC.closeModal = function () {
    const m = $('modal');
    m.hidden = true;
    m.innerHTML = '';
    ui.modal = false;
    if (ui.modalDone) { const f = ui.modalDone; ui.modalDone = null; f(null); }
  };
  $('modal').addEventListener('pointerdown', e => { if (e.target === $('modal')) SC.closeModal(); });
  /* Ask a question with buttons; resolves with the chosen value (or null when closed). */
  SC.ask = function (title, bodyHtml, buttons) {
    return new Promise(resolve => {
      const dlg = SC.modal('<h3>' + E(title) + '</h3>' + bodyHtml + '<div class="btns">' +
        buttons.map((b, i) => '<button class="btn ' + (b.cls || '') + '" data-i="' + i + '"' + (b.focus ? ' data-autofocus' : '') + '>' + E(b.label) + '</button>').join('') + '</div>');
      ui.modalDone = resolve;
      dlg.querySelector('.btns').addEventListener('click', e => {
        const b = e.target.closest('button[data-i]');
        if (!b) return;
        ui.modalDone = null;
        SC.closeModal();
        resolve(buttons[+b.dataset.i].value);
      });
    });
  };

  // ---- opening sessions ----
  function showPlan(r, what) {
    const open = (r.open || []).map(a => (/[\s"']/.test(a) ? "'" + a.replace(/'/g, "'\\''") + "'" : a)).join(' ');
    const dlg = SC.modal(
      '<h3>' + (SC.dryRun ? 'Test mode: nothing was opened' : 'The command') + '</h3>' +
      '<p class="muted">This is exactly what ' + (SC.dryRun ? 'would run' : 'runs') + ' to open ' + E(what) + '.</p>' +
      (r.warnings && r.warnings.length ? '<div class="warnbox">' + r.warnings.map(E).join('<br>') + '</div>' : '') +
      '<p><b>Paste-able command</b></p><pre id="planCmd">' + E(r.command) + '</pre>' +
      '<p><b>Launcher script</b> <span class="muted">' + E(U.homePath(r.launcher, SC.data.home)) + '</span></p><pre>' + E(r.script) + '</pre>' +
      '<p><b>How the window is opened</b></p><pre>' + E(open) + '</pre>' +
      '<div class="btns"><button class="btn" data-a="copy">Copy command</button><button class="btn accent" data-a="close" data-autofocus>Close</button></div>', { wide: true });
    dlg.querySelector('.btns').addEventListener('click', e => {
      const a = e.target.dataset.a;
      if (a === 'copy') U.copy(r.command).then(ok => SC.toast(ok ? 'Command copied' : 'Could not copy', { error: !ok }));
      if (a === 'close') SC.closeModal();
    });
  }
  SC.doSpawn = async function (body, what) {
    // The very first time, the Mac shows a box asking for permission; say so if the answer takes a moment.
    const slow = SC.dryRun ? 0 : setTimeout(() => SC.toast('Waiting for your Mac… If it asks whether this may control Terminal, click OK (it asks only once).', { ms: 20000 }), 2500);
    try {
      const r = await SC.spawn(body);
      clearTimeout(slow);
      ui.lastSpawn = r;
      if (r.dryRun) { showPlan(r, what); return r; }
      if (r.ok) {
        SC.toast('Opening ' + what + ' in ' + r.terminal + '…');
        for (const w of (r.warnings || [])) SC.toast(w, { error: true });
      } else {
        const canSwitch = r.terminal !== 'Ghostty' && (r.installed || []).includes('Ghostty');
        const dlg = SC.modal('<h3>It did not open</h3><p>' + E(r.message) + '</p>' +
          '<p class="muted">' + (r.copied ? 'The command is on your clipboard: paste it into any terminal window.' : 'You can also run this in any terminal window:') + '</p>' +
          '<pre>' + E(r.command) + '</pre>' +
          (canSwitch ? '<p class="muted">Ghostty needs no permission from the Mac. “Use Ghostty” switches to it from now on (change it back under ? → Settings).</p>' : '') +
          '<div class="btns"><button class="btn" data-a="copy">Copy command</button>' +
          (canSwitch ? '<button class="btn" data-a="ghostty">Use Ghostty</button>' : '') +
          '<button class="btn" data-a="retry">Try again</button><button class="btn accent" data-a="close" data-autofocus>Close</button></div>');
        dlg.querySelector('.btns').addEventListener('click', e => {
          const a = e.target.dataset.a;
          if (a === 'copy') U.copy(r.command).then(() => SC.toast('Command copied'));
          if (a === 'close') SC.closeModal();
          if (a === 'retry') { SC.closeModal(); SC.doSpawn(body, what); }
          if (a === 'ghostty') {
            SC.state.settings.terminal = 'Ghostty';
            SC.touch('settings');
            SC.closeModal();
            Promise.resolve(SC.flush()).then(() => SC.doSpawn(body, what));
          }
        });
      }
      return r;
    } catch (e) {
      clearTimeout(slow);
      SC.toast(e.message || 'Could not open it', { error: true });
      return null;
    }
  };
  async function copyCommand(body) {
    try {
      const r = await SC.spawn(Object.assign({ dryRun: true }, body));
      const ok = await U.copy(r.command);
      SC.toast(ok ? 'Command copied: paste it into a terminal' : 'Could not copy', { error: !ok });
    } catch (e) { SC.toast(e.message, { error: true }); }
  }
  function openNote(s) {
    const l = SC.live.get(s.id);
    if (l) return 'It is open in a window right now' + (l.windows > 1 ? ' (in ' + l.windows + ' windows)' : '') + (l.status === 'busy' ? ', and Claude is working in it' : '') + '.';
    return 'It changed ' + U.ago(s.mtime) + ', so it is probably open in another window.';
  }
  SC.openNote = openNote;
  async function resume(s) {
    const what = '“' + U.short(SC.titleOf(s), 50) + '”';
    await SC.refreshLive();
    if (SC.isOpen(s)) {
      // already open: bring its window to the front instead of asking
      let f = null;
      try { f = await SC.api.post('/api/focus', { sessionId: s.id }); } catch (e) { f = null; }
      if (f && f.focused) { SC.toast(f.message || 'Brought its window to the front.'); return f; }
      const why = f && f.message ? f.message + ' ' : '';
      const v = await SC.ask('This session is already open',
        '<p>' + E(openNote(s)) + ' ' + E(why) + (f && f.reason === 'background' ? 'Fork it to work on a copy in a window. Opening it twice' : 'Find that window instead: opening it twice') + ' makes two windows write to the same conversation.</p>',
        [{ label: 'Cancel', value: null, cls: 'accent', focus: true }, { label: 'Open a copy (fork)', value: 'fork' }, { label: 'Open a second window anyway', value: 'resume', cls: 'danger' }]);
      if (!v) return;
      return SC.doSpawn({ action: v, sessionId: s.id }, what);
    }
    return SC.doSpawn({ action: 'resume', sessionId: s.id }, what);
  }
  SC.resumeSession = resume;

  // ---- details of one session (loaded when needed) ----
  const details = new Map(), pending = new Set();
  let panelFor = null, hoverId = null;
  SC.clearDetails = function () { details.clear(); };
  async function loadDetail(id) {
    if (pending.has(id)) return;
    pending.add(id);
    try { details.set(id, await SC.api.get('/api/session?id=' + encodeURIComponent(id))); } catch (e) { details.set(id, { error: e.message, links: {}, commands: [] }); }
    pending.delete(id);
    if (ui.sel && ui.sel.type === 'node' && ui.sel.id === id) SC.renderPanel(true);
    if (hoverId === id) fillHover(id);
  }

  const LINK_GROUPS = [['jira', 'Jira'], ['slack', 'Slack'], ['notion', 'Notion'], ['artifact', 'Artifacts'], ['figma', 'Figma'], ['github', 'GitHub'], ['google', 'Google'], ['web', 'Other']];
  const IN_WORD = { continued: 'Continued from', fork: 'Copy (fork) of', handover: 'Handover from', helper: 'Started by', worktree: 'Worktree of', manual: 'Linked from' };
  const OUT_WORD = { continued: 'Continued in', fork: 'Copied (forked) to', handover: 'Handed over to', helper: 'Started helper', worktree: 'Has worktree', manual: 'Linked to' };

  function chipHtml(word, act) {
    const c = SC.chipColors(word);
    return '<button class="chip" data-act="' + act + '" data-v="' + E(word) + '" style="background:' + c.bg + ';color:' + c.fg + '">' + E(word) + '</button>';
  }

  SC.renderPanel = function (keepScroll) {
    const sel = ui.sel;
    const s = sel && sel.type === 'node' ? SC.data.byId.get(sel.id) : null;
    const wasOpen = ui.panelOpen;
    if (!s) {
      panel.hidden = true;
      panel.innerHTML = '';
      ui.panelOpen = false;
      panelFor = null;
      document.body.classList.remove('panel-open');
      if (wasOpen) SC.requestRender();
      return;
    }
    const active = document.activeElement;
    if (keepScroll && active && panel.contains(active) && (active.tagName === 'INPUT')) return;   // don't pull the field from under the typing
    const d = details.get(s.id);
    if (!d) loadDetail(s.id);
    const st = SC.state, n = SC.nodes.get(s.id);
    const title = SC.titleOf(s), renamed = !!st.titles[s.id];
    const accent = SC.accentOf(s);
    const hidden = st.hidden.includes(s.id);
    const dur = s.end - s.start;
    const h = [];
    h.push('<div class="head"><div class="stripe" style="background:' + accent + '"></div>' +
      '<button class="btn icon close" data-act="close" title="Close (Esc)">&times;</button>' +
      '<h2 data-act="rename" title="Click to rename">' + E(title) + '<span class="pen">rename</span></h2>' +
      '<div class="sub">' +
      (s.active ? '<span class="badge live">running now</span>' : '') +
      '<span class="badge" style="border-color:' + SC.KIND_COLOR[s.kind] + '">' + E(s.run === 'guide' ? 'guide' : SC.KIND_ONE[s.kind]) + '</span>' +
      '<span>' + E(s.projectLabel) + (s.worktree ? ' ⑂ ' + E(s.worktree) : '') + '</span>' +
      (hidden ? '<span class="badge">hidden</span>' : '') +
      '</div>' +
      '<div class="sub" style="margin-top:4px">' + E(U.fmtDay(s.start)) + ' ' + new Date(s.start).getFullYear() + ', ' + E(U.fmtTime(s.start)) + ' → ' +
      (U.dayKey(s.end) === U.dayKey(s.start) ? '' : E(U.fmtDay(s.end)) + ', ') + E(U.fmtTime(s.end)) +
      ' <span>(' + E(U.fmtDuration(dur)) + ')</span></div>' +
      '<div class="sub">' + s.msgs + ' messages (' + s.prompts + ' from you, ' + s.replies + ' replies)' +
      (s.model ? ' · ' + E(s.model) : '') + (typeof s.cost === 'number' ? ' · $' + s.cost.toFixed(2) : '') + '</div>' +
      '</div>');

    h.push('<div class="sec"><div class="acts">' +
      '<button class="btn accent" data-act="resume" title="' + (s.active ? 'It is open: bring its window to the front' : 'Open this session again in a new Terminal window') + '">' + (s.active ? 'Go to window' : 'Resume') + '</button>' +
      '<button class="btn" data-act="fork" title="Open a copy with the same history; the original stays as it is">Fork (copy)</button>' +
      '<button class="btn" data-act="new" title="Start an empty session in the same folder">New session here</button>' +
      '<button class="btn" data-act="copyid" title="Copy the session id">Copy id</button></div>' +
      '<div class="acts2">' +
      '<button class="btn' + (ui.focus === s.id ? ' on' : '') + '" data-act="focus" title="Dim everything not linked to this session (Enter)">' + (ui.focus === s.id ? 'Stop focusing' : 'Focus') + '</button>' +
      '<button class="btn" data-act="note" title="Add a sticky note connected to this session">Add note</button>' +
      '<button class="btn" data-act="link" title="Then click another session to draw a link to it (L)">Link to…</button>' +
      '<button class="btn" data-act="' + (hidden ? 'unhide' : 'hide') + '" title="' + (hidden ? 'Put it back on the board' : 'Take it off the board (bring it back from Filters)') + '">' + (hidden ? 'Unhide' : 'Hide') + '</button>' +
      '<button class="btn" data-act="copycmd" title="Copy the terminal command that resumes it">Copy command</button>' +
      '</div>' +
      (d && d.cwdExists === false ? '<div class="warnbox">The folder this session ran in no longer exists, so Resume and Fork may not find it.</div>' : '') +
      '</div>');

    if (SC.data.statusOn) {
      const stt = SC.stateOf(s), btns = stateButtons(stt, true);
      h.push('<div class="sec status"><h3>Where it stands</h3><div class="strow">' + stateBadge(stt) +
        (stt.key ? '<span class="muted">' + E(stt.info.hint) + (stt.note ? ' · ' + E(stt.note) : '') + '</span>' : '<span class="muted">no status: it wrote no report and is not open</span>') + '</div>' +
        (stt.key === 'replaced' ? '<div class="rel"><span class="k">Replaced by</span>' + (stt.by && stt.by.id ? '<button class="go" data-act="go" data-id="' + stt.by.id + '" title="Go to the session that took over">' + E(stt.by.name) + '</button>' : '<span class="muted">' + E(stt.by ? stt.by.name : 'a newer session (not named)') + '</span>') + '</div>' : '') +
        (stt.sent || (s.report && s.report.sent) ? '<div class="about"><b>Sent:</b> ' + linkify(stt.sent || s.report.sent) + '</div>' : '') +
        (btns ? '<div class="acts2">' + btns + '</div>' : '') + '</div>');
    }
    if (s.report) {
      const r = s.report, si = SC.STATUS[r.status];
      h.push('<div class="sec latest"><h3>Latest (its report)</h3>' +
        '<div><span class="badge" style="background:' + si.color + ';border-color:' + si.color + ';color:#10151d">' + E(si.label.toLowerCase()) + '</span> <span class="muted">' + E(U.ago(r.at)) + '</span></div>' +
        (r.outcome ? '<div class="about"><b>Done:</b> ' + E(r.outcome) + '</div>' : '') +
        (r.left ? '<div class="about"><b>Left:</b> ' + E(r.left) + '</div>' : '') +
        '<div class="muted" style="font-size:11px;word-break:break-all">' + E(r.file || '') + '</div></div>');
    }
    h.push('<div class="sec"><h3>What it was about</h3><div class="about">' + E(s.about || 'No summary available.') + '</div>');
    if (d && d.recaps && d.recaps.length > 1) {
      for (const r of d.recaps.slice(0, -1).slice(-2)) h.push('<div class="recap">' + E(r) + '</div>');
    }
    h.push('</div>');

    if (s.keywords.length) h.push('<div class="sec"><h3>Keywords <span style="text-transform:none;letter-spacing:0;font-weight:400">(click to search)</span></h3><div class="chips">' + s.keywords.map(k => chipHtml(k, 'kw')).join('') + '</div></div>');

    h.push('<div class="sec"><h3>Label and colour</h3>' +
      '<div class="field"><label>Label</label><input type="text" id="labelIn" maxlength="40" placeholder="e.g. important, follow up" value="' + E(st.labels[s.id] || '') + '"></div>' +
      '<div class="field"><label>Colour</label><div class="swatches">' +
      SC.PALETTE.map(c => '<button class="sw' + (st.colors[s.id] === c ? ' on' : '') + '" data-act="color" data-v="' + c + '" style="background:' + c + '" title="Use this colour"></button>').join('') +
      '<button class="sw none" data-act="color" data-v="" title="Back to automatic colour">&times;</button></div></div>' +
      (renamed ? '<div class="field"><label>Name</label><span class="muted" style="flex:1;color:var(--muted)">was: ' + E(U.short(SC.baseName(s), 40)) + '</span><button class="linkbtn" data-act="resetname">Reset</button></div>' : '') +
      '</div>');

    // links found in the conversation
    const cmds = (d && d.commands) || s.commands.map(c => [c, 0]);
    const lk = [];
    if (cmds.length) lk.push('<div class="grp"><b>Commands</b><div>' + cmds.map(c => '<button class="chip cmd" data-act="cmd" data-v="' + E(c[0]) + '" title="Show only sessions that used ' + E(c[0]) + '">' + E(c[0]) + (c[1] > 1 ? ' ×' + c[1] : '') + '</button>').join('') + '</div></div>');
    if (d && d.links) {
      for (const g of LINK_GROUPS) {
        const arr = d.links[g[0]];
        if (!arr || !arr.length) continue;
        lk.push('<div class="grp"><b>' + g[1] + '</b><div>' + arr.map(x => '<a href="' + E(x.url) + '" target="_blank" rel="noopener noreferrer" title="' + E(x.url) + '">' + E(x.label) + '</a>').join('') + '</div></div>');
      }
    } else if (!d) lk.push('<div class="muted" style="color:var(--muted)">Loading links…</div>');
    if (lk.length) h.push('<div class="sec"><h3>Links</h3><div class="links">' + lk.join('') + '</div></div>');

    // related sessions
    const rel = [];
    const removed = [];
    for (const e of SC.edges()) {
      if (e.to !== s.id && e.from !== s.id) continue;
      const incoming = e.to === s.id;
      const other = SC.data.byId.get(incoming ? e.from : e.to);
      if (!other) continue;
      rel.push('<div class="rel"><span class="dot" style="background:' + SC.EDGE_COLOR[e.kind] + '"></span><span class="k">' + (incoming ? IN_WORD : OUT_WORD)[e.kind] + (e.guess ? ' (guess)' : '') + '</span>' +
        '<button class="go" data-act="go" data-id="' + other.id + '" title="Go to this session">' + E(SC.titleOf(other)) + '</button>' +
        '<button class="x" data-act="unlink" data-id="' + E(e.id) + '" title="Remove this link">&times;</button></div>');
    }
    for (const id of st.removedEdges) { const p = id.split(':'); if (p[1] === s.id || p[2] === s.id) removed.push(id); }
    const kids = SC.kidCount(s.id);
    if (rel.length || removed.length) {
      h.push('<div class="sec"><h3>Related sessions</h3>' + rel.join('') +
        (kids && st.view.layout === 'tree' ? '<div style="margin-top:4px"><button class="linkbtn" data-act="collapse">' + (st.collapsed.includes(s.id) ? 'Show' : 'Fold away') + ' the ' + kids + ' below it</button></div>' : '') +
        (removed.length ? '<div style="margin-top:4px"><button class="linkbtn" data-act="restorelinks">Put back ' + removed.length + ' removed link' + (removed.length > 1 ? 's' : '') + '</button></div>' : '') +
        '</div>');
    }
    const myNotes = st.notes.filter(x => x.attach === s.id);
    if (myNotes.length) h.push('<div class="sec"><h3>Notes on this session</h3>' + myNotes.map(x => '<div class="rel"><span class="dot" style="background:' + (SC.NOTE_HEX[x.color] || '#ffe37a') + '"></span><button class="go" data-act="gonote" data-id="' + E(x.id) + '">' + E(U.short((x.text || '(empty note)').split('\n')[0], 60)) + '</button></div>').join('') + '</div>');

    if (d && !d.error) {
      h.push('<div class="sec"><h3>How it started</h3>' +
        (d.firstPrompt ? '<div class="msg you"><span class="who">You</span>' + E(d.firstPrompt) + '</div>' : '') +
        (d.firstReply ? '<div class="msg"><span class="who">Claude</span>' + E(d.firstReply) + '</div>' : '') + '</div>');
      if (s.msgs > 2) {
        h.push('<div class="sec"><h3>How it ended</h3>' +
          (d.lastPrompt && d.lastPrompt !== d.firstPrompt ? '<div class="msg you"><span class="who">You</span>' + E(d.lastPrompt) + '</div>' : '') +
          (d.lastReply && d.lastReply !== d.firstReply ? '<div class="msg"><span class="who">Claude</span>' + E(d.lastReply) + '</div>' : '') + '</div>');
      }
    } else if (d && d.error) h.push('<div class="sec"><div class="warnbox">' + E(d.error) + '</div></div>');
    else h.push('<div class="sec muted" style="color:var(--muted)">Loading messages…</div>');

    h.push('<div class="sec"><h3>Details</h3><div class="kv">' +
      '<b>Session id</b><span style="font-family:var(--mono);font-size:11px">' + E(s.id) + '</span>' +
      '<b>Folder</b><span>' + E(U.homePath(s.cwd, SC.data.home)) + '</span>' +
      '<b>Last change</b><span>' + E(U.fmtDateTime(s.mtime)) + ' (' + E(U.ago(s.mtime)) + ')</span>' +
      '<b>Size</b><span>' + (s.size / 1048576).toFixed(1) + ' MB on disk' + (s.tools ? ' · ' + s.tools + ' tool uses' : '') + '</span>' +
      (s.subagents ? '<b>Sub-agents</b><span>' + s.subagents + ' helper agents inside this session</span>' : '') +
      (s.compactions ? '<b>Long session</b><span>Claude summarised earlier parts ' + s.compactions + ' time' + (s.compactions > 1 ? 's' : '') + ' to keep going</span>' : '') +
      (s.historyStart && s.historyStart < s.start - 60000 ? '<b>History from</b><span>' + E(U.fmtDateTime(s.historyStart)) + ' (copied from the original)</span>' : '') +
      (n && st.view.layout === 'free' && st.positions[s.id] ? '' : '') +
      '</div></div>');

    const top = keepScroll && panelFor === s.id ? panel.scrollTop : 0;
    panel.innerHTML = h.join('');
    panel.hidden = false;
    panel.scrollTop = top;
    panelFor = s.id;
    ui.panelOpen = true;
    document.body.classList.add('panel-open');
    if (!wasOpen) SC.requestRender();
  };

  function startRename() {
    const s = SC.data.byId.get(ui.sel.id);
    const h2 = panel.querySelector('h2');
    if (!s || !h2) return;
    const inp = document.createElement('input');
    inp.className = 'titleedit';
    inp.type = 'text';
    inp.maxLength = 140;
    inp.value = SC.titleOf(s);
    h2.replaceWith(inp);
    inp.focus();
    inp.select();
    let done = false;
    const finish = save => {
      if (done) return;
      done = true;
      const v = inp.value.trim();
      if (save && v !== SC.titleOf(s)) {
        SC.checkpoint('rename');
        if (!v || v === SC.baseName(s)) delete SC.state.titles[s.id]; else SC.state.titles[s.id] = v;
        SC.touch('titles');
        SC.prepSearch();
        SC.reprep();
      }
      SC.renderPanel(true);
    };
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); finish(true); } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); } });
    inp.addEventListener('blur', () => finish(true));
  }
  SC.startRename = startRename;

  panel.addEventListener('click', e => {
    const t = e.target.closest('[data-act]');
    if (!t || !ui.sel) return;
    const id = ui.sel.id, s = SC.data.byId.get(id), st = SC.state;
    if (!s) return;
    const what = '“' + U.short(SC.titleOf(s), 50) + '”';
    switch (t.dataset.act) {
      case 'close': SC.select(null); break;
      case 'resume': resume(s); break;
      case 'fork': SC.doSpawn({ action: 'fork', sessionId: id }, 'a copy of ' + what); break;
      case 'new': SC.doSpawn({ action: 'new', cwd: s.cwd }, 'a new session in ' + (s.worktree || s.projectLabel)); break;
      case 'copyid': U.copy(id).then(ok => SC.toast(ok ? 'Session id copied' : 'Could not copy', { error: !ok })); break;
      case 'copycmd': copyCommand({ action: 'resume', sessionId: id }); break;
      case 'focus': if (ui.focus === id) SC.clearFocus(); else SC.focusNode(id); SC.renderPanel(true); break;
      case 'note': SC.addNoteFor(id); break;
      case 'link': SC.startLinking({ type: 'node', id: id }); break;
      case 'hide':
        SC.checkpoint('hide');
        if (!st.hidden.includes(id)) st.hidden.push(id);
        SC.touch('hidden');
        SC.select(null);
        SC.afterStateChange(true);
        SC.toast('Hidden. Bring it back from Filters.', { action: { label: 'Undo', fn: () => SC.doUndo() } });
        break;
      case 'unhide':
        SC.checkpoint('unhide');
        st.hidden = st.hidden.filter(x => x !== id);
        SC.touch('hidden');
        SC.afterStateChange(true);
        break;
      case 'rename': startRename(); break;
      case 'resetname':
        SC.checkpoint('rename');
        delete st.titles[id];
        SC.touch('titles'); SC.prepSearch(); SC.reprep(); SC.renderPanel(true);
        break;
      case 'kw': SC.setSearchText(t.dataset.v); break;
      case 'cmd': SC.toggleCommandFilter(t.dataset.v); break;
      case 'go': SC.jumpToNode(t.dataset.id); break;
      case 'st-sent': case 'st-done': case 'st-replaced': case 'st-reopen': case 'st-gonew': stateAction(id, t.dataset.act.slice(3)); break;
      case 'gonote': SC.selectNote(t.dataset.id, true); break;
      case 'unlink':
        SC.removeLink(t.dataset.id);
        SC.afterStateChange(true);
        SC.toast('Link removed', { action: { label: 'Undo', fn: () => SC.doUndo() } });
        break;
      case 'restorelinks':
        SC.checkpoint('restore links');
        st.removedEdges = st.removedEdges.filter(x => { const p = x.split(':'); return p[1] !== id && p[2] !== id; });
        SC.touch('removedEdges'); SC.invalidate(); SC.afterStateChange(true);
        break;
      case 'collapse': SC.toggleCollapse(id); break;
      case 'color': {
        SC.checkpoint('colour');
        const v = t.dataset.v;
        if (v) st.colors[id] = v; else delete st.colors[id];
        SC.touch('colors'); SC.recolor(); SC.renderPanel(true);
        break;
      }
    }
  });
  panel.addEventListener('change', e => {
    if (e.target.id !== 'labelIn' || !ui.sel) return;
    const id = ui.sel.id, v = e.target.value.trim();
    if ((SC.state.labels[id] || '') === v) return;
    SC.checkpoint('label');
    if (v) SC.state.labels[id] = v; else delete SC.state.labels[id];
    SC.touch('labels'); SC.prepSearch(); SC.reprep();
  });
  panel.addEventListener('keydown', e => { if (e.target.id === 'labelIn' && e.key === 'Enter') e.target.blur(); });

  // ---- hover card ----
  let hoverTimer = 0, hideTimer = 0, overCard = false;
  function fillHover(id) {
    const s = SC.data.byId.get(id);
    if (!s) return;
    const d = details.get(id);
    const links = [];
    if (d && d.links) {
      for (const g of ['jira', 'slack', 'notion', 'artifact', 'figma']) for (const x of (d.links[g] || []).slice(0, g === 'jira' ? 4 : 2)) {
        if (links.length < 7) links.push('<a href="' + E(x.url) + '" target="_blank" rel="noopener noreferrer">' + E(U.short(x.label, 34)) + '</a>');
      }
    }
    const lt = SC.latestOf(s), lsi = SC.STATUS[lt.status];
    hover.innerHTML = '<div class="t">' + E(SC.titleOf(s)) + '</div>' +
      (lsi ? '<div class="a"><span class="badge" style="background:' + lsi.color + ';border-color:' + lsi.color + ';color:#10151d">' + E(lsi.label.toLowerCase()) + '</span> ' + E(lt.text) + '</div>' : '') +
      '<div class="a">' + E(s.about || '') + '</div>' +
      (s.commands.length ? '<div class="l">' + s.commands.slice(0, 4).map(c => '<span class="chip cmd" style="cursor:default">' + E(c) + '</span>').join('') + '</div>' : '') +
      (links.length ? '<div class="l">' + links.join('') + '</div>' : (d ? '' : '<div class="m">Loading links…</div>')) +
      '<div class="m">' + E(U.fmtDateTime(s.start)) + ' · ' + s.msgs + ' messages · ' + E(SC.KIND_ONE[s.kind]) + ' · click the card for more</div>';
  }
  SC.showHover = function (id) {
    clearTimeout(hoverTimer);
    clearTimeout(hideTimer);
    if (hoverId === id && !hover.hidden) return;
    hoverTimer = setTimeout(() => {
      const n = SC.nodes.get(id);
      if (!n || !n.vis || ui.drag || ui.modal || ui.hover !== id) return;
      hoverId = id;
      if (!details.get(id)) loadDetail(id);
      fillHover(id);
      hover.hidden = false;
      const z = SC.cam.z, a = SC.toScreen(n.x, n.y), w = n.w * z, hgt = hover.offsetHeight, limitR = SC.vw - (ui.panelOpen ? SC.CONST.PANEL_W : 0);
      let x = a.x + w + 14;
      if (x + 334 > limitR) x = a.x - 334 - 14;
      if (x < 8) x = Math.min(Math.max(8, a.x), limitR - 338);
      let y = U.clamp(a.y, SC.CONST.TOP + 8, Math.max(SC.CONST.TOP + 8, SC.vh - hgt - 34));
      if (x >= a.x - 4 && x <= a.x + w) y = Math.min(SC.vh - hgt - 34, a.y + n.h * z + 10);      // no room at the sides: go below
      hover.style.left = Math.round(x) + 'px';
      hover.style.top = Math.round(y) + 'px';
    }, 480);
  };
  SC.hideHover = function (now) {
    clearTimeout(hoverTimer);
    clearTimeout(hideTimer);
    if (hover.hidden) { hoverId = null; return; }
    const go = () => { if (!overCard || now) { hover.hidden = true; hoverId = null; } };
    if (now) go(); else hideTimer = setTimeout(go, 260);
  };
  hover.addEventListener('mouseenter', () => { overCard = true; clearTimeout(hideTimer); });
  hover.addEventListener('mouseleave', () => { overCard = false; SC.hideHover(); });

  // ---- sticky notes ----
  function noteEl(id) { return notesEl.querySelector('.note[data-id="' + id + '"]'); }
  function buildNote(note) {
    const el = document.createElement('div');
    el.className = 'note c-' + (SC.NOTE_COLORS.includes(note.color) ? note.color : 'yellow');
    el.dataset.id = note.id;
    const att = note.attach ? SC.data.byId.get(note.attach) : null;
    el.innerHTML = (att ? '<div class="pin" title="Connected to this session">↳ ' + E(U.short(SC.titleOf(att), 32)) + '</div>' : '') +
      '<div class="body' + (note.text ? '' : ' empty') + '">' + U.mdLite(note.text) + '</div>' +
      '<div class="hook" title="Drag onto a session to connect this note to it"></div><div class="grip" title="Drag to resize"></div>';
    if (ui.sel && ui.sel.type === 'note' && ui.sel.id === note.id) el.classList.add('sel');
    return el;
  }
  SC.renderNotes = function () {
    // the note being typed in is left alone, so no keystroke is lost when the board refreshes
    let keep = ui.editing ? noteEl(ui.editing) : null;
    if (keep && !SC.noteById(ui.editing)) { ui.editing = null; keep = null; }
    for (const el of Array.from(notesEl.children)) if (el !== keep) el.remove();
    for (const note of SC.state.notes) {
      if (keep && note.id === ui.editing) continue;
      notesEl.appendChild(buildNote(note));
    }
    SC.positionNotes();
  };
  SC.positionNotes = function (animate) {
    let shelf = 0;
    const S = SC.search;
    SC.noteXY.clear();
    for (const note of SC.state.notes) {
      const el = noteEl(note.id);
      if (!el) continue;
      const p = SC.notePos(note, shelf);
      if (p.shelf) shelf++;
      SC.noteXY.set(note.id, { x: p.x, y: p.y, anchored: p.anchored });
      el.classList.toggle('anim', !!animate);
      el.style.left = p.x + 'px';
      el.style.top = p.y + 'px';
      el.style.width = (note.w || 220) + 'px';
      el.style.height = (note.h || 150) + 'px';
      const dim = (ui.family && !(note.attach && ui.family.has(note.attach))) || (S.tokens.length && !(note.attach && S.matches.has(note.attach)) && !S.tokens.every(t => U.norm(note.text).indexOf(t) >= 0));
      el.classList.toggle('dim', !!dim);
    }
    if (animate) setTimeout(() => { for (const el of notesEl.children) el.classList.remove('anim'); }, 420);
    SC.requestRender();
  };
  SC.selectNote = function (id, center) {
    SC.select({ type: 'note', id: id });
    const p = SC.noteXY.get(id), note = SC.noteById(id);
    if (center && p && note) SC.centerOn({ x: p.x, y: p.y, w: note.w, h: note.h }, { minZ: 0.7 });
  };
  SC.syncNoteSelection = function () {
    for (const el of notesEl.children) el.classList.toggle('sel', !!(ui.sel && ui.sel.type === 'note' && ui.sel.id === el.dataset.id));
    renderNoteBar();
  };
  function renderNoteBar() {
    const note = ui.sel && ui.sel.type === 'note' ? SC.noteById(ui.sel.id) : null;
    if (!note || ui.editing === note.id) { notebar.hidden = true; return; }
    notebar.innerHTML = SC.NOTE_COLORS.map(c => '<button class="nsw' + (note.color === c ? ' on' : '') + '" data-a="color" data-v="' + c + '" style="background:' + SC.NOTE_HEX[c] + '" title="' + c + '"></button>').join('') +
      '<span class="sep"></span>' +
      '<button class="btn" data-a="edit" title="Write in the note (double-click it)">Edit</button>' +
      (note.attach ? '<button class="btn" data-a="detach" title="Disconnect from its session">Disconnect</button>' : '<button class="btn" data-a="attach" title="Then click a session">Connect to session</button>') +
      '<span class="sep"></span>' +
      '<button class="btn accent" data-a="send" title="Start Claude with this note as the prompt">Send to Claude…</button>' +
      '<button class="btn danger" data-a="del" title="Delete this note (Delete key)">Delete</button>';
    notebar.hidden = false;
    SC.positionBars();
  }
  notebar.addEventListener('click', e => {
    const b = e.target.closest('[data-a]');
    const note = ui.sel && ui.sel.type === 'note' ? SC.noteById(ui.sel.id) : null;
    if (!b || !note) return;
    switch (b.dataset.a) {
      case 'color': SC.checkpoint('note colour'); note.color = b.dataset.v; SC.touch('notes'); SC.renderNotes(); renderNoteBar(); break;
      case 'edit': SC.editNote(note.id); break;
      case 'attach': SC.startLinking({ type: 'note', id: note.id }); break;
      case 'detach': SC.detachNote(note.id); break;
      case 'send': SC.openSendDialog(note.id); break;
      case 'del': SC.deleteNote(note.id); break;
    }
  });
  SC.deleteNote = function (id) {
    SC.checkpoint('delete note');
    SC.state.notes = SC.state.notes.filter(n => n.id !== id);
    SC.touch('notes');
    if (ui.editing === id) ui.editing = null;
    SC.select(null);
    SC.renderNotes();
    SC.toast('Note deleted', { action: { label: 'Undo', fn: () => SC.doUndo() } });
  };
  SC.attachNote = function (noteId, sid) {
    const note = SC.noteById(noteId), n = SC.nodes.get(sid), p = SC.noteXY.get(noteId);
    if (!note || !n) return;
    SC.checkpoint('connect note');
    note.attach = sid;
    // keep it where it is on screen if that is close to the card, otherwise bring it next to the card
    if (p && Math.abs(p.x - n.x) < 900 && Math.abs(p.y - n.y) < 700) { note.dx = Math.round(p.x - n.x); note.dy = Math.round(p.y - n.y); } else { note.dx = n.w + 34; note.dy = -10; }
    note.updated = Date.now();
    SC.touch('notes');
    SC.renderNotes();
    SC.syncNoteSelection();
    SC.toast('Note connected to “' + U.short(SC.titleOf(n.s), 40) + '”. It now follows that card in every layout.');
  };
  SC.detachNote = function (noteId) {
    const note = SC.noteById(noteId), p = SC.noteXY.get(noteId);
    if (!note) return;
    SC.checkpoint('disconnect note');
    note.attach = null;
    delete note.dx; delete note.dy;
    note.pos = note.pos || {};
    if (p) note.pos[SC.state.view.layout] = { x: Math.round(p.x), y: Math.round(p.y) };
    SC.touch('notes');
    SC.renderNotes();
    SC.syncNoteSelection();
  };
  SC.addNoteFor = function (sid) {
    const n = SC.nodes.get(sid);
    if (!n) return;
    const note = SC.addNote(n.x + n.w + 34, n.y - 10, '');
    note.attach = sid;
    const taken = SC.state.notes.filter(x => x.attach === sid).length - 1;
    note.dx = n.w + 34 + taken * 24;
    note.dy = -10 + taken * 28;
    SC.touch('notes');
    SC.renderNotes();
    SC.select({ type: 'note', id: note.id });
    SC.editNote(note.id);
  };
  SC.editNote = function (id) {
    const note = SC.noteById(id), el = noteEl(id);
    if (!note || !el || el.querySelector('textarea')) return;
    ui.editing = id;
    notebar.hidden = true;
    const ta = document.createElement('textarea');
    ta.value = note.text || '';
    ta.placeholder = 'Write here. # heading, - list, [ ] to-do, **bold**';
    ta.spellcheck = false;
    el.querySelector('.body').style.visibility = 'hidden';
    el.appendChild(ta);
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    let done = false;
    const finish = save => {
      if (done) return;
      done = true;
      ui.editing = null;
      const v = ta.value.replace(/\s+$/, '');
      if (save && v !== (note.text || '')) {
        SC.checkpoint('edit note');
        note.text = v;
        note.updated = Date.now();
        SC.touch('notes');
      }
      const fresh = buildNote(note);
      el.replaceWith(fresh);
      SC.positionNotes();
      // grow the note if the text does not fit
      const body = fresh.querySelector('.body');
      if (body.scrollHeight > (note.h || 150) + 2) { note.h = Math.min(900, body.scrollHeight + 6); SC.touch('notes'); SC.positionNotes(); }
      SC.syncNoteSelection();
    };
    ta.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.key === 'Escape' || (e.key === 'Enter' && (e.metaKey || e.ctrlKey))) { e.preventDefault(); finish(true); }
    });
    ta.addEventListener('blur', () => finish(true));
    ta.addEventListener('pointerdown', e => e.stopPropagation());
    ta.addEventListener('dblclick', e => e.stopPropagation());
  };

  notesEl.addEventListener('pointerdown', e => {
    const el = e.target.closest('.note');
    if (!el || e.button !== 0) return;
    if (e.target.tagName === 'TEXTAREA' || e.target.closest('a')) return;
    const note = SC.noteById(el.dataset.id);
    if (!note) return;
    e.preventDefault();
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    SC.hideHover(true);
    const p = SC.noteXY.get(note.id) || { x: 0, y: 0 };
    if (ui.linking) { SC.cancelLinking(); }
    if (e.target.classList.contains('box')) {
      const line = +e.target.closest('.md-box').dataset.line;
      const lines = (note.text || '').split('\n');
      if (lines[line] !== undefined) {
        SC.checkpoint('tick');
        lines[line] = /\[( )\]/.test(lines[line]) ? lines[line].replace('[ ]', '[x]') : lines[line].replace(/\[(x|X)\]/, '[ ]');
        note.text = lines.join('\n');
        note.updated = Date.now();
        SC.touch('notes');
        el.querySelector('.body').innerHTML = U.mdLite(note.text);
      }
      return;
    }
    SC.select({ type: 'note', id: note.id });
    const w = SC.toWorld(e.clientX, e.clientY);
    if (e.target.classList.contains('hook')) {
      ui.drag = { type: 'link', from: { type: 'note', id: note.id }, x0: p.x + note.w, y0: p.y + note.h / 2, x: w.x, y: w.y, over: null };
      SC.canvas.classList.add('linking');
    } else if (e.target.classList.contains('grip')) {
      ui.drag = { type: 'noteResize', id: note.id, sx: e.clientX, sy: e.clientY, w0: note.w, h0: note.h, moved: false };
    } else {
      ui.drag = { type: 'note', id: note.id, sx: e.clientX, sy: e.clientY, x0: p.x, y0: p.y, moved: false };
    }
  });
  notesEl.addEventListener('dblclick', e => {
    const el = e.target.closest('.note');
    if (!el || e.target.tagName === 'TEXTAREA' || e.target.classList.contains('box') || e.target.closest('a')) return;
    e.preventDefault();
    SC.select({ type: 'note', id: el.dataset.id });
    SC.editNote(el.dataset.id);
  });

  /* Called while a note is being dragged / resized (from the pointer code in ui.js). */
  SC.dragNote = function (d, e) {
    const note = SC.noteById(d.id), el = noteEl(d.id);
    if (!note || !el) return;
    const z = SC.cam.z, dx = (e.clientX - d.sx) / z, dy = (e.clientY - d.sy) / z;
    if (!d.moved) {
      if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) < 4) return;
      d.moved = true;
      SC.checkpoint(d.type === 'note' ? 'move note' : 'resize note');
      notebar.hidden = true;
    }
    if (d.type === 'noteResize') {
      note.w = Math.round(U.clamp(d.w0 + dx, 130, 640));
      note.h = Math.round(U.clamp(d.h0 + dy, 70, 900));
      el.style.width = note.w + 'px';
      el.style.height = note.h + 'px';
    } else {
      const x = Math.round(d.x0 + dx), y = Math.round(d.y0 + dy);
      const n = note.attach ? SC.nodes.get(note.attach) : null;
      if (n && n.vis) { note.dx = x - n.x; note.dy = y - n.y; } else { note.pos = note.pos || {}; note.pos[SC.state.view.layout] = { x: x, y: y }; }
      SC.noteXY.set(note.id, { x: x, y: y, anchored: !!(n && n.vis) });
      el.style.left = x + 'px';
      el.style.top = y + 'px';
    }
    SC.requestRender();
  };
  SC.dropNote = function (d) {
    if (d.moved) { const note = SC.noteById(d.id); if (note) note.updated = Date.now(); SC.touch('notes'); }
    SC.syncNoteSelection();
  };

  /* Keep the little toolbars next to the thing they belong to. */
  SC.positionBars = function () {
    if (!notebar.hidden && ui.sel && ui.sel.type === 'note') {
      const note = SC.noteById(ui.sel.id), p = SC.noteXY.get(ui.sel.id);
      if (note && p) {
        const a = SC.toScreen(p.x, p.y);
        const w = notebar.offsetWidth;
        notebar.style.left = Math.round(U.clamp(a.x, 8, Math.max(8, SC.vw - w - 8))) + 'px';
        notebar.style.top = Math.round(U.clamp(a.y - 42, SC.CONST.TOP + 6, SC.vh - 70)) + 'px';
      }
    }
    if (!cardbar.hidden && ui.sel && ui.sel.type === 'node') {
      const n = SC.nodes.get(ui.sel.id);
      if (n && n.vis) {
        const a = SC.toScreen(n.rx === undefined ? n.x : n.rx, n.ry === undefined ? n.y : n.ry);
        const limitR = SC.vw - (ui.panelOpen ? SC.CONST.PANEL_W : 0);
        cardbar.style.left = Math.round(U.clamp(a.x, 8, Math.max(8, limitR - cardbar.offsetWidth - 8))) + 'px';
        cardbar.style.top = Math.round(U.clamp(a.y - 42, SC.CONST.TOP + 6, SC.vh - 70)) + 'px';
      }
    }
    if (!edgebar.hidden && ui.sel && ui.sel.type === 'edge' && ui.edgeAt) {
      const a = SC.toScreen(ui.edgeAt.x, ui.edgeAt.y);
      edgebar.style.left = Math.round(U.clamp(a.x + 10, 8, SC.vw - edgebar.offsetWidth - 8)) + 'px';
      edgebar.style.top = Math.round(U.clamp(a.y - 44, SC.CONST.TOP + 6, SC.vh - 70)) + 'px';
    }
  };
  SC.renderEdgeBar = function () {
    const e = ui.sel && ui.sel.type === 'edge' ? SC.edges().find(x => x.id === ui.sel.id) : null;
    if (!e) { edgebar.hidden = true; return; }
    const a = SC.data.byId.get(e.from), b = SC.data.byId.get(e.to);
    edgebar.innerHTML = '<span class="lbl"><b style="color:' + SC.EDGE_COLOR[e.kind] + '">' + E(SC.EDGE_LABEL[e.kind] || e.kind) + (e.guess ? ' (a guess)' : '') + '</b>: ' +
      E(U.short(SC.titleOf(a), 28)) + ' → ' + E(U.short(SC.titleOf(b), 28)) + '</span>' +
      '<button class="btn danger" data-a="del" title="Remove this link (Delete key)">Remove link</button>';
    edgebar.hidden = false;
    SC.positionBars();
  };
  edgebar.addEventListener('click', e => { if (e.target.closest('[data-a="del"]')) SC.deleteSelection(); });

  // ---- where a card stands: Done / Sent / Replaced by (on the card, in the panel, in the "Your turn" list) ----
  function stateDot(key) { return '<span class="st st-' + key + '" style="--c:' + SC.STATES[key].color + '"></span>'; }
  SC.stateDot = stateDot;
  function stateBadge(st) {
    if (!st.key) return '<span class="badge">no status</span>';
    return '<span class="badge stbadge" style="background:' + st.info.color + ';border-color:' + st.info.color + ';color:' + st.info.ink + '">' + E(st.info.zone) + '</span>';
  }
  function linkify(text) {
    return E(text).replace(/https?:\/\/[^\s<]+/g, u => '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + (u.length > 46 ? u.slice(0, 44) + '…' : u) + '</a>');
  }
  /* The buttons that make sense for a card. full = the side panel (also for cards without a status). */
  function stateButtons(st, full) {
    const b = [], pre = full ? 'data-act="st-' : 'data-a="';
    const btn = (a, label, title, cls) => '<button class="btn' + (cls ? ' ' + cls : '') + '" ' + pre + a + '" title="' + E(title) + '">' + E(label) + '</button>';
    if (!full && st.key === 'replaced' && st.by && st.by.id) b.push(btn('gonew', '→ ' + U.short(st.by.name, 26), 'Go to the session that took over'));
    if (st.mark) b.push(btn('reopen', 'Reopen', 'Take your mark off: the card shows what its report says again'));
    else if (st.key !== 'replaced') {
      const live = st.key === 'question' || st.key === 'your-turn' || st.key === 'not-done';
      if (st.info && st.info.wait) b.push(btn('sent', 'Sent', 'You sent or posted it yourself: the card becomes Done', 'accent'));
      if (st.key !== 'done' && (full || live)) b.push(btn('done', 'Mark done', 'Nothing left for you here: the card becomes Done'));
      if (full || live) b.push(btn('replaced', 'Replaced by…', 'A newer session took over: this card greys out and points to it'));
    }
    return b.join('');
  }
  function stateAction(id, act) {
    const s = SC.data.byId.get(id);
    if (!s) return;
    if (act === 'gonew') { const st = SC.stateOf(s); if (st.by && st.by.id) SC.jumpToNode(st.by.id); return; }
    if (act === 'replaced') { SC.pickReplacement(id); return; }
    SC.markCard(id, act === 'reopen' ? null : act);
  }
  SC.markCard = function (id, kind, by) {
    const s = SC.data.byId.get(id);
    if (!s || !SC.setMark(id, kind, by)) return;
    SC.reprep();
    SC.afterStateChange(true);
    const what = kind === 'sent' ? 'Sent, so done' : kind === 'done' ? 'Marked done' : kind === 'replaced' ? 'Marked as replaced' : 'Reopened';
    SC.toast(what + ': ' + U.short(SC.titleOf(s), 44), { action: { label: 'Undo', fn: () => SC.doUndo() } });
  };
  SC.pickReplacement = function (id) {
    const s = SC.data.byId.get(id);
    if (!s) return;
    const dlg = SC.modal('<h3>Which session took over from “' + E(U.short(SC.titleOf(s), 60)) + '”?</h3>' +
      '<p class="muted">This card greys out and points to the newer one. Undo with ⌘Z or “Reopen”.</p>' +
      '<input type="search" id="repFind" placeholder="Find the newer session by name…" autocomplete="off" data-autofocus><div class="pick" id="repPick"></div>' +
      '<div class="btns"><button class="btn" data-a="none" title="Grey it out without pointing anywhere">Replaced, no newer session</button><button class="btn accent" data-a="close">Cancel</button></div>');
    const find = dlg.querySelector('#repFind'), pick = dlg.querySelector('#repPick');
    const all = SC.data.sessions.filter(o => o.id !== id && o.kind !== 'auto').sort((a, b) => b.start - a.start);
    const fill = () => {
      const q = U.norm(find.value.trim());
      const rows = all.filter(o => !q || U.norm(SC.titleOf(o)).indexOf(q) >= 0).slice(0, 40);
      pick.innerHTML = rows.map(o => '<button data-id="' + o.id + '"><span class="tt">' + E(SC.titleOf(o)) + '</span><span class="when">' + E(U.fmtDay(o.start)) + ' ' + E(U.fmtTime(o.start)) + '</span></button>').join('') ||
        '<div class="muted" style="padding:6px 9px">No session with that name.</div>';
    };
    fill();
    find.addEventListener('input', fill);
    dlg.addEventListener('click', e => {
      const row = e.target.closest('#repPick button[data-id]');
      const a = e.target.dataset.a;
      if (row) { SC.closeModal(); SC.markCard(id, 'replaced', row.dataset.id); }
      else if (a === 'none') { SC.closeModal(); SC.markCard(id, 'replaced', null); }
      else if (a === 'close') SC.closeModal();
    });
  };

  /* The small bar above the selected card: only for cards where a click helps (waiting, stopped, marked, replaced). */
  SC.renderCardBar = function () {
    const s = ui.sel && ui.sel.type === 'node' ? SC.data.byId.get(ui.sel.id) : null;
    const n = s && SC.nodes.get(s.id);
    const st = s ? SC.stateOf(s) : null;
    const html = s && n && n.vis && st.key && SC.data.statusOn ? stateButtons(st, false) : '';
    if (!html) { cardbar.hidden = true; return; }
    cardbar.innerHTML = '<span class="lbl">' + stateDot(st.key) + E(st.info.zone) + '</span><span class="sep"></span>' + html;
    cardbar.dataset.id = s.id;
    cardbar.hidden = false;
    SC.positionBars();
  };
  cardbar.addEventListener('click', e => {
    const b = e.target.closest('[data-a]');
    if (b && cardbar.dataset.id) stateAction(cardbar.dataset.id, b.dataset.a);
  });

  /* "Your turn": everything that waits on you, the one that has waited longest first. Click = go to the card. */
  SC.renderWaiting = function () {
    const on = !!SC.data.statusOn, tab = document.querySelector('#layouts button[data-layout="status"]');
    $('btnWait').hidden = !on;
    if (tab) tab.hidden = !on;
    if (!on) { waitEl.hidden = true; return; }
    const list = SC.waiting();
    const nq = list.filter(w => w.st.key === 'question').length, ny = list.length - nq;
    const q = $('waitQ'), y = $('waitY');
    q.hidden = !nq; q.textContent = nq;
    y.hidden = !ny; y.textContent = ny;
    $('btnWait').classList.toggle('on', !!SC.state.settings.waitOpen);
    $('btnWait').title = (list.length ? nq + ' need your answer, ' + ny + ' are your turn' : 'Nothing waits on you') + ' (press W)';
    ui.waitOpen = !!SC.state.settings.waitOpen;
    if (!ui.waitOpen) { waitEl.hidden = true; return; }
    const today = U.startOfDay(Date.now());
    const older = list.filter(w => w.st.since < today).length;
    const top = waitEl.scrollTop;
    waitEl.innerHTML = '<div class="whead"><b>Waiting on you</b><span class="n">' + list.length + '</span><span class="sp"></span>' +
      '<button class="linkbtn" data-a="board" title="The Status layout: one zone per state (press 4)">Status board</button>' +
      '<button class="mini" data-a="close" title="Close (W)">&times;</button></div>' +
      (list.length ? '<div class="wrows">' + list.map(w => {
        const r = w.s.report || {};
        return '<div class="wrow" data-id="' + w.s.id + '" title="Go to this card">' + stateDot(w.st.key) +
          '<div class="wmain"><div class="wt"><span class="nm">' + E(SC.titleOf(w.s)) + '</span><span class="age">' + E(U.ago(w.st.since).replace(/ ago$/, '')) + '</span></div>' +
          '<div class="wl">' + E(r.left || r.outcome || '') + '</div></div>' +
          '<button class="wdone" data-a="done" title="Mark done (undo with ⌘Z)">&#10003;</button></div>';
      }).join('') + '</div>' : '<div class="wempty">All clear. Nothing waits on you.</div>') +
      (older ? '<div class="wfoot"><button class="linkbtn" data-a="older" title="For old cards you already dealt with. Undo with ⌘Z.">Mark the ' + older + ' from before today as done</button></div>' : '');
    waitEl.hidden = false;
    waitEl.scrollTop = top;
  };
  SC.toggleWaiting = function (open) {
    if (!SC.data.statusOn) return;
    const st = SC.state.settings;
    st.waitOpen = open === undefined ? !st.waitOpen : !!open;
    SC.touch('settings');
    SC.renderWaiting();
  };
  $('btnWait').onclick = () => SC.toggleWaiting();
  waitEl.addEventListener('click', e => {
    const a = (e.target.closest('[data-a]') || {}).dataset;
    const row = e.target.closest('.wrow');
    if (a && a.a === 'close') { SC.toggleWaiting(false); return; }
    if (a && a.a === 'board') { SC.setLayout('status'); return; }
    if (a && a.a === 'older') {
      const today = U.startOfDay(Date.now());
      const old = SC.waiting().filter(w => w.st.since < today);
      if (!old.length) return;
      SC.checkpoint('mark ' + old.length + ' older done');
      const marks = Object.assign({}, SC.state.marks);
      for (const w of old) marks[w.s.id] = { kind: 'done', by: null, at: Date.now(), sig: (w.s.report && w.s.report.sig) || '' };
      SC.state.marks = marks;
      SC.touch('marks');
      SC.reprep();
      SC.afterStateChange(true);
      SC.toast(old.length + ' older cards marked done', { action: { label: 'Undo', fn: () => SC.doUndo() } });
      return;
    }
    if (!row) return;
    if (a && a.a === 'done') { SC.markCard(row.dataset.id, 'done'); return; }
    SC.jumpToNode(row.dataset.id);
  });

  // ---- send a note to Claude ----
  SC.openSendDialog = function (noteId) {
    const note = SC.noteById(noteId);
    if (!note) return;
    if (!(note.text || '').trim()) { SC.toast('The note is empty: write something first.', { error: true }); SC.editNote(noteId); return; }
    const d = SC.data;
    const folders = [];
    const seen = new Set();
    const add = (cwd, label) => { if (cwd && !seen.has(cwd)) { seen.add(cwd); folders.push({ cwd: cwd, label: label }); } };
    add(d.defaultCwd, U.homePath(d.defaultCwd, d.home) + '  (this folder)');
    const counts = new Map();
    for (const s of d.sessions) if (s.cwd && s.project !== 'desktop') counts.set(s.cwd, (counts.get(s.cwd) || 0) + 1);
    Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).forEach(x => add(x[0], U.homePath(x[0], d.home)));
    let mode = note.attach && d.byId.has(note.attach) ? 'existing' : 'new';
    let target = note.attach && d.byId.has(note.attach) ? note.attach : null;
    const dlg = SC.modal(
      '<h3>Send this note to Claude</h3>' +
      '<div class="notepreview">' + E(U.short(note.text, 700)) + '</div>' +
      '<label class="opt" data-m="new"><input type="radio" name="sm" value="new"><div class="grow"><b>A new session</b><div class="muted">Starts Claude with the note as the first message.</div>' +
      '<select id="sendCwd">' + folders.map(f => '<option value="' + E(f.cwd) + '">' + E(f.label) + '</option>').join('') + '</select></div></label>' +
      '<label class="opt" data-m="existing"><input type="radio" name="sm" value="existing"><div class="grow"><b>An existing session</b><div class="muted">Re-opens that session and sends the note as the next message.</div>' +
      '<input type="search" id="sendFind" placeholder="Find a session by name…" autocomplete="off"><div class="pick" id="sendPick"></div>' +
      '<label style="display:flex;gap:7px;align-items:center;margin-top:7px"><input type="checkbox" id="sendFork"> Use a copy (fork), so the original session stays as it is</label></div></label>' +
      '<div class="btns"><button class="btn" data-a="cancel">Cancel</button><button class="btn" data-a="copy">Copy command</button><button class="btn accent" data-a="send" data-autofocus>Send</button></div>', {});
    const pick = dlg.querySelector('#sendPick'), find = dlg.querySelector('#sendFind');
    const sync = () => {
      dlg.querySelectorAll('.opt').forEach(o => { const on = o.dataset.m === mode; o.classList.toggle('on', on); o.querySelector('input[type=radio]').checked = on; });
    };
    const fill = () => {
      const q = U.norm(find.value.trim());
      let list = d.sessions.slice().sort((a, b) => b.start - a.start);
      if (q) list = list.filter(s => U.norm(SC.titleOf(s)).indexOf(q) >= 0 || s.id.indexOf(q) === 0);
      else list = list.filter(s => s.kind !== 'auto');
      if (target && !list.some(s => s.id === target)) { const t = d.byId.get(target); if (t) list.unshift(t); }
      else if (target) { const i = list.findIndex(s => s.id === target); list.unshift(list.splice(i, 1)[0]); }
      pick.innerHTML = list.slice(0, 60).map(s => '<button type="button" data-id="' + s.id + '" class="' + (s.id === target ? 'on' : '') + '"><span class="tt">' + E(SC.titleOf(s)) + '</span><span class="when">' + (SC.isOpen(s) ? '<b class="badge live">open</b> ' : '') + E(U.fmtDay(s.start)) + '</span></button>').join('') ||
        '<div class="muted" style="padding:8px">No session with that name.</div>';
    };
    fill();
    sync();
    find.addEventListener('input', fill);
    find.addEventListener('focus', () => { mode = 'existing'; sync(); });
    pick.addEventListener('click', e => { const b = e.target.closest('button[data-id]'); if (!b) return; e.preventDefault(); target = b.dataset.id; mode = 'existing'; sync(); fill(); });
    dlg.querySelector('#sendCwd').addEventListener('focus', () => { mode = 'new'; sync(); });
    dlg.querySelectorAll('input[name=sm]').forEach(r => r.addEventListener('change', () => { mode = r.value; sync(); }));
    const body = () => {
      if (mode === 'new') return { body: { action: 'note_new', cwd: dlg.querySelector('#sendCwd').value, note: note.text }, what: 'a new session with your note' };
      if (!target) { SC.toast('Pick the session to send it to.', { error: true }); return null; }
      const fork = dlg.querySelector('#sendFork').checked;
      return { body: { action: 'note_resume', sessionId: target, note: note.text, fork: fork }, what: (fork ? 'a copy of ' : '') + '“' + U.short(SC.titleOf(d.byId.get(target)), 40) + '” with your note' };
    };
    dlg.querySelector('.btns').addEventListener('click', async e => {
      const a = e.target.dataset.a;
      if (a === 'cancel') return SC.closeModal();
      if (a !== 'send' && a !== 'copy') return;
      const b = body();
      if (!b) return;
      if (a === 'copy') { await copyCommand(b.body); return; }
      const t = b.body.sessionId ? d.byId.get(b.body.sessionId) : null;
      if (t && !b.body.fork) await SC.refreshLive();
      if (t && !b.body.fork && SC.isOpen(t)) {
        SC.closeModal();
        const v = await SC.ask('That session is already open',
          '<p>' + E(openNote(t)) + ' Sending opens a second window on the same conversation, so copy the note and paste it into the open window instead.</p>',
          [{ label: 'Copy note', value: 'copy', cls: 'accent', focus: true }, { label: 'Send to a copy (fork)', value: 'fork' }, { label: 'Open a second window anyway', value: 'go', cls: 'danger' }, { label: 'Cancel', value: null }]);
        if (!v) return;
        if (v === 'copy') {
          const ok = await U.copy(b.body.note);
          SC.toast(ok ? 'Note copied. Go to the open window and paste it (Cmd+V).' : 'Could not copy the note', { error: !ok, ms: 8000 });
          return;
        }
        if (v === 'fork') b.body.fork = true;
        SC.doSpawn(b.body, b.what);
        return;
      }
      SC.closeModal();
      SC.doSpawn(b.body, b.what);
    });
  };

  // ---- start a new session (e.g. for the day) ----
  SC.folderChoices = function () {
    const d = SC.data, folders = [], seen = new Set();
    const add = (cwd, label) => { if (cwd && !seen.has(cwd)) { seen.add(cwd); folders.push({ cwd: cwd, label: label }); } };
    add(d.defaultCwd, U.homePath(d.defaultCwd, d.home) + '  (this folder)');
    const counts = new Map();
    for (const s of d.sessions) if (s.cwd && s.project !== 'desktop') counts.set(s.cwd, (counts.get(s.cwd) || 0) + 1);
    Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).forEach(x => add(x[0], U.homePath(x[0], d.home)));
    return folders;
  };
  SC.openNewSessionDialog = function () {
    if (ui.modal) return;
    const folders = SC.folderChoices();
    const quick = SC.quickCommands();
    const dlg = SC.modal(
      '<h3>Start a new session</h3>' +
      '<label class="lbl">Folder</label><select id="nsCwd">' + folders.map(f => '<option value="' + E(f.cwd) + '">' + E(f.label) + '</option>').join('') + '</select>' +
      '<label class="lbl" style="display:block;margin-top:10px">First message <span class="muted">(optional)</span></label>' +
      '<textarea id="nsText" rows="3" style="width:100%;box-sizing:border-box" placeholder="Leave empty for a blank session, or type what Claude should do first"></textarea>' +
      (quick.length ? '<div class="chips"><span class="hint">Quick start:</span>' + quick.map(c => '<button type="button" class="chip" data-chip="' + E(c) + '">' + E(c) + '</button>').join('') + '</div>'
        : '<div class="chips"><span class="hint">No quick-start commands yet ·</span><button type="button" class="linkbtn" data-a="addquick">add some</button></div>') +
      '<div class="btns"><button class="btn" data-a="cancel">Cancel</button><button class="btn" data-a="copy">Copy command</button><button class="btn accent" data-a="start" data-autofocus>Start</button></div>');
    const ta = dlg.querySelector('#nsText');
    dlg.addEventListener('click', e => { if (e.target.dataset.a === 'addquick') { SC.closeModal(); SC.openSetup(3); } });
    const chips = dlg.querySelectorAll('.chip');
    const markChip = () => chips.forEach(c => c.classList.toggle('on', ta.value.trim() === c.dataset.chip));
    dlg.querySelector('.chips').addEventListener('click', e => { const c = e.target.closest('[data-chip]'); if (c) { ta.value = c.dataset.chip; markChip(); ta.focus(); } });
    ta.addEventListener('input', markChip);
    const body = () => {
      const cwd = dlg.querySelector('#nsCwd').value, text = ta.value.trim();
      return text ? { action: 'note_new', cwd: cwd, note: text } : { action: 'new', cwd: cwd };
    };
    ta.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); dlg.querySelector('[data-a="start"]').click(); } });
    dlg.querySelector('.btns').addEventListener('click', async e => {
      const a = e.target.dataset.a;
      if (a === 'cancel') return SC.closeModal();
      if (a === 'copy') return copyCommand(body());
      if (a !== 'start') return;
      const b = body();
      SC.closeModal();
      SC.doSpawn(b, b.note ? 'a new session (' + U.short(b.note, 30) + ')' : 'a new session');
    });
  };

  // ---- help ----
  SC.openHelp = function () {
    const k = (keys, text) => '<tr><td>' + keys.split(' ').map(x => '<kbd>' + x + '</kbd>').join(' ') + '</td><td>' + text + '</td></tr>';
    const term = (SC.state.settings && SC.state.settings.terminal) || 'Terminal';
    const dlg = SC.modal(
      '<h3>' + E(SC.APP_NAME) + ': how it works</h3>' +
      '<p class="muted">Every card is one Claude Code session. Nothing here leaves your Mac. What you move, rename, colour, hide or write is saved by itself.</p>' +
      '<div class="cols"><div><p><b>Move around</b></p><table class="keys">' +
      k('drag', 'move the board (two fingers on the trackpad also work)') +
      k('pinch', 'or the mouse wheel: zoom where the pointer is') +
      k('F', 'show everything') + k('T', 'today / newest session') + k('0', 'back to 100%') + k('+ -', 'zoom in / out') +
      (SC.data.statusOn ? k('1 2 3 4', 'Tree / Timeline / Free / Status layout') + k('W', 'the “Your turn” list: what waits on you') : k('1 2 3', 'Tree / Timeline / Free layout')) +
      k('← ↑ → ↓', 'next card in that direction') +
      '</table><p><b>Find</b></p><table class="keys">' +
      k('/', 'search; small typos are fine') + k('Enter', 'next match (Shift+Enter: previous)') + k('Esc', 'clear / close / stop') +
      '</table></div><div><p><b>Cards</b></p><table class="keys">' +
      k('click', 'open details, Resume, Fork, links') +
      k('Enter', 'focus: dim everything not linked to it') + k('[ ]', 'back / forward between focused cards') +
      k('L', 'draw a link: then click the other card (or drag the pink dot)') +
      k('C', 'fold or unfold what hangs below a card (Tree)') + k('H', 'hide the card') +
      k('Delete', 'remove the selected link or note') +
      '</table><p><b>Notes and undo</b></p><table class="keys">' +
      k('S', 'start a new session (with a quick-start command if you set some)') +
      k('N', 'new sticky note (or double-click the board)') +
      k('⌘Z', 'undo (Shift+⌘Z: redo)') + k('R', 'look for new sessions now') +
      '</table></div></div>' +
      (SC.data.statusOn ? '<p class="muted"><b>Where a card stands</b> comes from its report: ' + SC.STATE_ORDER.map(k => SC.stateDot(k) + ' ' + E(SC.STATES[k].zone.toLowerCase())).join(' &nbsp; ') +
      '. Click a card for <b>Sent</b>, <b>Mark done</b> or <b>Replaced by…</b> when you already dealt with it (⌘Z undoes it). <b>Status</b> (4) shows one zone per state.</p>' : '') +
      '<p class="muted">In <b>Timeline</b>, drag a card up or down to reorder it inside its day. In <b>Free</b>, drag cards anywhere (hold Shift to bring what hangs below it).</p>' +
      '<p><b>Settings</b></p>' +
      '<p>Open sessions in: ' + ['Terminal', 'iTerm', 'Ghostty'].map(t => '<label><input type="radio" name="term" value="' + t + '"' + (term === t ? ' checked' : '') + '> ' + t + '</label>').join(' &nbsp; ') +
      '<br><span class="muted">Terminal and iTerm: your Mac asks once whether this may control them, click OK. Ghostty needs no permission.</span></p>' +
      '<p>New sessions start in: <b>' + E(U.homePath(SC.data.defaultCwd, SC.data.home) || '~') + '</b> &nbsp;·&nbsp; Quick start: ' +
      (SC.quickCommands().length ? SC.quickCommands().map(c => '<code>' + E(c) + '</code>').join(' ') : '<span class="muted">none</span>') +
      ' &nbsp;·&nbsp; <button class="linkbtn" data-a="setup">Run setup again</button></p>' +
      '<p>Status board and reminder: <b>' + (SC.data.statusOn ? 'on' : 'off') + '</b> &nbsp;·&nbsp; <button class="linkbtn" data-a="advanced">Advanced settings</button>' +
      ' &nbsp;·&nbsp; Version <b>' + E(SC.version) + '</b> <span id="updState" class="muted"></span> <button class="linkbtn" data-a="checkupd">Check for updates</button></p>' +
      '<p><label><input type="checkbox" id="setEdges"' + (SC.state.view.showEdges !== false ? ' checked' : '') + '> Show the link lines between cards</label></p>' +
      '<p><button class="linkbtn" data-a="reseed-tree">Re-arrange the Free layout like the Tree</button> &nbsp;·&nbsp; <button class="linkbtn" data-a="reseed-timeline">like the Timeline</button>' +
      (SC.state.removedEdges.length ? ' &nbsp;·&nbsp; <button class="linkbtn" data-a="restore">Put back ' + SC.state.removedEdges.length + ' removed links</button>' : '') + '</p>' +
      '<div class="btns"><button class="btn accent" data-a="close" data-autofocus>Got it</button></div>', { wide: true });
    dlg.addEventListener('change', e => {
      if (e.target.name === 'term') { SC.state.settings.terminal = e.target.value; SC.touch('settings'); SC.toast('Sessions will open in ' + e.target.value); }
      if (e.target.id === 'setEdges') { SC.state.view.showEdges = e.target.checked; SC.touch('view'); SC.requestRender(); }
    });
    dlg.addEventListener('click', e => {
      const a = e.target.dataset.a;
      if (a === 'close') SC.closeModal();
      if (a === 'setup') { SC.closeModal(); SC.openSetup(1); }
      if (a === 'advanced') { SC.closeModal(); SC.openAdvanced(); }
      if (a === 'update') { SC.closeModal(); SC.runUpdate(); }
      if (a === 'checkupd') {
        const el = dlg.querySelector('#updState');
        el.textContent = '· looking…';
        const show = i => {
          if (!i) el.textContent = '· could not look (is the Canvas server running?)';
          else if (!i.enabled) el.textContent = '· not looked for in test mode';
          else if (i.available && i.canUpdate) el.innerHTML = '· <button class="linkbtn" data-a="update">Update to v' + E(i.latest) + '</button>';
          else if (i.available) el.textContent = '· v' + i.latest + ' is out (this copy runs from a source folder: update it with git)';
          else if (i.latest) el.textContent = '· up to date';
          else el.textContent = '· could not reach GitHub';
        };
        SC.checkUpdate(true).then(i => { if (i && i.checking) setTimeout(() => SC.checkUpdate().then(show), 4000); else show(i); });
      }
      if (a === 'restore') { SC.checkpoint('restore links'); SC.state.removedEdges = []; SC.touch('removedEdges'); SC.invalidate(); SC.afterStateChange(true); SC.closeModal(); SC.toast('Links are back'); }
      if (a === 'reseed-tree' || a === 'reseed-timeline') {
        SC.checkpoint('re-arrange');
        const nodes = SC.visibleSessions().map(s => SC.nodes.get(s.id));
        SC.state.positions = {};
        SC.seedFree(nodes, SC.edges(), a === 'reseed-timeline' ? 'timeline' : 'tree');
        SC.closeModal();
        SC.setLayout('free', true);
        SC.afterStateChange(true);
        SC.toast('Free layout re-arranged', { action: { label: 'Undo', fn: () => SC.doUndo() } });
      }
    });
  };
})(window.SC);
