#!/usr/bin/python3
"""Session Canvas updater: get the newest release from GitHub and install it over this copy.

    session-canvas update            (the command; the board's "Update" button runs the same thing)
    /usr/bin/python3 app/updater.py check | update [--home <install folder>] [--force]

What `update` does
  1. asks GitHub's public API for the newest release of the project (no login needed);
  2. stops when this copy is already that version;
  3. downloads the release zip (from github.com only) into a temporary folder;
  4. checks it really is a Session Canvas zip: one top folder, no odd paths, install.sh + app/server.py +
     bin/session-canvas inside, and its VERSION is the version the release says it is;
  5. runs its install.sh without questions (your board data and settings in data/ are kept, shell files
     are not touched) and starts the board again if it was running.
Nothing else is sent anywhere: the only requests are the two GETs above.

Python 3.9 standard library only.
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

REPO = os.environ.get('SESSION_CANVAS_REPO') or 'j2thex/session-canvas'
API = os.environ.get('SESSION_CANVAS_API') or 'https://api.github.com/repos/%s/releases/latest' % REPO
DOWNLOAD_PREFIXES = ('https://github.com/%s/' % REPO, 'https://api.github.com/repos/%s/' % REPO)
MAX_ZIP = 30 * 1024 * 1024
DAY = 24 * 3600
NEEDED = ('install.sh', 'VERSION', 'app/server.py', 'app/indexer.py', 'app/web/index.html', 'bin/session-canvas')
PY = '/usr/bin/python3'


class UpdateError(Exception):
    """Something the person can read; the update stops and nothing was changed."""


def version_tuple(v):
    """'v1.2.0' -> (1, 2, 0). Anything that is not numbers and dots -> ()."""
    m = re.match(r'^v?(\d+(?:\.\d+){0,3})$', (v or '').strip())
    return tuple(int(x) for x in m.group(1).split('.')) if m else ()


def newer(latest, current):
    a, b = version_tuple(latest), version_tuple(current)
    if not a:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def is_install(home):
    """True for a folder made by install.sh (not a source checkout, which is updated with git)."""
    return (os.path.isfile(os.path.join(home, 'bin', 'session-canvas')) and os.path.isfile(os.path.join(home, 'app', 'server.py'))
            and not os.path.exists(os.path.join(home, '.git')) and not os.path.exists(os.path.join(home, 'install.sh')))


def read_version(home):
    try:
        with open(os.path.join(home, 'VERSION'), 'r', encoding='utf-8') as fh:
            return fh.read().strip()
    except OSError:
        return ''


def _get(url, timeout=15, limit=MAX_ZIP):
    req = urllib.request.Request(url, headers={'User-Agent': 'session-canvas-updater', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('The download is larger than expected; stopped.')
    return data


def latest_release(fetch=_get):
    """{'version', 'tag', 'url', 'notes'} of the newest release. Raises UpdateError / OSError when it cannot tell."""
    try:
        rel = json.loads(fetch(API, 15, 2 * 1024 * 1024).decode('utf-8'))
    except ValueError:
        raise UpdateError('GitHub answered with something unexpected.')
    tag = rel.get('tag_name') if isinstance(rel, dict) else None
    if not version_tuple(tag):
        raise UpdateError('No release was found.')
    url = None
    for a in rel.get('assets') or []:
        if re.match(r'^session-canvas-[\w.\-]+\.zip$', a.get('name') or ''):
            url = a.get('browser_download_url')
            break
    if not url:                                # a release without the zip attached: GitHub's own zip of the tag
        url = 'https://github.com/%s/archive/refs/tags/%s.zip' % (REPO, tag)
    return {'version': tag.lstrip('v'), 'tag': tag, 'url': url, 'page': rel.get('html_url') or ''}


class Checker(object):
    """Looks for a newer release at most once a day, in the background, and remembers the answer in a small
    file. Never raises: with no network the board simply shows no update note."""

    def __init__(self, path, current, fetch=None, every=DAY, retry=3600):
        self.path = path
        self.current = current
        self.fetch = fetch or latest_release
        self.every = every
        self.retry = retry                     # after a failed look (offline): try again after an hour
        self.lock = threading.Lock()
        self.busy = False

    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d):
        try:
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(d, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def check_now(self):
        d = self._load()
        d['triedAt'] = int(time.time())
        try:
            rel = self.fetch()
            d.update(checkedAt=d['triedAt'], latest=rel['version'], page=rel.get('page') or '', ok=True)
        except Exception:
            d['ok'] = False
        self._save(d)
        with self.lock:
            self.busy = False
        return d

    def info(self, force=False):
        """What is known now; starts a look in the background when the last one is old enough."""
        d = self._load()
        now = time.time()
        age = now - (d.get('triedAt') or 0)
        due = age > (self.every if d.get('ok') else self.retry)
        if force and age > 20:
            due = True
        if due:
            with self.lock:
                start = not self.busy
                self.busy = True
            if start:
                threading.Thread(target=self.check_now, name='update-check', daemon=True).start()
        latest = d.get('latest') or None
        return {'latest': latest, 'available': bool(latest and newer(latest, self.current)),
                'checkedAt': int(d.get('checkedAt') or 0) * 1000, 'checking': bool(due), 'page': d.get('page') or ''}


def check_zip(path, want_version=None):
    """The top folder of a proper Session Canvas zip. Raises UpdateError otherwise."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise UpdateError('The download is not a zip file.')
    with zf:
        names = zf.namelist()
        tops = set()
        total = 0
        for info in zf.infolist():
            n = info.filename
            if n.startswith('/') or '\\' in n or '..' in n.split('/') or (stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK):
                raise UpdateError('The zip holds a path it should not (%s).' % n[:80])
            total += info.file_size
            tops.add(n.split('/', 1)[0])
        if len(tops) != 1 or total > 10 * MAX_ZIP:
            raise UpdateError('The zip does not look like Session Canvas.')
        top = tops.pop()
        for need in NEEDED:
            if top + '/' + need not in names:
                raise UpdateError('The zip does not look like Session Canvas (%s is missing).' % need)
        version = zf.read(top + '/VERSION').decode('utf-8', 'replace').strip()
        if 'Session Canvas' not in zf.read(top + '/install.sh').decode('utf-8', 'replace')[:400]:
            raise UpdateError('The zip does not look like Session Canvas.')
        if want_version and version_tuple(version) != version_tuple(want_version):
            raise UpdateError('The zip says it is version %s, the release says %s.' % (version, want_version))
    return top


def server_info(home):
    """(running, port, dry_run) of the board that belongs to this install."""
    data = os.environ.get('SESSION_CANVAS_DATA') or os.path.join(home, 'data')
    try:
        with open(os.path.join(data, 'cache', 'server.json'), 'r', encoding='utf-8') as fh:
            d = json.load(fh)
        pid, port = int(d.get('pid') or 0), int(d.get('port') or 0)
        os.kill(pid, 0)
        with urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=3) as r:
            if json.loads(r.read().decode('utf-8')).get('app') == 'session-canvas':
                return True, port, bool(d.get('dryRun'))
    except Exception:
        pass
    return False, 0, False


def update(home, force=False, say=print, fetch=_get, release=None):
    """Install the newest release over `home`. Returns the version now installed."""
    home = os.path.realpath(os.path.expanduser(home))
    fresh = not os.path.exists(os.path.join(home, 'app', 'server.py'))
    if not fresh and not is_install(home):
        raise UpdateError('%s is a source folder, not an install. Update it with git.' % home)
    current = read_version(home)
    rel = release or latest_release()
    if not fresh and not force and not newer(rel['version'], current):
        say('Session Canvas %s is the newest version.' % (current or '?'))
        return current
    if not any(rel['url'].startswith(p) for p in DOWNLOAD_PREFIXES):
        raise UpdateError('The release points to a download outside the project (%s).' % rel['url'][:120])
    say('Downloading Session Canvas %s …' % rel['version'])
    tmp = tempfile.mkdtemp(prefix='session-canvas-update-')
    try:
        zpath = os.path.join(tmp, 'release.zip')
        with open(zpath, 'wb') as fh:
            fh.write(fetch(rel['url'], 120, MAX_ZIP))
        top = check_zip(zpath, rel['version'])
        out = os.path.join(tmp, 'unzipped')
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(out)
        src = os.path.join(out, top)
        for f in ('install.sh', 'uninstall.sh', os.path.join('bin', 'session-canvas'), 'make-release.sh'):
            if os.path.exists(os.path.join(src, f)):
                os.chmod(os.path.join(src, f), 0o755)
        was_running, port, dry = server_info(home)
        env = dict(os.environ)
        env.pop('SESSION_CANVAS_HOME', None)
        # an update never edits shell files; a first install may add ~/.local/bin to the PATH
        p = subprocess.run(['/bin/zsh', os.path.join(src, 'install.sh'), '--yes', '--no-start', '--dir', home] + ([] if fresh else ['--no-path']),
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=300)
        text = p.stdout.decode('utf-8', 'replace')
        if p.returncode != 0 and '--no-path' in text:      # a release older than this option
            p = subprocess.run(['/bin/zsh', os.path.join(src, 'install.sh'), '--yes', '--no-start', '--dir', home],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=300)
            text = p.stdout.decode('utf-8', 'replace')
        if p.returncode != 0:
            raise UpdateError('The installer stopped:\n' + text[-1500:])
        now = read_version(home)
        say('Updated %s → %s. Your board and settings are kept.' % (current or 'nothing', now) if not fresh else 'Installed %s in %s.' % (now, home))
        if was_running:
            cmd = [os.path.join(home, 'bin', 'session-canvas'), 'start', '--no-open', '--port', str(port)] + (['--dry-run'] if dry else [])
            env['SESSION_CANVAS_HOME'] = home
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=120)
            say(r.stdout.decode('utf-8', 'replace').strip() or 'Started again.')
            say('Reload the board in your browser (Cmd+R).')
        elif fresh:
            say('Start it with: %s' % os.path.join(home, 'bin', 'session-canvas'))
        return now
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Session Canvas updater')
    ap.add_argument('what', choices=('check', 'update'))
    ap.add_argument('--home', default=os.environ.get('SESSION_CANVAS_HOME') or os.path.join(os.path.expanduser('~'), '.session-canvas'))
    ap.add_argument('--force', action='store_true', help='install the newest release even when this copy is not older')
    args = ap.parse_args(argv)
    stamp = lambda s: print(s, flush=True)
    try:
        if args.what == 'check':
            rel = latest_release()
            cur = read_version(args.home)
            stamp('Installed: %s · newest: %s%s' % (cur or 'none', rel['version'],
                                                    ' · run: session-canvas update' if newer(rel['version'], cur) else ' · up to date'))
            return 0
        update(args.home, force=args.force, say=stamp)
        return 0
    except UpdateError as e:
        stamp('Update stopped: %s' % e)
        return 1
    except (OSError, subprocess.SubprocessError) as e:
        stamp('Update stopped: could not reach GitHub or run the installer (%s). Nothing was changed.' % e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
