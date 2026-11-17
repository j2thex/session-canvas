"""Saving the board (state.json) and building the commands that open Claude sessions.

Nothing here opens Terminal or starts Claude: the "claude" program is replaced by a tiny script that
only writes down the arguments it was given.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import server  # noqa: E402

SID = '91e71eb1-71a5-46d7-8ff6-91e49599f5a5'

# A note that would do damage if any part of it ever reached a shell.
NASTY = ('He said "hi" and \'bye\'\n'
         '$(touch {marker}) `touch {marker}` ; touch {marker} && rm -rf ~ | cat > {marker}\n'
         '\\ back\\slash \\n $HOME ${{PATH}} !history *.md ~ # not a comment\n'
         '\ttab, emoji \U0001f355, accents café, percent %s %d, <tag> & ampersand\n'
         "'; touch {marker}; echo '\n"
         'last line')


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='canvas-test-')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------- state.json

class StatePersistence(TempCase):
    def path(self):
        return os.path.join(self.tmp, 'state.json')

    def test_round_trip_survives_a_restart(self):
        s = server.StateStore(self.path())
        self.assertEqual(s.get()['rev'], 0)
        note = {'id': 'n1', 'text': 'Line 1\n"quoted" \U0001f355 café', 'color': 'pink', 'w': 220, 'h': 150, 'attach': SID, 'dx': 280, 'dy': -10, 'pos': {'tree': {'x': 1.5, 'y': -20}}}
        patch = {
            'view': {'layout': 'timeline', 'colorBy': 'kind', 'theme': 'light', 'cams': {'timeline': {'x': 10.5, 'y': -3, 'z': 0.62}},
                     'filters': {'kinds': {'auto': False}, 'projects': [], 'from': 1794000000000, 'to': None, 'commands': ['/morning'], 'showHidden': False}},
            'positions': {SID: {'x': 100, 'y': 200}},
            'order': {'proj|you|2026-11-12': [SID, 'other']},
            'edges': [{'id': 'm:a:b', 'from': 'a', 'to': 'b', 'kind': 'manual'}],
            'removedEdges': ['a:x:y'],
            'notes': [note],
            'titles': {SID: 'My own title'}, 'labels': {SID: 'important'}, 'colors': {SID: '#ff8a3d'},
            'hidden': ['h1'], 'collapsed': ['c1'], 'settings': {'terminal': 'Ghostty'},
        }
        rev = s.patch(patch)
        self.assertEqual(rev, 1)
        again = server.StateStore(self.path()).get()          # a fresh start reads the file
        for k, v in patch.items():
            self.assertEqual(again[k], v, k)
        self.assertEqual(again['rev'], 1)
        with open(self.path(), encoding='utf-8') as fh:
            self.assertEqual(json.load(fh)['notes'][0]['text'], note['text'])

    def test_partial_patch_keeps_the_rest(self):
        s = server.StateStore(self.path())
        s.patch({'titles': {'a': 'A'}, 'hidden': ['x']})
        s.patch({'hidden': []})
        st = s.get()
        self.assertEqual((st['titles'], st['hidden'], st['rev']), ({'a': 'A'}, [], 2))

    def test_settings_merge_so_an_old_tab_cannot_wipe_them(self):
        s = server.StateStore(self.path())
        s.patch({'settings': {'terminal': 'Ghostty', 'reportFolders': ['/r'], 'remindMin': 30}})
        s.patch({'settings': {'terminal': 'iTerm', 'waitOpen': True}})      # an older page that knows only two settings
        s.patch({'settings': {'remindMin': None}})                          # None removes one
        self.assertEqual(server.StateStore(self.path()).get()['settings'],
                         {'terminal': 'iTerm', 'reportFolders': ['/r'], 'waitOpen': True})

    def test_rejects_unknown_keys_and_wrong_shapes(self):
        s = server.StateStore(self.path())
        for bad in ({}, None, {'nope': 1}, {'notes': {}}, {'titles': []}, {'view': 'x'}, {'rev': 5}):
            with self.assertRaises(server.UserError):
                s.patch(bad)
        self.assertEqual(s.get()['rev'], 0)
        self.assertFalse(os.path.exists(self.path()))         # nothing was written

    def test_writes_are_atomic_and_leave_no_temp_files(self):
        s = server.StateStore(self.path())
        errors = []

        def writer(i):
            try:
                for j in range(25):
                    s.patch({'titles': {'k%d' % i: 'v%d' % j}, 'notes': [{'id': 'n', 'text': 'x' * 2000}]})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    if os.path.exists(self.path()):
                        with open(self.path(), encoding='utf-8') as fh:
                            json.load(fh)                      # never a half-written file
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)] + [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(s.get()['rev'], 150)
        self.assertEqual(server.StateStore(self.path()).get()['rev'], 150)
        left = [n for n in os.listdir(self.tmp) if '.tmp-' in n]
        self.assertEqual(left, [])

    def test_recovers_from_a_damaged_file(self):
        s = server.StateStore(self.path())
        s.patch({'titles': {'a': 'first'}})
        s._last_bak = 0
        s.patch({'titles': {'a': 'second'}})                   # the backup now holds "first"
        with open(self.path(), 'w') as fh:
            fh.write('{"titles": {"a": "sec')                  # simulate a damaged file
        s2 = server.StateStore(self.path())
        self.assertEqual(s2.get()['titles'], {'a': 'first'})
        self.assertTrue(s2.recovered)
        self.assertTrue(any('.broken-' in n for n in os.listdir(self.tmp)))   # the damaged copy is kept
        os.remove(self.path())
        os.remove(self.path() + '.bak')
        self.assertEqual(server.StateStore(self.path()).get()['titles'], {})   # nothing at all -> clean start

    def test_ignores_wrong_types_in_an_old_file(self):
        with open(self.path(), 'w') as fh:
            json.dump({'notes': 'oops', 'titles': {'a': 'b'}, 'rev': 'x', 'extra': 1}, fh)
        st = server.StateStore(self.path()).get()
        self.assertEqual((st['notes'], st['titles'], st['rev']), ([], {'a': 'b'}, 0))
        self.assertNotIn('extra', st)


# ---------------------------------------------------------------------------------------- opening sessions

FAKE_CLAUDE = '''#!/usr/bin/python3
import json, os, sys
json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(),
           "env": sorted(k for k in os.environ if k.startswith("CLAUDE") or k == "AI_AGENT")},
          open(os.environ["FAKE_OUT"], "w"))
'''


class Spawn(TempCase):
    def setUp(self):
        super(Spawn, self).setUp()
        self.work = os.path.realpath(os.path.join(self.tmp, 'my work (folder) $x'))     # a folder name with spaces and specials
        self.other = os.path.realpath(os.path.join(self.tmp, "it's other"))
        os.makedirs(self.work)
        os.makedirs(self.other)
        self.claude = os.path.join(self.tmp, 'fake claude')
        with open(self.claude, 'w') as fh:
            fh.write(FAKE_CLAUDE)
        os.chmod(self.claude, 0o755)
        self.sp = server.Spawner(os.path.join(self.tmp, 'launch dir'), claude_bin=self.claude, default_cwd=self.work, dry_run=True)
        self.marker = os.path.join(self.tmp, 'PWNED')
        self.out = os.path.join(self.tmp, 'out.json')

    def plan(self, **req):
        return self.sp.plan(req, session_cwd=req.pop('_cwd', self.other), known_cwds=[self.other], terminal=req.pop('_terminal', 'Terminal'),
                            fallback_cwd=req.pop('_fallback', None))

    def run_launcher(self, plan, extra_env=None):
        """Run the launcher exactly as written, with the fake claude; returns what claude received."""
        env = {'PATH': '/usr/bin:/bin', 'HOME': self.tmp, 'FAKE_OUT': self.out}
        env.update(extra_env or {})
        if os.path.exists(self.out):
            os.remove(self.out)
        p = subprocess.run(['/bin/zsh', plan['launcher']], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        with open(self.out) as fh:
            return json.load(fh)

    def test_resume_fork_new(self):
        p = self.plan(action='resume', sessionId=SID)
        self.assertEqual(p['argv'], [self.claude, '--resume', SID])
        self.assertEqual(self.run_launcher(p), {'argv': ['--resume', SID], 'cwd': self.other, 'env': []})
        self.assertIn("claude --resume " + SID, p['command'])
        self.assertTrue(p['command'].startswith("cd '"))          # the folder (it has a quote in its name) is quoted
        p = self.plan(action='fork', sessionId=SID)
        self.assertEqual(self.run_launcher(p)['argv'], ['--resume', SID, '--fork-session'])
        p = self.plan(action='new', cwd=self.other)
        got = self.run_launcher(p)
        self.assertEqual((got['argv'], got['cwd']), ([], self.other))
        p = self.plan(action='new')                                # no folder given -> the work folder
        self.assertEqual(self.run_launcher(p)['cwd'], self.work)
        self.assertEqual(stat.S_IMODE(os.stat(p['launcher']).st_mode), 0o700)

    def test_nasty_note_arrives_as_one_untouched_argument_and_runs_nothing(self):
        note = NASTY.format(marker=self.marker)
        for req in ({'action': 'note_new'}, {'action': 'note_resume', 'sessionId': SID}, {'action': 'note_resume', 'sessionId': SID, 'fork': True}):
            p = self.plan(note=note, **req)
            got = self.run_launcher(p)
            self.assertEqual(got['argv'][-1], note)                # byte for byte: quotes, $(), backticks, newlines, backslashes
            head = got['argv'][:-1]
            self.assertEqual(head, {'note_new': []}.get(req['action'], ['--resume', SID] + (['--fork-session'] if req.get('fork') else [])))
            self.assertFalse(os.path.exists(self.marker), 'part of the note was executed!')
            self.assertNotIn('touch', p['script'])                 # the note is not written into the launcher…
            self.assertIn('"$(cat ', p['script'])                  # …it is read from a file as a single argument
            self.assertEqual(stat.S_IMODE(os.stat(p['promptFile']).st_mode), 0o600)
            # the paste-able one-liner is safe too: run it through a shell with the fake claude first in PATH
            bindir = os.path.join(self.tmp, 'bin')
            os.makedirs(bindir, exist_ok=True)
            link = os.path.join(bindir, 'claude')
            if not os.path.exists(link):
                os.symlink(self.claude, link)
            os.remove(self.out)
            r = subprocess.run(['/bin/zsh', '-c', p['command']], env={'PATH': bindir + ':/usr/bin:/bin', 'HOME': self.tmp, 'FAKE_OUT': self.out},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr.decode())
            with open(self.out) as fh:
                self.assertEqual(json.load(fh)['argv'][-1], note)
            self.assertFalse(os.path.exists(self.marker))

    def test_notes_that_look_like_options_or_subcommands(self):
        self.assertEqual(server.safe_prompt('- [ ] first\n- [ ] second'), '\n- [ ] first\n- [ ] second')   # not read as an option
        self.assertEqual(server.safe_prompt('--dangerously-skip-permissions'), '\n--dangerously-skip-permissions')
        self.assertEqual(server.safe_prompt('update'), 'update ')                                           # not read as `claude update`
        self.assertEqual(server.safe_prompt('mcp'), 'mcp ')
        self.assertEqual(server.safe_prompt('/retro'), '/retro')                                            # slash commands pass as they are
        self.assertEqual(server.safe_prompt('fix the bug'), 'fix the bug')
        self.assertEqual(server.safe_prompt('line one\r\nline two\r\n\n'), 'line one\nline two')
        self.assertEqual(server.safe_prompt('a\x00b c'), 'ab c')
        for bad in ('', '   \n ', None, 5, 'x' * (server.MAX_NOTE + 1)):
            with self.assertRaises(server.UserError):
                server.safe_prompt(bad)
        got = self.run_launcher(self.plan(action='note_new', note='--help'))
        self.assertEqual(got['argv'], ['\n--help'])                # one argument that does not start with "-"

    def test_session_environment_is_not_inherited(self):
        p = self.plan(action='resume', sessionId=SID)
        got = self.run_launcher(p, {'CLAUDECODE': '1', 'CLAUDE_CODE_ENTRYPOINT': 'cli', 'CLAUDE_CODE_SSE_PORT': '1', 'AI_AGENT': 'x',
                                    'CLAUDE_CODE_PLUGIN_DIRS': '/mods'})
        self.assertEqual(got['env'], ['CLAUDE_CODE_PLUGIN_DIRS'])  # only the sidebar setting survives
        env = server.clean_env()
        self.assertFalse(any((k.startswith('CLAUDE') and k != 'CLAUDE_CODE_PLUGIN_DIRS') or k == 'AI_AGENT' for k in env))

    def test_rejects_bad_requests(self):
        cases = [
            dict(action='rm -rf'), dict(action='resume'), dict(action='resume', sessionId='not-an-id'),
            dict(action='resume', sessionId=SID + '; touch x'), dict(action='fork', sessionId='../../etc/passwd'),
            dict(action='new', cwd='/etc'), dict(action='new', cwd='relative/path'), dict(action='new', cwd=self.tmp),
            dict(action='note_new', note=''), dict(action='note_new'), dict(action='note_resume', sessionId=SID, note='  '),
        ]
        for req in cases:
            with self.assertRaises(server.UserError, msg=str(req)):
                self.plan(**req)
        with self.assertRaises(server.UserError):                  # a session the index does not know
            self.sp.plan({'action': 'resume', 'sessionId': SID}, session_cwd=None)
        with self.assertRaises(server.UserError):                  # its folder is gone and there is no fallback
            self.sp.plan({'action': 'resume', 'sessionId': SID}, session_cwd=os.path.join(self.tmp, 'gone'))
        p = self.sp.plan({'action': 'resume', 'sessionId': SID}, session_cwd=os.path.join(self.tmp, 'gone'), fallback_cwd=self.work)
        self.assertEqual(p['cwd'], self.work)
        self.assertEqual(len(p['warnings']), 1)

    def test_how_the_window_is_opened(self):
        p = self.plan(action='resume', sessionId=SID)
        o = p['open']
        self.assertEqual(o[0], 'osascript')
        script = ' '.join(o)
        self.assertIn('tell application "Terminal" to do script "/bin/zsh -l ', script)
        self.assertIn('tell application "Terminal" to activate', script)
        # the launcher path has a space: quoted for the shell, and the AppleScript string stays balanced
        line = [a for a in o if 'do script' in a][0]
        inner = line.split('do script ', 1)[1]
        self.assertTrue(inner.startswith('"') and inner.rstrip().endswith('"') or ' in window 1' in inner)
        self.assertIn("'" + p['launcher'] + "'", line)
        self.assertEqual(server.applescript_string('a "b" \\ c'), '"a \\"b\\" \\\\ c"')
        g = self.plan(action='resume', sessionId=SID, _terminal='Ghostty')
        self.assertEqual(g['open'][:4], ['open', '-na', 'Ghostty.app', '--args'])
        self.assertEqual(g['open'][-1], g['launcher'])
        i = self.plan(action='resume', sessionId=SID, _terminal='iTerm')
        self.assertEqual(i['open'][0], 'osascript')
        self.assertIn('tell application "iTerm"', ' '.join(i['open']))
        self.assertIn('create window with default profile command "/bin/zsh -l ', ' '.join(i['open']))
        self.assertIn("'" + i['launcher'] + "'", ' '.join(i['open']))
        for x in (p, g, i):
            self.assertNotIn('ghostty-tint', x['script'])          # no personal shell files are sourced

    def test_old_launchers_are_cleaned_up(self):
        p = self.plan(action='resume', sessionId=SID)
        old = os.path.join(os.path.dirname(p['launcher']), 'old.sh')
        with open(old, 'w') as fh:
            fh.write('x')
        os.utime(old, (1, 1))
        self.plan(action='resume', sessionId=SID)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(p['launcher']))


class LauncherHook(unittest.TestCase):
    def test_before_session_file_is_sourced_only_when_it_exists(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix='canvas-hook-'))
        try:
            work = os.path.join(tmp, 'work')
            os.makedirs(work)
            sp = server.Spawner(os.path.join(tmp, 'data', 'cache', 'launch'), claude_bin='/bin/echo', default_cwd=work, dry_run=True)
            with open(sp.plan({'action': 'new'})['launcher']) as fh:
                self.assertNotIn('before-session', fh.read())
            hook = os.path.join(tmp, 'data', 'before-session.zsh')
            with open(hook, 'w') as fh:
                fh.write('export CANVAS_HOOK=1\n')
            with open(sp.plan({'action': 'new'})['launcher']) as fh:
                text = fh.read()
            self.assertIn('[[ -r %s ]] && source %s\n' % (hook, hook), text)
            self.assertLess(text.index('before-session'), text.index('exec '))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
