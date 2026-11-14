"""Builders for small fake Claude Code transcripts (same shape as the real JSONL files)."""
import json
import os
import time
import uuid as uuidlib

WORK = '/home/tester/Projects/demo'


def encode_cwd(cwd):
    import re
    return re.sub(r'[^A-Za-z0-9]', '-', cwd)


def iso(ts):
    """Seconds since 1970 (UTC) -> '2026-11-10T09:00:00.000Z'."""
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(ts)) + '.000Z'


def new_id():
    return str(uuidlib.uuid4())


def user(text, ts, sid, cwd=WORK, uid=None, entry='cli', **extra):
    d = {'parentUuid': None, 'isSidechain': False, 'promptId': 'p1', 'type': 'user',
         'message': {'role': 'user', 'content': text}, 'uuid': uid or new_id(), 'timestamp': iso(ts),
         'userType': 'external', 'entrypoint': entry, 'cwd': cwd, 'sessionId': sid, 'version': '2.1.300', 'gitBranch': 'main',
         'promptSource': 'typed', 'origin': {'kind': 'human'}}
    d.update(extra)
    return d


def assistant(text, ts, sid, cwd=WORK, uid=None, entry='cli', tools=(), model='claude-opus-5-5', **extra):
    content = []
    if text:
        content.append({'type': 'text', 'text': text})
    for name, inp in tools:
        content.append({'type': 'tool_use', 'id': 'toolu_' + new_id()[:8], 'name': name, 'input': inp})
    d = {'parentUuid': None, 'isSidechain': False, 'type': 'assistant', 'uuid': uid or new_id(), 'timestamp': iso(ts),
         'message': {'role': 'assistant', 'model': model, 'content': content}, 'userType': 'external', 'entrypoint': entry,
         'cwd': cwd, 'sessionId': sid, 'version': '2.1.300', 'gitBranch': 'main'}
    d.update(extra)
    return d


def tool_result(text, ts, sid, cwd=WORK, uid=None, entry='cli', **extra):
    d = {'parentUuid': None, 'isSidechain': False, 'promptId': 'p1', 'type': 'user',
         'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'toolu_x', 'content': text}]},
         'uuid': uid or new_id(), 'timestamp': iso(ts), 'userType': 'external', 'entrypoint': entry, 'cwd': cwd,
         'sessionId': sid, 'version': '2.1.300', 'gitBranch': 'main', 'toolUseResult': {'stdout': text}}
    d.update(extra)
    return d


def write_session(projects_root, sid, records, cwd=WORK, raw_lines=()):
    """Write one transcript where Claude Code would put it; returns the file path."""
    d = os.path.join(projects_root, encode_cwd(cwd))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + '.jsonl')
    with open(path, 'w', encoding='utf-8') as fh:
        for r in records:
            fh.write(json.dumps(r, separators=(',', ':'), ensure_ascii=False) + '\n')
        for ln in raw_lines:
            fh.write(ln + '\n')
    return path


def simple_session(projects_root, sid, start, prompt, reply, cwd=WORK, entry='cli', extra_records=(), **kw):
    recs = [user(prompt, start, sid, cwd=cwd, entry=entry, **kw), assistant(reply, start + 30, sid, cwd=cwd, entry=entry)]
    recs.extend(extra_records)
    return write_session(projects_root, sid, recs, cwd=cwd)


# ---- a whole made-up history (tests, demo screenshots) --------------------------------------------

DEMO_TOPICS = [
    ('Fix the login redirect loop', 'login redirect cookies session'),
    ('Add dark mode to settings', 'theme tokens settings toggle'),
    ('Speed up the search endpoint', 'search index query latency'),
    ('Write release notes for 2.4', 'release notes changelog customers'),
    ('Plan the billing migration', 'billing invoices migration stripe'),
    ('Review the onboarding flow', 'onboarding signup checklist emails'),
    ('Clean up flaky CI tests', 'ci flaky retries pipeline'),
    ('Design the export to CSV', 'export csv download columns'),
    ('Investigate the memory leak', 'memory leak heap profiler'),
    ('Draft the Q3 roadmap', 'roadmap quarter priorities themes'),
    ('Refactor the payments module', 'payments refactor module interfaces'),
    ('Set up error monitoring', 'monitoring alerts errors dashboards'),
    ('Translate the app to Spanish', 'translation locale strings spanish'),
    ('Improve the mobile layout', 'mobile layout breakpoints responsive'),
    ('Write the API docs', 'api docs endpoints examples'),
]


def demo_corpus(projects_root, base_dir, n_you=110, n_auto=70, n_helpers=40, n_forks=12, n_continued=8,
                n_handovers=6, n_desktop=6, seed=11, now=None):
    """Writes a realistic made-up history of Claude Code sessions. Returns a dict with the ids by type and the
    project folders (real, empty folders under base_dir, so Resume can cd into them)."""
    import random
    rnd = random.Random(seed)
    now = int(now or time.time())
    folders = []
    for name in ('acme-app', 'acme-website', 'notes'):
        p = os.path.realpath(os.path.join(base_dir, name))
        os.makedirs(p, exist_ok=True)
        folders.append(p)
    out = {'folders': folders, 'you': [], 'auto': [], 'helpers': [], 'forks': [], 'continued': [], 'handovers': [],
           'desktop': [], 'records': {}}
    cmds = ['/review', '/standup', '/release-notes', '/test']

    def you_records(sid, start, cwd, i):
        title, words = DEMO_TOPICS[i % len(DEMO_TOPICS)]
        recs = [{'type': 'ai-title', 'aiTitle': title if i < len(DEMO_TOPICS) else '%s (%d)' % (title, i), 'sessionId': sid}]
        t = start
        first = '%s. Context: %s.' % (title, words)
        if i % 5 == 0:
            first += ' Ticket https://example.atlassian.net/browse/ACME-%d' % (100 + i)
        if i % 7 == 0:
            first = '<command-message>%s</command-message>\n<command-name>%s</command-name>\n<command-args>%s</command-args>' % (
                cmds[i % 4][1:], cmds[i % 4], words)
        recs.append(user(first, t, sid, cwd=cwd))
        reply = 'Here is a plan for %s. I looked at %s.' % (title.lower(), words)
        if i % 3 == 0:
            reply += ' The config override in settings.json wins over the default.'
        if i % 4 == 0:
            reply += ' PR: https://github.com/acme/acme-app/pull/%d' % (200 + i)
        if i % 6 == 0:
            reply += ' Spec: https://www.notion.so/acme/Spec-%032x' % (i + 1)
        recs.append(assistant(reply, t + 40, sid, cwd=cwd, tools=[('Read', {'file_path': cwd + '/README.md'})]))
        for k in range(rnd.randint(0, 3)):
            t += rnd.randint(120, 1800)
            recs.append(user('And what about %s? Also mention ACME-%d.' % (words.split()[k % 4], 100 + i), t, sid, cwd=cwd))
            recs.append(assistant('Done: %s updated and checked.' % words.split()[k % 4], t + 30, sid, cwd=cwd))
        return recs

    yous = []
    for i in range(n_you):
        sid = new_id()
        start = now - rnd.randint(3600, 42 * 86400)
        cwd = folders[0] if i % 3 else folders[i % 2 + 1] if i % 2 else folders[0]
        recs = you_records(sid, start, cwd, i)
        yous.append((sid, start, cwd, recs))
        out['you'].append(sid)
    for i in range(n_auto):
        sid = new_id()
        start = now - rnd.randint(3600, 42 * 86400)
        recs = [user('<command-message>daily-digest</command-message>\n<command-name>/daily-digest</command-name>\n<command-args>morning</command-args>',
                     start, sid, cwd=folders[2], entry='sdk-cli', promptSource=None, origin=None),
                assistant('Digest written: 3 new issues, 2 merged pull requests.', start + 50, sid, cwd=folders[2], entry='sdk-cli')]
        write_session(projects_root, sid, recs, cwd=folders[2])
        out['auto'].append(sid)
    for i in range(n_helpers):          # background helpers started from a "you" session
        sid = new_id()
        psid, pstart, pcwd, precs = yous[(i * 7) % len(yous)]
        hstart = pstart + 90 + i
        name = 'W%02d·%s' % (i % 9 + 1, DEMO_TOPICS[i % len(DEMO_TOPICS)][1].split()[0])
        precs.append(tool_result('%s %s (job, sonnet) → /tmp/helpers/%s.md' % (sid[:8], name, sid[:8]), pstart + 80, psid, cwd=pcwd))
        recs = [user('Helper task: check %s' % DEMO_TOPICS[i % len(DEMO_TOPICS)][1], hstart, sid, cwd=pcwd, sessionKind='bg'),
                assistant('Checked. Nothing blocking.', hstart + 60, sid, cwd=pcwd, sessionKind='bg'),
                {'type': 'custom-title', 'customTitle': name, 'sessionId': sid}]
        write_session(projects_root, sid, recs, cwd=pcwd)
        out['helpers'].append(sid)
    pending = []
    copies = rnd.sample(range(len(yous)), min(len(yous), n_forks + n_continued))
    for j, k in enumerate(copies):      # forks and continuations: start with a copy of the parent's history
        psid, pstart, pcwd, precs = yous[k]
        sid = new_id()
        hist = []
        for r in precs:
            if r.get('type') in ('user', 'assistant') and r.get('uuid'):
                c = json.loads(json.dumps(r))
                c['sessionId'] = sid
                hist.append(c)
        t = pstart + 2 * 86400
        own = [user('Continuing: what is left to do?', t, sid, cwd=pcwd), assistant('Two small things are left.', t + 30, sid, cwd=pcwd)]
        pending.append((sid, hist + own, pcwd))       # written after the parents: a copy is always the younger file
        if j < n_continued:
            precs.append({'type': 'continued-in', 'continuedInSessionId': sid, 'sessionId': psid})
            out['continued'].append((psid, sid))
        else:
            out['forks'].append((psid, sid))
    for i in range(n_handovers):
        psid, pstart, pcwd, precs = yous[(i * 11 + 3) % len(yous)]
        sid = new_id()
        t = pstart + 86400
        write_session(projects_root, sid, [user('Pick up where session %s stopped: finish the tests.' % psid, t, sid, cwd=pcwd),
                                           assistant('Picked it up; tests are green.', t + 60, sid, cwd=pcwd)], cwd=pcwd)
        out['handovers'].append((psid, sid))
    for i in range(n_desktop):
        sid = new_id()
        start = now - rnd.randint(3600, 30 * 86400)
        cwd = os.path.join(base_dir, 'desktop-chat-%d' % i)
        os.makedirs(cwd, exist_ok=True)
        write_session(projects_root, sid, [user('Quick question about %s' % DEMO_TOPICS[i][1], start, sid, cwd=cwd, entry='claude-desktop'),
                                           assistant('Short answer.', start + 20, sid, cwd=cwd, entry='claude-desktop')], cwd=cwd)
        out['desktop'].append(sid)
    for sid, start, cwd, recs in yous:
        write_session(projects_root, sid, recs, cwd=cwd)
        out['records'][sid] = recs
    if pending:
        time.sleep(0.7)                 # Claude Code's copies are newer files; the indexer relies on that
        for sid, recs, cwd in pending:
            write_session(projects_root, sid, recs, cwd=cwd)
    return out
