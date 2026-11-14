#!/usr/bin/python3
"""Session Canvas indexer.

Reads Claude Code session transcripts (~/.claude/projects/<folder>/<session-id>.jsonl) and builds a
small local index: one summary per session (title, times, counts, keywords, links), the links between
sessions (continued, forked, handover, helper, worktree), and the plain text used by search.

Python 3.9 standard library only. Nothing here talks to the network.

Cache: <cache_dir>/index.db (sqlite), one row per transcript, reused while the file's size and
modified time stay the same. Delete the folder to rebuild from scratch.
"""
import calendar
import collections
import glob
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time

PARSER_VERSION = 11

# Commands that are housekeeping, not work: they never count as a prompt or as a "command used".
HOUSEKEEPING = {
    '/mcp', '/model', '/login', '/logout', '/config', '/clear', '/compact', '/resume', '/exit', '/quit',
    '/help', '/terminal-setup', '/status', '/cost', '/feedback', '/init', '/doctor', '/permissions',
    '/bridge-probe', '/rename', '/color', '/theme', '/vim', '/usage', '/context', '/memory', '/hooks',
    '/agents', '/plugin', '/add-dir', '/export', '/ide', '/release-notes', '/upgrade', '/fast', '/effort',
    '/controller', '/remote-control', '/tasks', '/bashes', '/statusline', '/keybindings', '/sandbox',
}

NON_PROMPT_TAGS = ('<task-notification', '<local-command', '<bash-', '<user-memory-input', '<agent-message',
                   '<tools-used', '<command-stdout', '<command-stderr')

UUID_RE = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b')
URL_RE = re.compile(r'https?://[^\s<>"\'`\\\]\[(){}|^*]+')
JIRA_RE = re.compile(r'(?<![A-Za-z0-9/_.\-])([A-Z][A-Z0-9]{1,9})-(\d{1,6})(?![A-Za-z0-9_\-])')
BROWSE_RE = re.compile(r'atlassian\.net/browse/([A-Z][A-Z0-9]{1,9})-(\d{1,6})')
JIRA_HOST_RE = re.compile(r'https?://([A-Za-z0-9-]+\.atlassian\.net)/browse/')
CMD_NAME_RE = re.compile(r'<command-name>\s*(/[^<\s]+)\s*</command-name>')
CMD_ARGS_RE = re.compile(r'<command-args>(.*?)</command-args>', re.S)
USE_SKILL_RE = re.compile(r'\bUse the /([A-Za-z0-9:_.\-]+) skill\b')
LAUNCH_RE = re.compile(r'(?m)^([0-9a-f]{8}) (.{1,100}?) \((job|session), ([\w.\-]+)\) → ')
GUIDE_RE = re.compile(r'Guide opened in a new Ghostty window: (.{1,100}?) → ')
SYSREM_RE = re.compile(r'<system-reminder>.*?</system-reminder>\s*', re.S)
MDLINK_RE = re.compile(r'\[([^\]\n]{2,90})\]\((https?://[^)\s]+)\)')
GENERIC_LINK_TEXT = set('here link this thread message slack notion page source permalink url doc ticket it'.split())
TAG_RE = re.compile(r'</?[a-zA-Z][a-zA-Z0-9_\-]*(?:\s[^<>\n]{0,200})?>')
RECAP_TAIL_RE = re.compile(r'\s*\(disable recaps in /config\)\s*$')
CONTINUED_PREFIX = 'This session is being continued from a previous conversation'

# ---- keyword extraction -------------------------------------------------------------------------

NOISE_RE = re.compile(
    r'```.*?```'                                   # fenced code
    r'|`[^`\n]{1,200}`'                            # inline code
    r'|https?://\S+'                               # links
    r'|<[^>\n]{1,200}>'                            # tags
    r'|\bmcp__\S+'                                 # tool names
    r'|\S*[/\\]\S+'                                # paths
    r'|\b[\w\-]+\.(?:md|json|jsonl|py|sh|txt|html|css|tsx?|jsx?|csv|tsv|png|jpe?g|gif|pdf|ya?ml|zsh|log|xlsx|docx|toml|lock)\b'
    r'|\b\w+_\w+\b'                                # snake_case
    r'|\b[a-z]+[A-Z]\w+\b'                         # camelCase
    r'|\b[A-Z][A-Z0-9]{1,9}-\d+\b'                 # Jira keys (shown as links instead)
    r'|\b[0-9a-f]{7,}\b'                           # hashes / ids
    r'|\b\d[\w.:\-]*\b',                           # numbers, times, dates
    re.S)
SPLIT_RE = re.compile(r'[.,;:!?()\[\]{}|"“”‘\n\r\t*#>=+~→·—–]+|\s-\s')
WORD_RE = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'’\-]*[A-Za-zÀ-ɏ]|[A-Za-zÀ-ɏ]")

STOPWORDS = set('''
a about above across after afterwards again against ago ahead all almost alone along already also although always am
among an and another any anybody anyone anything anyway anywhere are aren't around as at away back be became because
become been before behind being below beside besides between beyond both but by came can can't cannot could couldn't
did didn't do does doesn't doing don't done down during each either else enough etc even ever every everyone everything
few for from further get gets getting give given gives go goes going gone got had hadn't has hasn't have haven't having
he her here hers herself him himself his how however i i'd i'll i'm i've if in into is isn't it it's its itself just
keep kept know known last later least less let let's like likely made make makes making many may maybe me might mine
more most much must my myself near need needs neither never next no nobody none nor not nothing now of off often on once
one ones only onto or other others our ours ourselves out over own per perhaps please put rather really right said same
saw say says see seem seemed seems seen several shall she should shouldn't since so some somebody someone something
sometimes soon still such take taken takes than that that's the their theirs them themselves then there there's these
they they'd they'll they're they've thing things think this those though through thus to together too took toward
towards under until up upon us use used uses using very via want wants was wasn't way we we'd we'll we're we've well
went were weren't what what's whatever when where whether which while who whom whose why will with within without won't
would wouldn't yes yet you you'd you'll you're you've your yours yourself yourselves
ok okay pls plz thx thanks thank cuz coz bc gonna wanna gotta yeah yep nope hey hi hello lol btw imo fyi asap tbh idk
u ur im dont doesnt cant wont didnt isnt thats whats lets ill ive youre theyre theres heres aint
sure fine good great nice cool awesome perfect exactly actually basically simply quite pretty bit lot lots kind sort
able also already always anything around bad best better big bigger biggest come comes coming different due early easy
end ends ever every example far feel find finds first found full fully hard help helps high idea important instead
later latest left long longer look looking looks low main mean means new non old open part place point possible
probably real same second set show showing shown shows small start started starting starts stuff tell third time times
today tomorrow yesterday top total try trying turn two three four five six seven eight nine ten was week weeks day days
month months year years hour hours minute minutes morning afternoon evening tonight monday tuesday wednesday thursday
friday saturday sunday mon tue wed thu fri sat sun jan feb mar apr jun jul aug sep sept oct nov dec january february
march april june july august september october november december
add added adding adds ask asked asking asks call called calls change changed changes check checked checking checks
click copy create created creates creating delete deleted did do done edit edited fix fixed gave get give include
included includes including keep move moved name named names note noted notes number numbers open opened order paste
read reading ready remove removed rename reply run running runs save saved send sent share shared type typed update
updated updates updating view write writing written wrote yet
file files folder folders line lines page pages link links list lists item items text word words step steps
thing section sections title titles key keys
claude session sessions tool tools prompt prompts command commands skill skills message messages chat
user assistant result results question questions answer answers reply summary context
option options current currently below above following based needed here's there's i'll i've
el la los las un una unos unas de del al y o u que qué en con por para como cómo es son esta este esto estos estas
pero si sí no ya muy más menos todo toda todos todas hay fue ser estar tiene tengo puede pueden hacer hecho bien
vale gracias hola porque cuando donde dónde sobre entre también solo sólo ahora aquí allí mi tu su nos les lo le se
'''.split())


# The person's own first name (from the home folder, e.g. "alex.smith" -> "alex") is in every session: not a keyword.
_me = re.split(r'[^a-z]+', os.path.basename(os.path.expanduser('~')).lower())[0]
USER_WORDS = set([_me, _me + 's']) if len(_me) > 2 else set()
STOPWORDS.update('true false null none enter press shift ctrl cmd tab esc todo tbd via'.split())
STOPWORDS.update('''
accept accepted according actual agree agreed ahead allow allowed allows answer appear appears apply applied approach
attempt available avoid aware became become begin behind believe bring brings broken build building built carry case
cases catch cause caused certain chance choose chosen clear clearly close closed cover covered covers decide decided
depends describe described detail details direct directly display displayed done double draft drafted earlier easier
either empty entire exact exists expect expected explain explained extra fact fail failed fails fast faster feels fewer
fill filled final finally finish finished fit fits flag flagged follow follows form format forward general goes
handle handled happen happened happens having hold holds idea ideas instead issue issues join joined kept knows large
larger leave leaves length less let level likely limit limited live load loaded longer lost matter matters maybe mention
mentioned might miss missed missing mostly moving needed neither normal nowhere obvious offer offered okay often
original otherwise overall own pass passed past pick picked piece places plain plus position prefer present previous
problem problems proper provide provided pull pushed quick raise raised rather reach reached reason reasons recent
refer related remain remains replace replaced require required rest return returned returns round safe seems select
selected separate short shorter side similar simple single skip skipped slow somewhere sorted specific stay stays stop
stopped straight suggest suggested suggestion suggests support supposed switch switched taking tried tries turn turned
unclear understand unless unsure usual wait waiting whole wide wider willing wish within wonder working works worth
wrong yourself anymore else everywhere focus focusing matching count counts search retry process processed planned
recorded refreshed caught scanned claiming weigh casual exist kind kinds half again mine
'''.split())
LY_KEEP = set('weekly monthly yearly quarterly hourly daily biweekly anomaly family supply assembly multiply reply apply'.split())


def norm_cmd(name):
    """'/anthropic-skills:release-note-creator' and 'release-note-creator' are the same command: '/release-note-creator'."""
    name = (name or '').strip().lstrip('/')
    if ':' in name:
        name = name.rsplit(':', 1)[1]
    return '/' + name if name else ''


def iso_to_ms(s):
    """'2026-10-22T11:14:58.900Z' -> epoch milliseconds (UTC). Returns None when it can't be read."""
    try:
        secs = calendar.timegm((int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19]), 0, 0, 0))
        frac = s[20:23] if len(s) > 20 and s[19] == '.' else ''
        return secs * 1000 + (int(frac) if frac.isdigit() else 0)
    except (ValueError, IndexError, TypeError):
        return None


def encode_cwd(cwd):
    """How Claude Code names a project folder: every character that is not a letter or digit becomes '-'."""
    return re.sub(r'[^A-Za-z0-9]', '-', cwd or '')


def clean_url(u):
    u = u.rstrip('.,;:!?\'")>]}')
    # markdown leftovers like "...)**" or "...](" are cut by URL_RE already; drop a dangling '&' or '?'
    return u.rstrip('&?')


def squash(text, limit):
    """One-line version of a text, cut at a word boundary."""
    t = ' '.join((text or '').split())
    if len(t) <= limit:
        return t
    cut = t[:limit]
    sp = cut.rfind(' ')
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(' ,;:.-') + '…'


def first_sentences(text, limit):
    """The opening of a reply: skips headings, tables and bullets markup; cut to ~limit characters."""
    lines = []
    for ln in (text or '').split('\n'):
        s = ln.strip()
        if not s or s.startswith(('|', '```', '---', '===')):
            continue
        s = re.sub(r'^(#{1,6}\s+|[-*•]\s+|\d+[.)]\s+|>\s+)', '', s)
        s = re.sub(r'\*\*|__|`', '', s)
        s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', s)
        lines.append(s)
        if sum(len(x) for x in lines) > limit:
            break
    return squash(' '.join(lines), limit)


class _Terms(object):
    """Counts words and word pairs for one session."""
    __slots__ = ('tf', 'caps', 'cap1', 'bi', 'ntok', 'budget')

    def __init__(self):
        self.tf = collections.Counter()
        self.caps = collections.Counter()
        self.cap1 = collections.Counter()
        self.bi = collections.Counter()
        self.ntok = 0
        self.budget = 260000

    def add(self, text, weight, limited=False):
        if not text:
            return
        if limited:
            if self.budget <= 0:
                return
            self.budget -= len(text)
        text = NOISE_RE.sub(' ', text[:40000])
        tf, caps, cap1, bi = self.tf, self.caps, self.cap1, self.bi
        stop = STOPWORDS
        for chunk in SPLIT_RE.split(text):
            if len(chunk) < 2:
                continue
            prev = None
            for w in WORD_RE.findall(chunk):
                w = w.strip("'’-")
                n = len(w)
                lw = w.lower()
                if lw.endswith("'s") or lw.endswith('’s'):
                    lw = lw[:-2]
                    w = w[:-2]
                    n -= 2
                if n < 3:
                    if not (n == 2 and w.isupper()):
                        prev = None
                        continue
                if n > 24 or lw in stop or (n > 5 and lw.endswith('ly') and lw not in LY_KEEP):
                    prev = None
                    continue
                self.ntok += 1
                tf[lw] += weight
                if n > 1 and w.isupper():
                    caps[lw] += 1
                elif w[0].isupper():
                    cap1[lw] += 1
                if prev is not None:
                    bi[prev + ' ' + lw] += weight
                prev = lw


def _user_text(content):
    """(text, has_tool_result) of a user message's content."""
    if isinstance(content, str):
        return content, False
    texts = []
    has_tr = False
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get('type')
            if bt == 'text':
                texts.append(b.get('text') or '')
            elif bt == 'tool_result':
                has_tr = True
    return '\n'.join(texts), has_tr


def _walk_result_text(content):
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                bt = b.get('type')
                if bt == 'text':
                    yield b.get('text') or ''
                elif bt == 'tool_result':
                    for x in _walk_result_text(b.get('content')):
                        yield x


_ARROW_RAW = (b'\xe2\x86\x92', b'\\u2192')


def parse_session(path):
    """Read one transcript and return {'meta': {...}, 'text': str, 'uuids': [...], 'uts': [...]}.

    Streams the file line by line (files can be 50 MB). Never raises on a bad line: it is counted and skipped.
    """
    st = os.stat(path)
    sid = os.path.basename(path)[:-6]
    dir_name = os.path.basename(os.path.dirname(path))

    prompts = replies = tools = compactions = bad = images = 0
    starts_with_compact = False
    first_prompt = last_prompt = first_reply = last_reply = None
    first_ts = last_ts = None
    first_prompt_ts = None
    ai_title = custom_title = agent_name = None
    continued_in = None
    worktree = None
    relocated = None
    cost = None
    cwds = collections.Counter()
    cwd_first = cwd_last = None
    entries = collections.Counter()
    models = collections.Counter()
    commands = collections.Counter()
    tool_names = collections.Counter()
    urls = collections.Counter()
    jira = collections.Counter()
    artifacts = {}
    url_labels = {}
    recaps = []
    refs = []
    launches = []
    guides = []
    uuids = []
    uts = []
    segments = []
    seg_chars = 0
    bg = False
    terms = _Terms()

    def scan_links(text, weight=1):
        if 'http' in text:
            for m in URL_RE.finditer(text):
                u = clean_url(m.group(0))
                if len(u) > 12 and len(u) < 400:
                    urls[u] += weight
            if '](http' in text:
                for m in MDLINK_RE.finditer(text):
                    u = clean_url(m.group(2))
                    lab = m.group(1).strip('*_` ')
                    if u not in url_labels and len(lab) > 1 and not lab.startswith('http'):
                        url_labels[u] = lab
        if '-' in text:
            for m in JIRA_RE.finditer(text):
                jira[m.group(0)] += weight

    def add_segment(text):
        nonlocal seg_chars
        if seg_chars > 1500000:
            return
        t = text if len(text) <= 60000 else text[:60000]
        segments.append(t)
        seg_chars += len(t)

    try:
        fh = open(path, 'rb')
    except OSError:
        return None
    with fh:
        for raw in fh:
            if len(raw) < 12:
                continue
            if raw.startswith(b'{"type":"api-request'):
                continue
            if raw.startswith(b'{"parentUuid":') and b'"attachment":{' in raw[:200]:
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                bad += 1
                continue
            if not isinstance(d, dict):
                continue
            t = d.get('type')

            if t == 'user' or t == 'assistant':
                if d.get('isSidechain'):
                    continue
                ts = d.get('timestamp')
                uu = d.get('uuid')
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                if uu:
                    uuids.append(uu)
                    ms = iso_to_ms(ts) if ts else None
                    uts.append(int(ms // 1000) if ms else 0)
                cwd = d.get('cwd')
                if cwd:
                    cwds[cwd] += 1
                    if cwd_first is None:
                        cwd_first = cwd
                    cwd_last = cwd
                ep = d.get('entrypoint')
                if ep:
                    entries[ep] += 1
                if d.get('sessionKind') == 'bg':
                    bg = True
                msg = d.get('message')
                if not isinstance(msg, dict):
                    continue

                if t == 'user':
                    text, has_tr = _user_text(msg.get('content'))
                    if has_tr:
                        if (b'(job, ' in raw or b'(session, ' in raw or b'Guide opened' in raw) and \
                                (_ARROW_RAW[0] in raw or _ARROW_RAW[1] in raw):
                            ms = iso_to_ms(ts) if ts else None
                            for txt in _walk_result_text(msg.get('content')):
                                for m in LAUNCH_RE.finditer(txt):
                                    launches.append([m.group(1), m.group(2).strip(), ms, uu, m.group(3)])
                                for m in GUIDE_RE.finditer(txt):
                                    guides.append([m.group(1).strip(), ms, uu])
                        continue
                    if d.get('isCompactSummary'):
                        compactions += 1
                        if prompts == 0:
                            starts_with_compact = True
                        continue
                    if d.get('isMeta') or d.get('promptSource') == 'system':
                        continue
                    if '<system-reminder>' in text:
                        text = SYSREM_RE.sub('', text)
                    text = text.strip()
                    if not text:
                        continue
                    if text.startswith(CONTINUED_PREFIX):
                        compactions += 1
                        if prompts == 0:
                            starts_with_compact = True
                        continue
                    if text[0] == '<':
                        m = CMD_NAME_RE.search(text[:600])
                        if m:
                            name = norm_cmd(m.group(1))
                            if name in HOUSEKEEPING:
                                continue
                            a = CMD_ARGS_RE.search(text)
                            args = a.group(1).strip() if a else ''
                            commands[name] += 1
                            text = (name + ' ' + args).strip()
                        elif text.startswith(NON_PROMPT_TAGS):
                            continue
                        else:
                            text = TAG_RE.sub(' ', text).strip()
                            if not text:
                                continue
                    prompts += 1
                    if first_prompt is None:
                        first_prompt = text
                        first_prompt_ts = ts
                        for m in UUID_RE.finditer(text[:2000]):
                            if m.group(0) != sid and m.group(0) not in refs:
                                refs.append(m.group(0))
                    last_prompt = text
                    for m in USE_SKILL_RE.finditer(text[:400]):
                        commands[norm_cmd(m.group(1))] += 1
                    scan_links(text, 3)
                    terms.add(text, 3)
                    add_segment(text)
                else:
                    if d.get('isApiErrorMessage'):
                        continue
                    model = msg.get('model')
                    if model == '<synthetic>':
                        continue
                    if model:
                        models[model] += 1
                    content = msg.get('content')
                    if not isinstance(content, list):
                        continue
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        bt = b.get('type')
                        if bt == 'text':
                            txt = b.get('text') or ''
                            if not txt.strip():
                                continue
                            replies += 1
                            if first_reply is None:
                                first_reply = txt
                            last_reply = txt
                            scan_links(txt, 1)
                            terms.add(txt, 1, limited=True)
                            add_segment(txt)
                        elif bt == 'tool_use':
                            tools += 1
                            name = b.get('name') or ''
                            tool_names[name] += 1
                            inp = b.get('input')
                            if isinstance(inp, dict):
                                if name == 'Skill':
                                    sk = inp.get('skill')
                                    if isinstance(sk, str) and sk.strip('/ '):
                                        commands[norm_cmd(sk)] += 1
                                for v in inp.values():
                                    if isinstance(v, str) and len(v) < 4000:
                                        scan_links(v, 1)
                continue

            if t == 'system':
                if d.get('subtype') == 'away_summary':
                    c = d.get('content')
                    if isinstance(c, str) and c.strip():
                        recaps.append(RECAP_TAIL_RE.sub('', c.strip()))
                        if len(recaps) > 6:
                            del recaps[0]
                ts = d.get('timestamp')
                if ts and (last_ts is None or ts > last_ts):
                    last_ts = ts
            elif t == 'ai-title':
                ai_title = d.get('aiTitle') or ai_title
            elif t == 'custom-title':
                custom_title = d.get('customTitle') or custom_title
            elif t == 'agent-name':
                agent_name = d.get('agentName') or agent_name
            elif t == 'continued-in':
                continued_in = d.get('continuedInSessionId') or continued_in
            elif t == 'worktree-state':
                ws = d.get('worktreeSession')
                if isinstance(ws, dict) and ws.get('worktreePath'):
                    worktree = {'name': ws.get('worktreeName') or os.path.basename(ws.get('worktreePath')),
                                'path': ws.get('worktreePath'), 'original': ws.get('originalCwd')}
            elif t == 'relocated':
                relocated = d.get('relocatedCwd') or relocated
            elif t == 'frame-link':
                fu = d.get('frameUrl')
                if isinstance(fu, str) and fu.startswith(('http://', 'https://')):
                    artifacts[fu] = d.get('title') or artifacts.get(fu) or ''
            elif t == 'cost-state':
                c = d.get('totalCostUSD')
                if isinstance(c, (int, float)):
                    cost = c

    # ---- derive ---------------------------------------------------------------------------------
    entry = entries.most_common(1)[0][0] if entries else None
    if entry == 'sdk-cli':
        kind = 'auto'
    elif bg:
        kind = 'helper'
    elif entry == 'claude-desktop':
        kind = 'desktop'
    else:
        kind = 'you'

    # The folder to open this session from: the cwd whose encoded name is the transcript's folder.
    resume_cwd = None
    for c in cwds:
        if encode_cwd(c) == dir_name:
            resume_cwd = c
            break
    if resume_cwd is None:
        resume_cwd = relocated if (relocated and encode_cwd(relocated) == dir_name) else (cwd_last or cwd_first)
    if worktree is None and resume_cwd and '/.claude/worktrees/' in resume_cwd:
        base, name = resume_cwd.split('/.claude/worktrees/', 1)
        worktree = {'name': name.split('/')[0], 'path': resume_cwd, 'original': base}

    if custom_title:
        title, title_src = custom_title, 'custom'
    elif ai_title:
        title, title_src = ai_title, 'ai'
    elif agent_name:
        title, title_src = agent_name, 'name'
    elif first_prompt:
        title, title_src = squash(first_prompt.split('\n', 1)[0] if not first_prompt.startswith('/') else first_prompt, 90), 'prompt'
    else:
        title, title_src = '(empty session)', 'none'
    if not isinstance(title, str):          # a format change must not break the whole board
        title = str(title)

    top_terms = terms.tf.most_common(240)
    tf = dict(top_terms)
    caps = {k: terms.caps[k] for k in tf if terms.caps.get(k)}
    cap1 = {k: terms.cap1[k] for k in tf if terms.cap1.get(k)}
    bi = {k: v for k, v in terms.bi.most_common(90) if v >= 2}

    start_ms = iso_to_ms(first_ts) if first_ts else None
    end_ms = iso_to_ms(last_ts) if last_ts else None

    sub_dir = os.path.join(os.path.dirname(path), sid, 'subagents')
    try:
        subagents = sum(1 for n in os.listdir(sub_dir) if n.endswith('.jsonl'))
    except OSError:
        subagents = 0

    meta = {
        'id': sid, 'path': path, 'dir': dir_name, 'size': st.st_size, 'mtime': st.st_mtime,
        'birth': getattr(st, 'st_birthtime', None),
        'cwd': resume_cwd, 'cwdFirst': cwd_first, 'worktree': worktree,
        'entry': entry, 'bg': bg, 'kind': kind,
        'title': title, 'titleSource': title_src,
        'start': start_ms, 'end': end_ms, 'firstPromptAt': iso_to_ms(first_prompt_ts) if first_prompt_ts else None,
        'prompts': prompts, 'replies': replies, 'tools': tools, 'compactions': compactions,
        'startsWithCompact': starts_with_compact,
        'firstPrompt': (first_prompt or '')[:1600], 'lastPrompt': (last_prompt or '')[:1600],
        'firstReply': (first_reply or '')[:1600], 'lastReply': (last_reply or '')[:2400],
        'recaps': recaps[-3:],
        'commands': dict(commands.most_common(30)),
        'toolTop': tool_names.most_common(6),
        'urls': dict(urls.most_common(80)), 'jira': dict(jira.most_common(60)),
        'urlLabels': dict((u, url_labels[u]) for u, _ in urls.most_common(80) if u in url_labels),
        'artifacts': artifacts,
        'model': models.most_common(1)[0][0] if models else None,
        'cost': cost, 'continuedIn': continued_in, 'refs': refs[:8],
        'launches': launches, 'guides': guides,
        'tf': tf, 'caps': caps, 'cap1': cap1, 'bi': bi, 'ntok': terms.ntok,
        'subagents': subagents, 'bad': bad,
    }
    return {'meta': meta, 'text': '\n\n'.join(segments), 'uuids': uuids, 'uts': uts}


def _parse_safe(path):
    try:
        return path, parse_session(path), None
    except Exception as e:  # never let one odd file stop the index
        return path, None, '%s: %s' % (type(e).__name__, e)


# ---- derived data: keywords ---------------------------------------------------------------------

def _display_form(term, tf, caps, cap1):
    def one(w):
        n = tf.get(w, 0) or 1
        weightless = max(1.0, n / 2.0)       # tf is weighted (x3 for the user's words); caps counts are raw
        if caps.get(w, 0) >= weightless * 0.5 or (len(w) <= 3 and caps.get(w, 0) >= 1 and caps.get(w, 0) >= cap1.get(w, 0)):
            return w.upper()
        if cap1.get(w, 0) + caps.get(w, 0) >= weightless * 0.6 and cap1.get(w, 0) >= 2:
            return w[:1].upper() + w[1:]
        return w
    return ' '.join(one(w) for w in term.split(' '))


def compute_keywords(metas, want=7):
    """{sid: [keyword, ...]} using a cheap TF-IDF across all sessions (words + two-word phrases)."""
    n_docs = 0
    df = collections.Counter()
    for m in metas.values():
        tf = m.get('tf') or {}
        if not tf:
            continue
        n_docs += 1
        for w in tf:
            df[w] += 1
        for b in (m.get('bi') or {}):
            df[b] += 1
    if n_docs == 0:
        return {sid: [] for sid in metas}

    def idf(term):
        return math.log((n_docs + 1.0) / (df[term] + 0.5))

    out = {}
    for sid, m in metas.items():
        tf = m.get('tf') or {}
        bi = m.get('bi') or {}
        caps = m.get('caps') or {}
        cap1 = m.get('cap1') or {}
        if not tf:
            out[sid] = []
            continue
        ntok = m.get('ntok') or 0
        chosen = []
        # strict first; relax for short sessions so they still get a handful of keywords
        for min_tf, min_bi in ((3 if ntok >= 400 else 2, 4), (1, 3)):
            scored = []
            for w, c in tf.items():
                if c < min_tf or w in USER_WORDS:
                    continue
                if len(w) > 4 and w.endswith('s') and not w.endswith('ss') and w[:-1] in tf:
                    continue                  # plural folded into its singular
                c2 = c + (tf.get(w + 's', 0) if len(w) > 3 else 0)
                i = idf(w)
                if i < 0.25:
                    continue                  # in nearly every session: says nothing about this one
                scored.append((math.sqrt(c2) * (i ** 1.4), w, c2))
            for b, c in bi.items():
                if c < min_bi:
                    continue
                p1, p2 = b.split(' ', 1)
                if p1 in USER_WORDS or p2 in USER_WORDS or p1 == p2:
                    continue
                i1, i2 = idf(p1), idf(p2)
                if min(i1, i2) < 0.35:
                    continue
                eff = min(idf(b), (i1 + i2) / 2.0 * 1.25)
                scored.append((1.35 * math.sqrt(c) * (eff ** 1.4), b, c))
            scored.sort(reverse=True)
            chosen = []
            used = set()
            phrase_words = set()
            n_phrases = 0
            for score, term, c in scored:
                parts = term.split(' ')
                if len(parts) == 1:
                    if term in used:
                        continue
                    stem = term[:max(4, len(term) - 3)]
                    if len(term) > 5 and any(x != term and x.startswith(stem) for x in used):
                        continue              # "override" / "overrides" / "overriding"
                else:
                    if n_phrases >= 3 or any(p in phrase_words for p in parts):
                        continue
                    chosen = [x for x in chosen if x[1] not in parts]     # the phrase replaces its words
                    n_phrases += 1
                    phrase_words.update(parts)
                chosen.append((score, term, c))
                used.update(parts)
                if len(chosen) >= want + 3:
                    break
            if len(chosen) >= min(want, 5):
                break
        out[sid] = [_display_form(t, tf, caps, cap1) for _, t, _ in chosen[:want]]
    return out


# ---- derived data: links between sessions --------------------------------------------------------

EDGE_WHY = {
    'continued': 'Continued from',
    'fork': 'Forked from',
    'handover': 'Handover from',
    'helper': 'Helper started by',
    'worktree': 'Worktree session of',
}


def read_runs(work_root):
    """Optional: rows of <work folder>/.state/sessions/<date>/runs.tsv, a log some launcher scripts keep of the
    background sessions they start (id8, name, kind, model, skill, time). Nothing breaks when it is absent."""
    rows = []
    if not work_root:
        return rows
    for f in sorted(glob.glob(os.path.join(work_root, '.state', 'sessions', '*', 'runs.tsv'))):
        date = os.path.basename(os.path.dirname(f))
        try:
            with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    p = line.rstrip('\n').split('\t')
                    if len(p) >= 6 and re.match(r'^[0-9a-f]{8}$', p[0]):
                        rows.append({'date': date, 'id8': p[0], 'name': p[1], 'kind': p[2], 'model': p[3],
                                     'skill': p[4], 'time': p[5]})
        except OSError:
            continue
    return rows


def _born(m):
    b = m.get('birth')
    if b:
        return b * 1000.0
    return m.get('start') or 0


def _is_hq(m):
    """A "home base" session that starts others: one named HQ (a convention, nothing more)."""
    t = (m.get('title') or '')
    return t == 'HQ' or t.startswith('HQ ') or ' HQ' in t


def detect_relations(metas, uu, runs=None):
    """Returns (edges, own_start).

    edges: [{'id','from','to','kind','guess','why'}], parent -> child.
    own_start: {sid: ms} for sessions that begin with a copy of another session's history (forks,
    continuations): the time of their first own message.
    """
    runs = runs or []
    edges = {}
    own_start = {}

    def add(frm, to, kind, guess=False):
        if frm == to or frm not in metas or to not in metas:
            return
        eid = 'a:%s:%s' % (frm, to)
        if eid in edges:
            return
        edges[eid] = {'id': eid, 'from': frm, 'to': to, 'kind': kind, 'guess': bool(guess),
                      'why': EDGE_WHY.get(kind, kind)}

    # (a1) shared history: the same message ids in two transcripts
    occ = collections.defaultdict(list)
    for sid, (uuids, _uts) in uu.items():
        if sid not in metas:
            continue
        for u in set(uuids):
            occ[u].append(sid)
    shared = collections.Counter()
    for u, sids in occ.items():
        if len(sids) > 1:
            sids.sort()
            for i in range(len(sids)):
                for j in range(i + 1, len(sids)):
                    shared[(sids[i], sids[j])] += 1
    partners = collections.defaultdict(list)
    for (a, b), n in shared.items():
        if n >= 2:
            partners[a].append((b, n))
            partners[b].append((a, n))
    has_history_parent = set()
    for sid, plist in partners.items():
        me = metas[sid]
        cands = [(n, _born(metas[o]), o) for o, n in plist if _born(metas[o]) < _born(me) - 500]
        if not cands:
            continue
        cands.sort(reverse=True)
        n, _b, parent = cands[0]
        kind = 'continued' if metas[parent].get('continuedIn') == sid else 'fork'
        add(parent, sid, kind)
        has_history_parent.add(sid)
        pset = set(uu[parent][0])
        uuids, uts = uu[sid]
        first_own = None
        for i, u in enumerate(uuids):
            if u not in pset:
                if i < len(uts) and uts[i]:
                    first_own = uts[i] * 1000
                break
        if first_own is None:
            first_own = int(_born(me)) or me.get('start')
        own_start[sid] = first_own

    # (a2) explicit "continued in" records without shared ids
    for sid, m in metas.items():
        c = m.get('continuedIn')
        if c and c in metas and c not in has_history_parent:
            add(sid, c, 'continued')
            has_history_parent.add(c)

    def start_of(sid):
        return own_start.get(sid) or metas[sid].get('start') or 0

    # (a3) starts with a compaction summary and nothing else explains it: most recent earlier session, same folder
    for sid, m in metas.items():
        if not m.get('startsWithCompact') or sid in has_history_parent:
            continue
        s0 = start_of(sid)
        best = None
        for o, om in metas.items():
            if o == sid or om.get('cwd') != m.get('cwd') or om.get('kind') == 'auto':
                continue
            oe = om.get('end') or 0
            if (om.get('start') or 0) < s0 and oe <= s0 + 300000:
                if best is None or oe > best[0]:
                    best = (oe, o)
        if best:
            add(best[1], sid, 'continued', guess=True)
            has_history_parent.add(sid)

    # handover: the first prompt names another session id
    for sid, m in metas.items():
        for ref in m.get('refs') or []:
            if ref in metas and ('a:%s:%s' % (ref, sid)) not in edges:
                add(ref, sid, 'handover')

    # (b) helpers: a launcher script that prints "<id8> <name> (job|session, model) -> file" into the parent's transcript
    by8 = {}
    for sid in metas:
        by8.setdefault(sid[:8], sid)
    runs_by_name = collections.defaultdict(list)
    for r in runs:
        runs_by_name[r['name']].append(r)
    claims = collections.defaultdict(list)
    for sid, m in metas.items():
        for item in m.get('launches') or []:
            child = by8.get(item[0])
            if child and child != sid:
                claims[child].append(sid)
        for item in m.get('guides') or []:
            name, ts = item[0], item[1]
            child = None
            for r in runs_by_name.get(name, []):
                c = by8.get(r['id8'])
                if c and abs((metas[c].get('start') or 0) - (ts or 0)) < 3600000:
                    child = c
                    break
            if child is None:
                for o, om in metas.items():
                    if om.get('title') == name and abs((om.get('start') or 0) - (ts or 0)) < 900000:
                        child = o
                        break
            if child and child != sid:
                claims[child].append(sid)
    has_parent = set(has_history_parent)
    for e in edges.values():
        has_parent.add(e['to'])
    for child, parents in claims.items():
        parents = sorted(set(parents), key=lambda p: _born(metas[p]))
        add(parents[0], child, 'helper')       # the original, not its later copy
        has_parent.add(child)

    def local_day(ms):
        return time.strftime('%Y-%m-%d', time.localtime((ms or 0) / 1000.0))

    def active_parent(sid, need_hq):
        m = metas[sid]
        s0 = start_of(sid)
        day = local_day(s0)
        root = (m.get('worktree') or {}).get('original') or m.get('cwd')
        best = None
        for o, om in metas.items():
            if o == sid or om.get('kind') != 'you' or om.get('cwd') != root:
                continue
            if need_hq and not _is_hq(om):
                continue
            os_, oe = start_of(o), (om.get('end') or 0)
            if os_ > s0 or local_day(os_) > day:
                continue
            spans = oe + 1800000 >= s0
            if not spans and local_day(oe) != day and local_day(os_) != day:
                continue
            rank = (1 if spans else 0, 1 if _is_hq(om) else 0, os_)
            if best is None or rank > best[0]:
                best = (rank, o)
        return best[1] if best else None

    # (b) fallback: a helper nobody claimed -> the HQ session that was running that day (a guess)
    for sid, m in metas.items():
        if sid in has_parent or m.get('kind') != 'helper':
            continue
        p = active_parent(sid, need_hq=True)
        if p:
            add(p, sid, 'helper', guess=True)
            has_parent.add(sid)

    # (c) worktree sessions: belong to the parent project; link to the session active there (a guess)
    for sid, m in metas.items():
        if sid in has_parent or not m.get('worktree'):
            continue
        p = active_parent(sid, need_hq=False)
        if p:
            add(p, sid, 'worktree', guess=True)
            has_parent.add(sid)

    return list(edges.values()), own_start


# ---- link labels ---------------------------------------------------------------------------------

def classify_url(u):
    low = u.lower()
    host = low.split('//', 1)[-1].split('/', 1)[0]
    if host.endswith('slack.com'):
        return 'slack'
    if 'notion.' in host:
        return 'notion'
    if host.endswith('atlassian.net'):
        return 'jira'
    if host.endswith('figma.com'):
        return 'figma'
    if host.endswith('claude.ai') and '/artifact' in low:
        return 'artifact'
    if host.endswith('github.com'):
        return 'github'
    if host.endswith('google.com'):
        return 'google'
    if host in ('localhost', '127.0.0.1') or host.startswith(('localhost:', '127.0.0.1:')):
        return None
    return 'web'


def label_url(u, cls, text=None):
    """A short human label for a link. `text` is the wording Claude used for it in a reply, when known."""
    if text and cls != 'jira':
        t = ' '.join(text.split())
        if t.lower() not in GENERIC_LINK_TEXT and not re.match(r'^[\W\d]+$', t):
            prefix = {'slack': 'Slack', 'notion': 'Notion', 'figma': 'Figma', 'google': 'Google', 'github': 'GitHub'}.get(cls)
            return (prefix + ' · ' + t[:70]) if prefix else t[:80]
    path = u.split('//', 1)[-1].split('/', 1)[-1] if '/' in u.split('//', 1)[-1] else ''
    path = path.split('?', 1)[0].split('#', 1)[0]
    if cls == 'slack':
        m = re.search(r'/archives/([A-Z0-9]+)(?:/p(\d{10})\d*)?', u)
        if m and m.group(2):
            when = time.strftime('%a %d %b %H:%M', time.localtime(int(m.group(2))))
            return 'Slack message · ' + when
        if m:
            return 'Slack channel ' + m.group(1)
        return 'Slack'
    if cls == 'notion':
        last = path.rstrip('/').rsplit('/', 1)[-1]
        m = re.match(r'^(.*?)-?([0-9a-f]{32})$', last)
        name = (m.group(1) if m else last).replace('-', ' ').strip()
        if name and not re.match(r'^[0-9a-f]{32}$', name):
            return 'Notion · ' + name[:60]
        return 'Notion page ' + ((m.group(2) if m else last)[:6])
    if cls == 'jira':
        m = BROWSE_RE.search(u)
        if m:
            return '%s-%s' % (m.group(1), m.group(2))
        m = re.search(r'/boards/(\d+)', u)
        if m:
            return 'Jira board ' + m.group(1)
        m = re.search(r'/projects/([A-Z][A-Z0-9]+)', u)
        if m:
            return 'Jira project ' + m.group(1)
        return 'Jira · ' + (path.rstrip('/').rsplit('/', 1)[-1][:40] or 'link')
    if cls == 'figma':
        parts = [p for p in path.split('/') if p]
        return 'Figma · ' + (parts[2].replace('-', ' ')[:50] if len(parts) > 2 else 'file')
    if cls == 'artifact':
        return 'Claude artifact'
    host = u.split('//', 1)[-1].split('/', 1)[0]
    tail = path.rstrip('/').rsplit('/', 1)[-1][:40]
    return host + (' · ' + tail if tail else '')


def build_links(meta, allowed_prefixes, jira_hosts=None):
    """Clickable links of one session, grouped: jira, slack, notion, artifact, figma, github, google, web."""
    groups = collections.OrderedDict((k, []) for k in ('jira', 'slack', 'notion', 'artifact', 'figma', 'github', 'google', 'web'))
    seen_jira = {}
    labels = meta.get('urlLabels') or {}
    for key, n in (meta.get('jira') or {}).items():
        if key.split('-', 1)[0] in allowed_prefixes:
            seen_jira[key] = seen_jira.get(key, 0) + n
    for u, n in (meta.get('urls') or {}).items():
        cls = classify_url(u)
        if cls is None:
            continue
        if cls == 'jira':
            m = BROWSE_RE.search(u)
            if m:
                key = '%s-%s' % (m.group(1), m.group(2))
                seen_jira[key] = seen_jira.get(key, 0) + n
                continue
            if '/browse/' in u or u.rstrip('/').endswith('atlassian.net'):
                continue                      # a placeholder such as /browse/KEY, or the bare site
        if cls == 'artifact':
            continue
        groups[cls].append({'url': u, 'label': label_url(u, cls, labels.get(u)), 'n': n})
    jira_hosts = jira_hosts or {}

    def key_url(key):
        host = jira_hosts.get(key.split('-', 1)[0])
        return ('https://%s/browse/%s' % (host, key)) if host else None
    keys = [{'url': key_url(key), 'label': key, 'n': n, 'key': True}
            for key, n in sorted(seen_jira.items(), key=lambda kv: (-kv[1], kv[0]))]
    keys = [k for k in keys if k['url']]
    groups['jira'] = keys + groups['jira']
    arts = dict(meta.get('artifacts') or {})
    for u, n in (meta.get('urls') or {}).items():
        if classify_url(u) == 'artifact' and u not in arts:
            arts[u] = ''
    for u, title in arts.items():
        groups['artifact'].append({'url': u, 'label': 'Artifact · ' + title if title else 'Claude artifact', 'n': 1})
    for k in groups:
        if k != 'jira':
            groups[k].sort(key=lambda x: -x['n'])
        del groups[k][14:]
    return groups


def make_about(m):
    """One or two plain lines: what was asked, and how it ended."""
    ask = m.get('firstPrompt') or ''
    if ask.startswith('/'):
        ask_line = squash(ask, 120)
    else:
        ask_line = squash(ask, 150)
    recaps = m.get('recaps') or []
    if recaps:
        outcome = squash(recaps[-1], 260)
    else:
        outcome = first_sentences(m.get('lastReply') or '', 220)
    if ask_line and outcome:
        return ask_line + ' → ' + outcome
    return ask_line or outcome or ''


# ---- the index -----------------------------------------------------------------------------------

class Index(object):
    def __init__(self, cache_dir, projects_root=None, work_root=None, use_pool=True):
        self.cache_dir = cache_dir
        self.projects_root = projects_root or os.path.join(os.path.expanduser('~'), '.claude', 'projects')
        self.work_root = work_root
        self.use_pool = use_pool
        self.lock = threading.RLock()
        self.metas = {}          # path -> meta
        self.texts = {}          # sid -> text
        self.lowers = {}         # sid -> lowercased text (built on first search)
        self.uu = {}             # sid -> (uuids, uts)
        self.sig = {}            # path -> (mtime_ns, size)
        self.generation = 0
        self.loaded = False
        self.progress = {'state': 'starting', 'done': 0, 'total': 0, 'parsed': 0}
        self.last_stats = {}
        self.last_refresh = 0.0
        self.errors = []
        self._payload = None
        self._details = {}
        os.makedirs(cache_dir, exist_ok=True)

    # -- cache --
    def _db(self):
        db = sqlite3.connect(os.path.join(self.cache_dir, 'index.db'), timeout=30)
        db.execute('CREATE TABLE IF NOT EXISTS sessions (path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, '
                   'ver INTEGER, meta TEXT, txt TEXT, uuids TEXT, uts TEXT)')
        return db

    def _load_cache(self):
        try:
            db = self._db()
            rows = db.execute('SELECT path, mtime_ns, size, ver, meta, txt, uuids, uts FROM sessions').fetchall()
            db.close()
        except sqlite3.Error as e:
            self.errors.append('cache unreadable, rebuilding: %s' % e)
            try:
                os.remove(os.path.join(self.cache_dir, 'index.db'))
            except OSError:
                pass
            return
        for path, mtime_ns, size, ver, meta, txt, uuids, uts in rows:
            if ver != PARSER_VERSION:
                continue
            try:
                m = json.loads(meta)
            except ValueError:
                continue
            self.metas[path] = m
            self.sig[path] = (mtime_ns, size)
            self.texts[m['id']] = txt or ''
            ul = uuids.split('\n') if uuids else []
            tl = [int(x) for x in uts.split(',')] if uts else []
            self.uu[m['id']] = (ul, tl)

    def scan_files(self):
        out = []
        try:
            dirs = sorted(os.listdir(self.projects_root))
        except OSError:
            return out
        for dname in dirs:
            dpath = os.path.join(self.projects_root, dname)
            try:
                names = os.listdir(dpath)
            except OSError:
                continue
            for n in names:
                if not n.endswith('.jsonl'):
                    continue
                p = os.path.join(dpath, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_size == 0:
                    continue
                out.append((p, st.st_mtime_ns, st.st_size))
        return out

    def refresh(self, force=False):
        """Bring the index up to date. Returns stats. Safe to call from several threads (one runs at a time)."""
        with self.lock:
            t0 = time.time()
            if not self.loaded:
                self._load_cache()
                self.loaded = True
                first = True
            else:
                first = False
            files = self.scan_files()
            current = set(p for p, _, _ in files)
            todo = [p for p, mt, sz in files if force or self.sig.get(p) != (mt, sz)]
            gone = [p for p in list(self.metas) if p not in current]
            self.progress = {'state': 'indexing' if todo else 'ready', 'done': len(files) - len(todo),
                             'total': len(files), 'parsed': 0}
            sigs = dict((p, (mt, sz)) for p, mt, sz in files)
            results = []
            if todo:
                results = self._parse_many(todo)
            changed = bool(results or gone or first)
            if results or gone:
                db = self._db()
                for path, res, err in results:
                    if err or res is None:
                        self.errors.append('%s: %s' % (os.path.basename(path), err or 'unreadable'))
                        del self.errors[:-50]
                        self.sig[path] = sigs.get(path)      # do not retry until the file changes
                        continue
                    m = res['meta']
                    old = self.metas.get(path)
                    if old and old.get('id') in self.lowers:
                        del self.lowers[old['id']]
                    self.metas[path] = m
                    self.sig[path] = sigs.get(path)
                    self.texts[m['id']] = res['text']
                    self.lowers.pop(m['id'], None)
                    self.uu[m['id']] = (res['uuids'], res['uts'])
                    mt, sz = sigs.get(path, (0, 0))
                    db.execute('REPLACE INTO sessions (path, mtime_ns, size, ver, meta, txt, uuids, uts) VALUES (?,?,?,?,?,?,?,?)',
                               (path, mt, sz, PARSER_VERSION, json.dumps(m, ensure_ascii=False), res['text'],
                                '\n'.join(res['uuids']), ','.join(str(x) for x in res['uts'])))
                for path in gone:
                    m = self.metas.pop(path, None)
                    self.sig.pop(path, None)
                    if m:
                        self.texts.pop(m['id'], None)
                        self.lowers.pop(m['id'], None)
                        self.uu.pop(m['id'], None)
                    db.execute('DELETE FROM sessions WHERE path = ?', (path,))
                db.commit()
                db.close()
            if changed or self._payload is None:
                self._rebuild()
                self.generation += 1
            self.last_refresh = time.time()
            self.last_stats = {'files': len(files), 'parsed': len(results), 'removed': len(gone),
                               'ms': int((time.time() - t0) * 1000), 'first': first}
            self.progress = {'state': 'ready', 'done': len(files), 'total': len(files), 'parsed': len(results)}
            return dict(self.last_stats)

    def _parse_many(self, todo):
        results = []
        done0 = self.progress['done']
        main = sys.modules.get('__main__')
        can_pool = bool(getattr(main, '__file__', None))     # worker processes re-import the main script
        if self.use_pool and can_pool and len(todo) >= 12:
            try:
                import concurrent.futures
                workers = max(2, min(8, (os.cpu_count() or 4) - 1))
                # biggest first so the long ones don't all land at the end
                todo = sorted(todo, key=lambda p: -(self.sig_size(p)))
                with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
                    for r in ex.map(_parse_safe, todo, chunksize=1):
                        results.append(r)
                        self.progress['parsed'] = len(results)
                        self.progress['done'] = done0 + len(results)
                return results
            except Exception as e:
                self.errors.append('parallel read failed, using one process: %s' % e)
                results = []
        for p in todo:
            results.append(_parse_safe(p))
            self.progress['parsed'] = len(results)
            self.progress['done'] = done0 + len(results)
        return results

    @staticmethod
    def sig_size(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    # -- derived --
    def _rebuild(self):
        by_id = {}
        for path, m in self.metas.items():
            if (m.get('prompts') or 0) + (m.get('replies') or 0) == 0:
                continue                      # opened and closed without a conversation
            by_id[m['id']] = m
        runs = read_runs(self.work_root)
        run_by8 = {}
        for r in runs:
            run_by8[r['id8']] = r
        edges, own_start = detect_relations(by_id, self.uu, runs)
        keywords = compute_keywords(by_id)
        # Jira keys (ABC-123) count only for projects seen in a real Jira link, and link to that same site.
        prefixes = set()
        host_votes = collections.defaultdict(collections.Counter)
        for m in by_id.values():
            for u in (m.get('urls') or {}):
                b = BROWSE_RE.search(u)
                if b:
                    prefixes.add(b.group(1))
                    h = JIRA_HOST_RE.search(u)
                    if h:
                        host_votes[b.group(1)][h.group(1).lower()] += 1
        jira_hosts = {p: c.most_common(1)[0][0] for p, c in host_votes.items()}
        home = os.path.expanduser('~')
        sessions = []
        details = {}
        projects = collections.OrderedDict()
        for sid, m in by_id.items():
            wt = m.get('worktree')
            cwd = m.get('cwd') or ''
            if m.get('kind') == 'desktop' or '/scratch-workspaces/' in cwd:
                pkey, plabel = 'desktop', 'Desktop app chats'
            else:
                root = (wt or {}).get('original') or cwd
                pkey, plabel = root or 'unknown', os.path.basename(root.rstrip('/')) or 'unknown'
            pr = projects.setdefault(pkey, {'key': pkey, 'label': plabel, 'count': 0, 'cwd': pkey if pkey.startswith('/') else None})
            pr['count'] += 1
            links = build_links(m, prefixes, jira_hosts)
            start = own_start.get(sid) or m.get('start') or int((m.get('birth') or m.get('mtime') or 0) * 1000)
            end = max(m.get('end') or start, start)
            run = run_by8.get(sid[:8])
            cmds = sorted((m.get('commands') or {}).items(), key=lambda kv: (-kv[1], kv[0]))
            about = make_about(m)
            s = {
                'id': sid, 'title': m.get('title') or '', 'titleSource': m.get('titleSource'),
                'project': pkey, 'projectLabel': plabel, 'worktree': (wt or {}).get('name'),
                'cwd': cwd, 'kind': m.get('kind'), 'run': (run or {}).get('kind'),
                'start': start, 'end': end, 'historyStart': m.get('start'),
                'prompts': m.get('prompts') or 0, 'replies': m.get('replies') or 0, 'tools': m.get('tools') or 0,
                'msgs': (m.get('prompts') or 0) + (m.get('replies') or 0),
                'keywords': keywords.get(sid, []), 'about': about,
                'commands': [c for c, _ in cmds][:8],
                'jira': [x['label'] for x in links['jira'] if x.get('key')][:6],
                'linkCounts': dict((k, len(v)) for k, v in links.items() if v),
                'model': short_model(m.get('model')), 'cost': m.get('cost'),
                'subagents': m.get('subagents') or 0, 'compactions': m.get('compactions') or 0,
                'mtime': int((m.get('mtime') or 0) * 1000), 'size': m.get('size') or 0,
            }
            sessions.append(s)
            details[sid] = {
                'id': sid, 'path': m.get('path'), 'cwd': cwd, 'cwdExists': None,
                'fallbackCwd': (wt or {}).get('original'),
                'links': links, 'commands': cmds,
                'firstPrompt': m.get('firstPrompt') or '', 'firstReply': m.get('firstReply') or '',
                'lastPrompt': m.get('lastPrompt') or '', 'lastReply': m.get('lastReply') or '',
                'recaps': m.get('recaps') or [], 'tools': m.get('toolTop') or [],
                'model': m.get('model'), 'entry': m.get('entry'),
            }
        sessions.sort(key=lambda s: (s['start'], s['id']))
        self._details = details
        self._payload = {
            'sessions': sessions, 'edges': edges,
            'projects': sorted(projects.values(), key=lambda p: -p['count']),
            'home': home, 'defaultCwd': self.work_root,
        }

    # -- queries --
    def payload(self):
        with self.lock:
            p = dict(self._payload or {'sessions': [], 'edges': [], 'projects': []})
            p['generation'] = self.generation
            p['indexedAt'] = int(self.last_refresh * 1000)
            p['stats'] = dict(self.last_stats)
            p['errors'] = list(self.errors[-5:])
            return p

    def detail(self, sid):
        with self.lock:
            d = self._details.get(sid)
            if not d:
                return None
            d = dict(d)
        d['cwdExists'] = bool(d.get('cwd')) and os.path.isdir(d['cwd'])
        return d

    def known_cwds(self):
        with self.lock:
            return set(d.get('cwd') for d in self._details.values() if d.get('cwd'))

    def session_cwd(self, sid):
        with self.lock:
            d = self._details.get(sid)
            return d.get('cwd') if d else None

    def session_fallback_cwd(self, sid):
        with self.lock:
            d = self._details.get(sid)
            return d.get('fallbackCwd') if d else None

    def search(self, q, limit=80):
        """Full-text search over what was said. Every word must appear (any order); "quotes" keep a phrase."""
        terms = parse_query(q)
        if not terms:
            return {'q': q, 'terms': [], 'total': 0, 'results': []}
        with self.lock:
            valid = set(self._details)
            out = []
            for sid in valid:
                low = self.lowers.get(sid)
                if low is None:
                    txt = self.texts.get(sid) or ''
                    low = txt.lower()
                    if len(low) != len(txt):
                        low = ''.join(c.lower() if len(c.lower()) == 1 else c for c in txt)
                    self.lowers[sid] = low
                score = 0
                first = None
                ok = True
                for t in terms:
                    i = low.find(t)
                    if i < 0:
                        ok = False
                        break
                    score += min(low.count(t), 25)
                    if first is None or len(t) > len(first[1]):
                        first = (i, t)
                if not ok:
                    continue
                txt = self.texts.get(sid) or ''
                i, t = first
                a = max(0, i - 70)
                b = min(len(txt), i + len(t) + 110)
                snip = txt[a:b]
                if a > 0:
                    sp = snip.find(' ')
                    if 0 <= sp < 20:
                        snip = snip[sp + 1:]
                    snip = '…' + snip
                if b < len(txt):
                    sp = snip.rfind(' ')
                    if sp > len(snip) - 20:
                        snip = snip[:sp]
                    snip = snip + '…'
                out.append({'id': sid, 'score': score, 'snippet': ' '.join(snip.split())})
        out.sort(key=lambda r: (-r['score'], r['id']))
        return {'q': q, 'terms': terms, 'total': len(out), 'results': out[:limit]}


def parse_query(q):
    q = (q or '').strip().lower()
    if not q:
        return []
    terms = []
    for m in re.finditer(r'"([^"]+)"|(\S+)', q):
        t = (m.group(1) or m.group(2) or '').strip()
        if t and t not in terms:
            terms.append(t)
    return terms[:8]


def short_model(model):
    if not model:
        return None
    for name in ('fable', 'opus', 'sonnet', 'haiku'):
        if name in model:
            return name
    return model


if __name__ == '__main__':
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    idx = Index(os.path.join(here, '.cache'))
    t0 = time.time()
    stats = idx.refresh(force='--force' in sys.argv)
    p = idx.payload()
    print('sessions: %d  links: %d  read: %d files in %d ms (total %.1fs)' % (
        len(p['sessions']), len(p['edges']), stats['parsed'], stats['ms'], time.time() - t0))
