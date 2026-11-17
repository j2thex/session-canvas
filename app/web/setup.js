/* Session Canvas — first-run setup wizard (also reachable from ? → Settings → Run setup again). */
(function (SC) {
  'use strict';
  const U = SC.U, E = U.esc;

  function settings() { return SC.state.settings || (SC.state.settings = {}); }
  SC.quickCommands = () => (Array.isArray(settings().quick) ? settings().quick : []).filter(x => typeof x === 'string' && x.trim());

  /* step: start at this step (0..4). Resolves when the wizard closes. */
  SC.openSetup = async function (step) {
    if (SC.ui && SC.ui.modal) SC.closeModal();
    let info = { terminals: ['Terminal'], folders: [], home: '', defaultCwd: '', claude: null, projectsFound: true, name: SC.APP_NAME };
    try { info = Object.assign(info, await SC.api.get('/api/setup')); } catch (e) { /* the defaults still work */ }
    const st = settings();
    const pick = {
      cwd: st.defaultCwd || (info.folders[0] && info.folders[0].cwd) || info.defaultCwd || info.home,
      terminal: info.terminals.includes(st.terminal) ? st.terminal : info.terminals.includes('Ghostty') && !st.terminal ? 'Terminal' : (st.terminal || 'Terminal'),
      quick: SC.quickCommands().slice(),
    };
    if (!info.terminals.includes(pick.terminal)) pick.terminal = info.terminals[0] || 'Terminal';
    let i = Math.max(0, Math.min(4, step || 0));
    const steps = ['Welcome', 'Folder', 'Terminal', 'Quick start', 'Done'];
    const n = SC.data.sessions.length;
    const used = () => (SC.data.commands || []).map(c => c[0]).filter(c => !pick.quick.includes(c)).slice(0, 6);
    const homeShort = c => U.homePath(c, info.home);

    function body() {
      const dots = '<div class="wz-dots">' + steps.map((s, k) => '<span class="' + (k === i ? 'on' : k < i ? 'done' : '') + '">' + E(s) + '</span>').join('') + '</div>';
      let h = '';
      if (i === 0) {
        h = '<h3>Welcome to ' + E(info.name || 'Session Canvas') + '</h3>' +
          '<p>Every Claude Code session on this Mac becomes a card on one board. Cards are linked when one session continued, copied or started another. You can search everything that was said, and reopen any session with one click.</p>' +
          '<ul class="wz-facts">' +
          '<li>' + (n ? '<b>' + n + '</b> sessions found.' : (info.projectsFound ? 'No sessions yet. Use Claude Code and they will appear here by themselves.' : 'Claude Code has not saved any sessions on this Mac yet.')) + '</li>' +
          '<li>' + (info.claude ? 'Claude Code found: <code>' + E(homeShort(info.claude)) + '</code>' : '<b class="warn">Claude Code was not found.</b> Install it first, otherwise the Resume buttons cannot open anything.') + '</li>' +
          '<li>Everything stays on this Mac. Nothing is sent anywhere.</li></ul>' +
          '<p class="muted">Three quick questions and you are done. You can change every answer later under <b>?</b> → Settings.</p>';
      } else if (i === 1) {
        const opts = info.folders.slice(0, 7);
        if (pick.cwd && !opts.some(f => f.cwd === pick.cwd)) opts.unshift({ cwd: pick.cwd, sessions: 0 });
        h = '<h3>Where should new sessions start?</h3>' +
          '<p class="muted">The folder Claude opens in when you press <b>+ Session</b>. Usually your main project.</p>' +
          '<div class="wz-list">' + opts.map(f => '<label class="opt' + (f.cwd === pick.cwd ? ' on' : '') + '"><input type="radio" name="wzcwd" value="' + E(f.cwd) + '"' + (f.cwd === pick.cwd ? ' checked' : '') + '><div class="grow"><b>' + E(homeShort(f.cwd)) + '</b>' +
            (f.sessions ? '<div class="muted">' + f.sessions + ' sessions</div>' : '') + '</div></label>').join('') + '</div>' +
          '<label class="lbl" style="margin-top:10px">Or type a folder</label><input type="text" id="wzPath" placeholder="~/Projects/my-app" value="">' +
          '<div class="muted" id="wzPathMsg"></div>';
      } else if (i === 2) {
        const about = {
          Terminal: 'The Mac\'s own terminal. The first time, macOS asks whether ' + E(info.name || 'this') + ' may control Terminal: click OK once.',
          iTerm: 'iTerm2. Like Terminal, macOS asks once for permission: click OK.',
          Ghostty: 'Ghostty. Needs no permission from the Mac.',
        };
        h = '<h3>Which terminal should sessions open in?</h3>' +
          '<div class="wz-list">' + info.terminals.map(t => '<label class="opt' + (t === pick.terminal ? ' on' : '') + '"><input type="radio" name="wzterm" value="' + E(t) + '"' + (t === pick.terminal ? ' checked' : '') + '><div class="grow"><b>' + E(t) + '</b><div class="muted">' + about[t] + '</div></div></label>').join('') + '</div>' +
          (info.terminals.length === 1 ? '<p class="muted">Only Terminal is installed. iTerm and Ghostty show up here once installed.</p>' : '');
      } else if (i === 3) {
        h = '<h3>Quick-start commands <span class="muted" style="font-weight:400">(optional)</span></h3>' +
          '<p class="muted">One-click first messages for <b>+ Session</b>, for example a slash command you run every morning. Leave empty if you don\'t need any.</p>' +
          '<div class="chips" id="wzChips">' + (pick.quick.length ? pick.quick.map((c, k) => '<span class="chip on">' + E(c) + ' <button type="button" class="chip-x" data-del="' + k + '" title="Remove">×</button></span>').join('') : '<span class="hint">None yet.</span>') + '</div>' +
          '<div class="wz-add"><input type="text" id="wzQuick" placeholder="/my-command or a short first message" maxlength="200"><button class="btn" data-a="add">Add</button></div>' +
          (used().length ? '<div class="chips"><span class="hint">Used in your sessions:</span>' + used().map(c => '<button type="button" class="chip" data-sug="' + E(c) + '">+ ' + E(c) + '</button>').join('') + '</div>' : '');
      } else {
        h = '<h3>All set</h3>' +
          '<ul class="wz-facts">' +
          '<li>New sessions start in <b>' + E(homeShort(pick.cwd)) + '</b></li>' +
          '<li>Sessions open in <b>' + E(pick.terminal) + '</b></li>' +
          '<li>' + (pick.quick.length ? 'Quick start: ' + pick.quick.map(c => '<code>' + E(c) + '</code>').join(' ') : 'No quick-start commands') + '</li></ul>' +
          '<p class="muted">Optional, for later: a Status board fed by report files and a reminder. <button class="linkbtn" data-a="advanced">Advanced…</button></p>' +
          '<p><b>Try it safely:</b> “Show me a test” shows the exact command a Resume would run, without opening anything.</p>' +
          '<p class="muted">Tips: press <kbd>/</kbd> to search, <kbd>S</kbd> for a new session, <kbd>?</kbd> for help and settings.</p>';
      }
      const back = i > 0 ? '<button class="btn" data-a="back">Back</button>' : '<button class="btn" data-a="later">Later</button>';
      const next = i < 4 ? '<button class="btn accent" data-a="next" data-autofocus>' + (i === 0 ? 'Start' : 'Next') + '</button>'
        : (n ? '<button class="btn" data-a="test">Show me a test</button>' : '') + '<button class="btn accent" data-a="finish" data-autofocus>Open the board</button>';
      return '<div class="wizard">' + dots + h + '<div class="btns">' + back + next + '</div></div>';
    }

    function save(done) {
      const s = settings();
      s.defaultCwd = pick.cwd;
      s.terminal = pick.terminal;
      s.quick = pick.quick.slice(0, 12);
      if (done) s.setupDone = true;
      SC.touch('settings');
      if (pick.cwd) SC.data.defaultCwd = pick.cwd;
    }

    async function checkPath(v) {
      v = (v || '').trim();
      if (!v) return null;
      if (v[0] === '~') v = info.home + v.slice(1);
      try {
        const r = await SC.api.get('/api/dir?path=' + encodeURIComponent(v));
        return r.ok ? r.path : (r.error || 'That folder does not exist.');
      } catch (e) { return 'Could not check that folder.'; }
    }

    return new Promise(resolve => {
      let dlg;
      const render = () => {
        dlg = SC.modal(body(), { wide: false });
        SC.ui.modalDone = () => { save(false); settings().setupDone = true; SC.touch('settings'); cleanup(); resolve(false); };
      };
      render();
      const root = () => document.getElementById('modal');
      const onClick = async e => {
        const t = e.target;
        const a = t.dataset && t.dataset.a;
        if (t.dataset && t.dataset.del !== undefined) { pick.quick.splice(+t.dataset.del, 1); render(); return; }
        if (t.dataset && t.dataset.sug) { if (!pick.quick.includes(t.dataset.sug)) pick.quick.push(t.dataset.sug); render(); return; }
        if (a === 'add') {
          const inp = document.getElementById('wzQuick');
          const v = (inp.value || '').trim();
          if (v && !pick.quick.includes(v)) pick.quick.push(v);
          render();
          const again = document.getElementById('wzQuick');
          if (again) again.focus();
          return;
        }
        if (a === 'back') { i--; render(); return; }
        if (a === 'later') { SC.ui.modalDone = null; settings().setupDone = true; SC.touch('settings'); SC.closeModal(); cleanup(); resolve(false); return; }
        if (a === 'next') {
          if (i === 1) {
            const typed = document.getElementById('wzPath').value;
            if (typed.trim()) {
              const r = await checkPath(typed);
              if (!r || r[0] !== '/') { document.getElementById('wzPathMsg').textContent = r || 'Type a full folder path.'; return; }
              pick.cwd = r;
            }
          }
          i++; render(); return;
        }
        if (a === 'test') {
          const newest = SC.data.sessions.slice().sort((x, y) => y.start - x.start)[0];
          save(true);
          SC.ui.modalDone = null;
          SC.closeModal(); cleanup(); resolve(true);
          if (newest) { SC.jumpToNode(newest.id); SC.doSpawn({ action: 'resume', sessionId: newest.id, dryRun: true }, '“' + U.short(SC.titleOf(newest), 40) + '”'); }
          return;
        }
        if (a === 'advanced') { save(true); SC.ui.modalDone = null; SC.closeModal(); cleanup(); resolve(true); SC.openAdvanced(); return; }
        if (a === 'finish') { save(true); SC.ui.modalDone = null; SC.closeModal(); cleanup(); resolve(true); SC.toast('Saved. Change it any time under ? → Settings.'); }
      };
      const onChange = e => {
        if (e.target.name === 'wzcwd') { pick.cwd = e.target.value; root().querySelectorAll('.opt').forEach(o => o.classList.toggle('on', o.querySelector('input').checked)); }
        if (e.target.name === 'wzterm') { pick.terminal = e.target.value; root().querySelectorAll('.opt').forEach(o => o.classList.toggle('on', o.querySelector('input').checked)); }
      };
      const onKey = e => {
        if (e.key === 'Enter' && e.target.id === 'wzQuick') { e.preventDefault(); root().querySelector('[data-a="add"]').click(); }
        if (e.key === 'Enter' && e.target.id === 'wzPath') { e.preventDefault(); root().querySelector('[data-a="next"]').click(); }
      };
      const cleanup = () => { root().removeEventListener('click', onClick); root().removeEventListener('change', onChange); root().removeEventListener('keydown', onKey); };
      root().addEventListener('click', onClick);
      root().addEventListener('change', onChange);
      root().addEventListener('keydown', onKey);
    });
  };

  /* Advanced (optional, all off by default): status reports and the reminder. ? → Settings → Advanced settings. */
  SC.openAdvanced = function () {
    const st = settings(), home = SC.data.home || '';
    const folders = (Array.isArray(st.reportFolders) ? st.reportFolders : []).filter(x => typeof x === 'string');
    const mins = typeof st.remindMin === 'number' && st.remindMin >= 0 ? st.remindMin : 30;
    const dlg = SC.modal('<h3>Advanced settings <span class="muted" style="font-weight:400">(optional)</span></h3>' +
      '<p class="muted">Leave everything empty if you don\'t use these. The board works without them.</p>' +
      '<p><b>Status reports</b><br><span class="muted">If your sessions write small report files (first lines: <code>status: done | not-done | your-turn | question</code>, <code>name:</code>, <code>outcome:</code>, <code>left:</code>), ' +
      'the board shows where each card stands, a <b>Status</b> layout and a <b>Your turn</b> list. Give the folder(s) that hold them, one per line. Reports sit in the folder or in one sub-folder per day. The README has the details.</span></p>' +
      '<textarea id="advFolders" rows="3" style="width:100%;box-sizing:border-box" placeholder="~/Projects/my-app/reports">' + E(folders.map(f => U.homePath(f, home)).join('\n')) + '</textarea>' +
      '<label class="lbl" style="margin-top:8px">Your first name as the reports write it (optional): “&lt;name&gt; picks / decides / answers …” then counts as a question for you</label>' +
      '<input type="text" id="advName" maxlength="40" value="' + E(typeof st.userName === 'string' ? st.userName : '') + '">' +
      '<p style="margin-top:14px"><b>Reminder</b><br><span class="muted">When a card has waited on you this long, the board runs your command once with one line of text (for example a script that shows a notification). Needs status reports.</span></p>' +
      '<label class="lbl">Command: the full path of a script or program</label><input type="text" id="advCmd" placeholder="~/bin/notify-me.sh" value="' + E(typeof st.notifyCommand === 'string' ? U.homePath(st.notifyCommand, home) : '') + '">' +
      '<label class="lbl" style="margin-top:8px">Remind after this many minutes (0 = never)</label><input type="number" id="advMin" min="0" max="10080" step="5" style="width:110px" value="' + mins + '">' +
      '<div class="muted warn" id="advMsg" style="margin-top:8px"></div>' +
      '<div class="btns"><button class="btn" data-a="cancel">Cancel</button><button class="btn accent" data-a="save" data-autofocus>Save</button></div>', { wide: true });
    const abs = v => { v = (v || '').trim(); return v[0] === '~' ? home + v.slice(1) : v; };
    dlg.addEventListener('click', async e => {
      const a = e.target.dataset.a;
      if (a === 'cancel') { SC.closeModal(); return; }
      if (a !== 'save') return;
      const msg = dlg.querySelector('#advMsg'), out = [];
      for (const line of dlg.querySelector('#advFolders').value.split('\n').map(x => x.trim()).filter(Boolean)) {
        let r = null;
        try { r = await SC.api.get('/api/dir?path=' + encodeURIComponent(abs(line))); } catch (err) { r = null; }
        if (!r || !r.ok) { msg.textContent = 'This folder was not found: ' + line; return; }
        if (!out.includes(r.path)) out.push(r.path);
      }
      const cmd = abs(dlg.querySelector('#advCmd').value);
      if (cmd && cmd[0] !== '/') { msg.textContent = 'The command must be a full path, starting with / or ~.'; return; }
      const m = parseFloat(dlg.querySelector('#advMin').value);
      st.reportFolders = out.slice(0, 8);
      st.userName = dlg.querySelector('#advName').value.trim().slice(0, 40);
      st.notifyCommand = cmd.slice(0, 500);
      st.remindMin = isFinite(m) && m >= 0 ? m : 30;
      SC.touch('settings');
      SC.closeModal();
      await SC.flush();
      await SC.refresh(false);
      SC.toast(out.length ? 'Saved. Status reports are on.' : 'Saved. Status reports are off.');
    });
  };
})(window.SC);
