"""install.sh, the session-canvas command and uninstall.sh, run in a throw-away HOME (nothing real is touched).

    /usr/bin/python3 -m unittest app/tests/test_install.py -v
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(os.path.dirname(HERE))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Install(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp(prefix='canvas-home-'))
        self.dest = os.path.join(self.home, '.session-canvas')
        self.env = {'HOME': self.home, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'TERM': 'dumb'}

    def tearDown(self):
        self.run_cmd([os.path.join(self.dest, 'bin', 'session-canvas'), 'stop'], check=False)
        shutil.rmtree(self.home, ignore_errors=True)

    def run_cmd(self, argv, check=True, extra=None):
        env = dict(self.env)
        env.update(extra or {})
        if not os.path.exists(argv[0]):
            return None
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        out = p.stdout.decode('utf-8', 'replace')
        if check:
            self.assertEqual(p.returncode, 0, out)
        return out

    def install(self, *extra):
        return self.run_cmd([os.path.join(PKG, 'install.sh'), '--yes', '--no-autostart', '--no-start'] + list(extra))

    def test_install_upgrade_uninstall(self):
        out = self.install()
        self.assertIn('Installed in', out)
        for f in ('app/server.py', 'app/indexer.py', 'app/web/index.html', 'app/web/setup.js', 'bin/session-canvas', 'uninstall.sh', 'VERSION', 'README.md', 'LICENSE'):
            self.assertTrue(os.path.exists(os.path.join(self.dest, f)), f)
        self.assertFalse(os.path.exists(os.path.join(self.dest, 'app', 'tests')))           # tests are not installed
        link = os.path.join(self.home, '.local', 'bin', 'session-canvas')
        self.assertEqual(os.path.realpath(link), os.path.join(self.dest, 'bin', 'session-canvas'))
        with open(os.path.join(self.home, '.zshrc')) as fh:
            self.assertIn('session-canvas: PATH', fh.read())
        self.assertFalse(os.path.exists(os.path.join(self.home, 'Library', 'LaunchAgents', 'com.sessioncanvas.server.plist')))
        self.assertEqual(oct(os.stat(os.path.join(self.dest, 'data')).st_mode & 0o777), '0o700')

        # the board data survives an upgrade
        state = os.path.join(self.dest, 'data', 'state.json')
        with open(state, 'w') as fh:
            json.dump({'version': 1, 'rev': 3, 'notes': [{'id': 'n1', 'text': 'keep me'}], 'settings': {'setupDone': True}}, fh)
        out = self.install()
        self.assertIn('Upgraded', out)
        with open(state) as fh:
            self.assertEqual(json.load(fh)['notes'][0]['text'], 'keep me')
        with open(os.path.join(self.home, '.zshrc')) as fh:
            self.assertEqual(fh.read().count('session-canvas: PATH'), 1)                     # added once only
        self.assertEqual([n for n in os.listdir(self.dest) if n.startswith('.install') or n.endswith('.old')], [])

        # the command: start (test mode), status, version, stop
        cmd = os.path.join(self.dest, 'bin', 'session-canvas')
        port = free_port()
        out = self.run_cmd([cmd, '--dry-run', '--no-open', '--port', str(port)])
        self.assertIn('started: http://127.0.0.1:%d/' % port, out)
        with urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=10) as r:
            h = json.loads(r.read().decode())
        self.assertTrue(h['dryRun'])
        with urllib.request.urlopen('http://127.0.0.1:%d/api/state' % port, timeout=10) as r:
            self.assertEqual(json.loads(r.read().decode())['notes'][0]['text'], 'keep me')    # it uses the kept data
        self.assertIn('is running', self.run_cmd([cmd, 'status']))
        with open(os.path.join(PKG, 'VERSION')) as fh:
            self.assertEqual(self.run_cmd([cmd, 'version']).strip(), fh.read().strip())
        self.assertIn('stopped', self.run_cmd([cmd, 'stop']))
        self.assertIn('not running', self.run_cmd([cmd, 'status'], check=False))

        # uninstall without --purge keeps the board data; --purge removes everything
        out = self.run_cmd([cmd, 'uninstall', '--yes'])
        self.assertIn('kept', out)
        self.assertFalse(os.path.exists(os.path.join(self.dest, 'app')))
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.exists(state))
        self.install()
        with open(state) as fh:
            self.assertEqual(json.load(fh)['notes'][0]['text'], 'keep me')                   # reinstall picks it up
        out = self.run_cmd([os.path.join(self.dest, 'uninstall.sh'), '--purge'])
        self.assertIn('board data removed', out)
        self.assertFalse(os.path.exists(self.dest))

    def test_refuses_bad_places_and_options(self):
        p = subprocess.run([os.path.join(PKG, 'install.sh'), '--nope'], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(p.returncode, 2)
        p = subprocess.run([os.path.join(PKG, 'install.sh'), '--yes', '--no-start', '--dir', PKG], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertNotEqual(p.returncode, 0)
        p = subprocess.run([os.path.join(PKG, 'uninstall.sh'), '--yes'], env=dict(self.env, SESSION_CANVAS_HOME=self.home),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertNotEqual(p.returncode, 0)                                                    # never removes a folder that is not an install
        self.assertTrue(os.path.isdir(self.home))

    def test_autostart_file(self):
        self.run_cmd([os.path.join(PKG, 'install.sh'), '--yes', '--autostart', '--no-start'])
        plist = os.path.join(self.home, 'Library', 'LaunchAgents', 'com.sessioncanvas.server.plist')
        self.assertTrue(os.path.exists(plist))
        out = subprocess.run(['/usr/bin/plutil', '-lint', plist], stdout=subprocess.PIPE).stdout.decode()
        self.assertIn('OK', out)
        with open(plist) as fh:
            self.assertIn(os.path.join(self.dest, 'app', 'server.py'), fh.read())
        self.run_cmd([os.path.join(PKG, 'install.sh'), '--yes', '--no-autostart', '--no-start'])
        self.assertFalse(os.path.exists(plist))


if __name__ == '__main__':
    unittest.main(verbosity=2)
