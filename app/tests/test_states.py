"""v1.2: where a card stands (question / your turn / done / replaced), the marks made on the board, the
"waiting on you" list and the reminder ping.

Nothing here sends anything: the reminder gets a fake sender that only collects the lines.
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
MIN = 60000


def parse_report(path):
    return indexer.parse_report(path, 'Sam')


class ReportLines(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='canvas-st-'))
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

    def sessions(self):
        ix = indexer.Index(os.path.join(self.tmp, 'cache'), projects_root=self.projects, work_root=self.work, use_pool=False,
                           report_dirs=[os.path.join(self.work, 'reports')], user_name='Sam')
        ix.refresh()
        return dict((s['id'], s) for s in ix.payload()['sessions'])

    def peer(self, slug, name, report_text, at=0):
        """A visible helper window: its first prompt carries the name and the report path (as HQ writes it)."""
        sid = fx.new_id()
        path = self.write(slug + '.md', report_text)
        footer = ('\nMISSION RULE. You are the helper "%s", started by HQ.\n2. REPORT TO HQ EVERY TIME YOU STOP. HQ reads: %s\n' % (name, path))
        fx.simple_session(self.projects, sid, T0 + at, '/draft do the thing ' + 'x ' * 400 + footer, 'Working on it.', cwd=self.work)
        return sid

    def test_status_question_and_its_other_spellings(self):
        for word in ('question', 'Question', 'needs-clarification', 'needs answer', 'needs_input', 'clarify'):
            r = parse_report(self.write('q.md', 'status: %s\nname: W17·Pick a date\nleft: which day?\n' % word))
            self.assertEqual(r['status'], 'question', word)
            self.assertNotIn('ask', r)
        self.assertEqual(indexer.card_state({'id': 'a', 'report': r})['state'], 'question')

    def test_old_your_turn_reports_keep_working_and_questions_are_recognised(self):
        ask = ('Sam picks 1/2/3; helper writes on OK',
               'Sam must answer: 1. OK to create the toggle?',
               'Sam says yes to the draft; Sam watches the video + chooses the Lara ping',
               'Sam reviews the 2 drafts and decides to post',
               'post in #int or DM Dana?')
        act = ('Sam sends the Slack draft in the thread. Owner waits for Mika.',
               'Sam OKs Gero + Dana drafts; Sam confirms Vale text after 1:1',
               'Sam fills the 1:1 slot + deletes old draft → helper saves Slack draft → Sam sends',
               "draft waits on Robin's answer; then Sam sends",          # somebody else answers: still "your turn"
               '')
        for left in ask:
            r = parse_report(self.write('a.md', 'status: your-turn\nname: x\noutcome: o\nleft: %s\n' % left))
            self.assertEqual(r['status'], 'your-turn')                      # what the helper wrote is kept
            self.assertTrue(r.get('ask'), left)
            self.assertEqual(indexer.card_state({'id': 'a', 'report': r})['state'], 'question', left)
        for left in act:
            r = parse_report(self.write('a.md', 'status: your-turn\nname: x\noutcome: draft saved\nleft: %s\n' % left))
            self.assertFalse(r.get('ask'), left)
            self.assertEqual(indexer.card_state({'id': 'a', 'report': r})['state'], 'your-turn', left)

    def test_sent_line_anywhere_turns_a_waiting_card_done(self):
        p = self.write('s.md', 'status: your-turn\nname: W17·Mika reply\noutcome: draft saved\nleft: Sam sends it\n\n' +
                       'detail line\n' * 30 + 'sent: https://example.slack.com/archives/C1/p123\n')
        r = parse_report(p)
        self.assertEqual(r['sent'], 'https://example.slack.com/archives/C1/p123')
        self.assertEqual(indexer.card_state({'id': 'a', 'report': r}), {'state': 'done', 'why': 'sent'})
        for no in ('', 'no', '-', 'not yet', 'None'):
            r = parse_report(self.write('s.md', 'status: your-turn\nname: x\nleft: Sam sends it\nsent: %s\n' % no))
            self.assertEqual(r['sent'], '', no)
            self.assertEqual(indexer.card_state({'id': 'a', 'report': r})['state'], 'your-turn', no)
        # the extra lines never leak into the outcome of a report that has none
        r = parse_report(self.write('s.md', 'status: done\nname: x\nsent: https://x.y/z\nreplaces: a, b\n\nAll posted.\n'))
        self.assertEqual((r['outcome'], r['replaces']), ('All posted.', ['a', 'b']))

    def test_sig_changes_only_when_the_header_changes(self):
        a = parse_report(self.write('s.md', 'status: your-turn\nname: x\noutcome: draft\nleft: Sam sends\n'))
        b = parse_report(self.write('s.md', 'status: your-turn\nname: x\noutcome: draft\nleft: Sam sends\n\nmore detail below\n'))
        c = parse_report(self.write('s.md', 'status: your-turn\nname: x\noutcome: draft v2\nleft: Sam sends\n'))
        self.assertEqual(a['sig'], b['sig'])
        self.assertNotEqual(a['sig'], c['sig'])

    def test_replaces_and_replaced_by_link_the_cards(self):
        old1 = self.peer('daily-follow-ups', 'W17·Daily follow-ups', 'status: your-turn\nname: W17·Daily follow-ups\nleft: Sam OKs drafts\n', 0)
        old2 = self.peer('away-handover', 'W17·Away handover', 'status: your-turn\nname: W17·Away handover\nleft: Sam sends\n', 100)
        old3 = self.peer('overrides-go-live', 'W17·Overrides go-live', 'status: not-done\nname: W17·Overrides go-live\nleft: x\nreplaced-by: robin-alignment\n', 200)
        new = self.peer('robin-alignment', 'W17·Robin alignment',
                        'status: done\nname: W17·Robin alignment\noutcome: done\nleft: nothing\nreplaces: daily-follow-ups, W17·Away handover, no-such-slug\n', 300)
        lone = self.peer('gone', 'W17·Gone', 'status: your-turn\nname: W17·Gone\nleft: x\nreplaced-by: %s/some-later-thing.md\n' % self.day, 400)
        keep = self.peer('keep', 'W17·Keep', 'status: your-turn\nname: W17·Keep\nleft: Sam sends\n', 500)
        s = self.sessions()
        for sid in (old1, old2, old3):
            self.assertEqual(s[sid]['replacedBy'], {'id': new, 'name': 'Robin alignment'})
            self.assertEqual(indexer.card_state(s[sid])['state'], 'replaced')
            self.assertEqual(indexer.card_state(s[sid])['by'], new)
        self.assertIsNone(s[new]['replacedBy'])
        self.assertEqual(indexer.card_state(s[new])['state'], 'done')
        self.assertEqual(s[lone]['replacedBy'], {'id': None, 'name': 'some-later-thing'})     # named, but not on the board
        self.assertIsNone(s[keep]['replacedBy'])                                               # nothing is guessed
        self.assertEqual([w['id'] for w in indexer.waiting_list(s.values())], [keep])

    def test_a_report_never_replaces_itself(self):
        a = self.peer('solo', 'W17·Solo', 'status: your-turn\nname: W17·Solo\nleft: Sam sends\nreplaces: solo\nreplaced-by: W17·Solo\n')
        s = self.sessions()
        self.assertEqual(s[a]['replacedBy'], {'id': None, 'name': 'Solo'})
        # no session of that name: the line still closes the card, pointing nowhere
        self.assertEqual(indexer.card_state(s[a])['state'], 'replaced')


class CardState(unittest.TestCase):
    def rep(self, status, **kw):
        r = {'status': status, 'sig': 'abc', 'at': 1000, 'left': 'l', 'outcome': 'o'}
        r.update(kw)
        return r

    def test_states_from_the_report_and_the_window(self):
        cs = indexer.card_state
        self.assertEqual(cs({'id': 'a'})['state'], '')
        self.assertEqual(cs({'id': 'a'}, active=True)['state'], 'running')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('not-done')})['state'], 'not-done')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('not-done')}, active=True)['state'], 'running')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('done')}, active=True)['state'], 'done')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('your-turn')}, active=True)['state'], 'your-turn')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('question')})['state'], 'question')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('your-turn', ask=True)})['state'], 'question')
        self.assertEqual(cs({'id': 'a', 'report': self.rep('question', sent='https://x')})['state'], 'done')

    def test_marks_win_until_the_report_header_changes(self):
        cs = indexer.card_state
        s = {'id': 'a', 'report': self.rep('your-turn')}
        for kind in ('done', 'sent'):
            self.assertEqual(cs(s, {'a': {'kind': kind, 'sig': 'abc', 'at': 5}}), {'state': 'done', 'why': 'mark-' + kind})
        self.assertEqual(cs(s, {'a': {'kind': 'replaced', 'by': 'b', 'sig': 'abc'}}), {'state': 'replaced', 'by': 'b', 'why': 'mark'})
        self.assertEqual(cs(s, {'a': {'kind': 'done', 'sig': 'OLD'}})['state'], 'your-turn')       # the helper wrote something new
        self.assertEqual(cs(s, {'b': {'kind': 'done', 'sig': 'abc'}})['state'], 'your-turn')       # somebody else's mark
        self.assertEqual(cs(s, {'a': {'kind': 'nonsense'}})['state'], 'your-turn')
        self.assertEqual(cs(s, {'a': 'done'})['state'], 'your-turn')                                # a damaged state file
        self.assertEqual(cs({'id': 'a'}, {'a': {'kind': 'done', 'sig': ''}})['state'], 'done')     # a card with no report
        # a mark also wins over a "replaced" line, so "Reopen" is not needed to say "done"
        self.assertEqual(cs({'id': 'a', 'replacedBy': {'id': 'n', 'name': 'N'}, 'report': self.rep('done')})['state'], 'replaced')

    def test_waiting_list_is_oldest_first_and_skips_what_is_marked(self):
        ss = [{'id': 'new', 'name': 'New', 'report': self.rep('your-turn', at=9000)},
              {'id': 'old', 'name': 'Old', 'report': self.rep('question', at=1000, left='which one?')},
              {'id': 'mid', 'name': 'Mid', 'report': self.rep('your-turn', at=5000, ask=True)},
              {'id': 'fin', 'name': 'Fin', 'report': self.rep('done', at=100)},
              {'id': 'sent', 'name': 'Sent', 'report': self.rep('your-turn', at=50, sent='yes, 17:02')},
              {'id': 'none', 'name': 'None'}]
        w = indexer.waiting_list(ss)
        self.assertEqual([(x['id'], x['state']) for x in w], [('old', 'question'), ('mid', 'question'), ('new', 'your-turn')])
        self.assertEqual(w[0]['left'], 'which one?')
        w = indexer.waiting_list(ss, {'old': {'kind': 'sent', 'sig': 'abc'}, 'new': {'kind': 'replaced', 'by': 'fin', 'sig': 'abc'}})
        self.assertEqual([x['id'] for x in w], ['mid'])


class ReminderPing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='canvas-ping-')
        self.path = os.path.join(self.tmp, 'pings.json')
        self.sent = []
        # a fixed "now" at 11:00 local time, so the quiet hours do not depend on when the tests run
        lt = time.localtime()
        self.now = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 11, 0, 0, 0, 0, -1)) * 1000)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def reminder(self, **kw):
        return server.Reminder(self.path, self.sent.append, after_min=kw.pop('after_min', 30), url='http://127.0.0.1:7788/', **kw)

    def w(self, sid, mins_ago, state='your-turn', sig='s1', name=None):
        return {'id': sid, 'name': name or sid.title(), 'state': state, 'since': self.now - mins_ago * MIN, 'sig': sig, 'left': 'x'}

    def test_first_run_is_silent_then_one_line_per_card(self):
        r = self.reminder()
        self.assertIsNone(r.tick([self.w('old', 600)], self.now))                # what already waited before v1.2: no ping
        self.assertEqual(self.sent, [])
        self.assertIsNone(r.tick([self.w('old', 600), self.w('fresh', 5)], self.now))   # helpers announce new reports themselves
        self.now += 30 * MIN
        line = r.tick([self.w('old', 630), self.w('fresh', 35, 'question', name='Pick a date')], self.now)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(line, self.sent[0])
        self.assertIn('1 card waiting on you', line)
        self.assertIn('Pick a date (needs your answer, 35 min)', line)
        self.assertNotIn('Old', line)
        self.assertIn('http://127.0.0.1:7788/', line)
        for i in range(5):                                                       # never twice for the same card + report
            self.assertIsNone(r.tick([self.w('old', 640), self.w('fresh', 40 + i, 'question')], self.now + (5 + i) * MIN))
        self.assertEqual(len(self.sent), 1)

    def test_not_repeated_after_a_restart_and_again_only_for_a_new_report(self):
        self.reminder().tick([], self.now)
        self.reminder().tick([self.w('a', 31)], self.now)
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(self.reminder().tick([self.w('a', 90)], self.now + 59 * MIN))      # a new Reminder = the server restarted
        self.assertEqual(len(self.sent), 1)
        self.reminder().tick([self.w('a', 45, sig='s2')], self.now + 60 * MIN)               # the helper asked something new
        self.assertEqual(len(self.sent), 2)
        with open(self.path) as fh:
            self.assertEqual(sorted(json.load(fh)['pinged']), ['a|s2'])                      # cards that moved on are forgotten

    def test_several_cards_make_one_line(self):
        r = self.reminder()
        r.tick([], self.now)
        cards = [self.w('c%d' % i, 40 + i * 10) for i in range(5)]
        line = r.tick(cards, self.now)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('5 cards waiting on you', line)
        self.assertIn('C4 (your turn, 1 h 20)', line)           # the one that waited longest comes first
        self.assertTrue(line.index('C4') < line.index('C3') < line.index('C2'))
        self.assertIn('+2 more', line)
        self.assertLessEqual(len(line), 290)                    # the reminder command cuts at 300

    def test_quiet_hours_wait_for_the_morning(self):
        r = self.reminder()
        r.tick([], self.now)
        night = self.now + 11 * 60 * MIN                        # 22:00
        self.assertIsNone(r.tick([self.w('a', 0)], night - 40 * MIN + 40 * MIN))
        self.assertIsNone(r.tick([{'id': 'a', 'name': 'A', 'state': 'your-turn', 'since': night - 40 * MIN, 'sig': 's1'}], night))
        self.assertEqual(self.sent, [])
        morning = self.now + 22 * 60 * MIN                      # 09:00 the next day
        self.assertIsNotNone(r.tick([{'id': 'a', 'name': 'A', 'state': 'your-turn', 'since': night - 40 * MIN, 'sig': 's1'}], morning))
        self.assertEqual(len(self.sent), 1)

    def test_off_switches_and_a_failing_sender(self):
        r = server.Reminder(self.path, None)
        self.assertIsNone(r.tick([self.w('a', 500)], self.now))
        self.assertFalse(os.path.exists(self.path))             # no sender: nothing is even written
        r = self.reminder(after_min=0)
        self.assertIsNone(r.tick([self.w('a', 500)], self.now))

        def boom(_text):
            raise RuntimeError('no network')
        r = server.Reminder(self.path, boom, after_min=30)
        r.tick([], self.now)
        self.assertIsNotNone(r.tick([self.w('a', 31)], self.now))               # the failure does not reach the server
        r2 = self.reminder()
        self.assertIsNone(r2.tick([self.w('a', 32)], self.now + MIN))           # ... and is not retried every minute

    def test_fmt_wait(self):
        self.assertEqual([server.fmt_wait(m * MIN) for m in (0, 35, 60, 80, 62, 600, 3000)],
                         ['0 min', '35 min', '1 h', '1 h 20', '1 h', '10 h', '2 days'])


class WaitingApi(ApiCase):
    """A dry-run server (like every test server): the list works, the ping can never start."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        day = time.strftime('%Y-%m-%d', time.localtime(T0))
        d = os.path.join(cls.work, 'reports', day)
        os.makedirs(d)
        rows = []
        cls.reports = {}
        for i, (slug, text) in enumerate((('ask', 'status: question\nname: W17·Ask\noutcome: two options\nleft: Sam picks A or B\n'),
                                          ('send', 'status: your-turn\nname: W17·Send\noutcome: draft saved\nleft: Sam sends it\n'),
                                          ('fin', 'status: done\nname: W17·Fin\noutcome: done\nleft: nothing\n'))):
            p = os.path.join(d, slug + '.md')
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(text)
            os.utime(p, (T0 + i * 600, T0 + i * 600))
            cls.reports[slug] = p
            rows.append('%s\tW17·%s\tjob\tsonnet\tdraft\t10:3%d\t%s\n' % (cls.ids[i][:8], slug.title(), i, p))
        with open(os.path.join(d, 'runs.tsv'), 'w', encoding='utf-8') as fh:
            fh.writelines(rows)
        cls.app.store.patch({'settings': {'reportFolders': [os.path.join(cls.work, 'reports')], 'userName': 'Sam'}})
        cls.app.apply_settings()
        cls.app.rescan()

    def test_waiting_list_json_and_text(self):
        st, d, _ = self.get('/api/waiting')
        self.assertEqual(st, 200)
        self.assertEqual(d['counts'], {'question': 1, 'your-turn': 1})
        self.assertEqual([(w['id'], w['state'], w['name']) for w in d['waiting']],
                         [(self.ids[0], 'question', 'Ask'), (self.ids[1], 'your-turn', 'Send')])
        self.assertTrue(d['waiting'][0]['file'].endswith('ask.md'))
        self.assertTrue(d['waiting'][0]['waited'])
        st, text, _ = self.get('/api/waiting?format=text')
        lines = text.strip().split('\n')
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('needs your answer\t'))
        self.assertIn('\tAsk\tSam picks A or B\t', lines[0])

    def test_marks_are_saved_and_take_cards_off_the_list(self):
        sig = [w for w in self.get('/api/waiting')[1]['waiting'] if w['id'] == self.ids[1]][0]['sig']
        st, d, _ = self.post('/api/state', {'patch': {'marks': {self.ids[1]: {'kind': 'sent', 'by': None, 'at': 1, 'sig': sig}}}})
        self.assertEqual(st, 200)
        self.assertEqual(self.get('/api/state')[1]['marks'][self.ids[1]]['kind'], 'sent')
        with open(os.path.join(self.tmp, 'state.json')) as fh:
            self.assertEqual(json.load(fh)['marks'][self.ids[1]]['sig'], sig)                 # on disk: survives a restart
        self.app.rescan()                                                                      # ... and a rescan
        self.assertEqual([w['id'] for w in self.get('/api/waiting')[1]['waiting']], [self.ids[0]])
        # the helper writes a new header: the old mark no longer hides the card
        with open(self.reports['send'], 'w', encoding='utf-8') as fh:
            fh.write('status: your-turn\nname: W17·Send\noutcome: v2 draft saved\nleft: Sam sends v2\n')
        self.app.rescan()
        self.assertEqual([w['id'] for w in self.get('/api/waiting')[1]['waiting']], [self.ids[0], self.ids[1]])
        self.assertEqual(self.post('/api/state', {'patch': {'marks': {}}})[0], 200)            # undo = the mark is gone
        self.assertEqual(self.post('/api/state', {'patch': {'marks': []}})[0], 400)

    def test_two_sessions_with_one_report_are_listed_once(self):
        rep = {'status': 'your-turn', 'file': 'reports/d/a.md', 'at': 5, 'sig': 'x'}
        sessions = [{'id': 'old', 'start': 1, 'report': rep}, {'id': 'new', 'start': 2, 'report': rep},
                    {'id': 'other', 'start': 3, 'report': dict(rep, file='reports/d/b.md', at=9)}]
        self.assertEqual([w['id'] for w in indexer.waiting_list(sessions)], ['new', 'other'])

    def test_no_ping_in_dry_run(self):
        calls = []
        self.assertTrue(self.app.dry_run)
        self.assertFalse(self.app.start_reminders(send=calls.append, after_min=30, every=0.01))
        self.assertIsNone(self.app.reminder)
        time.sleep(0.1)
        self.assertEqual(calls, [])

    def test_version_is_on_the_page(self):
        v = self.get('/api/health')[1]['version']
        self.assertRegex(v, r'^\d+\.\d+\.\d+$')
        self.assertIn('name="canvas-version" content="%s"' % v, self.get('/')[1])


class LivePing(unittest.TestCase):
    """The clock itself, with a fake sender (the only place a non-dry-run App runs in the tests)."""

    def test_the_clock_pings_once_through_the_given_sender(self):
        tmp = tempfile.mkdtemp(prefix='canvas-live-')
        try:
            projects, work = os.path.join(tmp, 'projects'), os.path.realpath(os.path.join(tmp, 'work'))
            day = time.strftime('%Y-%m-%d')
            d = os.path.join(work, 'reports', day)
            os.makedirs(projects)
            os.makedirs(d)
            sid = fx.new_id()
            fx.simple_session(projects, sid, time.time() - 7200, 'Draft a reply', 'Draft saved.', cwd=work)
            app = server.App(server.parse_args(['--port', '0', '--state', os.path.join(tmp, 'state.json'), '--cache', os.path.join(tmp, 'cache'),
                                                '--projects', projects, '--root', work, '--claude', '/nonexistent/claude']))
            app.index.use_pool = False
            app.port = 7788
            app.index.refresh()
            sent = []
            app.store.patch({'settings': {'reportFolders': [os.path.join(work, 'reports')]}})
            app.apply_settings()
            self.assertFalse(app.start_reminders(after_min=30))                 # no reminder command was given
            self.assertTrue(app.start_reminders(send=sent.append, after_min=0.001, every=0.05))
            app.reminder.hours = (0, 24)
            app.reminder.tick([])                                               # the silent first run
            rep = os.path.join(d, 'reply.md')
            with open(rep, 'w', encoding='utf-8') as fh:
                fh.write('status: your-turn\nname: W17·Reply\noutcome: draft saved\nleft: Sam sends it\n')
            old = time.time() - 3600
            os.utime(rep, (old, old))
            with open(os.path.join(d, 'runs.tsv'), 'w', encoding='utf-8') as fh:
                fh.write('%s\tW17·Reply\tjob\tsonnet\tdraft\t10:30\t%s\n' % (sid[:8], rep))
            app.index.last_refresh = 0                                          # let the clock look again right away
            deadline = time.time() + 10
            while not sent and time.time() < deadline:
                time.sleep(0.05)
            time.sleep(0.3)
            self.assertEqual(len(sent), 1, sent)
            self.assertIn('Reply (your turn, 1 h)', sent[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
