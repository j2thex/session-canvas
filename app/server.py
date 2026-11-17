#!/usr/bin/python3
"""Session Canvas server: a local board of all your Claude Code sessions.

Start it with the `session-canvas` command (installed by install.sh), or by hand:
    /usr/bin/python3 app/server.py [--port 7788] [--dry-run]

What it does
  * Serves the board (app/web/) on http://127.0.0.1:<port>/ and nowhere else.
  * Reads Claude Code's session transcripts (~/.claude/projects/*/*.jsonl) through indexer.py. Read-only.
  * Keeps what you change on the board (positions, links, notes, names, colours, hidden cards, settings)
    in <data>/state.json, written atomically (temp file + rename) so a crash can't leave half a file.
    <data> is ~/.session-canvas/data unless SESSION_CANVAS_DATA says otherwise.
  * Opens Claude Code in a new terminal window when you press Resume / Fork / New session / Send note.

How a session is opened
  A small launcher script is written to <data>/cache/launch/ and the terminal is asked to run it.
  The launcher does:  cd <the session's folder> && exec claude <arguments>
      Resume              claude --resume <id>
      Fork                claude --resume <id> --fork-session        (a copy with a new id)
      New session         claude
      Note -> new         claude "<note>"
      Note -> existing    claude --resume <id> "<note>"             (the note becomes the next prompt)
  A note never touches a shell: it is saved to a file and passed as one argument with "$(cat file)".
  Two guards keep the CLI from misreading it: a note starting with "-" gets a leading newline (so it
  is not taken for an option) and a one-word note gets a trailing space (so "update" is not taken for
  the `claude update` sub-command).

Terminals: Terminal and iTerm are driven with osascript (macOS asks once for permission to control
them); Ghostty is started with `open -na Ghostty.app --args -e ...`, which needs no permission.

Dry run (--dry-run or CANVAS_DRY_RUN=1): the buttons never open a window; the server answers with the
exact command, launcher and terminal call it WOULD have run. A request can also ask for it
({"dryRun": true}), which is how "Copy command" works.

Going to a session that is already open (POST /api/focus, used by Resume on a running session)
  Claude Code lists every running session in ~/.claude/sessions/<pid>.json. From that pid we walk up the
  parent processes (`ps`) until we reach the terminal app that owns the window, then bring it forward:
      Ghostty    each window the Canvas opens is its own Ghostty process (`open -na`), so activating that
                 process by pid is exact and needs no permission. For a session inside the main Ghostty app
                 (several windows) we first ask Ghostty's own scripting to `focus` the terminal whose
                 title contains the session's title (a best effort: the answer says when the window may
                 be another one).
      Terminal   AppleScript picks the tab whose tty is the session's tty.
      iTerm      the app is brought to the front (the right tab is not picked).
  Background sessions (claude --bg) have no window, so the page falls back to the "already open" choices.

Status reports (optional, off until a report folder is set under ? -> Settings -> Advanced)
  A session can say where it stands in a small text file, <report folder>/<date>/<name>.md, that starts with:
      status: done | not-done | your-turn | question      (question = the person must answer or decide)
      name: ...    outcome: ...    left: ...
  and may hold, anywhere:
      sent: <link>                  what the card waited for was sent -> done
      replaces: slug, slug          this session took over from those -> their cards grey out
      replaced-by: slug             a newer session took over from this one
  The person can also press Done / Sent / Replaced by on a card (kept in state.json under "marks" and written into
  the report file itself; undo puts the report back if nobody changed it since).
  GET /api/waiting (add ?format=text for plain lines) lists every card that waits on the person, oldest
  first, so a script can read it instead of looking at the board.

Reminder (optional, off until a command is set under Settings -> Advanced)
  ONE line is handed to that command when cards have waited more than N minutes (default 30) without the
  person acting: once per card and report, between 08:00 and 20:00, never in dry-run mode. What was
  already sent is remembered in <cache>/pings.json; on the very first run everything already waiting is
  noted silently.

Updates (updater.py)
  At most once a day the server asks GitHub's public API for the newest release (never in dry-run mode
  or in the tests, silent when offline). The page shows "Update to vX"; POST /api/update runs
  `updater.py update`, which downloads the release zip, checks it and runs its install.sh. Your board
  data and settings are kept.

Safety: binds to 127.0.0.1 only; requests must carry the right Host; every change needs the page's
token and a same-origin Origin header (so another website can't press your buttons); nothing is sent
to the internet.

Python 3.9 standard library only.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import indexer  # noqa: E402
import updater  # noqa: E402

APP_NAME = 'Session Canvas'


def _read_version():
    for p in (os.path.join(HERE, 'VERSION'), os.path.join(os.path.dirname(HERE), 'VERSION')):
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                v = fh.read().strip()
                if v:
                    return v
        except OSError:
            pass
    return '0.0.0'


VERSION = _read_version()
WEB = os.path.join(HERE, 'web')
APP_HOME = os.path.dirname(HERE)              # the install folder (holds app/, bin/, VERSION, data/)
DATA_DIR = os.environ.get('SESSION_CANVAS_DATA') or os.path.join(os.path.expanduser('~'), '.session-canvas', 'data')
TERMINALS = ('Terminal', 'iTerm', 'Ghostty')
TERMINAL_APPS = {'Terminal': ('/System/Applications/Utilities/Terminal.app', '/Applications/Utilities/Terminal.app'),
                 'iTerm': ('/Applications/iTerm.app',), 'Ghostty': ('/Applications/Ghostty.app',)}


def find_claude():
    """Where the claude program is: CANVAS_CLAUDE_BIN, then PATH, then the usual install places."""
    env = os.environ.get('CANVAS_CLAUDE_BIN')
    if env:
        return env
    home = os.path.expanduser('~')
    cands = [shutil.which('claude'), os.path.join(home, '.local', 'bin', 'claude'), os.path.join(home, '.claude', 'local', 'claude'),
             '/opt/homebrew/bin/claude', '/usr/local/bin/claude']
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def installed_terminals():
    home = os.path.expanduser('~')
    out = []
    for t in TERMINALS:
        paths = list(TERMINAL_APPS[t]) + [os.path.join(home, 'Applications', os.path.basename(TERMINAL_APPS[t][0]))]
        if any(os.path.isdir(p) for p in paths):
            out.append(t)
    return out or ['Terminal']
SESSION_ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
MAX_BODY = 8 * 1024 * 1024
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_NOTE = 100000

STATE_KEYS = {
    'view': dict, 'positions': dict, 'order': dict, 'edges': list, 'removedEdges': list, 'notes': list,
    'titles': dict, 'labels': dict, 'colors': dict, 'hidden': list, 'collapsed': list, 'settings': dict,
    # what the person marked on a card: {session id: {'kind': 'done' | 'sent' | 'replaced', 'by': id, 'at': ms, 'sig': str}}
    'marks': dict,
}



def _atomic_write(path, text):
    tmp = '%s.tmp-%d-%d' % (path, os.getpid(), threading.get_ident())
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.replace(tmp, path)

class UserError(Exception):
    """A problem to show to the person in plain words (HTTP 400)."""


# ---- state.json ----------------------------------------------------------------------------------

def default_state():
    s = {'version': 1, 'rev': 0, 'savedAt': 0}
    for k, t in STATE_KEYS.items():
        s[k] = t()
    return s


class StateStore(object):
    """Everything the person changed on the board, in one JSON file, written atomically."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._last_bak = 0.0
        self.recovered = None
        self.state = self._load()

    def _read(self, path):
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError('state is not an object')
        return data

    def _load(self):
        base = default_state()
        data = None
        if os.path.exists(self.path):
            try:
                data = self._read(self.path)
            except (ValueError, OSError) as e:
                # keep the broken file for inspection, fall back to the backup
                broken = '%s.broken-%s' % (self.path, time.strftime('%Y%m%d-%H%M%S'))
                try:
                    shutil.copy2(self.path, broken)
                except OSError:
                    broken = None
                self.recovered = 'state.json could not be read (%s); used the backup. Broken copy: %s' % (e, broken)
        if data is None and os.path.exists(self.path + '.bak'):
            try:
                data = self._read(self.path + '.bak')
            except (ValueError, OSError):
                data = None
        if data:
            for k, t in STATE_KEYS.items():
                if isinstance(data.get(k), t):
                    base[k] = data[k]
            if isinstance(data.get('rev'), int):
                base['rev'] = data['rev']
            base['savedAt'] = data.get('savedAt') or 0
        return base

    def get(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def patch(self, patch):
        """Replace whole top-level keys (e.g. {'notes': [...]}), except settings, which are merged; returns the new revision."""
        if not isinstance(patch, dict) or not patch:
            raise UserError('Nothing to save.')
        for k, v in patch.items():
            if k not in STATE_KEYS:
                raise UserError('Unknown setting: %s' % k)
            if not isinstance(v, STATE_KEYS[k]):
                raise UserError('Wrong shape for %s.' % k)
        with self.lock:
            for k, v in patch.items():
                if k == 'settings' and isinstance(self.state.get('settings'), dict):
                    # merge, never replace: an older open tab must not wipe settings it doesn't know (None deletes a key)
                    merged = dict(self.state['settings'])
                    for sk, sv in v.items():
                        if sv is None:
                            merged.pop(sk, None)
                        else:
                            merged[sk] = sv
                    v = merged
                self.state[k] = v
            self.state['rev'] = int(self.state.get('rev') or 0) + 1
            self.state['savedAt'] = int(time.time() * 1000)
            self._write()
            return self.state['rev']

    def _write(self):
        d = os.path.dirname(self.path) or '.'
        os.makedirs(d, exist_ok=True)
        tmp = '%s.tmp-%d-%d' % (self.path, os.getpid(), threading.get_ident())
        try:
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(self.state, fh, ensure_ascii=False, indent=1, sort_keys=True)
                fh.write('\n')
                fh.flush()
                os.fsync(fh.fileno())
            now = time.time()
            if os.path.exists(self.path) and now - self._last_bak > 60:
                try:
                    shutil.copy2(self.path, self.path + '.bak')
                    self._last_bak = now
                except OSError:
                    pass
            os.replace(tmp, self.path)          # atomic on the same disk
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


# ---- opening sessions ----------------------------------------------------------------------------

def safe_prompt(note):
    """Turn note text into ONE safe command-line argument for claude (see the module docstring)."""
    if not isinstance(note, str):
        raise UserError('The note has no text.')
    s = note.replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')
    s = s.strip('\n').rstrip()
    if not s.strip():
        raise UserError('The note is empty: write something first.')
    if len(s) > MAX_NOTE:
        raise UserError('The note is too long to send (over %d characters).' % MAX_NOTE)
    if s[0] == '-':
        s = '\n' + s                  # not an option
    if re.match(r'^[A-Za-z][A-Za-z0-9_\-]*$', s):
        s = s + ' '                   # not a sub-command
    return s


def applescript_string(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def open_command(terminal, launcher):
    """The exact argv that opens a new window running the launcher."""
    if terminal == 'Ghostty':
        return ['open', '-na', 'Ghostty.app', '--args', '-e', '/bin/zsh', '-l', launcher]
    cmd = '/bin/zsh -l ' + shlex.quote(launcher)
    q = applescript_string(cmd)
    if terminal == 'iTerm':
        return ['osascript',
                '-e', 'tell application "iTerm"',
                '-e', '  create window with default profile command ' + q,
                '-e', '  activate',
                '-e', 'end tell']
    return ['osascript',
            '-e', 'if application "Terminal" is running then',
            '-e', '  tell application "Terminal" to do script ' + q,
            '-e', 'else',
            '-e', '  tell application "Terminal" to do script ' + q + ' in window 1',
            '-e', 'end if',
            '-e', 'tell application "Terminal" to activate']


class Spawner(object):
    def __init__(self, launch_dir, claude_bin=None, default_cwd=None, dry_run=False):
        self.launch_dir = launch_dir
        self.claude_bin = claude_bin or find_claude() or 'claude'
        self.default_cwd = default_cwd or os.path.expanduser('~')
        self.dry_run = dry_run

    def plan(self, req, session_cwd=None, known_cwds=(), terminal='Terminal', fallback_cwd=None, default_cwd=None):
        """Validate a request and write the launcher. Returns everything that would run. Opens nothing."""
        action = req.get('action')
        if action not in ('resume', 'fork', 'new', 'note_new', 'note_resume'):
            raise UserError('Unknown action.')
        sid = req.get('sessionId')
        warnings = []
        if action in ('resume', 'fork', 'note_resume'):
            if not isinstance(sid, str) or not SESSION_ID_RE.match(sid):
                raise UserError('That is not a session id.')
            cwd = session_cwd
            if not cwd:
                raise UserError('This session is not in the index any more. Press Rescan and try again.')
            if not os.path.isdir(cwd):
                if fallback_cwd and os.path.isdir(fallback_cwd):
                    warnings.append('The folder this session ran in is gone (%s). Opening from %s instead; '
                                    'Claude may not find the session there.' % (cwd, fallback_cwd))
                    cwd = fallback_cwd
                else:
                    raise UserError('The folder this session ran in no longer exists: %s' % cwd)
        else:
            default_cwd = default_cwd or self.default_cwd
            cwd = req.get('cwd') or default_cwd
            if not isinstance(cwd, str) or not os.path.isabs(cwd):
                raise UserError('Pick a folder for the new session.')
            cwd = os.path.normpath(cwd)
            allowed = set(os.path.normpath(c) for c in known_cwds if c)
            allowed.add(os.path.normpath(default_cwd))
            if cwd not in allowed:
                raise UserError('New sessions can only start in a folder you already used with Claude.')
            if not os.path.isdir(cwd):
                raise UserError('That folder no longer exists: %s' % cwd)

        prompt = None
        if action in ('note_new', 'note_resume'):
            prompt = safe_prompt(req.get('note'))

        args = []
        if action in ('resume', 'fork', 'note_resume'):
            args += ['--resume', sid]
        if action == 'fork' or (action == 'note_resume' and req.get('fork')):
            args.append('--fork-session')

        os.makedirs(self.launch_dir, exist_ok=True)
        self._cleanup()
        tag = '%s-%s-%s-%s' % (action.replace('_', '-'), (sid or 'new')[:8], time.strftime('%H%M%S'), secrets.token_hex(3))
        launcher = os.path.join(self.launch_dir, tag + '.sh')
        prompt_file = None
        q = shlex.quote
        cmd = ' '.join([q(self.claude_bin)] + [q(a) for a in args])
        if prompt is not None:
            prompt_file = os.path.join(self.launch_dir, tag + '.prompt.txt')
            fd = os.open(prompt_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(prompt)
            cmd += ' "$(cat %s)"' % q(prompt_file)
        # Optional: your own lines to run in every window the board opens (colours, environment), if the file exists
        hook = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(self.launch_dir))), 'before-session.zsh')
        extra = '[[ -r %s ]] && source %s\n' % (q(hook), q(hook)) if os.path.isfile(hook) else ''
        script = (
            '#!/bin/zsh -l\n'
            '# Session Canvas launcher (made %s). Opens one Claude Code session. Safe to delete.\n'
            '# Start clean: this must be its own top-level session even if the Canvas was started from inside Claude.\n'
            'for v in ${(k)parameters[(I)CLAUDE*]} AI_AGENT; do [[ $v == CLAUDE_CODE_PLUGIN_DIRS ]] || unset $v; done\n'
            '%s'
            'cd %s || { print -r -- "Session Canvas: folder not found"; exit 1; }\n'
            'exec %s\n'
        ) % (time.strftime('%Y-%m-%d %H:%M:%S'), extra, q(cwd), cmd)
        fd = os.open(launcher, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(script)

        # A one-line version the person can paste into any terminal (the note is quoted, never run).
        pasteable = 'cd %s && %s' % (q(cwd), ' '.join(['claude'] + [q(a) for a in args] + ([q(prompt)] if prompt is not None else [])))
        return {
            'action': action, 'sessionId': sid, 'cwd': cwd, 'terminal': terminal,
            'argv': [self.claude_bin] + args + ([prompt] if prompt is not None else []),
            'command': pasteable, 'launcher': launcher, 'script': script, 'promptFile': prompt_file,
            'open': open_command(terminal, launcher), 'warnings': warnings,
        }

    def run(self, plan):
        """Really open the window. Returns (ok, message)."""
        # The first time, macOS asks the person "…wants to control Terminal/iTerm". Give them time to read and click OK.
        try:
            p = subprocess.run(plan['open'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                               env=clean_env())
        except subprocess.TimeoutExpired:
            return False, ('The Mac did not answer. It probably asked whether this may control Terminal and is still waiting: '
                           'click OK in that box, then press the button again.')
        except OSError as e:
            return False, 'Could not start it: %s' % e
        if p.returncode != 0:
            err = (p.stderr or b'').decode('utf-8', 'replace').strip()
            if '-1743' in err or 'Not authorized' in err or 'not allowed' in err.lower():
                return False, ('macOS blocked this. Allow it once in System Settings → Privacy & Security → '
                               'Automation (let it control %s), then try again.' % plan['terminal'])
            return False, 'The window did not open: %s' % (err[:300] or 'unknown error')
        return True, 'Opened in %s.' % plan['terminal']

    def _cleanup(self):
        try:
            now = time.time()
            for n in os.listdir(self.launch_dir):
                p = os.path.join(self.launch_dir, n)
                if now - os.path.getmtime(p) > 3 * 86400:
                    os.remove(p)
        except OSError:
            pass


def clean_env():
    """The environment for helper commands: no Claude session variables leak into what we open."""
    env = {}
    for k, v in os.environ.items():
        if (k.startswith('CLAUDE') and k != 'CLAUDE_CODE_PLUGIN_DIRS') or k == 'AI_AGENT':
            continue
        env[k] = v
    return env


def copy_to_clipboard(text):
    try:
        subprocess.run(['pbcopy'], input=text.encode('utf-8'), timeout=5, env=clean_env())
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def live_sessions(sessions_dir=None):
    """Sessions that are open right now. Claude Code writes ~/.claude/sessions/<pid>.json for every running
    window ({pid, sessionId, status, kind, ...}); a file whose process is gone is left over and ignored."""
    d = sessions_dir or os.environ.get('CANVAS_LIVE_DIR') or os.path.join(os.path.expanduser('~'), '.claude', 'sessions')
    out = {}
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(d, name), 'r', encoding='utf-8') as fh:
                info = json.load(fh)
            pid, sid = int(info.get('pid') or 0), info.get('sessionId')
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if not sid or pid <= 0:
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            pass
        prev = out.get(sid)
        if prev and prev['since'] >= int(info.get('startedAt') or 0):
            prev['windows'] += 1
            continue
        out[sid] = {'pid': pid, 'status': info.get('status') or '', 'kind': info.get('kind') or '',
                    'since': int(info.get('startedAt') or 0), 'windows': (prev['windows'] + 1) if prev else 1}
    return out


# ---- going to the window of a session that is already open ---------------------------------------

ACTIVATE_JXA = ('ObjC.import("AppKit"); function run(a) { var p = $.NSRunningApplication'
                '.runningApplicationWithProcessIdentifier(parseInt(a[0])); if (p.isNil()) return "gone"; '
                'p.unhide; return p.activateWithOptions(3) ? "ok" : "refused"; }')


GHOSTTY_PICK_JXA = ('function run(a) { var g = Application(parseInt(a[0])); '
                    'var ts = g.terminals.whose({name: {_contains: a[1]}})(); '
                    'if (!ts.length) return "notfound"; g.focus(ts[0]); return "ok"; }')


def process_table():
    """{pid: (parent pid, tty, command)} for every process of this Mac."""
    out = {}
    try:
        p = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,tty=,command='], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return out
    for line in p.stdout.decode('utf-8', 'replace').split('\n'):
        f = line.split(None, 3)
        if len(f) == 4 and f[0].isdigit() and f[1].isdigit():
            out[int(f[0])] = (int(f[1]), f[2], f[3])
    return out


def find_window(pid, table):
    """The terminal window a process lives in: {'app', 'appPid', 'tty', 'single'} or None (no window)."""
    row = table.get(pid)
    if not row or not re.match(r'^ttys?\d+$', row[1]):
        return None
    tty = '/dev/' + row[1]
    cur = pid
    for _ in range(15):
        row = table.get(cur)
        if not row:
            return None
        cmd = row[2]
        if '/Ghostty.app/' in cmd:
            # a window opened by the Canvas (or guide.sh) is its own Ghostty process: `ghostty -e …`
            return {'app': 'Ghostty', 'appPid': cur, 'tty': tty, 'single': ' -e ' in cmd}
        if '/Terminal.app/' in cmd:
            return {'app': 'Terminal', 'appPid': cur, 'tty': tty, 'single': False}
        if '/iTerm.app/' in cmd or '/iTerm2.app/' in cmd:
            return {'app': 'iTerm', 'appPid': cur, 'tty': tty, 'single': False}
        cur = row[0]
        if cur <= 1:
            return None
    return None


def focus_commands(win, title=''):
    """The exact commands that bring that window to the front, in order."""
    if win['app'] == 'Terminal':
        tty = applescript_string(win['tty'])
        return [['osascript',
                 '-e', 'tell application "Terminal"',
                 '-e', '  repeat with w in windows',
                 '-e', '    repeat with t in tabs of w',
                 '-e', '      if tty of t is ' + tty + ' then',
                 '-e', '        set selected tab of w to t',
                 '-e', '        set index of w to 1',
                 '-e', '        activate',
                 '-e', '        return "ok"',
                 '-e', '      end if',
                 '-e', '    end repeat',
                 '-e', '  end repeat',
                 '-e', 'end tell',
                 '-e', 'return "notfound"']]
    cmds = [['osascript', '-l', 'JavaScript', '-e', ACTIVATE_JXA, str(win['appPid'])]]
    title = ' '.join((title or '').split())[:60]
    if win['app'] == 'Ghostty' and not win.get('single') and len(title) >= 4:
        # the main Ghostty app can hold several windows: first pick the one whose title has the session's title
        cmds.insert(0, ['osascript', '-l', 'JavaScript', '-e', GHOSTTY_PICK_JXA, str(win['appPid']), title])
    return cmds


def front_pid():
    """The pid of the app in front right now, or None if the Mac won't say."""
    try:
        asn = subprocess.run(['/usr/bin/lsappinfo', 'front'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5).stdout.decode('utf-8', 'replace').strip()
        if not asn:
            return None
        out = subprocess.run(['/usr/bin/lsappinfo', 'info', '-only', 'pid', asn], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=5).stdout.decode('utf-8', 'replace')
        m = re.search(r'pid"?\s*=\s*(\d+)', out)
        return int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def _osascript(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=clean_env())
        return p.returncode, p.stdout.decode('utf-8', 'replace').strip(), p.stderr.decode('utf-8', 'replace').strip()
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    except OSError as e:
        return 127, '', str(e)


def focus_session(sid, title='', dry_run=False, live=None, table=None, run=_osascript, front=front_pid):
    """Bring the window of a running session to the front. Always answers with a dict for the page:
    {'ok', 'focused', 'reason', 'message', 'app', 'commands'}; never raises for "could not"."""
    live = live_sessions() if live is None else live
    info = live.get(sid)
    if not info:
        return {'ok': False, 'focused': False, 'reason': 'closed',
                'message': 'This session is not open in a window any more.'}
    if info.get('kind') == 'bg':
        return {'ok': False, 'focused': False, 'reason': 'background',
                'message': 'It is a background helper, so it has no window to show.'}
    win = find_window(info['pid'], process_table() if table is None else table)
    if not win:
        return {'ok': False, 'focused': False, 'reason': 'nowindow',
                'message': 'Could not tell which window it is in (it is not in Terminal, iTerm or Ghostty).'}
    cmds = focus_commands(win, title)
    res = {'ok': True, 'focused': False, 'app': win['app'], 'appPid': win['appPid'], 'tty': win['tty'], 'commands': cmds}
    if dry_run:
        res.update(dryRun=True, reason='dryrun',
                   message='Test mode: its %s window was found but not brought to the front.' % win['app'])
        return res
    exact = win.get('single')
    if len(cmds) > 1:                       # the main Ghostty app: pick the right window by its title
        exact = run(cmds[0], 6)[1] == 'ok'
    code, out, err = run(cmds[-1])
    if win['app'] == 'Terminal':
        if code == 0 and out == 'ok':
            res.update(focused=True, message='Brought its Terminal tab to the front.')
        elif '-1743' in err or 'Not authorized' in err or 'not allowed' in err.lower() or code == 124:
            res.update(ok=False, reason='blocked', message='macOS did not let the Canvas reach Terminal (allow it in System '
                       'Settings → Privacy & Security → Automation).')
        else:
            res.update(ok=False, reason='notfound', message='Could not find its tab in Terminal.')
        return res
    name = win['app']
    if code != 0 or out != 'ok':
        res.update(ok=False, reason='failed', message='Could not bring its %s window forward (%s).' % (name, err or out or code))
        return res
    for _ in range(6):                      # give the Mac a moment, then check it really is in front
        now = front()
        if now is None or now == win['appPid']:
            break
        time.sleep(0.15)
    else:
        res.update(ok=False, reason='refused', message='macOS did not bring %s forward.' % name)
        return res
    res.update(focused=True, exact=bool(exact),
               message='Brought its %s window to the front.' % name if exact else
               '%s is in front. If you see another of its windows, this session is in one of the others.' % name)
    return res


# ---- reminder ping --------------------------------------------------------------------------------

def fmt_wait(ms):
    m = max(0, int(ms // 60000))
    if m < 60:
        return '%d min' % m
    if m < 48 * 60:
        return '%d h' % (m // 60) if m % 60 < 5 or m >= 600 else '%d h %02d' % (m // 60, m % 60)
    return '%d days' % (m // 1440)


STATE_WORDS = {'question': 'needs your answer', 'your-turn': 'your turn'}


class Reminder(object):
    """One short line when cards have waited on the person for a while. Each card + report is pinged once."""

    def __init__(self, path, send, after_min=30, hours=(8, 20), url=''):
        self.path = path
        self.send = send                      # callable(text); None = never send (dry run, tests)
        self.after_ms = int(after_min * 60000)
        self.hours = hours
        self.url = url
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) and isinstance(d.get('pinged'), dict) else None
        except (OSError, ValueError):
            return None

    def _save(self, pinged):
        tmp = self.path + '.tmp'
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump({'pinged': pinged}, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass

    @staticmethod
    def key(w):
        return '%s|%s' % (w['id'], w.get('sig') or '')

    def text(self, due, now):
        parts = ['%s (%s, %s)' % (w['name'][:48], STATE_WORDS.get(w['state'], w['state']), fmt_wait(now - w['since']))
                 for w in due[:3]]
        more = ' +%d more' % (len(due) - 3) if len(due) > 3 else ''
        head = '%d card%s waiting on you' % (len(due), '' if len(due) == 1 else 's')
        return ('Canvas: %s: %s%s' % (head, ' · '.join(parts), more) + (' → ' + self.url if self.url else ''))[:290]

    def tick(self, waiting, now_ms=None):
        """Look at what waits now; returns the line that was sent, or None."""
        if not self.send or self.after_ms <= 0:
            return None
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        with self.lock:
            data = self._load()
            keys = dict((self.key(w), w) for w in waiting)
            if data is None:                  # first run ever: what already waits is old news
                self._save(dict((k, now) for k in keys))
                return None
            pinged = dict((k, v) for k, v in data['pinged'].items() if k in keys)       # forget cards that moved on
            due = [w for k, w in keys.items() if k not in pinged and now - w['since'] >= self.after_ms]
            hour = time.localtime(now / 1000.0).tm_hour
            if not due or not (self.hours[0] <= hour < self.hours[1]):
                if len(pinged) != len(data['pinged']):
                    self._save(pinged)
                return None
            due.sort(key=lambda w: (w['since'], w['id']))
            line = self.text(due, now)
            for w in due:
                pinged[self.key(w)] = now
            self._save(pinged)                # remembered first: a failed send is not repeated every minute
        try:
            self.send(line)
        except Exception:
            pass
        return line


def notify_sender(command):
    """The reminder command from Settings -> Advanced: the full path of a script or program. It is run with
    the reminder line as its one argument (never through a shell). None when it is not set or not there."""
    script = os.path.expanduser((command or '').strip()) if isinstance(command, str) else ''
    if not script or not os.path.isabs(script) or not os.path.isfile(script):
        return None
    argv = [script] if os.access(script, os.X_OK) else ['/bin/zsh', script]

    def send(text):
        subprocess.run(argv + [text], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=45, env=clean_env())
    return send


def remind_minutes(settings):
    """Minutes a card may wait before the reminder (Settings -> Advanced). 30 unless set; 0 = never."""
    v = (settings or {}).get('remindMin')
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
        return 30.0
    return min(float(v), 7 * 24 * 60.0)


# ---- the app -------------------------------------------------------------------------------------

class App(object):
    def __init__(self, args):
        self.args = args
        self.dry_run = bool(args.dry_run)
        self.token = secrets.token_urlsafe(24)
        self.cache_dir = args.cache
        self.store = StateStore(args.state)
        self.index = indexer.Index(args.cache, projects_root=args.projects, work_root=self.default_cwd())
        self.apply_settings()
        self.spawner = Spawner(os.path.join(args.cache, 'launch'), claude_bin=args.claude, default_cwd=self.default_cwd(),
                               dry_run=self.dry_run)
        self.client_log = []
        self.spawn_log = []
        self.port = None
        self.started = time.time()
        self.index_lock = threading.Lock()
        self.index_error = None
        self.reminder = None                  # set by start_reminders(); never in dry-run mode or in tests
        self.updates = None                   # set by start_updates(); never in dry-run mode or in tests
        self.update_proc = None

    # --- Board buttons write into the report file, so HQ, the board and the session read the same thing ---
    MARK_WORD = {'done': 'Done', 'sent': 'Sent', 'replaced': 'Replaced'}

    def _edits_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(self.args.state)), 'report-edits.json')

    def _load_edits(self):
        try:
            with open(self._edits_path(), encoding='utf-8') as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_edits(self, d):
        _atomic_write(self._edits_path(), json.dumps(d, ensure_ascii=False, indent=1))

    def _report_path(self, sess):
        """The report file of a session, only when it sits inside a configured report folder."""
        rep = (sess or {}).get('report') or {}
        f = rep.get('file')
        if not isinstance(f, str) or not f:
            return None
        p = f if os.path.isabs(f) else os.path.join(self.index.work_root or '', f)
        rp = os.path.realpath(p)
        for d in self.index.report_dirs or []:
            if rp.startswith(os.path.realpath(d) + os.sep) and rp.endswith('.md') and os.path.isfile(rp):
                return rp
        return None

    @staticmethod
    def edit_report_text(text, kind, by_token='', when=''):
        """The report with its header turned into done: status line set, plus a sent / replaced-by / marked line."""
        lines = text.split('\n')
        head = min(len(lines), 12)
        si = next((i for i in range(head) if re.match(r'^status\s*:', lines[i], re.I)), None)
        if si is None:
            lines.insert(0, 'status: done')
            si, head = 0, head + 1
        else:
            lines[si] = 'status: done'
        last = si
        for i in range(si, head):
            if re.match(r'^(name|outcome|left)\s*:', lines[i], re.I):
                last = i
        if kind == 'sent':
            extra = 'sent: marked Sent on the board, %s' % when
        elif kind == 'replaced':
            extra = 'replaced-by: %s' % (by_token or 'a newer session')
        else:
            extra = 'marked: Done on the board, %s' % when
        lines.insert(last + 1, extra)
        return '\n'.join(lines)

    def marks_to_reports(self, old, new):
        """Write each new board mark into its report; put the report back when a mark is undone
        (only if nobody changed the file since). Returns True when a file changed. Never in dry-run mode."""
        if self.dry_run or not (self.index.report_dirs or []):
            return False
        sessions = {x.get('id'): x for x in ((self.index.payload() or {}).get('sessions') or [])}
        edits = self._load_edits()
        changed = False
        when = time.strftime('%-d %b %H:%M')
        for sid in sorted(set(old) | set(new)):
            o, n = old.get(sid), new.get(sid)
            if o == n:
                continue
            had = edits.get(sid)
            valid = isinstance(n, dict) and n.get('kind') in self.MARK_WORD
            if had and (not valid or had.get('kind') != n.get('kind')):
                try:
                    with open(had['file'], encoding='utf-8') as fh:
                        cur = fh.read()
                    if hashlib.sha256(cur.encode('utf-8')).hexdigest() == had.get('after'):
                        _atomic_write(had['file'], had['before'])
                        changed = True
                except (OSError, KeyError):
                    pass
                edits.pop(sid, None)
            if not valid or sid in edits:
                continue
            path = self._report_path(sessions.get(sid))
            if not path:
                continue
            token = ''
            if n['kind'] == 'replaced':
                tgt = sessions.get(n.get('by')) or {}
                tp = self._report_path(tgt)
                token = os.path.splitext(os.path.basename(tp))[0] if tp else (tgt.get('name') or '')
            try:
                with open(path, encoding='utf-8') as fh:
                    before = fh.read()
                after = self.edit_report_text(before, n['kind'], token, when)
                _atomic_write(path, after)
            except OSError:
                continue
            edits[sid] = {'file': path, 'kind': n['kind'], 'before': before,
                          'after': hashlib.sha256(after.encode('utf-8')).hexdigest()}
            changed = True
        self._save_edits(edits)
        return changed

    def waiting(self):
        """Every card that waits on the person (oldest first), after the marks made on the board."""
        sessions = (self.index.payload() or {}).get('sessions') or []
        return indexer.waiting_list(sessions, self.store.get().get('marks') or {})

    def apply_settings(self):
        """Hand the optional Advanced settings to the index: report folders and the name used in reports.
        Returns True when something changed (the caller then looks at the reports again)."""
        st = self.settings()
        folders = st.get('reportFolders')
        dirs = indexer.report_dirs_of([f for f in folders if isinstance(f, str) and os.path.isabs(os.path.expanduser(f.strip() or '.'))]
                                      if isinstance(folders, list) else [])
        name = st.get('userName') if isinstance(st.get('userName'), str) else ''
        root = self.default_cwd()
        ix = self.index
        if (dirs, name, root) == (ix.report_dirs, ix.user_name, ix.work_root):
            return False
        with ix.lock:
            ix.report_dirs, ix.user_name, ix.work_root = dirs, name, root
        return True

    def start_reminders(self, send=None, after_min=None, every=60.0):
        """A quiet clock: look for new reports once a minute (also when no page is open) and remind when due.
        The command and the minutes come from Settings -> Advanced and are read again on every tick, so a
        change needs no restart. `send` / `after_min` fix them instead (used by the tests)."""
        if self.dry_run:
            return False
        fixed = send is not None or after_min is not None
        if fixed and ((after_min is not None and after_min <= 0) or send is None):
            return False
        self.reminder = Reminder(os.path.join(self.cache_dir, 'pings.json'), send, after_min=after_min or 30,
                                 url='http://127.0.0.1:%d/' % (self.port or 0))

        def loop():
            while True:
                time.sleep(every)
                try:
                    if not fixed:
                        st = self.settings()
                        self.reminder.send = notify_sender(st.get('notifyCommand'))
                        self.reminder.after_ms = int(remind_minutes(st) * 60000)
                    if self.reminder.send and self.reminder.after_ms > 0 and self.index.report_dirs and self.ready():
                        self.rescan(min_age=45.0)
                        self.reminder.tick(self.waiting())
                except Exception as e:        # a reminder must never take the board down
                    sys.stderr.write('reminder: %s\n' % e)
        threading.Thread(target=loop, name='reminder', daemon=True).start()
        return True

    # -- updates --
    def start_updates(self):
        """Allow the once-a-day look for a newer release. Only main() calls this, and never in dry-run mode."""
        if self.dry_run or os.environ.get('SESSION_CANVAS_NO_UPDATE_CHECK'):
            return False
        self.updates = updater.Checker(os.path.join(self.cache_dir, 'update.json'), VERSION)
        return True

    def update_info(self, force=False):
        proc = self.update_proc
        info = {'current': VERSION, 'latest': None, 'available': False, 'checkedAt': 0,
                'updating': bool(proc and proc.poll() is None), 'failed': '',
                'canUpdate': updater.is_install(APP_HOME), 'enabled': bool(self.updates)}
        if proc and proc.poll() not in (None, 0):          # it stopped without replacing this server: say why
            try:
                with open(os.path.join(self.cache_dir, 'update.log'), 'r', encoding='utf-8', errors='replace') as fh:
                    info['failed'] = (fh.read()[-600:].strip().split('\n') or [''])[-1][:300]
            except OSError:
                info['failed'] = 'The update stopped.'
        if self.updates:
            info.update(self.updates.info(force=force))
        return info

    def run_update(self):
        """Start `updater.py update` on its own (it stops and restarts this server). Returns (ok, message)."""
        if not updater.is_install(APP_HOME):
            return False, 'This copy runs from a source folder, not from an install. Update it with git.'
        argv = [sys.executable or '/usr/bin/python3', os.path.join(HERE, 'updater.py'), 'update', '--home', APP_HOME]
        if self.dry_run:
            return True, 'Test mode: would run ' + ' '.join(shlex.quote(a) for a in argv)
        if self.update_proc and self.update_proc.poll() is None:
            return True, 'The update is already running.'
        try:
            with open(os.path.join(self.cache_dir, 'update.log'), 'wb') as log:
                self.update_proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                                                    cwd=os.path.expanduser('~'), env=clean_env())
        except OSError as e:
            return False, 'Could not start the update: %s' % e
        return True, 'Updating. The board comes back by itself in a few seconds.'

    def settings(self):
        st = self.store.get().get('settings')
        return st if isinstance(st, dict) else {}

    def default_cwd(self):
        """The folder new sessions start in: the one picked in setup, else --root, else the home folder."""
        for c in (self.settings().get('defaultCwd'), self.args.root):
            if isinstance(c, str) and os.path.isabs(c) and os.path.isdir(c):
                return os.path.normpath(c)
        return os.path.expanduser('~')

    def start_indexing(self):
        t = threading.Thread(target=self._first_index, name='index', daemon=True)
        t.start()

    def _first_index(self):
        try:
            self.index.refresh()
        except Exception as e:      # shown in the page instead of a silent blank board
            self.index_error = '%s: %s' % (type(e).__name__, e)
            self.index.progress = {'state': 'error', 'done': 0, 'total': 0, 'parsed': 0, 'error': self.index_error}

    def rescan(self, min_age=0.0):
        """Look for new or changed transcripts. Skipped if the last look was less than min_age seconds ago."""
        if not self.index.loaded:
            return None
        if time.time() - self.index.last_refresh < min_age:
            return None
        if not self.index_lock.acquire(False):
            return None                       # another request is already scanning
        try:
            return self.index.refresh()
        finally:
            self.index_lock.release()

    def ready(self):
        return self.index.loaded and self.index.progress.get('state') == 'ready' and self.index.generation > 0


CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png',
    '.json': 'application/json; charset=utf-8', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8',
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = APP_NAME.replace(' ', '') + '/' + VERSION
    app = None      # set by make_server

    # -- plumbing --
    def log_message(self, fmt, *args):
        if self.app.args.verbose:
            sys.stderr.write('%s %s\n' % (time.strftime('%H:%M:%S'), fmt % args))

    def _send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        # No other site may put the board in a frame (clickjacking), and the page runs only its own script files.
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get('Host') or '').strip().lower()
        port = self.app.port
        return host in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

    def _origin_ok(self):
        origin = self.headers.get('Origin')
        if not origin or origin == 'null':
            return origin is None
        port = self.app.port
        return origin.lower() in ('http://127.0.0.1:%d' % port, 'http://localhost:%d' % port)

    def _body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            raise UserError('That is too much to send at once.')
        raw = self.rfile.read(n) if n > 0 else b''
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise UserError('Could not read the request.')
        if not isinstance(data, dict):
            raise UserError('Could not read the request.')
        return data

    # -- GET --
    def do_GET(self):
        try:
            if not self._host_ok():
                return self._send(403, {'error': 'This address is not allowed.'})
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = u.path
            if path.startswith('/api/'):
                return self._api_get(path, q)
            return self._static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send(500, {'error': 'Something went wrong on the server: %s' % e})
            except Exception:
                pass

    do_HEAD = do_GET

    def _static(self, path):
        if path in ('/', '/index.html'):
            with open(os.path.join(WEB, 'index.html'), 'r', encoding='utf-8') as fh:
                html = fh.read()
            html = html.replace('{{TOKEN}}', self.app.token).replace('{{DRY_RUN}}', '1' if self.app.dry_run else '0')
            html = html.replace('{{VERSION}}', VERSION).replace('{{APP_NAME}}', APP_NAME)
            return self._send(200, html, CONTENT_TYPES['.html'])
        name = os.path.normpath(path.lstrip('/'))
        full = os.path.realpath(os.path.join(WEB, name))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            return self._send(404, 'Not found', 'text/plain; charset=utf-8')
        ext = os.path.splitext(full)[1].lower()
        with open(full, 'rb') as fh:
            data = fh.read()
        return self._send(200, data, CONTENT_TYPES.get(ext, 'application/octet-stream'))

    def _api_get(self, path, q):
        app = self.app
        if path == '/api/health':
            return self._send(200, {'ok': True, 'app': 'session-canvas', 'version': VERSION, 'pid': os.getpid(),
                                    'port': app.port, 'dryRun': app.dry_run, 'ready': app.ready(),
                                    'name': APP_NAME, 'root': app.default_cwd(), 'uptime': int(time.time() - app.started)})
        if path == '/api/dir':
            raw = (q.get('path', [''])[0] or '').strip()
            if raw.startswith('~'):
                raw = os.path.expanduser(raw)
            if not raw or not os.path.isabs(raw):
                return self._send(200, {'ok': False, 'error': 'Type a full folder path, starting with / or ~.'})
            p = os.path.realpath(raw)
            if not os.path.isdir(p):
                return self._send(200, {'ok': False, 'error': 'That folder does not exist.'})
            return self._send(200, {'ok': True, 'path': p})
        if path == '/api/setup':
            folders = collections.Counter()
            if app.ready():
                for s in app.index.payload().get('sessions') or []:
                    c = s.get('cwd')
                    if c and s.get('project') != 'desktop' and os.path.isdir(c):
                        folders[c] += 1
            claude = app.spawner.claude_bin if os.path.isfile(app.spawner.claude_bin) else find_claude()
            return self._send(200, {'name': APP_NAME, 'version': VERSION, 'home': os.path.expanduser('~'),
                                    'defaultCwd': app.default_cwd(), 'terminals': installed_terminals(),
                                    'folders': [{'cwd': c, 'sessions': n} for c, n in folders.most_common(30)],
                                    'claude': claude, 'projectsDir': app.args.projects,
                                    'projectsFound': os.path.isdir(app.args.projects), 'dryRun': app.dry_run})
        if path == '/api/progress':
            p = dict(app.index.progress)
            p['ready'] = app.ready()
            return self._send(200, p)
        if path == '/api/sessions':
            if not app.ready():
                p = dict(app.index.progress)
                return self._send(200, {'ready': False, 'progress': p, 'error': app.index_error})
            if q.get('rescan', ['0'])[0] == '1':
                app.rescan(min_age=15.0)
            gen = q.get('gen', [''])[0]
            if gen and gen == str(app.index.generation):
                return self._send(200, {'ready': True, 'unchanged': True, 'generation': app.index.generation,
                                        'indexedAt': int(app.index.last_refresh * 1000)})
            payload = app.index.payload()
            payload['defaultCwd'] = app.default_cwd()
            payload['ready'] = True
            payload['dryRun'] = app.dry_run
            payload['now'] = int(time.time() * 1000)
            return self._send(200, payload)
        if path == '/api/session':
            d = app.index.detail(q.get('id', [''])[0])
            if not d:
                return self._send(404, {'error': 'That session is not in the index.'})
            return self._send(200, d)
        if path == '/api/search':
            if not app.ready():
                return self._send(200, {'q': '', 'terms': [], 'total': 0, 'results': []})
            t0 = time.time()
            r = app.index.search(q.get('q', [''])[0][:300])
            r['ms'] = round((time.time() - t0) * 1000, 1)
            return self._send(200, r)
        if path == '/api/state':
            s = app.store.get()
            s['recovered'] = app.store.recovered
            return self._send(200, s)
        if path == '/api/update':
            return self._send(200, app.update_info(force=q.get('force', ['0'])[0] == '1'))
        if path == '/api/waiting':
            if not app.ready():
                return self._send(200, {'ready': False, 'waiting': [], 'counts': {}})
            if q.get('rescan', ['1'])[0] != '0':
                app.rescan(min_age=2.0)          # HQ asks this to decide what to do next: look for new reports first
            now = int(time.time() * 1000)
            items = app.waiting()
            for w in items:
                w['waited'] = fmt_wait(now - w['since'])
            counts = {'question': sum(1 for w in items if w['state'] == 'question'),
                      'your-turn': sum(1 for w in items if w['state'] == 'your-turn')}
            if q.get('format', [''])[0] == 'text':
                lines = ['%s\t%s\t%s\t%s\t%s' % (STATE_WORDS[w['state']], w['waited'], w['name'], w['left'] or w['outcome'], w['file'])
                         for w in items]
                return self._send(200, '\n'.join(lines) + ('\n' if lines else ''), CONTENT_TYPES['.txt'])
            return self._send(200, {'ready': True, 'now': now, 'counts': counts, 'waiting': items})
        if path == '/api/clientlog':
            return self._send(200, {'entries': app.client_log[-300:]})
        if path == '/api/live':
            d = os.environ.get('CANVAS_LIVE_DIR') or os.path.join(os.path.expanduser('~'), '.claude', 'sessions')
            return self._send(200, {'live': live_sessions(d), 'available': os.path.isdir(d), 'now': int(time.time() * 1000)})
        if path == '/api/spawnlog':
            return self._send(200, {'entries': app.spawn_log[-50:]})
        return self._send(404, {'error': 'Not found'})

    # -- POST --
    def do_POST(self):
        app = self.app
        try:
            if not self._host_ok() or not self._origin_ok():
                return self._send(403, {'error': 'This address is not allowed.'})
            body = self._body()
            token = self.headers.get('X-Canvas-Token') or body.pop('token', None)
            if not token or not secrets.compare_digest(str(token), app.token):
                return self._send(403, {'error': 'This page is out of date. Reload it (Cmd+R).'})
            body.pop('token', None)
            path = urlparse(self.path).path
            if path == '/api/state':
                before = app.store.get().get('marks') or {}
                rev = app.store.patch(body.get('patch'))
                if 'marks' in (body.get('patch') or {}) and app.marks_to_reports(before, app.store.get().get('marks') or {}) and app.ready():
                    app.rescan()                 # the report files changed: read them now
                if 'settings' in (body.get('patch') or {}) and app.apply_settings() and app.ready():
                    app.rescan()                 # report folders changed: read the reports now
                return self._send(200, {'ok': True, 'rev': rev})
            if path == '/api/update':
                ok, msg = app.run_update()
                return self._send(200, {'ok': ok, 'message': msg, 'current': VERSION, 'dryRun': app.dry_run})
            if path == '/api/rescan':
                stats = app.rescan(min_age=0.0)
                return self._send(200, {'ok': True, 'stats': stats, 'generation': app.index.generation})
            if path == '/api/spawn':
                return self._spawn(body)
            if path == '/api/focus':
                sid = body.get('sessionId')
                if not isinstance(sid, str) or not SESSION_ID_RE.match(sid):
                    raise UserError('That is not a session id.')
                return self._send(200, focus_session(sid, title=app.index.session_title(sid) or '',
                                                     dry_run=app.dry_run or bool(body.get('dryRun'))))
            if path == '/api/clientlog':
                entry = {'t': int(time.time() * 1000)}
                for k in ('level', 'msg', 'stack', 'where', 'data'):
                    if k in body:
                        v = body[k]
                        entry[k] = v[:4000] if isinstance(v, str) else v
                app.client_log.append(entry)
                del app.client_log[:-500]
                return self._send(200, {'ok': True})
            return self._send(404, {'error': 'Not found'})
        except UserError as e:
            self._send(400, {'ok': False, 'error': str(e)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send(500, {'ok': False, 'error': 'Something went wrong on the server: %s' % e})
            except Exception:
                pass

    def _spawn(self, body):
        app = self.app
        sid = body.get('sessionId')
        session_cwd = None
        fallback = None
        if isinstance(sid, str) and SESSION_ID_RE.match(sid):
            session_cwd = app.index.session_cwd(sid)
            fallback = app.index.session_fallback_cwd(sid)
        terminal = app.settings().get('terminal')
        if terminal not in TERMINALS:
            terminal = 'Terminal'
        plan = app.spawner.plan(body, session_cwd=session_cwd, known_cwds=app.index.known_cwds(), terminal=terminal,
                                fallback_cwd=fallback, default_cwd=app.default_cwd())
        dry = app.dry_run or bool(body.get('dryRun'))
        result = dict(plan)
        result['dryRun'] = dry
        result['installed'] = installed_terminals()
        if dry:
            result['ok'] = True
            result['message'] = 'Test mode: nothing was opened.' if app.dry_run else 'Command ready.'
        else:
            ok, msg = app.spawner.run(plan)
            result['ok'] = ok
            result['message'] = msg
            if not ok:
                result['copied'] = copy_to_clipboard(plan['command'])
        app.spawn_log.append({'t': int(time.time() * 1000), 'action': plan['action'], 'sessionId': plan['sessionId'],
                              'cwd': plan['cwd'], 'dryRun': dry, 'ok': result['ok']})
        del app.spawn_log[:-100]
        return self._send(200, result)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def make_server(app, port, auto_port=True):
    handler = type('BoundHandler', (Handler,), {'app': app})       # each server gets its own app
    last = None
    for p in ([port] + [port + i for i in range(1, 30)] if auto_port else [port]):
        try:
            srv = Server(('127.0.0.1', p), handler)
            app.port = srv.server_address[1]
            return srv
        except OSError as e:
            last = e
    raise SystemExit('Session Canvas: no free port near %d (%s)' % (port, last))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description='Session Canvas: a local board of Claude Code sessions.')
    ap.add_argument('--port', type=int, default=int(os.environ.get('CANVAS_PORT') or 7788))
    ap.add_argument('--strict-port', action='store_true', help='fail instead of trying the next ports')
    ap.add_argument('--dry-run', action='store_true', default=os.environ.get('CANVAS_DRY_RUN') in ('1', 'true', 'yes'),
                    help='never open Terminal; answer with the command that would run')
    ap.add_argument('--state', default=os.path.join(DATA_DIR, 'state.json'))
    ap.add_argument('--cache', default=os.path.join(DATA_DIR, 'cache'))
    ap.add_argument('--projects', default=os.environ.get('CANVAS_PROJECTS_DIR') or
                    os.path.join(os.path.expanduser('~'), '.claude', 'projects'))
    ap.add_argument('--root', default=None, help='default folder for new sessions until one is picked in setup')
    ap.add_argument('--claude', default=None, help='path of the claude program')
    ap.add_argument('--info', default=None, help='where to write {pid, port} (default: <cache>/server.json)')
    ap.add_argument('--verbose', action='store_true')
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    os.makedirs(args.cache, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.state)), exist_ok=True)
    try:                                # the cache holds the text of your sessions: this user only
        os.chmod(args.cache, 0o700)
    except OSError:
        pass
    app = App(args)
    srv = make_server(app, args.port, auto_port=not args.strict_port)
    info_path = args.info or os.path.join(args.cache, 'server.json')
    info = {'pid': os.getpid(), 'port': app.port, 'url': 'http://127.0.0.1:%d/' % app.port, 'dryRun': app.dry_run,
            'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    tmp = info_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(info, fh)
    os.replace(tmp, info_path)

    def stop(*_a):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    app.start_indexing()
    app.start_reminders()
    app.start_updates()
    print(APP_NAME + ' on %s%s (pid %d)' % (info['url'], '  [dry run]' if app.dry_run else '', os.getpid()))
    sys.stdout.flush()
    try:
        srv.serve_forever(poll_interval=0.25)
    finally:
        srv.server_close()
        try:
            with open(info_path, 'r', encoding='utf-8') as fh:
                if json.load(fh).get('pid') == os.getpid():
                    os.remove(info_path)
        except (OSError, ValueError):
            pass


if __name__ == '__main__':
    main()
