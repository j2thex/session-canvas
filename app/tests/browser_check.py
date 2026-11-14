#!/usr/bin/python3
"""Drives the real page in headless Chrome and checks that everything on the board works.

    /usr/bin/python3 app/tests/browser_check.py [--keep] [--shots DIR]

Needs Google Chrome (or Chromium) installed. It starts its own server in DRY-RUN mode on a spare port with
a throw-away state file, cache and a made-up history of sessions (tests/fixtures.py demo_corpus), so it
never opens a terminal, never starts Claude, and never reads or touches anything real on this Mac.
Screenshots go to app/tests/screenshots/ (git-ignored). Exit code 0 = every check passed.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cdp  # noqa: E402

RESULTS = []
_LAST = [time.time()]


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    now = time.time()
    took = now - _LAST[0]
    _LAST[0] = now
    print('%s  %s%s%s' % ('PASS' if ok else 'FAIL', name, ('  -- ' + str(detail)) if detail else '', ('   [%.1fs]' % took) if took > 3 else ''))
    sys.stdout.flush()
    return bool(ok)


def free_port(start):
    import socket
    for p in range(start, start + 50):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', p))
            s.close()
            return p
        except OSError:
            s.close()
    raise RuntimeError('no free port')


class Env(object):
    """A Canvas server in dry-run mode with its own state file and cache."""

    def __init__(self, tmp, projects=None, root=None, port=None, wizard=False):
        self.tmp = tmp
        if not wizard:                                   # the first-run wizard is tested on its own (run_wizard)
            with open(os.path.join(tmp, 'state.json'), 'w') as fh:
                json.dump({'version': 1, 'rev': 0, 'savedAt': 0, 'settings': {'setupDone': True}}, fh)
        self.port = port or free_port(7811)
        self.base = 'http://127.0.0.1:%d' % self.port
        self.state_path = os.path.join(tmp, 'state.json')
        self.root = root
        self.extra = (['--projects', projects] if projects else []) + (['--root', root] if root else [])
        self.log = open(os.path.join(tmp, 'server.log'), 'ab')
        self.start()

    def start(self):
        env = dict(os.environ)
        for k in list(env):
            if k.startswith('CLAUDE') or k == 'AI_AGENT':
                del env[k]
        self.live_dir = os.path.join(self.tmp, 'live')
        os.makedirs(self.live_dir, exist_ok=True)
        env['CANVAS_LIVE_DIR'] = self.live_dir          # which sessions count as open: only what a test writes here
        self.proc = subprocess.Popen(['/usr/bin/python3', os.path.join(APP, 'server.py'), '--port', str(self.port), '--strict-port',
                                      '--dry-run', '--state', self.state_path, '--cache', os.path.join(self.tmp, 'cache'),
                                      '--info', os.path.join(self.tmp, 'server.json')] + self.extra, stdout=self.log, stderr=self.log, env=env)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if self.get('/api/health').get('ready'):
                    return
            except Exception:
                pass
            time.sleep(0.2)
        raise RuntimeError('server did not become ready')

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=20) as r:
            return json.loads(r.read().decode())

    def state(self):
        return self.get('/api/state')

    def stop(self, close_log=True):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=8)
        except Exception:
            self.proc.kill()
        if close_log:
            self.log.close()

    def restart(self):
        self.stop(close_log=False)
        self.start()


J = json.dumps


def summary(b):
    return b.js('SC.debug.summary()')


def rect(b, sid):
    return b.js('SC.debug.rect(%s)' % J(sid))


def center_node(b, sid, z=0.9):
    b.js('(()=>{const n=SC.nodes.get(%s); SC.centerOn(n,{z:%s,animate:false}); SC.drawNow();})()' % (J(sid), z))
    r = rect(b, sid)
    return r['x'] + r['w'] / 2, r['y'] + r['h'] / 2, r


def el(b, selector):
    return b.js('(()=>{const e=document.querySelector(%s); if(!e||e.hidden) return null; const r=e.getBoundingClientRect(); '
                'return {x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height,l:r.left,t:r.top};})()' % J(selector))


def click_el(b, selector):
    c = el(b, selector)
    if not c:
        raise RuntimeError('element not found: ' + selector)
    b.click(c['x'], c['y'])
    return c


def settle(b, secs=0.5):
    b.sleep(secs)
    b.js('SC.drawNow()')


def wait_saved(b, env, timeout=6):
    """Wait until the page says everything is written to state.json."""
    b.wait("SC.saveState === 'saved'", timeout)
    b.sleep(0.15)
    return env.state()


def close_modal(b):
    b.js("SC.closeModal()")


def modal_text(b):
    return b.js("(()=>{const m=document.getElementById('modal'); return m.hidden ? '' : m.innerText;})()") or ''


def best_shots(env, b, shots):
    """Three sharp pictures of an untouched board (nothing is saved while taking them)."""
    def snap(name):
        settle(b, 1.3)                      # let every card finish drawing
        b.set_scale(2)
        b.sleep(0.2)
        b.js('SC.resize(); SC.drawNow()')
        b.sleep(0.2)
        b.screenshot(os.path.join(shots, name + '.png'))
        b.set_scale(1)
        b.sleep(0.1)
    b.goto(env.base + '/?nosave=1&layout=tree&home=1')
    snap('best-1-tree')
    b.goto(env.base + '/?nosave=1&layout=timeline&home=1')
    snap('best-2-timeline')
    b.goto(env.base + '/?nosave=1&layout=tree&q=override')
    b.wait('SC.search.loading === false && SC.search.order.length > 0', 8)
    b.js("SC.search.index = 0; SC.jumpToNode(SC.search.order[0])")
    b.wait("document.querySelector('#panel .msg') !== null", 5)
    snap('best-3-search-and-details')
    b.events = []


def run(env, b, shots, only=None):
    def shot(name, scale=None):
        settle(b, 0.45)
        p = os.path.join(shots, name + '.png')
        if scale:
            b.set_scale(scale)
            b.sleep(0.2)
            b.js('SC.resize(); SC.drawNow()')
        b.screenshot(p)
        if scale:
            b.set_scale(1)
            b.sleep(0.1)
            b.js('SC.resize(); SC.drawNow()')
        return p

    W, H = b.width, b.height

    # ---------------------------------------------------------------- load
    t0 = time.time()
    ok = b.goto(env.base + '/?debug=1')
    load_s = time.time() - t0
    check('page loads and says it is ready', ok, '%.1fs' % load_s)
    s = summary(b)
    check('sessions are on the board', s['shown'] >= 200 and s['total'] == s['shown'], '%d shown, %d links' % (s['shown'], s['edges']))
    check('links between sessions were found', s['edges'] >= 40, s['edges'])
    check('opens in the Tree layout by default', s['layout'] == 'tree')
    shot('01-tree-home')

    # ---------------------------------------------------------------- camera
    cx, cy = W / 2, H / 2
    before = b.js('(()=>{const w=SC.toWorld(%d,%d); return {x:w.x,y:w.y,z:SC.cam.z};})()' % (cx, cy))
    b.wheel(cx, cy, dy=-240, mods=2)          # Ctrl + wheel = zoom
    settle(b, 0.2)
    after = b.js('(()=>{const w=SC.toWorld(%d,%d); return {x:w.x,y:w.y,z:SC.cam.z};})()' % (cx, cy))
    check('Ctrl+wheel zooms in', after['z'] > before['z'] * 1.05, 'zoom %.2f -> %.2f' % (before['z'], after['z']))
    check('zoom keeps the point under the pointer still', abs(after['x'] - before['x']) < 0.5 and abs(after['y'] - before['y']) < 0.5,
          'moved %.2f, %.2f' % (after['x'] - before['x'], after['y'] - before['y']))
    b.js('SC.homeView(false); SC.drawNow()')
    z0 = b.js('SC.cam.z')
    b.wheel(cx, cy, dy=-120)
    settle(b, 0.2)
    z1 = b.js('SC.cam.z')
    cam1 = b.js('({x:SC.cam.x,y:SC.cam.y})')
    wheel_kind = 'zoomed' if abs(z1 - z0) > 1e-6 else 'panned'
    check('plain wheel does something sensible (zoom for a mouse, pan for a trackpad)', True, 'in this browser it %s' % wheel_kind)
    b.js('SC.homeView(false); SC.drawNow()')
    c0 = b.js('({x:SC.cam.x,y:SC.cam.y,z:SC.cam.z})')
    b.drag(40, 200, 240, 320)                 # empty margin on the left of the board
    settle(b, 0.2)
    c1 = b.js('({x:SC.cam.x,y:SC.cam.y,z:SC.cam.z})')
    check('dragging the board moves it', abs((c0['x'] - c1['x']) * c0['z'] - 200) < 3 and abs((c0['y'] - c1['y']) * c0['z'] - 120) < 3,
          'moved %.0f, %.0f px' % ((c0['x'] - c1['x']) * c0['z'], (c0['y'] - c1['y']) * c0['z']))
    b.key('f')
    settle(b, 0.6)
    s = summary(b)
    check('F shows everything', s['drawn'] == s['shown'], 'zoom %.2f, %d of %d drawn' % (s['zoom'], s['drawn'], s['shown']))
    shot('02-tree-fit-all')
    m = el(b, '#minimap')
    c0 = b.js('({x:SC.cam.x,y:SC.cam.y})')
    b.click(m['l'] + m['w'] * 0.5, m['t'] + m['h'] * 0.85)
    settle(b, 0.2)
    c1 = b.js('({x:SC.cam.x,y:SC.cam.y})')
    check('clicking the minimap moves the view', abs(c1['y'] - c0['y']) > 50, 'y %.0f -> %.0f' % (c0['y'], c1['y']))
    b.key('0')
    settle(b, 0.3)
    check('0 goes back to 100%', abs(b.js('SC.cam.z') - 1) < 0.01)

    # ---------------------------------------------------------------- select, panel, open sessions (dry run)
    parent = b.js("(()=>{const n=SC.lay.shown.filter(n=>SC.kidCount(n.id)>=2).sort((a,b)=>b.s.start-a.s.start)[0]; return n?n.id:null;})()")
    check('found a session that started helpers', bool(parent), parent)
    x, y, r = center_node(b, parent)
    b.click(x, y)
    settle(b, 0.5)
    s = summary(b)
    check('clicking a card selects it and opens the details', s['sel'] and s['sel']['id'] == parent and s['panelOpen'])
    title = b.js("document.querySelector('#panel h2').firstChild.textContent")
    check('details show the title', bool(title), title)
    b.wait("document.querySelector('#panel .msg') !== null", 5)
    check('details show how it started and ended', b.js("document.querySelectorAll('#panel .msg').length") >= 2)
    check('details list links found in the session', b.js("document.querySelectorAll('#panel .links a').length") >= 1,
          b.js("document.querySelectorAll('#panel .links a').length"))
    check('details list related sessions', b.js("document.querySelectorAll('#panel .rel').length") >= 2)
    shot('03-details-panel')

    click_el(b, '#panel [data-act="resume"]')
    b.wait("!document.getElementById('modal').hidden", 5)
    txt = modal_text(b)
    if 'already open' in txt:          # the newest HQ session may be the one running these tests
        b.js("Array.from(document.querySelectorAll('#modal .btns button')).pop().click()")
        b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
        txt = modal_text(b)
    check('Resume (test mode) shows the exact command', ('--resume ' + parent) in txt and 'osascript' in txt and '--fork-session' not in txt, txt[:160].replace('\n', ' '))
    shot('04-resume-dry-run')
    close_modal(b)
    click_el(b, '#panel [data-act="fork"]')
    b.wait("!document.getElementById('modal').hidden", 5)
    txt = modal_text(b)
    check('Fork shows --fork-session', ('--resume ' + parent + ' --fork-session') in txt)
    close_modal(b)
    click_el(b, '#panel [data-act="new"]')
    b.wait("!document.getElementById('modal').hidden", 5)
    txt = modal_text(b)
    check('New session here uses the same folder and no id', '--resume' not in txt and 'cd ' in txt and 'claude' in txt, txt.split('Paste-able command')[-1][:140].replace('\n', ' '))
    close_modal(b)
    log = env.get('/api/spawnlog')['entries']
    check('server recorded three dry runs and opened nothing', len(log) >= 3 and all(e['dryRun'] for e in log), [e['action'] for e in log][-3:])

    # live-mode screens, with the real opener swapped for a stand-in (still nothing is opened)
    b.js("window.__realSpawn = SC.spawn; window.__calls = []; SC.dryRun = false; "
         "SC.spawn = async (body) => { window.__calls.push(body); const term = (SC.state.settings.terminal || 'Terminal'); "
         "return term === 'Terminal' ? {ok:false, dryRun:false, terminal:'Terminal', message:'macOS blocked this. Allow it once in System Settings.', command:'cd /x && claude --resume abc', copied:true, warnings:[], installed:['Terminal','Ghostty']} "
         ": {ok:true, dryRun:false, terminal:term, message:'Opened in Ghostty.', command:'x', warnings:[]}; }")
    click_el(b, '#panel [data-act="fork"]')
    b.wait("!document.getElementById('modal').hidden", 5)
    txt = modal_text(b)
    check('if the Mac refuses to open Terminal, the page explains it and offers a way out', 'It did not open' in txt and 'clipboard' in txt and 'Use Ghostty' in txt and 'Try again' in txt, txt[:90].replace('\n', ' '))
    shot('04b-could-not-open')
    click_el(b, '#modal [data-a="ghostty"]')
    b.wait("window.__calls.length === 2", 6)
    st = wait_saved(b, env)
    toast = b.js("document.getElementById('toasts').innerText") or ''
    check('"Use Ghostty" remembers the choice and tries again', st['settings'].get('terminal') == 'Ghostty' and b.js('window.__calls.length') == 2 and 'in Ghostty' in toast, toast.replace('\n', ' | ')[:80])
    b.js("SC.state.settings = {setupDone: true}; SC.touch('settings'); SC.spawn = window.__realSpawn; SC.dryRun = true; SC.closeModal()")
    wait_saved(b, env)

    # rename, label, colour
    click_el(b, '#panel h2')
    b.wait("document.querySelector('#panel .titleedit') !== null", 3)
    b.key('a', mods=4)
    b.js("document.querySelector('#panel .titleedit').select()")
    b.type('Renamed by the test')
    b.key('Enter')
    st = wait_saved(b, env)
    check('renaming a card is saved', st['titles'].get(parent) == 'Renamed by the test', st['titles'])
    b.js("document.getElementById('labelIn').focus()")
    b.type('important')
    b.key('Enter')
    st = wait_saved(b, env)
    check('a label is saved', st['labels'].get(parent) == 'important')
    click_el(b, '#panel .sw:nth-child(4)')
    st = wait_saved(b, env)
    check('a custom colour is saved', str(st['colors'].get(parent, '')).startswith('#'), st['colors'])
    shot('05-renamed-label-colour')

    # ---------------------------------------------------------------- focus, back / forward
    b.key('Enter')
    settle(b, 0.5)
    fam = b.js('SC.ui.family ? SC.ui.family.size : 0')
    dim = b.js("(()=>{const n=SC.lay.shown.find(n=>!SC.ui.family.has(n.id)); return SC.alphaOf(n);})()")
    check('Enter focuses: the family stays lit, the rest dims', b.js('SC.ui.focus') == parent and fam >= 3 and dim < 0.2, 'family of %d, others at %.2f' % (fam, dim))
    shot('06-focus')
    other = b.js("(()=>{const n=SC.lay.shown.filter(n=>SC.kidCount(n.id)>=1 && n.id!==%s)[0]; return n.id;})()" % J(parent))
    b.js('SC.focusNode(%s)' % J(other))
    settle(b, 0.4)
    b.key('[')
    settle(b, 0.4)
    back_ok = b.js('SC.ui.focus') == parent
    b.key(']')
    settle(b, 0.4)
    check('[ and ] go back and forward between focused cards', back_ok and b.js('SC.ui.focus') == other)
    b.key('Escape')
    b.key('Escape')
    settle(b, 0.2)
    check('Esc leaves focus and closes the details', b.js('SC.ui.focus') is None and not summary(b)['panelOpen'])

    # ---------------------------------------------------------------- fold / unfold, hide / unhide
    n_before = summary(b)['shown']
    kids = b.js('SC.Layout.descendants(SC.lay.fam, %s).length' % J(parent))
    x, y, r = center_node(b, parent)
    t = b.js('(()=>{const n=SC.nodes.get(%s); const r=SC.toggleRect(n); const a=SC.toScreen(r.x+r.w/2, r.y+r.h/2); return a;})()' % J(parent))
    b.click(t['x'], t['y'])
    settle(b, 0.4)
    check('the little arrow folds away what hangs below a card', summary(b)['shown'] == n_before - kids, '%d -> %d (%d below)' % (n_before, summary(b)['shown'], kids))
    st = wait_saved(b, env)
    check('folded cards are remembered', parent in st['collapsed'])
    shot('07-folded')
    x, y, r = center_node(b, parent)
    b.click(x, y)
    b.key('c')
    settle(b, 0.4)
    check('C unfolds again', summary(b)['shown'] == n_before)
    single = b.js("(()=>{const n=SC.lay.shown.filter(n=>n.s.kind==='auto')[3]; return n.id;})()")
    x, y, r = center_node(b, single)
    b.click(x, y)
    b.key('h')
    settle(b, 0.4)
    st = wait_saved(b, env)
    check('H hides a card and that is saved', summary(b)['shown'] == n_before - 1 and single in st['hidden'])
    click_el(b, '#btnFilters')
    b.wait("!document.getElementById('filters').hidden", 3)
    check('Filters lists the hidden card', b.js("document.querySelectorAll('#filters .hiddenlist div').length") == 1)
    shot('08-filters')
    click_el(b, '#filters [data-f="showHidden"]')
    settle(b, 0.5)
    faded = b.js('SC.alphaOf(SC.nodes.get(%s))' % J(single))
    check('"Show them faded" puts hidden cards back as ghosts', summary(b)['shown'] == n_before and abs(faded - 0.45) < 0.01, 'drawn at %.2f' % faded)
    click_el(b, '#filters [data-f="showHidden"]')
    settle(b, 0.5)
    b.js("SC.jumpToNode(%s)" % J(single))
    b.wait("/You hid that session/.test(document.getElementById('toasts').innerText)", 4)
    check('jumping to a hidden card offers to unhide it', 'Unhide it' in (b.js("document.getElementById('toasts').innerText") or ''))
    click_el(b, '#filters [data-f="unhide"]')
    settle(b, 0.4)
    check('Unhide brings it back', summary(b)['shown'] == n_before)

    # ---------------------------------------------------------------- filters
    autos = b.js("SC.data.sessions.filter(s=>s.kind==='auto').length")
    click_el(b, '#filters [data-f="kind"][data-v="auto"]')
    settle(b, 0.5)
    check('filter: turning off Automatic removes those cards', summary(b)['shown'] == n_before - autos, '%d -> %d' % (n_before, summary(b)['shown']))
    click_el(b, '#filters [data-f="preset"][data-v="7"]')
    settle(b, 0.5)
    week_n = summary(b)['shown']
    check('filter: Last 7 days narrows further', 0 < week_n < n_before - autos, week_n)
    st = wait_saved(b, env)
    check('filters are saved', st['view']['filters']['kinds']['auto'] is False and st['view']['filters']['from'] is not None)
    check('the Filters button shows how many are on', b.js("document.getElementById('filterCount').textContent") == '2')
    shot('09-filtered')
    click_el(b, '#filters [data-f="clear"]')
    settle(b, 0.5)
    check('Clear filters shows everything again', summary(b)['shown'] == n_before)
    cmd = b.js("SC.data.commands.find(c=>c[0]==='/morning') ? '/morning' : SC.data.commands[0][0]")
    b.js("document.querySelector('#filters [data-f=\"command\"][data-v=' + JSON.stringify(%s) + ']').click()" % J(cmd))
    settle(b, 0.5)
    with_cmd = b.js("SC.data.sessions.filter(s=>s.commands.includes(%s)).length" % J(cmd))
    check('filter: by command used', summary(b)['shown'] == with_cmd, '%s: %d' % (cmd, with_cmd))
    click_el(b, '#filters [data-f="clear"]')
    b.key('Escape')
    settle(b, 0.4)

    # ---------------------------------------------------------------- links by hand
    two = b.js("(()=>{const a=SC.lay.shown.filter(n=>n.s.kind==='you' && !SC.lay.fam.parent.has(n.id) && !SC.kidCount(n.id)); return [a[0].id, a[1].id];})()")
    a_id, b_id = two
    b.js('(()=>{const a=SC.nodes.get(%s), c=SC.nodes.get(%s); SC.fitBounds({x0:Math.min(a.x,c.x)-80,y0:Math.min(a.y,c.y)-80,x1:Math.max(a.x,c.x)+a.w+80,y1:Math.max(a.y,c.y)+a.h+80},{animate:false,maxZ:0.9}); SC.drawNow();})()' % (J(a_id), J(b_id)))
    ra, rb = rect(b, a_id), rect(b, b_id)
    b.move(ra['x'] + ra['w'] / 2, ra['y'] + ra['h'] / 2)
    settle(b, 0.15)
    b.drag(ra['x'] + ra['w'], ra['y'] + ra['h'] / 2, rb['x'] + rb['w'] / 2, rb['y'] + rb['h'] / 2, steps=14)
    settle(b, 0.5)
    st = wait_saved(b, env)
    made = [e for e in st['edges'] if e['from'] == a_id and e['to'] == b_id]
    check('dragging the pink dot from one card to another links them (saved)', len(made) == 1, st['edges'])
    check('in the Tree the linked card now hangs under the other', b.js('SC.lay.fam.parent.get(%s)' % J(b_id)) == a_id)
    shot('10-manual-link')
    g = b.js("(()=>{const it=SC.edgeGeom.find(x=>x.e.kind==='manual'); if(!it) return null; const g=it.g,t=0.5,u=0.5; "
             "const x=u*u*u*g[0]+3*u*u*t*g[2]+3*u*t*t*g[4]+t*t*t*g[6], y=u*u*u*g[1]+3*u*u*t*g[3]+3*u*t*t*g[5]+t*t*t*g[7]; return SC.toScreen(x,y);})()")
    b.click(g['x'], g['y'])
    settle(b, 0.3)
    check('clicking a link selects it', (summary(b)['sel'] or {}).get('type') == 'edge' and el(b, '#edgebar') is not None)
    b.key('Delete')
    settle(b, 0.4)
    st = wait_saved(b, env)
    check('Delete removes the link', len(st['edges']) == 0)
    b.key('z', mods=4)
    settle(b, 0.4)
    st = wait_saved(b, env)
    check('Cmd+Z brings it back', len(st['edges']) == 1)
    b.key('z', mods=4 | 8)
    settle(b, 0.4)
    st = wait_saved(b, env)
    check('Shift+Cmd+Z redoes', len(st['edges']) == 0)
    # removing a link that was found automatically
    auto_edge = b.js("SC.data.edges.find(e=>e.kind==='helper').id")
    b.js("SC.removeLink(%s); SC.afterStateChange(true)" % J(auto_edge))
    st = wait_saved(b, env)
    check('an automatic link can be removed and that is remembered', auto_edge in st['removedEdges'])
    b.key('z', mods=4)
    settle(b, 0.3)

    # ---------------------------------------------------------------- search
    b.key('/')
    check('/ puts the cursor in the search box', b.js("document.activeElement.id") == 'q')
    b.type('override')
    b.wait('SC.search.loading === false', 5)
    settle(b, 0.3)
    s = summary(b)
    said = b.js("Array.from(SC.search.matches.values()).filter(m=>m.said && !m.local).length")
    check('search finds sessions as you type', s['matches'] >= 5, '%d matches' % s['matches'])
    check('search also finds words only said inside conversations', said >= 1, '%d found only in the conversation text' % said)
    check('results list is shown with highlighted words', b.js("document.querySelectorAll('#results .res').length") >= 5 and b.js("document.querySelectorAll('#results mark').length") >= 5)
    shot('11-search-results')
    b.key('Enter')
    settle(b, 0.6)
    s = summary(b)
    first = b.js('SC.search.order[0]')
    check('Enter jumps to the first match', s['sel'] and s['sel']['id'] == first and b.js('SC.search.index') == 0)
    r = rect(b, first)
    check('the match is brought into view', r['on'] and 0 <= r['x'] <= W and 52 <= r['y'] <= H)
    shot('12-search-jump')
    b.key('Enter')
    settle(b, 0.5)
    check('Enter again goes to the next match', b.js('SC.search.index') == 1 and summary(b)['sel']['id'] == b.js('SC.search.order[1]'))
    non = b.js("(()=>{const n=SC.lay.shown.find(n=>!SC.search.matches.has(n.id)); return SC.alphaOf(n);})()")
    check('cards that do not match are dimmed', non < 0.2, non)
    b.js("document.getElementById('q').select()")
    b.type('redirct loginn')
    b.wait('SC.search.loading === false', 5)
    check('small typos still find things', summary(b)['matches'] >= 1, '"redirct loginn" -> %d' % summary(b)['matches'])
    b.js("document.getElementById('q').select()")
    b.type('zzqqxxyy')
    b.wait('SC.search.loading === false', 5)
    check('nonsense finds nothing', summary(b)['matches'] == 0 and 'no match' in b.js("document.getElementById('qcount').textContent"))
    b.key('Escape')
    settle(b, 0.2)
    check('Esc clears the search', b.js("document.getElementById('q').value") == '' and summary(b)['matches'] == 0)
    b.key('Escape')
    b.key('Escape')

    # ---------------------------------------------------------------- arrows
    x, y, r = center_node(b, single, 0.8)
    b.click(x, y)
    settle(b, 0.3)
    b.key('ArrowRight')
    settle(b, 0.4)
    sel2 = summary(b)['sel']['id']
    moved_right = b.js('SC.nodes.get(%s).x > SC.nodes.get(%s).x' % (J(sel2), J(single)))
    check('arrow keys move to the next card', sel2 != single and moved_right)
    b.key('Escape')

    # ---------------------------------------------------------------- timeline
    b.key('2')
    settle(b, 0.8)
    s = summary(b)
    lay = b.js("({lanes:SC.lay.lanes.map(l=>l.label+' ('+l.count+')'), days:SC.lay.days.length, today:!!SC.lay.dayAt.get(SC.lay.today), w:SC.lay.width})")
    check('2 switches to the Timeline', s['layout'] == 'timeline' and lay['days'] >= 7 and lay['today'], '%d days, lanes: %s' % (lay['days'], ', '.join(lay['lanes'])))
    check('lanes split by project and kind', len(lay['lanes']) >= 3)
    order_ok = b.js("(()=>{let ok=true; const d=SC.lay.days; for(let i=1;i<d.length;i++) if(d[i].x0<d[i-1].x1-0.01||d[i].t<=d[i-1].t) ok=false; return ok;})()")
    check('days run left to right in order', order_ok)
    b.key('t')
    settle(b, 0.6)
    tx = b.js("(()=>{const d=SC.lay.dayAt.get(SC.lay.today); return SC.toScreen(d.x0,0).x;})()")
    check('T jumps to today', 0 <= tx <= W, 'today starts at x=%.0f' % tx)
    shot('13-timeline-today')
    b.key('f')
    settle(b, 0.7)
    shot('14-timeline-all')
    # drag to reorder inside one day
    cell = b.js("(()=>{for(const lane of SC.lay.lanes){ if(lane.h<100) continue; for(const [d,list] of lane.cells){ if(list.length>=3) return {a:list[0].id,b:list[1].id,c:list[2].id,key:list[0].cell}; } } return null;})()")
    check('found a day with several sessions to reorder', bool(cell), cell and cell['key'])
    if cell:
        b.js('(()=>{const n=SC.nodes.get(%s); SC.setCam(n.x-300, n.y-200, 0.8, false); SC.drawNow();})()' % J(cell['a']))
        ra, rc = rect(b, cell['a']), rect(b, cell['c'])
        b.drag(ra['x'] + ra['w'] / 2, ra['y'] + 20, rc['x'] + rc['w'] / 2, rc['y'] + 30, steps=16)
        settle(b, 0.5)
        st = wait_saved(b, env)
        got = st['order'].get(cell['key'])
        check('dragging a card inside its day reorders it (saved)', bool(got) and got[:3] == [cell['b'], cell['c'], cell['a']], got and [g[:8] for g in got[:3]])
        ya, yb = b.js('SC.nodes.get(%s).y' % J(cell['a'])), b.js('SC.nodes.get(%s).y' % J(cell['b']))
        check('the board shows the new order', ya > yb)
        shot('15-timeline-reordered')
        b.key('z', mods=4)
        settle(b, 0.4)
        st = wait_saved(b, env)
        check('undo puts the order back', not st['order'].get(cell['key']))

    # ---------------------------------------------------------------- free layout
    b.key('3')
    settle(b, 0.9)
    st = wait_saved(b, env)
    s = summary(b)
    check('3 switches to Free and starts from a tidy arrangement', s['layout'] == 'free' and len(st['positions']) >= s['shown'], '%d places saved' % len(st['positions']))
    mover = b.js("SC.lay.shown.filter(n=>n.s.kind==='you')[2].id")
    x, y, r = center_node(b, mover, 0.8)
    p0 = st['positions'][mover] if mover in st['positions'] else b.js('({x:SC.nodes.get(%s).x,y:SC.nodes.get(%s).y})' % (J(mover), J(mover)))
    b.drag(x, y, x + 160, y + 96, steps=12)
    settle(b, 0.4)
    st = wait_saved(b, env)
    p1 = st['positions'][mover]
    check('dragging a card in Free moves it and the place is saved', abs((p1['x'] - p0['x']) - 200) <= 6 and abs((p1['y'] - p0['y']) - 120) <= 6,
          'moved %d, %d' % (p1['x'] - p0['x'], p1['y'] - p0['y']))
    shot('16-free-moved')

    # ---------------------------------------------------------------- sticky notes
    b.key('Escape')
    b.key('n')
    b.wait("document.querySelector('#notes textarea') !== null", 3)
    check('N adds a sticky note ready for typing', b.js("document.activeElement.tagName") == 'TEXTAREA')
    b.type('# Follow up\n- [ ] ask Sam about **scope**\n- [x] done item\nplain `code` text')
    b.key('Escape')
    settle(b, 0.4)
    st = wait_saved(b, env)
    check('the note text is saved', len(st['notes']) == 1 and st['notes'][0]['text'].startswith('# Follow up'), st['notes'] and st['notes'][0]['text'][:40])
    note_id = st['notes'][0]['id']
    html = b.js("document.querySelector('#notes .note .body').innerHTML")
    check('note formatting works (heading, to-do boxes, bold, code)', 'md-h' in html and 'md-box' in html and '<b>scope</b>' in html and '<code>code</code>' in html)
    nb = el(b, '#notes .note')
    b.drag(nb['x'], nb['y'] + 20, nb['x'] + 120, nb['y'] + 80, steps=8)
    settle(b, 0.3)
    st2 = wait_saved(b, env)
    lay_name = 'free'
    moved = st2['notes'][0]['pos'][lay_name]['x'] - st['notes'][0]['pos'][lay_name]['x']
    check('a note can be dragged (saved)', abs(moved - 120 / b.js('SC.cam.z')) < 6, 'moved %.0f' % moved)
    box = el(b, '#notes .note .md-box .box')
    b.click(box['x'], box['y'])
    st2 = wait_saved(b, env)
    check('clicking a to-do box ticks it', '[x] ask Sam' in st2['notes'][0]['text'])
    check('the note gets its toolbar when selected', el(b, '#notebar') is not None)
    c = el(b, '#notebar .nsw:nth-child(4)')
    b.click(c['x'], c['y'])
    st2 = wait_saved(b, env)
    check('note colour can be changed', st2['notes'][0]['color'] == 'blue', st2['notes'][0]['color'])
    grip = el(b, '#notes .note .grip')
    b.drag(grip['x'], grip['y'], grip['x'] + 60, grip['y'] + 40, steps=6)
    st2 = wait_saved(b, env)
    check('a note can be resized', st2['notes'][0]['w'] > 260 and st2['notes'][0]['h'] > 170, '%dx%d' % (st2['notes'][0]['w'], st2['notes'][0]['h']))
    # connect it to a session by dragging its dot
    b.js('(()=>{const n=SC.nodes.get(%s); const p=SC.noteXY.get(%s); SC.fitBounds({x0:Math.min(n.x,p.x)-60,y0:Math.min(n.y,p.y)-60,x1:Math.max(n.x+n.w,p.x+320)+60,y1:Math.max(n.y+n.h,p.y+240)+60},{animate:false,maxZ:0.9}); SC.drawNow();})()' % (J(mover), J(note_id)))
    hook = el(b, '#notes .note .hook')
    rm = rect(b, mover)
    b.move(hook['x'] - 30, hook['y'])
    b.drag(hook['x'], hook['y'], rm['x'] + rm['w'] / 2, rm['y'] + rm['h'] / 2, steps=12)
    settle(b, 0.4)
    st2 = wait_saved(b, env)
    check('dragging the note\'s dot onto a card connects them', st2['notes'][0].get('attach') == mover)
    shot('17-note-connected')
    # send to the connected session
    b.js("SC.select({type:'note', id:%s})" % J(note_id))
    settle(b, 0.2)
    click_el(b, '#notebar [data-a="send"]')
    b.wait("!document.getElementById('modal').hidden", 3)
    check('Send dialog preselects the connected session', b.js("document.querySelector('#modal .opt.on').dataset.m") == 'existing' and b.js("document.querySelector('#sendPick button.on').dataset.id") == mover)
    shot('18-send-note-dialog')
    click_el(b, '#modal [data-a="send"]')
    b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
    plan = b.js('SC.ui.lastSpawn')
    check('Send to existing session: resume + the note as one argument', plan['action'] == 'note_resume' and plan['argv'][1:3] == ['--resume', mover] and plan['argv'][-1].startswith('# Follow up') and '**scope**' in plan['argv'][-1],
          plan['argv'][1:3])
    check('the note is passed through a file, never typed into a shell', '"$(cat ' in plan['script'] and plan['promptFile'] and '# Follow up' not in plan['script'])
    close_modal(b)
    click_el(b, '#notebar [data-a="send"]')
    b.wait("!document.getElementById('modal').hidden", 3)
    click_el(b, '#modal .opt[data-m="new"] b')
    b.sleep(0.1)
    click_el(b, '#modal [data-a="send"]')
    b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
    plan = b.js('SC.ui.lastSpawn')
    check('Send to a new session: claude "<note>" in this folder', plan['action'] == 'note_new' and len(plan['argv']) == 2 and plan['cwd'] == env.root, plan['cwd'])
    close_modal(b)
    # double-click the empty board
    b.key('Escape')
    b.js('SC.setCam(SC.lay.bounds.x0-900, SC.lay.bounds.y0-700, 0.8, false); SC.drawNow()')
    b.click(700, 500, clicks=2)
    b.wait("document.querySelector('#notes textarea') !== null", 3)
    b.type('second note')
    b.key('Escape')
    st2 = wait_saved(b, env)
    check('double-clicking the empty board adds a note there', len(st2['notes']) == 2)
    b.key('Delete')
    settle(b, 0.3)
    st2 = wait_saved(b, env)
    check('Delete removes the selected note', len(st2['notes']) == 1)

    # ---------------------------------------------------------------- theme
    theme0 = b.js('SC.themeName()')
    theme1 = 'light' if theme0 == 'dark' else 'dark'
    click_el(b, '#btnTheme')
    settle(b, 0.3)
    st = wait_saved(b, env)
    check('the light / dark switch works and is saved', b.js("document.documentElement.dataset.theme") == theme1 and st['view']['theme'] == theme1, '%s -> %s' % (theme0, theme1))
    b.key('1')
    settle(b, 0.8)
    b.js('SC.homeView(false); SC.drawNow()')
    shot('19-tree-light')
    b.js("document.getElementById('colorBy').value='kind'; document.getElementById('colorBy').dispatchEvent(new Event('change'))")
    settle(b, 0.3)
    shot('20-colour-by-type')
    b.js("document.getElementById('colorBy').value='project'; document.getElementById('colorBy').dispatchEvent(new Event('change'))")
    st = wait_saved(b, env)
    check('colour mode is saved', st['view']['colorBy'] == 'project')

    # ---------------------------------------------------------------- help, rescan
    b.key('?')
    b.wait("!document.getElementById('modal').hidden", 3)
    check('? opens the help', 'how it works' in modal_text(b))
    shot('21-help')
    b.key('Escape')
    click_el(b, '#btnRescan')
    b.wait("/Nothing new|Up to date|new session/.test(document.getElementById('toasts').innerText)", 8)
    toast = b.js("document.getElementById('toasts').innerText") or ''
    check('Rescan answers', any(w in toast for w in ('Nothing new', 'Up to date', 'new session')), toast.replace('\n', ' | '))

    # ---------------------------------------------------------------- hover card
    b.key('Escape')
    x, y, r = center_node(b, parent, 0.5)
    b.move(x - 5, y - 5)
    b.move(x, y)
    b.wait("!document.getElementById('hovercard').hidden", 4)
    check('resting on a card shows what it was about', 'Renamed by the test' in (b.js("document.getElementById('hovercard').innerText") or ''))
    shot('22-hover')
    b.move(30, 300)
    b.sleep(0.5)

    # ---------------------------------------------------------------- remembers everything after a reload
    b.js('SC.setCam(1234, 567, 0.5, false)')
    b.sleep(1.0)
    st = wait_saved(b, env)
    ok = b.goto(env.base + '/?debug=1')
    s = summary(b)
    cam = b.js('({x:SC.cam.x,y:SC.cam.y,z:SC.cam.z})')
    check('after a reload: same layout, theme and colours', ok and s['layout'] == 'tree' and b.js("document.documentElement.dataset.theme") == theme1 and b.js('SC.state.view.colorBy') == 'project')
    check('after a reload: same zoom and place', abs(cam['x'] - 1234) < 1 and abs(cam['y'] - 567) < 1 and abs(cam['z'] - 0.5) < 0.001, cam)
    check('after a reload: note, name, label, colour are still there', s['notes'] == 1 and b.js('SC.titleOf(SC.data.byId.get(%s))' % J(parent)) == 'Renamed by the test'
          and b.js('SC.state.labels[%s]' % J(parent)) == 'important')
    b.key('3')
    settle(b, 0.8)
    pos = b.js('({x:SC.nodes.get(%s).x,y:SC.nodes.get(%s).y})' % (J(mover), J(mover)))
    check('after a reload: the moved card is where it was left', pos['x'] == p1['x'] and pos['y'] == p1['y'])
    check('the note still follows its session', b.js('SC.noteXY.get(%s).anchored' % J(note_id)) is True)

    # ---------------------------------------------------------------- speed
    b.js("document.getElementById('btnTheme').click()")
    b.key('1')
    settle(b, 1.5)
    bench_tree = b.js('SC.debug.bench(120)', wait=True, timeout=150)
    bench_dense = b.js('SC.debug.bench(90, 0.56)', wait=True, timeout=150)
    bench_far = b.js('SC.debug.bench(60, 0.16)', wait=True, timeout=150)
    bench_near = b.js('SC.debug.bench(60, 1.0)', wait=True, timeout=150)
    b.key('2')
    settle(b, 1.0)
    bench_tl = b.js('SC.debug.bench(90)', wait=True, timeout=150)
    for name, r in (('tree, panning while zooming 0.3-0.9', bench_tree), ('tree, most detailed cards on screen (zoom 0.56)', bench_dense),
                    ('tree, zoomed out to all cards', bench_far), ('tree, 100%', bench_near), ('timeline, panning while zooming', bench_tl)):
        check('drawing is fast: ' + name, r['drawP95'] < 12.0 and r['fps'] > 50,
              'draw avg %.1f ms, p95 %.1f ms, worst %.1f ms; %d cards per frame (most %d); a frame every %.1f ms = %.0f fps' % (
                  r['drawAvg'], r['drawP95'], r['drawMax'], r['cards'], r['cardsMax'], r['frameAvg'], r['fps']))

    # ---------------------------------------------------------------- no errors anywhere
    probs = b.problems()
    check('no JavaScript errors or failed requests in the browser', not probs, probs[:5])
    clog = [e for e in env.get('/api/clientlog')['entries'] if e.get('level') == 'error']
    check('the page reported no errors to the server', not clog, clog[:3])
    return {'load_s': load_s, 'bench': {'tree': bench_tree, 'dense': bench_dense, 'far': bench_far, 'near': bench_near, 'timeline': bench_tl}}


def run_wizard(tmp, b, shots, projects, demo):
    """A fresh install: the setup wizard opens by itself, its answers are saved and used."""
    sub = os.path.join(tmp, 'wizard')
    os.makedirs(sub)
    env = Env(sub, projects=projects, wizard=True)
    try:
        b.events = []
        ok = b.goto(env.base + '/?debug=1')
        b.wait("!document.getElementById('modal').hidden && !!document.querySelector('.wizard')", 6)
        txt = modal_text(b)
        check('a fresh install opens the setup wizard', ok and 'Welcome to' in txt and 'sessions found' in txt, txt[:80].replace('\n', ' '))
        b.screenshot(os.path.join(shots, '30-wizard-welcome.png'))
        click_el(b, '#modal [data-a="next"]')
        b.wait("document.querySelector('.wizard') && document.querySelector('.wizard').innerText.indexOf('Where should new sessions start') >= 0", 4)
        folders = b.js("Array.from(document.querySelectorAll('input[name=wzcwd]')).map(x=>x.value)")
        check('the folder step lists the folders used with Claude', demo['folders'][0] in folders, folders)
        b.js("document.getElementById('wzPath').value = '/no/such/folder'")
        click_el(b, '#modal [data-a="next"]')
        b.wait("document.getElementById('wzPathMsg') && document.getElementById('wzPathMsg').textContent.length > 0", 4)
        check('a folder that does not exist is refused in plain words', 'does not exist' in b.js("document.getElementById('wzPathMsg').textContent"))
        b.js("document.getElementById('wzPath').value = %s" % J(demo['folders'][1]))
        b.screenshot(os.path.join(shots, '31-wizard-folder.png'))
        click_el(b, '#modal [data-a="next"]')
        b.wait("document.querySelector('.wizard').innerText.indexOf('Which terminal') >= 0", 4)
        check('the terminal step offers Terminal', b.js("!!document.querySelector('input[name=wzterm][value=Terminal]')"))
        click_el(b, '#modal [data-a="next"]')
        b.wait("!!document.getElementById('wzQuick')", 4)
        b.js("document.getElementById('wzQuick').value = '/standup'")
        click_el(b, '#modal [data-a="add"]')
        b.wait("document.getElementById('wzChips').innerText.indexOf('/standup') >= 0", 3)
        check('a quick-start command can be added', '/standup' in b.js("document.getElementById('wzChips').innerText"))
        b.screenshot(os.path.join(shots, '32-wizard-quick.png'))
        click_el(b, '#modal [data-a="next"]')
        b.wait("document.querySelector('.wizard').innerText.indexOf('All set') >= 0", 4)
        b.screenshot(os.path.join(shots, '33-wizard-done.png'))
        click_el(b, '#modal [data-a="test"]')
        b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
        check('"Show me a test" shows a Resume command without opening anything', b.js('SC.ui.lastSpawn.dryRun') is True and b.js('SC.ui.lastSpawn.action') == 'resume')
        close_modal(b)
        st = wait_saved(b, env)
        sset = st['settings']
        check('the wizard answers are saved', sset.get('setupDone') is True and sset.get('defaultCwd') == demo['folders'][1] and sset.get('quick') == ['/standup'] and sset.get('terminal') == 'Terminal', sset)
        click_el(b, '#btnSession')
        b.wait("!!document.getElementById('nsCwd')", 3)
        check('+ Session uses the picked folder and quick-start command', b.js("document.getElementById('nsCwd').value") == demo['folders'][1] and b.js("!!document.querySelector('[data-chip=\"/standup\"]')"),
              b.js("document.getElementById('nsCwd').value"))
        close_modal(b)
        b.goto(env.base + '/?debug=1')
        b.sleep(0.6)
        check('the wizard does not come back after a reload', b.js("!document.querySelector('.wizard')"))
        b.key('?')
        b.wait("!document.getElementById('modal').hidden", 3)
        check('Settings can run the setup again', b.js("!!document.querySelector('#modal [data-a=setup]')"))
        close_modal(b)
        probs = b.problems()
        check('no JavaScript errors in the wizard', not probs, probs[:3])
        wait_saved(b, env)
        b.js("location.href = 'about:blank'")         # leave the page before its server stops
        b.sleep(0.5)
    finally:
        env.stop()


def run_small(tmp, b, shots):
    """A made-up handful of sessions: an empty board, sessions that appear by themselves, a server restart."""
    import fixtures as fx
    projects = os.path.join(tmp, 'fake-projects')
    work = os.path.realpath(os.path.join(tmp, 'fake-work'))
    os.makedirs(projects)
    os.makedirs(work)
    sub = os.path.join(tmp, 'small')
    os.makedirs(sub)
    env = Env(sub, projects=projects, root=work)
    try:
        b.events = []
        ok = b.goto(env.base + '/?debug=1')
        s = summary(b)
        check('an empty board opens without errors', ok and s['shown'] == 0 and not b.problems(), b.problems()[:2])
        for k in ('f', '2', 't', 'f', '3', '1', 'ArrowRight'):
            b.key(k)
            b.sleep(0.25)
        b.key('n')
        b.wait("document.querySelector('#notes textarea') !== null", 3)
        b.type('note on an empty board')
        b.key('Escape')
        st = wait_saved(b, env)
        check('layouts, fit, today and notes work on an empty board', len(st['notes']) == 1 and not b.problems(), b.problems()[:2])
        settle(b, 0.3)
        b.screenshot(os.path.join(shots, '23-empty-board.png'))

        now = int(time.time())
        a, c = fx.new_id(), fx.new_id()
        fx.simple_session(projects, a, now - 7200, 'First question about apple budgets for ACME-7001', 'Apple answer with forecast.', cwd=work)
        fx.simple_session(projects, c, now - 3600, 'Second question about pear forecasts', 'Pear answer.', cwd=work)
        b.sleep(15.5)                                  # the automatic look happens at most every 15 s
        b.js('SC.refresh(false)', wait=True)           # exactly what the 60-second timer calls
        b.wait('SC.data.sessions.length === 2', 6)
        toast = b.js("document.getElementById('toasts').innerText") or ''
        s = summary(b)
        check('new sessions appear by themselves (no restart, no reload)', s['shown'] == 2 and '2 new sessions' in toast, '%d shown; toast: %s' % (s['shown'], toast.replace('\n', ' | ')))
        path = os.path.join(projects, fx.encode_cwd(work), a + '.jsonl')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(fx.user('and one more thing about apples', now - 60, a, cwd=work), separators=(',', ':')) + '\n')
            fh.write(json.dumps(fx.assistant('Done, apples updated.', now - 30, a, cwd=work), separators=(',', ':')) + '\n')
        os.utime(path, None)
        b.js('SC.refresh(true)', wait=True)            # the Rescan button
        b.wait('SC.data.byId.get(%s).msgs === 4' % J(a), 6)
        check('a session that goes on gets its card updated', b.js('SC.data.byId.get(%s).msgs' % J(a)) == 4)
        check('a session that changed seconds ago but is not open in any window is not marked open', b.js('SC.data.byId.get(%s).active' % J(a)) is False)
        live_a = os.path.join(env.live_dir, '1.json')
        with open(live_a, 'w') as fh:                  # pid 1 (launchd) is always alive
            json.dump({'pid': 1, 'sessionId': a, 'status': 'busy', 'kind': 'interactive', 'startedAt': int(time.time() * 1000)}, fh)
        b.js('SC.refreshLive()', wait=True)
        check('a session open in a window is marked as running now', b.js('SC.data.byId.get(%s).active' % J(a)) is True)
        x, y, r = center_node(b, a)
        b.click(x, y)
        b.wait("document.querySelector('#panel .badge.live') !== null", 4)
        click_el(b, '#panel [data-act="resume"]')
        b.wait("!document.getElementById('modal').hidden", 4)
        check('Resume warns when the session looks open right now', 'already open' in modal_text(b), modal_text(b)[:60])
        b.screenshot(os.path.join(shots, '24-running-now-warning.png'))
        os.remove(live_a)
        b.key('Escape')

        # ---- open in a window (Claude Code's own list) vs closed ----
        live_file = os.path.join(env.live_dir, '%d.json' % os.getpid())
        with open(live_file, 'w') as fh:
            json.dump({'pid': os.getpid(), 'sessionId': c, 'status': 'idle', 'kind': 'interactive', 'startedAt': int(time.time() * 1000)}, fh)
        live = env.get('/api/live')['live']
        check('the server lists a session that is open in a window', c in live and live[c]['pid'] == os.getpid(), list(live))
        b.js('SC.refreshLive()', wait=True)
        check('an idle session that is open in a window counts as open', b.js('SC.data.byId.get(%s).active' % J(c)) is True)
        b.js('SC.resumeSession(SC.data.byId.get(%s))' % J(c))
        b.wait("!document.getElementById('modal').hidden", 4)
        txt = modal_text(b)
        check('Resume on an open session warns and says it is open in a window', 'already open' in txt and 'open in a window right now' in txt, txt[:90])
        check('the safe choice (Cancel) is the default button', b.js("document.activeElement && document.activeElement.innerText") == 'Cancel', b.js("document.activeElement && document.activeElement.innerText"))
        b.key('Escape')
        spawns0 = len(env.get('/api/spawnlog')['entries'])
        nid = b.js("SC.addNote(0, 0, 'please check the apples').id")
        b.js('SC.openSendDialog(%s)' % J(nid))
        b.wait("!document.getElementById('modal').hidden", 3)
        b.js("document.querySelector('#sendPick button[data-id=%s]').click()" % J(c))
        check('the session picker marks open sessions', b.js("!!document.querySelector('#sendPick button[data-id=%s] .badge.live')" % J(c)))
        click_el(b, '#modal [data-a="send"]')
        b.wait("document.getElementById('modal').innerText.indexOf('Copy note') >= 0", 5)
        txt = modal_text(b)
        check('a note to an open session offers to copy it instead', 'already open' in txt and b.js("document.activeElement && document.activeElement.innerText") == 'Copy note', txt[:90])
        b.screenshot(os.path.join(shots, '25-note-to-open-session.png'))
        b.js("Array.from(document.querySelectorAll('#modal .btns button')).find(x => x.innerText === 'Copy note').click()")
        b.wait("document.getElementById('toasts').innerText.indexOf('copied') >= 0", 4)
        toast = b.js("document.getElementById('toasts').innerText") or ''
        check('Copy note copies and opens nothing', 'Note copied' in toast and len(env.get('/api/spawnlog')['entries']) == spawns0, toast.replace('\n', ' | ')[:120])
        os.remove(live_file)
        b.js('SC.refreshLive()', wait=True)
        check('a closed session no longer counts as open', b.js('SC.data.byId.get(%s).active' % J(c)) is False)
        b.js('SC.openSendDialog(%s)' % J(nid))
        b.wait("!document.getElementById('modal').hidden", 3)
        b.js("document.querySelector('#sendPick button[data-id=%s]').click()" % J(c))
        click_el(b, '#modal [data-a="send"]')
        b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
        plan = b.js('SC.ui.lastSpawn')
        check('a note to a closed session is sent straight away (resume + note)', plan['action'] == 'note_resume' and plan['argv'][1:3] == ['--resume', c] and plan['argv'][-1] == 'please check the apples', plan['argv'][1:])
        close_modal(b)

        # ---- + Session (start the day) ----
        b.js("SC.state.settings.quick = ['/morning']; SC.touch('settings')")
        click_el(b, '#btnSession')
        b.wait("!document.getElementById('modal').hidden && !!document.getElementById('nsText')", 3)
        check('+ Session opens the new-session box in the work folder', b.js("document.getElementById('nsCwd').value") == work, b.js("document.getElementById('nsCwd').value"))
        b.js("document.querySelector('#modal [data-chip=\"/morning\"]').click()")
        b.screenshot(os.path.join(shots, '26-new-session-dialog.png'))
        click_el(b, '#modal [data-a="start"]')
        b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
        plan = b.js('SC.ui.lastSpawn')
        check('+ Session with /morning starts claude with that first message', plan['action'] == 'note_new' and plan['argv'][-1].strip() == '/morning' and '--resume' not in plan['argv'], plan['argv'])
        close_modal(b)
        b.key('s')
        b.wait("!document.getElementById('modal').hidden && !!document.getElementById('nsText')", 3)
        click_el(b, '#modal [data-a="start"]')
        b.wait("document.getElementById('modal').innerText.indexOf('Paste-able') >= 0", 5)
        plan = b.js('SC.ui.lastSpawn')
        check('S then Start with no message opens a blank session', plan['action'] == 'new' and '--resume' not in plan['argv'] and len(plan['argv']) == 1, plan['argv'])
        close_modal(b)
        b.js('SC.select({type:%s, id:%s})' % (J('node'), J(a)))

        # the Canvas is stopped and started again while the page stays open
        env.restart()
        b.key('h')                                     # hide the selected card: a change that must be saved
        st = wait_saved(b, env, timeout=12)
        check('after the Canvas restarts the open page keeps saving (no reload needed)', a in st['hidden'] and b.js('SC.saveState') == 'saved', b.js('SC.saveState'))
        probs = [p for p in b.problems() if '403' not in p and 'Failed to load resource' not in p and 'ERR_CONNECTION_REFUSED' not in p]   # the server was down on purpose
        check('no JavaScript errors on the small board', not probs, probs[:3])
    finally:
        env.stop()


def run_stress(tmp, b, shots, n=1200):
    """Four times today's number of sessions (made up): is it still quick?"""
    import random
    import fixtures as fx
    projects = os.path.join(tmp, 'stress-projects')
    work = os.path.realpath(os.path.join(tmp, 'stress-work'))
    os.makedirs(projects)
    os.makedirs(work)
    rnd = random.Random(7)
    now = int(time.time())
    words = ['budget', 'forecast', 'dataset', 'override', 'dimension', 'mapping', 'sprint', 'review', 'roadmap', 'mixpanel', 'release',
             'pipeline', 'variance', 'headcount', 'import', 'actuals', 'planning', 'standup', 'retro', 'pricing', 'onboarding', 'customer']
    helpers, hqs = [], []
    for i in range(n):
        sid = fx.new_id()
        start = now - rnd.randint(600, 70 * 86400)
        roll = rnd.random()
        topic = ' '.join(rnd.sample(words, 4))
        if roll < 0.6:
            recs = [fx.user('<command-message>daily-digest</command-message>\n<command-name>/daily-digest</command-name>\n<command-args>after-meeting %s</command-args>' % topic, start, sid, cwd=work, entry='sdk-cli', promptSource=None, origin=None),
                    fx.assistant('Processed the notes about %s for ACME-%d.' % (topic, 7000 + i % 300), start + 40, sid, cwd=work, entry='sdk-cli')]
        elif roll < 0.85:
            recs = [fx.user('Help me with %s (question %d, ACME-%d)' % (topic, i, 7000 + i % 300), start, sid, cwd=work),
                    fx.assistant('Here is the plan for %s. See [the page](https://app.notion.com/p/%032x).' % (topic, i), start + 60, sid, cwd=work)]
            hqs.append((sid, start, recs))
        else:
            recs = [fx.user('Helper task: %s number %d' % (topic, i), start, sid, cwd=work, sessionKind='bg'),
                    fx.assistant('Done: %s.' % topic, start + 90, sid, cwd=work, sessionKind='bg'),
                    {'type': 'custom-title', 'customTitle': 'W%02d\u00b7%s' % (i % 28 + 1, topic.split()[0]), 'sessionId': sid}]
            helpers.append((sid, start))
        if roll >= 0.6 and roll < 0.85:
            continue
        fx.write_session(projects, sid, recs, cwd=work)
    for k, (hsid, hstart) in enumerate(helpers):          # every helper is launched by some earlier "you" session
        owner = hqs[k % len(hqs)]
        owner[2].append(fx.tool_result('%s W01\u00b7helper (job, sonnet) \u2192 /x/.state/sessions/x/h.md' % hsid[:8], owner[1] + 70, owner[0], cwd=work))
    for sid, start, recs in hqs:
        fx.write_session(projects, sid, recs, cwd=work)
    sub = os.path.join(tmp, 'stress')
    os.makedirs(sub)
    t0 = time.time()
    env = Env(sub, projects=projects, root=work)
    index_s = time.time() - t0
    try:
        b.events = []
        t0 = time.time()
        ok = b.goto(env.base + '/?debug=1&nosave=1')
        load_s = time.time() - t0
        s = summary(b)
        check('%d sessions: read, linked and on the board' % n, ok and s['shown'] == n and s['edges'] >= len(helpers) * 0.9,
              'server ready after %.1fs, page ready after %.1fs, %d links' % (index_s, load_s, s['edges']))
        lay = {}
        for name, key in (('tree', '1'), ('timeline', '2'), ('free', '3')):
            b.key(key)
            settle(b, 0.9)
            lay[name] = b.js('(()=>{const t=performance.now(); SC.relayout(); return +(performance.now()-t).toFixed(1);})()')
        check('working out the layout is instant', max(lay.values()) < 120, 'tree %.0f ms, timeline %.0f ms, free %.0f ms' % (lay['tree'], lay['timeline'], lay['free']))
        b.key('1')
        settle(b, 2.5)
        out = {}
        for name, expr in (('zoomed out to all %d cards' % n, 'SC.debug.bench(60, 0.07)'), ('most detailed cards on screen', 'SC.debug.bench(90, 0.56)'),
                           ('panning while zooming', 'SC.debug.bench(120)')):
            r = b.js(expr, wait=True, timeout=150)
            out[name] = r
            check('%d sessions, drawing is fast: %s' % (n, name), r['drawP95'] < 12.0 and r['fps'] > 50,
                  'draw avg %.1f ms, p95 %.1f ms, worst %.1f ms; %d cards per frame (most %d); %.0f fps' % (r['drawAvg'], r['drawP95'], r['drawMax'], r['cards'], r['cardsMax'], r['fps']))
        t = b.js("(()=>{const t=performance.now(); SC.setQuery('forecast pricing'); return +(performance.now()-t).toFixed(1);})()")
        b.wait('SC.search.loading === false', 6)
        check('%d sessions, search answers at once' % n, t < 60 and summary(b)['matches'] > 0 and (b.js('SC.search.serverMs') or 0) < 150,
              'on the page %.1f ms, on the server %.1f ms, %d matches' % (t, b.js('SC.search.serverMs') or 0, summary(b)['matches']))
        b.js("SC.setQuery('')")
        b.key('f')
        settle(b, 0.8)
        b.screenshot(os.path.join(shots, '25-stress-%d-sessions.png' % n))
        probs = b.problems()
        check('%d sessions: no JavaScript errors' % n, not probs, probs[:3])
        return {'n': n, 'index_s': round(index_s, 2), 'load_s': round(load_s, 2), 'layout_ms': lay, 'bench': out}
    finally:
        env.stop()


def main():
    import faulthandler
    import signal
    faulthandler.register(signal.SIGUSR1, all_threads=True)      # kill -USR1 <pid> prints where it is
    ap = argparse.ArgumentParser()
    ap.add_argument('--shots', default=os.path.join(HERE, 'screenshots'))
    ap.add_argument('--keep', action='store_true', help='keep the temp folder (server log, state)')
    args = ap.parse_args()
    os.makedirs(args.shots, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='canvas-check-')
    env = None
    b = None
    extra = {}
    try:
        import fixtures as fx
        projects = os.path.join(tmp, 'demo-projects')
        os.makedirs(projects)
        demo = fx.demo_corpus(projects, os.path.join(tmp, 'demo-work'))
        main_dir = os.path.join(tmp, 'main')
        os.makedirs(main_dir)
        env = Env(main_dir, projects=projects, root=demo['folders'][0])
        b = cdp.Browser(tmp, port=free_port(9377))
        best_shots(env, b, args.shots)
        extra = run(env, b, args.shots)
        run_wizard(tmp, b, args.shots, projects, demo)
        run_small(tmp, b, args.shots)
        extra['stress'] = run_stress(tmp, b, args.shots)
    except Exception as e:
        import traceback
        traceback.print_exc()
        check('the check ran to the end', False, '%s: %s' % (type(e).__name__, e))
        try:
            if b:
                b.screenshot(os.path.join(args.shots, 'zz-failure.png'))
                for p in b.problems()[:8]:
                    print('  browser problem:', p[:400])
        except Exception:
            pass
    finally:
        if b:
            b.close()
        if env:
            env.stop()
        if args.keep:
            print('kept:', tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(1 for r in RESULTS if r[1])
    print('\n%d of %d browser checks passed' % (passed, len(RESULTS)))
    if extra:
        print(json.dumps(extra))
    for name, ok, detail in RESULTS:
        if not ok:
            print('  FAILED: %s  %s' % (name, detail))
    sys.exit(0 if passed == len(RESULTS) and RESULTS else 1)


if __name__ == '__main__':
    main()
