"""The updater (nothing here touches the network or a real install) and the optional Advanced settings.

    /usr/bin/python3 -m unittest app/tests/test_update.py -v
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
PKG = os.path.dirname(APP)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)
import server  # noqa: E402
import updater  # noqa: E402
from test_api import ApiCase  # noqa: E402


def make_zip(path, version, top=None, files=None, skip=()):
    """A release zip made from this checkout (the files a real one holds), saying it is `version`."""
    top = top or 'session-canvas-%s' % version
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel in ('install.sh', 'uninstall.sh', 'README.md', 'LICENSE', 'CHANGELOG.md', 'bin/session-canvas'):
            if rel not in skip:
                zf.write(os.path.join(PKG, rel), top + '/' + rel)
        zf.writestr(top + '/VERSION', version + '\n')
        for base, _dirs, names in os.walk(APP):
            if 'tests' in base or '__pycache__' in base:
                continue
            for n in names:
                full = os.path.join(base, n)
                rel = os.path.relpath(full, PKG)
                if rel not in skip:
                    zf.write(full, top + '/' + rel)
        for name, text in (files or {}).items():
            zf.writestr(name, text)
    return path


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.newer('1.2.0', '1.0.1'))
        self.assertTrue(updater.newer('v1.10.0', '1.9.9'))
        self.assertTrue(updater.newer('1.2.1', '1.2'))
        self.assertFalse(updater.newer('1.2.0', '1.2.0'))
        self.assertFalse(updater.newer('1.2', '1.2.0'))
        self.assertFalse(updater.newer('1.1.9', '1.2.0'))
        self.assertFalse(updater.newer('nightly', '1.2.0'))           # not a version: never offered
        self.assertFalse(updater.newer('', '1.2.0'))

    def test_latest_release_reads_the_api_answer(self):
        api = {'tag_name': 'v1.3.0', 'html_url': 'https://github.com/x/y/releases/tag/v1.3.0',
               'assets': [{'name': 'notes.txt', 'browser_download_url': 'https://github.com/x/notes.txt'},
                          {'name': 'session-canvas-1.3.0-20270101.zip', 'browser_download_url': 'https://github.com/x/y/z.zip'}]}
        rel = updater.latest_release(fetch=lambda url, t, n: json.dumps(api).encode())
        self.assertEqual((rel['version'], rel['tag'], rel['url']), ('1.3.0', 'v1.3.0', 'https://github.com/x/y/z.zip'))
        api['assets'] = []                                            # no zip attached: GitHub's own zip of the tag
        rel = updater.latest_release(fetch=lambda url, t, n: json.dumps(api).encode())
        self.assertTrue(rel['url'].endswith('/archive/refs/tags/v1.3.0.zip'))
        with self.assertRaises(updater.UpdateError):
            updater.latest_release(fetch=lambda url, t, n: b'{"message": "Not Found"}')
        with self.assertRaises(updater.UpdateError):
            updater.latest_release(fetch=lambda url, t, n: b'<html>')


class ZipCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='canvas-zip-')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def z(self, **kw):
        return make_zip(os.path.join(self.tmp, 'r.zip'), kw.pop('version', '9.9.9'), **kw)

    def test_a_proper_zip_passes(self):
        self.assertEqual(updater.check_zip(self.z(), '9.9.9'), 'session-canvas-9.9.9')
        self.assertEqual(updater.check_zip(self.z(top='j2thex-session-canvas-abc123'), 'v9.9.9'), 'j2thex-session-canvas-abc123')

    def test_wrong_zips_are_refused(self):
        bad = [dict(skip=('install.sh',)), dict(skip=('app/server.py',)), dict(skip=('bin/session-canvas',)),
               dict(files={'other-top/file.txt': 'x'}), dict(files={'session-canvas-9.9.9/../../evil.sh': 'x'}),
               dict(files={'/etc/evil': 'x'})]
        for kw in bad:
            with self.assertRaises(updater.UpdateError, msg=str(kw)):
                updater.check_zip(self.z(**kw), '9.9.9')
        with self.assertRaises(updater.UpdateError):
            updater.check_zip(self.z(version='9.9.8'), '9.9.9')       # the zip is not the version the release names
        p = os.path.join(self.tmp, 'not.zip')
        with open(p, 'w') as fh:
            fh.write('<html>rate limited</html>')
        with self.assertRaises(updater.UpdateError):
            updater.check_zip(p)

    def test_a_link_inside_the_zip_is_refused(self):
        p = self.z()
        with zipfile.ZipFile(p, 'a') as zf:
            info = zipfile.ZipInfo('session-canvas-9.9.9/app/link')
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, '/etc/passwd')
        with self.assertRaises(updater.UpdateError):
            updater.check_zip(p, '9.9.9')


class Checker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='canvas-chk-')
        self.path = os.path.join(self.tmp, 'update.json')
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def checker(self, answer, **kw):
        def fetch():
            self.calls.append(1)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return updater.Checker(self.path, '1.2.0', fetch=fetch, **kw)

    def wait(self, c):
        deadline = time.time() + 5
        while c.busy and time.time() < deadline:
            time.sleep(0.01)

    def test_looks_once_then_remembers_for_a_day(self):
        c = self.checker({'version': '1.3.0', 'page': 'https://x'})
        first = c.info()
        self.assertEqual((first['available'], first['latest']), (False, None))      # nothing known yet, never blocks
        self.wait(c)
        again = c.info()
        self.assertEqual((again['available'], again['latest']), (True, '1.3.0'))
        self.wait(c)
        c2 = self.checker({'version': '1.4.0'})                                     # a restart: the answer is on disk
        self.assertEqual(c2.info()['latest'], '1.3.0')
        self.assertEqual(len(self.calls), 1)                                        # one look, not three
        with open(self.path) as fh:
            d = json.load(fh)
        d['triedAt'] -= 25 * 3600
        with open(self.path, 'w') as fh:
            json.dump(d, fh)
        c2.info()
        self.wait(c2)
        self.assertEqual(c2.info()['latest'], '1.4.0')                              # a day later it looks again

    def test_same_version_is_not_an_update(self):
        c = self.checker({'version': '1.2.0'})
        c.info()
        self.wait(c)
        self.assertFalse(c.info()['available'])

    def test_offline_is_silent(self):
        c = self.checker(OSError('no network'))
        self.assertFalse(c.info()['available'])
        self.wait(c)
        i = c.info()
        self.assertEqual((i['available'], i['latest']), (False, None))
        self.assertEqual(len(self.calls), 1)                                        # and it does not try again every time


class UpdateRun(unittest.TestCase):
    """The whole update against a throw-away HOME, with the 'download' read from a local zip."""

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix='canvas-upd-'))
        self.dest = os.path.join(self.home, '.session-canvas')
        self.env = dict(os.environ, HOME=self.home, PATH='/usr/bin:/bin:/usr/sbin:/sbin', TERM='dumb')
        self.env.pop('SESSION_CANVAS_HOME', None)
        self.env.pop('SESSION_CANVAS_DATA', None)
        p = subprocess.run([os.path.join(PKG, 'install.sh'), '--yes', '--no-autostart', '--no-start'], env=self.env,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout.decode())
        with open(os.path.join(self.dest, 'VERSION'), 'w') as fh:
            fh.write('1.0.1\n')                                                     # pretend this install is old
        self.state = os.path.join(self.dest, 'data', 'state.json')
        with open(self.state, 'w') as fh:
            json.dump({'version': 1, 'rev': 5, 'notes': [{'id': 'n1', 'text': 'keep me'}], 'settings': {'setupDone': True}}, fh)
        self.zip = make_zip(os.path.join(self.home, 'release.zip'), '9.9.9')
        self.said = []
        self._environ = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)

    def tearDown(self):
        subprocess.run([os.path.join(self.dest, 'bin', 'session-canvas'), 'stop'], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ.clear()
        os.environ.update(self._environ)
        shutil.rmtree(self.home, ignore_errors=True)

    def fetch(self, url, timeout=0, limit=0):
        with open(self.zip, 'rb') as fh:
            return fh.read()

    def rel(self, version='9.9.9', url=None):
        return {'version': version, 'tag': 'v' + version, 'url': url or updater.DOWNLOAD_PREFIXES[0] + 'releases/download/v%s/x.zip' % version}

    def test_update_keeps_the_board_and_leaves_shell_files_alone(self):
        zshrc = os.path.join(self.home, '.zshrc')
        with open(zshrc) as fh:
            before = fh.read()
        now = updater.update(self.dest, say=self.said.append, fetch=self.fetch, release=self.rel())
        self.assertEqual(now, '9.9.9')
        with open(os.path.join(self.dest, 'VERSION')) as fh:
            self.assertEqual(fh.read().strip(), '9.9.9')
        with open(self.state) as fh:
            self.assertEqual(json.load(fh)['notes'][0]['text'], 'keep me')
        with open(zshrc) as fh:
            self.assertEqual(fh.read(), before)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, 'app', 'updater.py')))
        self.assertTrue(os.access(os.path.join(self.dest, 'bin', 'session-canvas'), os.X_OK))
        self.assertIn('1.0.1 → 9.9.9', ' '.join(self.said))
        self.said[:] = []
        self.assertEqual(updater.update(self.dest, say=self.said.append, fetch=self.fetch, release=self.rel()), '9.9.9')
        self.assertIn('newest version', ' '.join(self.said))                        # a second run does nothing

    def test_a_bad_download_changes_nothing(self):
        with self.assertRaises(updater.UpdateError):                                # the zip is 9.9.9, the release says 9.9.8... newer than 1.0.1
            updater.update(self.dest, say=self.said.append, fetch=self.fetch, release=self.rel('9.9.8'))
        with self.assertRaises(updater.UpdateError):                                # a download from somewhere else is never fetched
            updater.update(self.dest, say=self.said.append, fetch=self.fetch, release=self.rel(url='https://example.com/x.zip'))
        with open(os.path.join(self.dest, 'VERSION')) as fh:
            self.assertEqual(fh.read().strip(), '1.0.1')
        with open(self.state) as fh:
            self.assertEqual(json.load(fh)['rev'], 5)

    def test_a_source_folder_is_never_updated(self):
        self.assertFalse(updater.is_install(PKG))
        self.assertTrue(updater.is_install(self.dest))
        with self.assertRaises(updater.UpdateError):
            updater.update(PKG, say=self.said.append, fetch=self.fetch, release=self.rel())

    def test_a_running_board_is_started_again_on_the_same_port(self):
        import socket
        import urllib.request
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        cmd = os.path.join(self.dest, 'bin', 'session-canvas')
        p = subprocess.run([cmd, '--dry-run', '--no-open', '--port', str(port)], env=self.env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout.decode())
        updater.update(self.dest, say=self.said.append, fetch=self.fetch, release=self.rel())
        with urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=10) as r:
            h = json.loads(r.read().decode())
        self.assertEqual((h['version'], h['dryRun']), ('9.9.9', True))
        with urllib.request.urlopen('http://127.0.0.1:%d/api/state' % port, timeout=10) as r:
            self.assertEqual(json.loads(r.read().decode())['notes'][0]['text'], 'keep me')
        p = subprocess.run([cmd, 'update', '--help'], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertIn('session-canvas update', p.stdout.decode())


class UpdateAndAdvancedApi(ApiCase):
    """A test server (dry run, like all of them): it never looks for updates, and reports are off until asked for."""

    def test_no_update_check_in_dry_run(self):
        self.assertFalse(self.app.start_updates())
        st, d, _ = self.get('/api/update?force=1')
        self.assertEqual(st, 200)
        self.assertEqual((d['enabled'], d['available'], d['latest'], d['current']), (False, False, None, server.VERSION))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'cache', 'update.json')))
        st, d, _ = self.post('/api/update', {})
        self.assertEqual(st, 200)
        self.assertTrue(d['ok'] is False or d['dryRun'])                             # from this source folder: refused; never run
        self.assertIsNone(self.app.update_proc)

    def test_update_needs_the_page_token_and_origin(self):
        import urllib.error
        import urllib.request
        for headers in ({'Content-Type': 'application/json'},
                        {'Content-Type': 'application/json', 'X-Canvas-Token': self.app.token, 'Origin': 'https://evil.example'}):
            req = urllib.request.Request('http://127.0.0.1:%d/api/update' % self.port, data=b'{}', headers=headers, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(cm.exception.code, 403)

    def test_reports_and_reminder_are_off_until_set(self):
        self.assertEqual(self.app.index.report_dirs, [])
        self.assertFalse(self.get('/api/sessions')[1]['statusOn'])
        self.assertEqual(self.get('/api/waiting')[1]['waiting'], [])
        self.assertIsNone(server.notify_sender(''))
        self.assertIsNone(server.notify_sender('relative/script.sh'))
        self.assertIsNone(server.notify_sender('/no/such/script.sh'))
        self.assertEqual(server.remind_minutes({}), 30)
        self.assertEqual(server.remind_minutes({'remindMin': 0}), 0)
        self.assertEqual(server.remind_minutes({'remindMin': 'soon'}), 30)
        # a report folder next to the sessions: off until the setting names it
        day = time.strftime('%Y-%m-%d', time.localtime(time.time()))
        d = os.path.join(self.work, 'reports', day)
        os.makedirs(d)
        rep = os.path.join(d, 'ask.md')
        with open(rep, 'w') as fh:
            fh.write('status: question\nname: Ask\noutcome: two options\nleft: A or B?\n')
        with open(os.path.join(d, 'runs.tsv'), 'w') as fh:
            fh.write('%s\tAsk\tjob\tsonnet\t-\t10:30\t%s\n' % (self.ids[0][:8], rep))
        self.app.rescan()
        self.assertEqual(self.get('/api/waiting')[1]['waiting'], [])
        st, _, _ = self.post('/api/state', {'patch': {'settings': {'setupDone': True, 'reportFolders': [os.path.join(self.work, 'reports'), '/no/such/folder', 7]}}})
        self.assertEqual(st, 200)
        self.assertTrue(self.get('/api/sessions')[1]['statusOn'])                   # on at once, no restart
        w = self.get('/api/waiting')[1]['waiting']
        self.assertEqual([(x['id'], x['state'], x['file']) for x in w], [(self.ids[0], 'question', os.path.join('reports', day, 'ask.md'))])
        self.post('/api/state', {'patch': {'settings': {'setupDone': True, 'reportFolders': None}}})   # settings merge: None removes one
        self.assertFalse(self.get('/api/sessions')[1]['statusOn'])
        self.assertEqual(self.get('/api/waiting')[1]['waiting'], [])

    def test_the_reminder_command_gets_one_argument(self):
        out = os.path.join(self.tmp, 'said.txt')
        script = os.path.join(self.tmp, 'notify me.sh')
        with open(script, 'w') as fh:
            fh.write('print -r -- "$#|$1" > %s\n' % out)                            # not executable: run with zsh
        send = server.notify_sender(script)
        send('2 cards waiting on you: "a" $(touch /tmp/never) ; b')
        with open(out) as fh:
            self.assertEqual(fh.read().strip(), '1|2 cards waiting on you: "a" $(touch /tmp/never) ; b')


if __name__ == '__main__':
    unittest.main(verbosity=2)
