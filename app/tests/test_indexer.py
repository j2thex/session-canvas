"""Reading transcripts, keywords, links between sessions, the cache and search.

Run all tests:  /usr/bin/python3 -m unittest discover -s app/tests -v
Only made-up transcripts are used (tests/fixtures.py); nothing on this Mac is read.
"""
import collections
import glob
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
import fixtures as fx  # noqa: E402

T0 = 1794300000          # a fixed moment in Nov 2026 (UTC seconds)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='canvas-test-')
        self.projects = os.path.join(self.tmp, 'projects')
        self.cache = os.path.join(self.tmp, 'cache')
        os.makedirs(self.projects)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, **kw):
        return indexer.Index(self.cache, projects_root=self.projects, work_root=kw.pop('work_root', self.tmp), use_pool=False, **kw)


# ---------------------------------------------------------------------------------------- parsing

class ParseSynthetic(TempCase):
    def test_counts_titles_and_what_is_not_a_prompt(self):
        sid = fx.new_id()
        recs = [
            {'type': 'custom-title', 'customTitle': 'My named session', 'sessionId': sid},
            {'type': 'ai-title', 'aiTitle': 'AI made title', 'sessionId': sid},
            fx.user('<system-reminder>\nignore me\n</system-reminder>\n\nPlease draft the design doc for ACME-7498 https://app.notion.com/p/abc123def4567890abc123def4567890', T0, sid),
            fx.user('Base directory for this skill: /x/y', T0 + 1, sid, isMeta=True),
            fx.assistant('Here is the draft. See [the design doc page](https://app.notion.com/p/abc123def4567890abc123def4567890) and ACME-7498.', T0 + 5, sid,
                         tools=[('Skill', {'skill': 'doc'}), ('Bash', {'command': 'ls https://example.atlassian.net/browse/ACME-6477'})]),
            fx.tool_result('total 0', T0 + 6, sid),
            fx.user('<command-name>/mcp</command-name>\n<command-message>mcp</command-message>\n<command-args></command-args>', T0 + 7, sid),
            fx.user('<local-command-stdout>ok</local-command-stdout>', T0 + 8, sid),
            fx.user('<task-notification>\n<task-id>1</task-id></task-notification>', T0 + 9, sid, promptSource='system', origin={'kind': 'task-notification'}),
            fx.user('<command-message>morning</command-message>\n<command-name>/morning</command-name>\n<command-args>wrap today</command-args>', T0 + 10, sid),
            fx.assistant('', T0 + 11, sid, tools=[('Read', {'file_path': '/x'})]),
            fx.assistant('side work', T0 + 12, sid, isSidechain=True),
            fx.assistant('No response requested.', T0 + 13, sid, model='<synthetic>'),
            fx.assistant('All wrapped up.', T0 + 20, sid),
            {'parentUuid': None, 'isSidechain': False, 'type': 'system', 'subtype': 'away_summary', 'content': 'You wrapped the day. Next: rest. (disable recaps in /config)',
             'timestamp': fx.iso(T0 + 25), 'uuid': fx.new_id(), 'sessionId': sid},
            {'type': 'cost-state', 'sessionId': sid, 'totalCostUSD': 1.25},
        ]
        path = fx.write_session(self.projects, sid, recs, raw_lines=['{"type":"api-request-blob","hash":"x","message":"y"}', 'this is not json', '{"broken": '])
        r = indexer.parse_session(path)
        m = r['meta']
        self.assertEqual(m['id'], sid)
        self.assertEqual(m['title'], 'My named session')          # a name the person gave beats the AI title
        self.assertEqual(m['titleSource'], 'custom')
        self.assertEqual(m['prompts'], 2)                          # the real ask + /morning; not /mcp, stdout, notifications, skill text
        self.assertEqual(m['replies'], 2)                          # not the sidechain, not the synthetic one, not the tool-only one
        self.assertEqual(m['tools'], 3)
        self.assertEqual(m['bad'], 2)                              # two broken lines were skipped, not fatal
        self.assertTrue(m['firstPrompt'].startswith('Please draft the design doc'))
        self.assertNotIn('system-reminder', m['firstPrompt'])
        self.assertEqual(m['lastPrompt'], '/morning wrap today')
        self.assertEqual(m['lastReply'], 'All wrapped up.')
        self.assertEqual(sorted(m['commands']), ['/doc', '/morning'])   # /mcp is housekeeping
        self.assertIn('ACME-7498', m['jira'])
        self.assertTrue(any('notion.com' in u for u in m['urls']))
        self.assertEqual(m['urlLabels'].get('https://app.notion.com/p/abc123def4567890abc123def4567890'), 'the design doc page')
        self.assertEqual(m['recaps'], ['You wrapped the day. Next: rest.'])
        self.assertEqual(m['cost'], 1.25)
        self.assertEqual(m['kind'], 'you')
        self.assertEqual(m['cwd'], fx.WORK)
        self.assertEqual(m['start'], T0 * 1000)
        self.assertEqual(m['end'], (T0 + 25) * 1000)
        self.assertIn('Please draft the design doc', r['text'])
        self.assertNotIn('side work', r['text'])
        self.assertEqual(len(r['uuids']), len(r['uts']))

    def test_title_falls_back_to_first_prompt_and_command(self):
        a, b = fx.new_id(), fx.new_id()
        pa = fx.simple_session(self.projects, a, T0, 'help me plan the sprint review\nsecond line', 'Sure.')
        pb = fx.write_session(self.projects, b, [
            fx.user('<command-message>daily-digest</command-message>\n<command-name>/daily-digest</command-name>\n<command-args>after-meeting Daily Standup</command-args>', T0, b, entry='sdk-cli', promptSource=None, origin=None),
            fx.assistant('Processed the standup notes.', T0 + 9, b, entry='sdk-cli')])
        ma, mb = indexer.parse_session(pa)['meta'], indexer.parse_session(pb)['meta']
        self.assertEqual(ma['title'], 'help me plan the sprint review')
        self.assertEqual(mb['title'], '/daily-digest after-meeting Daily Standup')
        self.assertEqual(mb['kind'], 'auto')                       # started by a script, not typed by a person

    def test_kinds_worktree_and_compact_start(self):
        wt = fx.WORK + '/.claude/worktrees/timeline-view'
        sid = fx.new_id()
        recs = [
            fx.user('Build the timeline', T0, sid, cwd=fx.WORK, sessionKind='bg'),
            {'type': 'worktree-state', 'worktreeSession': {'originalCwd': fx.WORK, 'worktreePath': wt, 'worktreeName': 'timeline-view'}, 'sessionId': sid},
            {'type': 'relocated', 'relocatedCwd': wt, 'sessionId': sid},
            fx.assistant('Done.', T0 + 60, sid, cwd=wt, sessionKind='bg'),
        ]
        m = indexer.parse_session(fx.write_session(self.projects, sid, recs, cwd=wt))['meta']
        self.assertEqual(m['kind'], 'helper')
        self.assertEqual(m['worktree'], {'name': 'timeline-view', 'path': wt, 'original': fx.WORK})
        self.assertEqual(m['cwd'], wt)                              # resume from the folder the transcript belongs to
        c = fx.new_id()
        recs = [fx.user(indexer.CONTINUED_PREFIX + ' that ran out of context.', T0, c, isCompactSummary=True),
                fx.user('carry on', T0 + 5, c), fx.assistant('Carrying on.', T0 + 9, c)]
        m = indexer.parse_session(fx.write_session(self.projects, c, recs))['meta']
        self.assertTrue(m['startsWithCompact'])
        self.assertEqual(m['prompts'], 1)
        self.assertEqual(m['firstPrompt'], 'carry on')
        d = fx.new_id()
        scratch = '/home/tester/Library/Application Support/Claude/scratch-workspaces/a/b/scratch-2026-10-16-bff349'
        m = indexer.parse_session(fx.simple_session(self.projects, d, T0, 'fix my dock', 'ok', cwd=scratch, entry='claude-desktop'))['meta']
        self.assertEqual(m['kind'], 'desktop')

    def test_helper_launch_lines_are_found_in_tool_output(self):
        sid = fx.new_id()
        recs = [fx.user('go', T0, sid),
                fx.assistant('Starting helpers.', T0 + 1, sid, tools=[('Bash', {'command': 'scripts/start-helpers.sh "x" "y"'})]),
                fx.tool_result('abcd1234 W13·mcp-test-prep (job, sonnet) → /x/.state/sessions/2026-11-13/mcp-test-prep.md', T0 + 2, sid),
                fx.tool_result('Guide opened in a new Ghostty window: \U0001f9ed Export QA → guides/x/INDEX.md', T0 + 3, sid),
                fx.tool_result('plain output with an arrow → but no launch', T0 + 4, sid)]
        m = indexer.parse_session(fx.write_session(self.projects, sid, recs))['meta']
        self.assertEqual([(x[0], x[1], x[4]) for x in m['launches']], [('abcd1234', 'W13·mcp-test-prep', 'job')])
        self.assertEqual([x[0] for x in m['guides']], ['\U0001f9ed Export QA'])

    def test_empty_and_unreadable_files(self):
        sid = fx.new_id()
        path = fx.write_session(self.projects, sid, [{'type': 'mode', 'mode': 'normal', 'sessionId': sid}])
        m = indexer.parse_session(path)['meta']
        self.assertEqual((m['prompts'], m['replies']), (0, 0))
        self.assertIsNone(indexer.parse_session(os.path.join(self.projects, 'nope', 'missing.jsonl')) if os.path.exists('/nonexistent') else None)
        idx = self.index()
        idx.refresh()
        self.assertEqual(idx.payload()['sessions'], [])            # opened-and-closed sessions are left off the board


class Keywords(unittest.TestCase):
    def metas(self):
        t = indexer._Terms()
        t.add('Please check the override formulas for the design doc. The override formulas are broken in version datasets.', 3)
        t.add('I checked the override formulas. Version datasets look fine; the design doc page is updated. '
              'See `some_code_here` and /home/x/file.md and https://example.com/a and ACME-1234 and 2026-11-13.', 1)
        a = {'tf': dict(t.tf), 'bi': dict(t.bi), 'caps': dict(t.caps), 'cap1': dict(t.cap1), 'ntok': t.ntok}
        metas = {'a': a}
        for i in range(12):                                        # other sessions share the everyday words
            u = indexer._Terms()
            u.add('standup notes about the roadmap and the deep dive, with %s' % ('mixpanel dashboards' if i % 2 else 'jira tickets'), 3)
            u.add('standup notes roadmap deep dive roadmap standup', 1)
            metas['s%d' % i] = {'tf': dict(u.tf), 'bi': dict(u.bi), 'caps': dict(u.caps), 'cap1': dict(u.cap1), 'ntok': u.ntok}
        return metas

    def test_picks_what_is_special_about_a_session(self):
        kw = indexer.compute_keywords(self.metas())
        low = [k.lower() for k in kw['a']]
        self.assertIn('override formulas', low)                    # a phrase beats its single words
        self.assertIn('version datasets', low)
        self.assertNotIn('override', low)
        self.assertLessEqual(len(kw['a']), 8)
        for bad in ('the', 'please', 'check', 'some_code_here', 'file', 'example', 'acme-1234', 'https'):
            self.assertNotIn(bad, low)
        self.assertFalse(any('/' in k or k[:1].isdigit() for k in kw['a']))

    def test_noise_never_becomes_a_term(self):
        t = indexer._Terms()
        t.add('```\ncode block secretword\n```\npineapple harvest here: tokenA mcp__claude_ai_Slack__send camelCaseThing snake_case_thing '
              '0123abcdef0 12:30 path/to/thing.py quickly', 1)
        for bad in ('secretword', 'camelcasething', 'snake', 'thing.py', 'mcp', 'claude', 'here', 'quickly'):
            self.assertNotIn(bad, t.tf)
        self.assertEqual(sorted(t.tf), ['harvest', 'pineapple', 'tokena'])
        self.assertEqual(dict(t.bi), {'pineapple harvest': 1})

    def test_own_name_and_ubiquitous_words_are_dropped(self):
        me = sorted(indexer.USER_WORDS)[0] if indexer.USER_WORDS else None
        metas = {}
        for i in range(10):
            t = indexer._Terms()
            t.add('%s asked about budgets and budgets again, plus topic%d topic%d topic%d' % (me or 'someone', i, i, i), 3)
            metas[str(i)] = {'tf': dict(t.tf), 'bi': dict(t.bi), 'caps': {}, 'cap1': {}, 'ntok': t.ntok}
        kw = indexer.compute_keywords(metas)
        for i in range(10):
            low = [k.lower() for k in kw[str(i)]]
            self.assertNotIn('budgets', low)                       # in every session: says nothing
            if me:
                self.assertNotIn(me, low)


# ---------------------------------------------------------------------------------------- relations

def meta(sid, start, **kw):
    m = {'id': sid, 'title': kw.pop('title', sid), 'start': start * 1000, 'end': (start + kw.pop('dur', 600)) * 1000, 'birth': kw.pop('birth', start),
         'cwd': kw.pop('cwd', fx.WORK), 'kind': kw.pop('kind', 'you'), 'commands': kw.pop('commands', {}), 'launches': [], 'guides': [], 'refs': [],
         'worktree': None, 'startsWithCompact': False, 'continuedIn': None}
    m.update(kw)
    return m


class Relations(unittest.TestCase):
    def edges(self, metas, uu, runs=None):
        e, own = indexer.detect_relations({m['id']: m for m in metas}, uu, runs)
        return {(x['from'], x['to']): x for x in e}, own

    def test_fork_shares_history_and_points_from_the_older_one(self):
        a, b = meta('A', T0), meta('B', T0, birth=T0 + 5000)       # B's history starts at the same time; its file is newer
        uu = {'A': (['u1', 'u2', 'u3', 'a4'], [T0, T0 + 1, T0 + 2, T0 + 6000]),
              'B': (['u1', 'u2', 'u3', 'b4', 'b5'], [T0, T0 + 1, T0 + 2, T0 + 5001, T0 + 5002])}
        e, own = self.edges([a, b], uu)
        self.assertEqual(list(e), [('A', 'B')])
        self.assertEqual(e[('A', 'B')]['kind'], 'fork')
        self.assertFalse(e[('A', 'B')]['guess'])
        self.assertEqual(own['B'], (T0 + 5001) * 1000)             # B really began at its first own message

    def test_continued_record_wins_over_fork_label(self):
        a, b = meta('A', T0, continuedIn='B'), meta('B', T0, birth=T0 + 900)
        uu = {'A': (['u1', 'u2'], [T0, T0 + 1]), 'B': (['u1', 'u2', 'b3'], [T0, T0 + 1, T0 + 901])}
        e, _ = self.edges([a, b], uu)
        self.assertEqual(e[('A', 'B')]['kind'], 'continued')

    def test_chain_of_forks_links_each_to_its_closest_original(self):
        a, b, c = meta('A', T0), meta('B', T0, birth=T0 + 100), meta('C', T0, birth=T0 + 200)
        uu = {'A': (['1', '2'], [T0, T0]), 'B': (['1', '2', '3', '4'], [T0, T0, T0 + 101, T0 + 102]), 'C': (['1', '2', '3', '4', '5'], [T0, T0, T0 + 101, T0 + 102, T0 + 201])}
        e, _ = self.edges([a, b, c], uu)
        self.assertEqual(sorted(e), [('A', 'B'), ('B', 'C')])

    def test_compact_start_links_to_the_previous_session_in_the_same_folder(self):
        old = meta('old', T0 - 5000, dur=4000)
        other_folder = meta('elsewhere', T0 - 100, dur=50, cwd='/home/tester/other')
        auto = meta('auto', T0 - 200, dur=100, kind='auto')
        new = meta('new', T0, startsWithCompact=True)
        e, _ = self.edges([old, other_folder, auto, new], {})
        self.assertEqual(list(e), [('old', 'new')])
        self.assertEqual(e[('old', 'new')]['kind'], 'continued')
        self.assertTrue(e[('old', 'new')]['guess'])                # marked as a guess

    def test_handover_reference(self):
        a = meta('11111111-1111-4111-8111-111111111111', T0)
        b = meta('22222222-2222-4222-8222-222222222222', T0 + 900, refs=['11111111-1111-4111-8111-111111111111', 'not-a-known-session'])
        e, _ = self.edges([a, b], {})
        self.assertEqual([(k, v['kind']) for k, v in e.items()], [((a['id'], b['id']), 'handover')])

    def test_helpers_from_launch_lines_go_to_the_original_not_its_copy(self):
        hq = meta('aaaaaaaa-0000-4000-8000-000000000001', T0, title='HQ')
        hq['launches'] = [['bbbbbbbb', 'W13·job', (T0 + 60) * 1000, 'uX', 'job']]
        copy = meta('aaaaaaaa-0000-4000-8000-000000000002', T0, birth=T0 + 500)
        copy['launches'] = [['bbbbbbbb', 'W13·job', (T0 + 60) * 1000, 'uX', 'job']]      # the fork carries the same tool output
        helper = meta('bbbbbbbb-0000-4000-8000-000000000003', T0 + 61, kind='helper', title='W13·job')
        uu = {hq['id']: (['u1', 'uX'], [T0, T0 + 60]), copy['id']: (['u1', 'uX', 'c3'], [T0, T0 + 60, T0 + 501]), helper['id']: (['h1'], [T0 + 61])}
        e, _ = self.edges([hq, copy, helper], uu)
        self.assertEqual(e[(hq['id'], helper['id'])]['kind'], 'helper')
        self.assertNotIn((copy['id'], helper['id']), e)
        self.assertEqual(e[(hq['id'], copy['id'])]['kind'], 'fork')

    def test_guide_is_matched_through_runs_tsv(self):
        hq = meta('aaaaaaaa-0000-4000-8000-000000000001', T0)
        hq['guides'] = [['\U0001f9ed Export QA', (T0 + 30) * 1000, 'u9']]
        guide = meta('cccccccc-0000-4000-8000-000000000009', T0 + 31, title='something else')
        runs = [{'date': '2026-11-10', 'id8': 'cccccccc', 'name': '\U0001f9ed Export QA', 'kind': 'guide', 'model': 'sonnet', 'skill': '-', 'time': '10:00'}]
        e, _ = self.edges([hq, guide], {}, runs)
        self.assertIn((hq['id'], guide['id']), e)

    def test_unclaimed_helper_falls_back_to_the_days_hq_as_a_guess(self):
        hq = meta('hq', T0, dur=20000, title='HQ')
        plain = meta('plain', T0 + 100, dur=20000)
        helper = meta('helper', T0 + 3000, kind='helper')
        e, _ = self.edges([hq, plain, helper], {})
        self.assertEqual(list(e), [('hq', 'helper')])
        self.assertTrue(e[('hq', 'helper')]['guess'])

    def test_worktree_session_links_to_the_session_active_in_the_parent_project(self):
        main = meta('main', T0, dur=9000)
        wt = meta('wt', T0 + 600, kind='you', cwd=fx.WORK + '/.claude/worktrees/x', worktree={'name': 'x', 'path': fx.WORK + '/.claude/worktrees/x', 'original': fx.WORK})
        e, _ = self.edges([main, wt], {})
        self.assertEqual(e[('main', 'wt')]['kind'], 'worktree')
        self.assertTrue(e[('main', 'wt')]['guess'])

    def test_no_self_links_and_unknown_ids_are_ignored(self):
        a = meta('A', T0, continuedIn='ghost', refs=['A'])
        a['launches'] = [['A', 'x', T0 * 1000, 'u', 'job']]
        e, _ = self.edges([a], {'A': (['u'], [T0])})
        self.assertEqual(e, {})


class DemoCorpus(unittest.TestCase):
    """A whole made-up history (tests/fixtures.py demo_corpus): every kind of link is found."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='canvas-demo-')
        projects = os.path.join(cls.tmp, 'projects')
        os.makedirs(projects)
        cls.o = fx.demo_corpus(projects, os.path.join(cls.tmp, 'work'))
        cls.idx = indexer.Index(os.path.join(cls.tmp, 'cache'), projects_root=projects, use_pool=False)
        cls.idx.refresh()
        cls.p = cls.idx.payload()
        cls.by = {s['id']: s for s in cls.p['sessions']}
        cls.e = {(x['from'], x['to']): x for x in cls.p['edges']}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_kind_of_link(self):
        for pair in self.o['continued']:
            self.assertEqual(self.e[pair]['kind'], 'continued')
        for pair in self.o['forks']:
            self.assertEqual(self.e[pair]['kind'], 'fork')
        for pair in self.o['handovers']:
            self.assertEqual(self.e[pair]['kind'], 'handover')
        helpers = [x for x in self.p['edges'] if x['kind'] == 'helper']
        self.assertEqual(len(helpers), len(self.o['helpers']))

    def test_edges_are_sane(self):
        for x in self.p['edges']:
            self.assertIn(x['from'], self.by)
            self.assertIn(x['to'], self.by)
            self.assertNotEqual(x['from'], x['to'])
        ids = [x['id'] for x in self.p['edges']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_kinds_and_keywords(self):
        kinds = collections.Counter(s['kind'] for s in self.p['sessions'])
        self.assertEqual(kinds['auto'], len(self.o['auto']))
        self.assertEqual(kinds['helper'], len(self.o['helpers']))
        self.assertEqual(kinds['desktop'], len(self.o['desktop']))
        for s in self.p['sessions']:
            for k in s['keywords']:
                self.assertNotIn(k.lower(), indexer.STOPWORDS)
                self.assertNotRegex(k, r'[/\\_<>{}]|^[0-9a-f]{8,}$|https?:')

    def test_a_copy_starts_at_its_own_first_message(self):
        parent, child = self.o['forks'][0]
        c = self.by[child]
        self.assertGreater(c['start'], c['historyStart'] + 3600 * 1000)

    def test_jira_keys_link_to_the_site_seen_in_the_transcripts(self):
        s = next(s for s in self.p['sessions'] if s['jira'])
        self.assertTrue(s['jira'][0].startswith('ACME-'))
        d = self.idx.detail(s['id'])
        self.assertTrue(d['links']['jira'][0]['url'].startswith('https://example.atlassian.net/browse/ACME-'))


# ---------------------------------------------------------------------------------------- index + cache + search

class IndexAndCache(TempCase):
    def make(self, n=4):
        ids = []
        for i in range(n):
            sid = fx.new_id()
            ids.append(sid)
            fx.simple_session(self.projects, sid, T0 + i * 3600, 'Question %d about pineapple budgets and ACME-%d' % (i, 7000 + i),
                              'Answer %d: the Banana forecast is ready. Unique%dword. https://example.atlassian.net/browse/ACME-%d' % (i, i, 7000 + i))
        return ids

    def test_cache_is_reused_and_only_changed_files_are_read_again(self):
        ids = self.make(4)
        idx = self.index()
        s = idx.refresh()
        self.assertEqual((s['files'], s['parsed']), (4, 4))
        gen = idx.generation
        s = idx.refresh()
        self.assertEqual(s['parsed'], 0)
        self.assertEqual(idx.generation, gen)                      # nothing changed -> the page is told "unchanged"
        # a new message arrives in one session
        path = os.path.join(self.projects, fx.encode_cwd(fx.WORK), ids[0] + '.jsonl')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(fx.user('one more thing about mangoes', T0 + 99, ids[0]), separators=(',', ':')) + '\n')
        os.utime(path, (time.time() + 2, time.time() + 2))
        s = idx.refresh()
        self.assertEqual(s['parsed'], 1)
        self.assertGreater(idx.generation, gen)
        self.assertEqual([x for x in idx.payload()['sessions'] if x['id'] == ids[0]][0]['prompts'], 2)
        # a brand-new session appears without a restart
        new = fx.new_id()
        fx.simple_session(self.projects, new, T0 + 99999, 'brand new', 'hello')
        s = idx.refresh()
        self.assertEqual(s['parsed'], 1)
        self.assertEqual(len(idx.payload()['sessions']), 5)
        # a deleted transcript disappears
        os.remove(path)
        s = idx.refresh()
        self.assertEqual(s['removed'], 1)
        self.assertEqual(len(idx.payload()['sessions']), 4)
        # a second start reads everything from the cache
        idx2 = self.index()
        s = idx2.refresh()
        self.assertEqual((s['files'], s['parsed']), (4, 0))
        self.assertEqual(len(idx2.payload()['sessions']), 4)

    def test_broken_cache_is_rebuilt(self):
        self.make(2)
        os.makedirs(self.cache)
        with open(os.path.join(self.cache, 'index.db'), 'w') as fh:
            fh.write('this is not a database')
        idx = self.index()
        s = idx.refresh()
        self.assertEqual(s['parsed'], 2)
        self.assertEqual(len(idx.payload()['sessions']), 2)

    def test_payload_shape(self):
        ids = self.make(3)
        idx = self.index()
        idx.refresh()
        p = idx.payload()
        self.assertEqual(sorted(p), sorted(['sessions', 'edges', 'projects', 'home', 'defaultCwd', 'generation', 'indexedAt', 'stats', 'errors']))
        s = p['sessions'][0]
        for k in ('id', 'title', 'project', 'projectLabel', 'cwd', 'kind', 'start', 'end', 'prompts', 'replies', 'msgs', 'keywords', 'about', 'commands', 'jira', 'linkCounts', 'mtime', 'size'):
            self.assertIn(k, s)
        self.assertEqual([x['id'] for x in p['sessions']], ids)   # oldest first
        self.assertEqual(s['jira'], ['ACME-7000'])
        self.assertIn('→', s['about'])                         # "what was asked -> how it ended"
        self.assertEqual(p['projects'][0]['label'], 'demo')
        d = idx.detail(ids[0])
        self.assertEqual(d['links']['jira'][0]['url'], 'https://example.atlassian.net/browse/ACME-7000')
        self.assertEqual(d['firstPrompt'], 'Question 0 about pineapple budgets and ACME-7000')
        self.assertFalse(d['cwdExists'])
        self.assertIsNone(idx.detail('nope'))

    def test_search(self):
        ids = self.make(4)
        idx = self.index()
        idx.refresh()
        r = idx.search('unique2word')
        self.assertEqual([x['id'] for x in r['results']], [ids[2]])
        self.assertIn('Unique2word', r['results'][0]['snippet'])   # snippet keeps the original capitals
        self.assertEqual(idx.search('BANANA forecast')['total'], 4)            # every word must appear, any case
        self.assertEqual(idx.search('"banana forecast" unique3word')['total'], 1)
        self.assertEqual(idx.search('"forecast banana"')['total'], 0)          # quotes keep the phrase together
        self.assertEqual(idx.search('zzzz')['total'], 0)
        self.assertEqual(idx.search('   ')['total'], 0)

    def test_link_labels(self):
        self.assertEqual(indexer.label_url('https://example.atlassian.net/browse/ACME-12', 'jira'), 'ACME-12')
        self.assertEqual(indexer.label_url('https://example.atlassian.net/jira/software/c/projects/ACME/boards/45', 'jira'), 'Jira board 45')
        self.assertTrue(indexer.label_url('https://acme.slack.com/archives/C01ABCDEF12/p1792671625227929', 'slack').startswith('Slack message'))
        self.assertEqual(indexer.label_url('https://app.notion.com/p/acme/QA-export-flow-40131fce868381d8be71c35420104074', 'notion'), 'Notion · QA export flow')
        self.assertEqual(indexer.label_url('https://app.notion.com/p/x', 'notion', 'Sprint 21 page'), 'Notion · Sprint 21 page')
        self.assertEqual(indexer.classify_url('https://claude.ai/artifact/abc'), 'artifact')
        self.assertIsNone(indexer.classify_url('http://127.0.0.1:7788/x'))
        self.assertEqual(indexer.iso_to_ms('2026-10-22T11:14:58.900Z'), 1792667698900)
        self.assertIsNone(indexer.iso_to_ms('garbage'))
        self.assertEqual(indexer.norm_cmd('/my-plugin:release-notes'), '/release-notes')
        self.assertEqual(indexer.norm_cmd('.claude/worktrees/x:prep'), '/prep')
        self.assertEqual(indexer.norm_cmd('daily-digest'), '/daily-digest')
        self.assertEqual(indexer.norm_cmd(''), '')
        self.assertEqual(indexer.encode_cwd('/home/a.b/My Work/.claude'), '-home-a-b-My-Work--claude')


if __name__ == '__main__':
    unittest.main(verbosity=2)
