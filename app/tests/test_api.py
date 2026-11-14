"""The web server: every endpoint, its JSON shape, and the safety checks.

A real server is started on a spare port (127.0.0.1 only) in DRY-RUN mode with a few fake transcripts.
Opening a window is replaced by a function that fails the test if it is ever called.
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import server  # noqa: E402
import fixtures as fx  # noqa: E402

T0 = 1794300000


class ApiCase(unittest.TestCase):
    dry_run = True

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='canvas-api-')
        cls.projects = os.path.join(cls.tmp, 'projects')
        cls.work = os.path.realpath(os.path.join(cls.tmp, 'work'))
        os.makedirs(cls.projects)
        os.makedirs(cls.work)
        cls.ids = []
        for i in range(3):
            sid = fx.new_id()
            cls.ids.append(sid)
            fx.simple_session(cls.projects, sid, T0 + i * 4000, 'Ask %d about override formulas for ACME-%d' % (i, 7100 + i),
                              'Reply %d: the override formulas are fixed. Zebra%d. https://example.atlassian.net/browse/ACME-%d' % (i, i, 7100 + i), cwd=cls.work)
        argv = ['--port', '0', '--state', os.path.join(cls.tmp, 'state.json'), '--cache', os.path.join(cls.tmp, 'cache'),
                '--projects', cls.projects, '--root', cls.work, '--claude', '/nonexistent/claude']
        if cls.dry_run:
            argv.append('--dry-run')
        cls.app = server.App(server.parse_args(argv))
        cls.app.index.use_pool = False
        cls.opened = []
        cls.app.spawner.run = lambda plan: (cls.opened.append(plan) or (True, 'Opened (fake).'))
        cls.srv = server.make_server(cls.app, 0, auto_port=False)
        cls.app.port = cls.srv.server_address[1]
        cls.port = cls.app.port
        cls.thread = threading.Thread(target=cls.srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        cls.thread.start()
        cls.app.start_indexing()
        deadline = time.time() + 20
        while not cls.app.ready() and time.time() < deadline:
            time.sleep(0.02)
        assert cls.app.ready(), cls.app.index_error

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None, token=True, raw=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        h = {}
        data = None
        if body is not None or raw is not None:
            data = raw if raw is not None else json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
        if token and method == 'POST':
            h['X-Canvas-Token'] = self.app.token
        h.update(headers or {})
        t0 = time.time()
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        ms = (time.time() - t0) * 1000
        c.close()
        ctype = r.getheader('Content-Type') or ''
        return r.status, (json.loads(payload.decode()) if 'json' in ctype else payload.decode('utf-8', 'replace')), ms

    def get(self, path, **kw):
        return self.req('GET', path, **kw)

    def post(self, path, body=None, **kw):
        return self.req('POST', path, body=body if body is not None else {}, **kw)


class Endpoints(ApiCase):
    def test_binds_to_this_mac_only(self):
        self.assertEqual(self.srv.server_address[0], '127.0.0.1')

    def test_page_and_static_files(self):
        st, html, _ = self.get('/')
        self.assertEqual(st, 200)
        self.assertIn('<canvas id="board"', html)
        self.assertIn('name="canvas-token" content="%s"' % self.app.token, html)
        self.assertIn('name="canvas-dry-run" content="1"', html)
        self.assertNotIn('{{', html)
        for f in ('/app.css', '/util.js', '/layout.js', '/model.js', '/draw.js', '/panels.js', '/setup.js', '/ui.js', '/icon.svg'):
            st, body, _ = self.get(f)
            self.assertEqual(st, 200, f)
            self.assertGreater(len(body), 200, f)
        for f in ('/nope.js', '/../server.py', '/..%2fserver.py', '/%2e%2e/state.json', '/web/../../server.py'):
            self.assertEqual(self.get(f)[0], 404, f)              # nothing outside web/ is ever served
        self.assertNotIn('http://', html.replace('http://127.0.0.1', ''))     # no outside resources: works offline
        self.assertNotIn('https://', html)

    def test_health_and_progress(self):
        st, h, _ = self.get('/api/health')
        self.assertEqual((st, h['ok'], h['app'], h['dryRun'], h['ready'], h['port']), (200, True, 'session-canvas', True, True, self.port))
        st, p, _ = self.get('/api/progress')
        self.assertEqual((p['state'], p['ready']), ('ready', True))
        self.assertGreaterEqual(p['total'], 3)

    def test_sessions_shape_and_unchanged_shortcut(self):
        st, p, ms = self.get('/api/sessions')
        self.assertEqual(st, 200)
        for k in ('ready', 'sessions', 'edges', 'projects', 'generation', 'indexedAt', 'stats', 'home', 'defaultCwd', 'dryRun', 'now'):
            self.assertIn(k, p)
        self.assertGreaterEqual(len(p['sessions']), 3)        # another test may have added one
        s = p['sessions'][0]
        self.assertEqual(s['id'], self.ids[0])
        self.assertEqual((s['kind'], s['projectLabel'], s['prompts'], s['replies'], s['msgs']), ('you', 'work', 1, 1, 2))
        self.assertEqual(s['jira'], ['ACME-7100'])
        self.assertIsInstance(s['keywords'], list)
        self.assertEqual(p['defaultCwd'], self.work)
        st, u, _ = self.get('/api/sessions?gen=%d' % p['generation'])
        self.assertEqual((u['ready'], u['unchanged'], 'sessions' in u), (True, True, False))
        st, full, _ = self.get('/api/sessions?gen=999999')
        self.assertEqual(len(full['sessions']), len(p['sessions']))

    def test_session_detail(self):
        st, d, _ = self.get('/api/session?id=' + self.ids[1])
        self.assertEqual(st, 200)
        for k in ('id', 'cwd', 'cwdExists', 'links', 'commands', 'firstPrompt', 'firstReply', 'lastPrompt', 'lastReply', 'recaps'):
            self.assertIn(k, d)
        self.assertTrue(d['cwdExists'])
        self.assertEqual(d['links']['jira'][0]['label'], 'ACME-7101')
        self.assertEqual(self.get('/api/session?id=nope')[0], 404)
        self.assertEqual(self.get('/api/session')[0], 404)

    def test_search(self):
        st, r, _ = self.get('/api/search?q=zebra1')
        self.assertEqual((st, r['total'], r['results'][0]['id']), (200, 1, self.ids[1]))
        self.assertIn('Zebra1', r['results'][0]['snippet'])
        self.assertIn('ms', r)
        self.assertEqual(self.get('/api/search?q=%22override%20formulas%22')[1]['total'], 3)
        self.assertEqual(self.get('/api/search?q=')[1]['total'], 0)
        self.assertEqual(self.get('/api/search?q=' + 'x' * 5000)[0], 200)

    def test_state_save_and_load(self):
        st, s, _ = self.get('/api/state')
        self.assertEqual(st, 200)
        for k in server.STATE_KEYS:
            self.assertIn(k, s)
        st, r, _ = self.post('/api/state', {'patch': {'titles': {self.ids[0]: 'Renamed'}, 'notes': [{'id': 'n1', 'text': 'hello'}]}})
        self.assertEqual((st, r['ok']), (200, True))
        st, s2, _ = self.get('/api/state')
        self.assertEqual(s2['titles'], {self.ids[0]: 'Renamed'})
        self.assertEqual(s2['rev'], r['rev'])
        with open(os.path.join(self.tmp, 'state.json'), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['notes'][0]['text'], 'hello')
        self.assertEqual(self.post('/api/state', {'patch': {'bogus': 1}})[0], 400)
        self.assertEqual(self.post('/api/state', {})[0], 400)
        # the "page is closing" path sends the token inside the body instead of a header
        st, r, _ = self.req('POST', '/api/state', body={'token': self.app.token, 'patch': {'hidden': ['x']}}, token=False)
        self.assertEqual(st, 200)
        self.assertEqual(self.get('/api/state')[1]['hidden'], ['x'])

    def test_rescan_finds_a_new_session_without_restart(self):
        gen = self.get('/api/sessions')[1]['generation']
        new = fx.new_id()
        fx.simple_session(self.projects, new, T0 + 90000, 'A brand new question about giraffes', 'Giraffe answer.', cwd=self.work)
        st, r, _ = self.post('/api/rescan')
        self.assertEqual((st, r['ok'], r['stats']['parsed']), (200, True, 1))
        self.assertGreater(r['generation'], gen)
        p = self.get('/api/sessions?gen=%d' % gen)[1]
        self.assertIn(new, [s['id'] for s in p['sessions']])
        self.assertEqual(self.get('/api/search?q=giraffes')[1]['total'], 1)

    def test_spawn_every_action_is_a_dry_run(self):
        sid = self.ids[0]
        before = len(self.opened)
        cases = [({'action': 'resume', 'sessionId': sid}, ['--resume', sid]),
                 ({'action': 'fork', 'sessionId': sid}, ['--resume', sid, '--fork-session']),
                 ({'action': 'new', 'cwd': self.work}, []),
                 ({'action': 'new'}, []),
                 ({'action': 'note_new', 'note': 'do "this" $(now)'}, ['do "this" $(now)']),
                 ({'action': 'note_resume', 'sessionId': sid, 'note': 'and `that`\nline 2'}, ['--resume', sid, 'and `that`\nline 2']),
                 ({'action': 'note_resume', 'sessionId': sid, 'note': 'x y', 'fork': True}, ['--resume', sid, '--fork-session', 'x y'])]
        for body, want in cases:
            st, r, _ = self.post('/api/spawn', body)
            self.assertEqual(st, 200, r)
            self.assertEqual((r['ok'], r['dryRun']), (True, True))
            self.assertEqual(r['argv'][1:], want)
            self.assertEqual(r['cwd'], self.work)
            for k in ('command', 'launcher', 'script', 'open', 'terminal', 'warnings', 'message'):
                self.assertIn(k, r)
            self.assertTrue(os.path.isfile(r['launcher']))
            self.assertEqual(r['open'][0], 'osascript')
        self.assertEqual(len(self.opened), before)                  # nothing was really opened
        log = self.get('/api/spawnlog')[1]['entries']
        self.assertTrue(all(e['dryRun'] for e in log))
        for bad in ({'action': 'resume', 'sessionId': 'x'}, {'action': 'resume', 'sessionId': fx.new_id()}, {'action': 'new', 'cwd': '/etc'},
                    {'action': 'note_new', 'note': ''}, {'action': 'explode'}):
            st, r, _ = self.post('/api/spawn', bad)
            self.assertEqual((st, r['ok']), (400, False), bad)
            self.assertTrue(r['error'])

    def test_terminal_setting_is_used(self):
        self.post('/api/state', {'patch': {'settings': {'terminal': 'Ghostty'}}})
        r = self.post('/api/spawn', {'action': 'resume', 'sessionId': self.ids[0]})[1]
        self.assertEqual((r['terminal'], r['open'][0]), ('Ghostty', 'open'))
        self.post('/api/state', {'patch': {'settings': {'terminal': 'rm -rf /'}}})
        r = self.post('/api/spawn', {'action': 'resume', 'sessionId': self.ids[0]})[1]
        self.assertEqual(r['terminal'], 'Terminal')                 # anything unknown falls back to Terminal
        self.post('/api/state', {'patch': {'settings': {}}})

    def test_setup_info(self):
        st, d, _ = self.get('/api/setup')
        self.assertEqual(st, 200)
        self.assertEqual(d['name'], server.APP_NAME)
        self.assertIn('Terminal', d['terminals'])
        self.assertEqual(d['defaultCwd'], self.work)                # --root until a folder is picked in setup
        self.assertEqual([f['cwd'] for f in d['folders']], [self.work])
        self.assertTrue(d['projectsFound'])

    def test_folder_check(self):
        self.assertEqual(self.get('/api/dir?path=' + self.work)[1], {'ok': True, 'path': self.work})
        self.assertFalse(self.get('/api/dir?path=' + self.work + '/nope')[1]['ok'])
        self.assertFalse(self.get('/api/dir?path=relative/path')[1]['ok'])
        self.assertTrue(self.get('/api/dir?path=~')[1]['ok'])

    def test_default_folder_from_settings(self):
        other = os.path.realpath(os.path.join(self.tmp, 'picked in setup'))
        os.makedirs(other, exist_ok=True)
        try:
            self.post('/api/state', {'patch': {'settings': {'defaultCwd': other}}})
            self.assertEqual(self.get('/api/setup')[1]['defaultCwd'], other)
            self.assertEqual(self.get('/api/sessions')[1]['defaultCwd'], other)
            r = self.post('/api/spawn', {'action': 'new'})[1]
            self.assertEqual(r['cwd'], other)                        # a folder never used with Claude is fine once picked
            self.post('/api/state', {'patch': {'settings': {'defaultCwd': '/no/such/folder'}}})
            self.assertEqual(self.get('/api/setup')[1]['defaultCwd'], self.work)   # gone -> back to --root
        finally:
            self.post('/api/state', {'patch': {'settings': {}}})

    def test_iterm_setting(self):
        self.post('/api/state', {'patch': {'settings': {'terminal': 'iTerm'}}})
        r = self.post('/api/spawn', {'action': 'resume', 'sessionId': self.ids[0]})[1]
        self.assertEqual((r['terminal'], r['open'][0]), ('iTerm', 'osascript'))
        self.post('/api/state', {'patch': {'settings': {}}})

    def test_client_log(self):
        self.post('/api/clientlog', {'level': 'error', 'msg': 'boom', 'stack': 'at x'})
        e = self.get('/api/clientlog')[1]['entries'][-1]
        self.assertEqual((e['level'], e['msg']), ('error', 'boom'))

    def test_changes_need_the_page_token(self):
        for path in ('/api/state', '/api/spawn', '/api/rescan', '/api/clientlog'):
            self.assertEqual(self.post(path, {'patch': {'hidden': []}}, token=False)[0], 403, path)
            self.assertEqual(self.post(path, {}, token=False, headers={'X-Canvas-Token': 'wrong'})[0], 403, path)

    def test_other_websites_cannot_call_it(self):
        good = {'Origin': 'http://127.0.0.1:%d' % self.port}
        self.assertEqual(self.post('/api/rescan', headers=good)[0], 200)
        for origin in ('https://evil.example', 'http://127.0.0.1:1', 'null', 'http://localhost.evil.example:%d' % self.port):
            self.assertEqual(self.post('/api/rescan', headers={'Origin': origin})[0], 403, origin)
        for host in ('evil.example', 'evil.example:%d' % self.port, '127.0.0.1:1', ''):          # DNS-rebinding style requests
            self.assertEqual(self.get('/api/sessions', headers={'Host': host})[0], 403, host)
            self.assertEqual(self.post('/api/spawn', {'action': 'new'}, headers={'Host': host})[0], 403, host)
        self.assertEqual(self.get('/api/health', headers={'Host': 'localhost:%d' % self.port})[0], 200)

    def test_bad_requests_get_a_clear_answer(self):
        self.assertEqual(self.req('POST', '/api/state', raw=b'{not json')[0], 400)
        self.assertEqual(self.req('POST', '/api/state', raw=b'[1,2]')[0], 400)
        self.assertEqual(self.post('/api/nope')[0], 404)
        self.assertEqual(self.get('/api/nope')[0], 404)
        st, r, _ = self.req('POST', '/api/state', raw=b'x', headers={'Content-Length': str(server.MAX_BODY + 1)})
        self.assertEqual(st, 400)

    def test_answers_quickly(self):
        times = {}
        for path in ('/api/sessions', '/api/state', '/api/search?q=override', '/api/session?id=' + self.ids[0], '/api/health'):
            ms = min(self.get(path)[2] for _ in range(5))
            times[path] = ms
            self.assertLess(ms, 250, '%s took %.0f ms' % (path, ms))


class LiveModeStillHonoursDryRunRequests(ApiCase):
    """With test mode OFF, a request can still ask for the command only ("Copy command")."""
    dry_run = False

    def test_per_request_dry_run_and_real_open_path(self):
        sid = self.ids[0]
        st, r, _ = self.post('/api/spawn', {'action': 'resume', 'sessionId': sid, 'dryRun': True})
        self.assertEqual((st, r['dryRun'], r['ok']), (200, True, True))
        self.assertEqual(len(self.opened), 0)
        st, r, _ = self.post('/api/spawn', {'action': 'resume', 'sessionId': sid})      # the (faked) real path
        self.assertEqual((st, r['dryRun'], r['ok']), (200, False, True))
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.opened[0]['argv'][1:], ['--resume', sid])
        self.assertEqual(self.get('/api/health')[1]['dryRun'], False)
        self.assertIn('content="0"', self.get('/')[1].split('canvas-dry-run')[1][:20])


if __name__ == '__main__':
    unittest.main(verbosity=2)
