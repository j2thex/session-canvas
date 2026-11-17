"""Helper reports on cards (status / outcome / left), clean names, and "go to the window that is already open".

Nothing here opens or moves a real window: the commands are built and a fake runner answers for osascript.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import indexer  # noqa: E402
import server  # noqa: E402
import fixtures as fx  # noqa: E402
from test_api import ApiCase  # noqa: E402

T0 = 1794300000


class Reports(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='canvas-rep-'))
        self.projects = os.path.join(self.tmp, 'projects')
        self.work = os.path.join(self.tmp, 'work')
        self.day = time.strftime('%Y-%m-%d', time.localtime(T0))
        self.dir = os.path.join(self.work, 'reports', self.day)
        os.makedirs(self.dir)
        os.makedirs(self.projects)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text, folder=None):
        p = os.path.join(folder or self.dir, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(text)
        return p

    def index(self):
        ix = indexer.Index(os.path.join(self.tmp, 'cache'), projects_root=self.projects, work_root=self.work, use_pool=False,
                           report_dirs=[os.path.join(self.work, 'reports')], user_name='Sam')
        ix.refresh()
        return ix

    def by_id(self, ix):
        return dict((s['id'], s) for s in ix.payload()['sessions'])

    def test_clean_name_drops_the_day_tag(self):
        self.assertEqual(indexer.clean_name('W16·W16·AI vs manual dataset number'), 'AI vs manual dataset number')
        self.assertEqual(indexer.clean_name('W16·Handover pack'), 'Handover pack')
        self.assertEqual(indexer.clean_name('Robo·R17 · Jira drafts'), 'Robo·R17 · Jira drafts')
        self.assertEqual(indexer.clean_name('W16·'), 'W16·')            # never an empty name
        self.assertEqual(indexer.clean_name('Weekly plan'), 'Weekly plan')

    def test_parse_report(self):
        p = self.write('a.md', 'status: your-turn\nname: W16·Product weekly\noutcome: block v2 is [ready](https://x.y/z)\n'
                               'left: Sam must answer:\n1. OK to create the toggle?\n2. other\n\nmore text\n')
        r = indexer.parse_report(p)
        self.assertEqual((r['status'], r['name'], r['outcome']), ('your-turn', 'Product weekly', 'block v2 is ready'))
        self.assertEqual(r['left'], 'Sam must answer: 1. OK to create the toggle?')
        # no outcome line: the first lines of text stand in for it
        p = self.write('b.md', 'status: Done\nname: Robo·R17 · Jira drafts\n\n**TL;DR**\n5 drafts below.\n')
        r = indexer.parse_report(p)
        self.assertEqual((r['status'], r['outcome']), ('done', '5 drafts below.'))
        # ordinary notes are not reports
        self.assertIsNone(indexer.parse_report(self.write('c.md', '# Prep · 15:00 Trio\nstatus: done\n')))
        self.assertIsNone(indexer.parse_report(self.write('d.md', 'status: maybe\nname: x\n')))
        self.assertIsNone(indexer.parse_report(os.path.join(self.dir, 'missing.md')))

    def test_cards_get_the_report_by_id_by_prompt_and_by_name(self):
        bg, peer, named, plain, old_peer = [fx.new_id() for _ in range(5)]
        rep_bg = self.write('weekly.md', 'status: your-turn\nname: W16·Product weekly\noutcome: draft ready\nleft: Sam picks a date\n')
        rep_peer = self.write('abc-1.md', 'status: done\nname: W16·ABC-1 warn-only\noutcome: ACs in Jira\nleft: nothing\n')
        self.write('named.md', 'status: not-done\nname: W16·Handover pack\noutcome: blocked on Notion\nleft: Sam logs in\n')
        self.write('runs.tsv', '%s\tW16·W16·Product weekly\tsession\tsonnet\tdoc\t10:31\t%s\n'
                               'peer\tW16·ABC-1 warn-only\tpeer\t-\tticket\t15:40\t%s\n' % (bg[:8], rep_bg, rep_peer))
        footer = ('\nMISSION RULE. You are the helper "W16·ABC-1 warn-only", started by HQ.\n'
                  '2. REPORT TO HQ EVERY TIME YOU STOP. HQ reads: %s\n   more rules\n' % rep_peer)
        fx.simple_session(self.projects, bg, T0, 'Use the /doc skill. Write the weekly.', 'Draft is ready. Waiting for you.', cwd=self.work)
        fx.simple_session(self.projects, peer, T0 + 100, '/ticket Rewrite the acceptance criteria of ABC-1 ' + 'x ' * 900 + footer,
                          'All done.', cwd=self.work)
        fx.write_session(self.projects, named, [{'type': 'custom-title', 'customTitle': 'W16·Handover pack', 'sessionId': named},
                                                 fx.user('pack it', T0 + 200, named, cwd=self.work),
                                                 fx.assistant('Blocked.', T0 + 230, named, cwd=self.work)], cwd=self.work)
        fx.simple_session(self.projects, plain, T0 + 300, 'What is an override formula?', 'It replaces a calculated value. More text here.', cwd=self.work)
        fx.simple_session(self.projects, old_peer, T0 + 400, 'P3 · Dana design review (launched by HQ from the Session Canvas). Sam steers.',
                          'Reviewed.', cwd=self.work)
        s = self.by_id(self.index())
        self.assertEqual(s[bg]['name'], 'Product weekly')                       # runs.tsv id -> report, tag stripped
        self.assertEqual((s[bg]['report']['status'], s[bg]['report']['left']), ('your-turn', 'Sam picks a date'))
        self.assertEqual(s[bg]['report']['file'], os.path.join('reports', self.day, 'weekly.md'))
        self.assertEqual(s[peer]['name'], 'ABC-1 warn-only')                    # a peer: named by its note's footer, not its first words
        self.assertEqual(s[peer]['report']['outcome'], 'ACs in Jira')
        self.assertEqual((s[named]['name'], s[named]['report']['status']), ('Handover pack', 'not-done'))   # by name
        self.assertIsNone(s[plain]['report'])                                   # no report: its last message, short
        self.assertEqual(s[plain]['name'], s[plain]['title'])
        self.assertTrue(s[plain]['last'].startswith('It replaces a calculated value'))
        self.assertEqual(s[old_peer]['name'], 'P3 · Dana design review')

    def test_a_peer_is_named_before_its_report_exists_and_a_new_report_shows_up(self):
        peer = fx.new_id()
        rep = os.path.join(self.dir, 'later.md')
        fx.simple_session(self.projects, peer, T0, 'Do the thing.\nYou are the helper "W16·Later thing", started by HQ. HQ reads: %s\n' % rep,
                          'Working on it.', cwd=self.work)
        ix = self.index()
        s = self.by_id(ix)[peer]
        self.assertEqual((s['name'], s['report']), ('Later thing', None))
        gen = ix.generation
        self.write('later.md', 'status: done\nname: W16·Later thing\noutcome: finished\nleft: nothing\n')
        ix.refresh()                                                           # no transcript changed, only the report
        self.assertGreater(ix.generation, gen)
        self.assertEqual(self.by_id(ix)[peer]['report']['outcome'], 'finished')
        g2 = ix.generation
        ix.refresh()
        self.assertEqual(ix.generation, g2)                                    # nothing changed: nothing rebuilt

    def test_reports_outside_the_work_folder_are_never_read(self):
        peer = fx.new_id()
        secret = self.write('secret.md', 'status: done\nname: x\noutcome: SECRET\n', folder=os.path.join(self.tmp, 'elsewhere'))
        fx.simple_session(self.projects, peer, T0, 'You are the helper "W16·Sneaky". HQ reads: %s\n' % secret, 'ok', cwd=self.work)
        s = self.by_id(self.index())[peer]
        self.assertIsNone(s['report'])
        self.assertEqual(s['name'], 'Sneaky')


TABLE = {
    100: (1, '??', '/Applications/Ghostty.app/Contents/MacOS/ghostty'),
    110: (100, 'ttys000', '-/bin/zsh'),
    111: (110, 'ttys000', 'claude'),
    200: (1, '??', '/Applications/Ghostty.app/Contents/MacOS/ghostty -e /bin/zsh -l /x/launch/note-new.sh'),
    210: (200, 'ttys015', '/usr/bin/login -flp sam /bin/zsh -l /x/launch/note-new.sh'),
    211: (210, 'ttys015', '/Users/sam/.local/bin/claude /ticket Rewrite'),
    300: (1, '??', '/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal'),
    310: (300, 'ttys003', 'login -pf sam'),
    311: (310, 'ttys003', '-zsh'),
    312: (311, 'ttys003', 'claude --resume abc'),
    400: (1, '??', '/Users/sam/.local/bin/claude daemon run'),
    410: (400, '??', 'claude bg-pty-host'),
    411: (410, 'ttys016', 'claude bg-spare'),
    500: (1, '??', 'sshd'),
    511: (500, 'ttys020', 'claude'),
}
SID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'


class Focus(unittest.TestCase):
    def live(self, pid, kind='interactive'):
        return {SID: {'pid': pid, 'status': 'idle', 'kind': kind, 'since': 1, 'windows': 1}}

    def go(self, pid, kind='interactive', title='My session', answers=None, front=None, dry=False):
        calls = []

        def run(cmd, timeout=10):
            calls.append(cmd)
            return (answers or {}).get(len(calls), (0, 'ok', ''))
        win = server.find_window(pid, TABLE)
        r = server.focus_session(SID, title=title, dry_run=dry, live=self.live(pid, kind), table=TABLE, run=run,
                                 front=(lambda: front) if front else (lambda: win and win['appPid']))
        return r, calls

    def test_find_window(self):
        self.assertEqual(server.find_window(111, TABLE), {'app': 'Ghostty', 'appPid': 100, 'tty': '/dev/ttys000', 'single': False})
        self.assertEqual(server.find_window(211, TABLE), {'app': 'Ghostty', 'appPid': 200, 'tty': '/dev/ttys015', 'single': True})
        self.assertEqual(server.find_window(312, TABLE)['app'], 'Terminal')
        self.assertIsNone(server.find_window(411, TABLE))          # a background helper: no terminal app above it
        self.assertIsNone(server.find_window(511, TABLE))          # over ssh
        self.assertIsNone(server.find_window(100, TABLE))          # no tty
        self.assertIsNone(server.find_window(999, TABLE))          # gone

    def test_a_canvas_window_is_brought_forward_by_its_own_process(self):
        r, calls = self.go(211)
        self.assertEqual((r['ok'], r['focused'], r['exact'], r['app']), (True, True, True, 'Ghostty'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3] + calls[0][-1:], ['osascript', '-l', 'JavaScript', '200'])

    def test_main_ghostty_picks_the_window_by_title_first(self):
        r, calls = self.go(111, title='Canvas "weekend" build')
        self.assertEqual((r['focused'], r['exact']), (True, True))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][-2:], ['100', 'Canvas "weekend" build'])      # the title is an argument, never code
        self.assertEqual(calls[1][-1], '100')
        r, calls = self.go(111, answers={1: (0, 'notfound', '')})
        self.assertEqual((r['focused'], r['exact']), (True, False))
        self.assertIn('one of the others', r['message'])

    def test_terminal_tab_is_found_by_tty(self):
        r, calls = self.go(312)
        self.assertEqual((r['focused'], r['app']), (True, 'Terminal'))
        self.assertIn('      if tty of t is "/dev/ttys003" then', calls[0])
        r, _ = self.go(312, answers={1: (0, 'notfound', '')})
        self.assertEqual((r['ok'], r['focused'], r['reason']), (False, False, 'notfound'))
        r, _ = self.go(312, answers={1: (1, '', 'execution error: Not authorized to send Apple events to Terminal. (-1743)')})
        self.assertEqual(r['reason'], 'blocked')

    def test_when_it_cannot_focus_it_says_why_and_runs_nothing(self):
        r, calls = self.go(411, kind='bg')
        self.assertEqual((r['ok'], r['focused'], r['reason'], calls), (False, False, 'background', []))
        r, calls = self.go(511)
        self.assertEqual((r['focused'], r['reason'], calls), (False, 'nowindow', []))
        r = server.focus_session(SID, live={}, table=TABLE, run=None)
        self.assertEqual((r['focused'], r['reason']), (False, 'closed'))
        r, calls = self.go(211, answers={1: (0, 'gone', '')})
        self.assertEqual((r['ok'], r['focused'], r['reason']), (False, False, 'failed'))
        r, calls = self.go(211, front=4242)                          # macOS kept another app in front
        self.assertEqual((r['ok'], r['focused'], r['reason']), (False, False, 'refused'))

    def test_dry_run_finds_the_window_but_never_touches_it(self):
        r, calls = self.go(211, dry=True)
        self.assertEqual((r['ok'], r['focused'], r['dryRun'], calls), (True, False, True, []))
        self.assertEqual(r['commands'][0][-1], '200')


class FocusEndpoint(ApiCase):
    def setUp(self):
        self.live = tempfile.mkdtemp(prefix='canvas-live-')
        self.old = os.environ.get('CANVAS_LIVE_DIR')
        os.environ['CANVAS_LIVE_DIR'] = self.live
        self.ran = []
        self._run = server._osascript
        server._osascript = lambda *a, **k: self.ran.append(a) or (1, '', 'must not run')

    def tearDown(self):
        server._osascript = self._run
        if self.old is None:
            os.environ.pop('CANVAS_LIVE_DIR', None)
        else:
            os.environ['CANVAS_LIVE_DIR'] = self.old
        shutil.rmtree(self.live, ignore_errors=True)

    def test_focus_endpoint_is_guarded_and_safe_in_test_mode(self):
        sid = self.ids[0]
        self.assertEqual(self.post('/api/focus', {'sessionId': sid}, token=False)[0], 403)
        self.assertEqual(self.post('/api/focus', {'sessionId': sid}, headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.post('/api/focus', {'sessionId': '../../etc'})[0], 400)
        st, r, _ = self.post('/api/focus', {'sessionId': sid})
        self.assertEqual((st, r['ok'], r['focused'], r['reason']), (200, False, False, 'closed'))
        with open(os.path.join(self.live, '%d.json' % os.getpid()), 'w') as fh:
            json.dump({'pid': os.getpid(), 'sessionId': sid, 'status': 'idle', 'kind': 'interactive', 'startedAt': 1}, fh)
        st, r, _ = self.post('/api/focus', {'sessionId': sid})
        self.assertEqual((st, r['focused']), (200, False))               # test mode: found or not, never moved
        self.assertIn(r['reason'], ('dryrun', 'nowindow'))
        with open(os.path.join(self.live, '1.json'), 'w') as fh:
            json.dump({'pid': 1, 'sessionId': self.ids[1], 'status': 'idle', 'kind': 'bg', 'startedAt': 1}, fh)
        st, r, _ = self.post('/api/focus', {'sessionId': self.ids[1]})
        self.assertEqual((st, r['reason']), (200, 'background'))
        self.assertEqual(self.ran, [])
        self.assertEqual(self.get('/api/spawnlog')[1]['entries'], [])     # going to a window is not "opening a session"


if __name__ == '__main__':
    unittest.main(verbosity=2)
