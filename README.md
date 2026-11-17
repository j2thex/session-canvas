# Session Canvas

**Every Claude Code session on your Mac, on one board.**

Session Canvas reads the sessions Claude Code already saves on your Mac and lays them out as cards on an
infinite board. You can see which session continued, copied or started which, search everything that was
said, and reopen any session in your terminal with one click.

![The board, with made-up demo sessions](docs/screenshot.png)

## What you get

- **One board, three views**: Tree (who started or continued whom), Timeline (day by day), Free (drag cards anywhere).
- **Links between sessions** found automatically: continued, copied (fork), handed over, started as a helper.
- **Search** everything said in every session, with small typos forgiven. Press `/`.
- **Reopen with one click**: Resume, Fork (a copy), New session in the same folder. A warning appears if that
  session is already open in another window, so two windows never write to the same conversation.
- **+ Session** starts a new session in your main folder, optionally with a quick-start command (for example the
  slash command you run every morning).
- **Sticky notes** you can send to a new or existing session as its next message.
- Rename, colour, hide, link, fold, undo. Everything you change is saved by itself.
- **Go to window**: clicking Resume on a session that is already open brings its window to the front.
- **Updates itself** when you say so: `session-canvas update`, or the "Update to v…" note at the bottom of the board.
- Optional, for people who run many sessions at once: a **Status** board and a **Your turn** list fed by small
  report files, and a reminder. Off until you turn them on. See [Status reports](#status-reports-optional).

## Install

Needs: a Mac, and [Claude Code](https://docs.claude.com/claude-code) installed. Nothing else: no Homebrew,
no pip, no Node. It uses Apple's own Python (`/usr/bin/python3`, part of Apple's Command Line Tools; if they are
missing the installer tells you the one command to run: `xcode-select --install`).

1. Download the newest `session-canvas-<version>.zip` from the
   [Releases page](https://github.com/j2thex/session-canvas/releases/latest) and unzip it (double-click).
2. In Terminal, go into that folder and run:

   ```sh
   ./install.sh
   ```

3. Answer two questions (add the command to your PATH? start at login?). Your browser opens the board.
4. A short **setup wizard** asks three things the first time: your main project folder, which terminal to use
   (Terminal, iTerm or Ghostty), and optional quick-start commands. Change them later under **?** → Settings.

The app goes to `~/.session-canvas/` and the `session-canvas` command to `~/.local/bin/`.

## Update

```sh
session-canvas update
```

It gets the newest release from GitHub, checks the download, installs it over the old one and starts the board
again. Your board, notes and settings are kept. The board also looks for a new version once a day and shows a small
**Update to v…** note at the bottom; clicking it does the same thing.

Still on 1.0.x (it has no `update` command yet)? Download the newest zip and run `./install.sh` once, as above.

The first time you open a session in Terminal or iTerm, macOS asks whether Session Canvas may control that
app. Click **OK** once. Ghostty needs no permission.

## Use

```sh
session-canvas            # start it (if needed) and open the board
session-canvas stop       # stop it
session-canvas status     # is it running?
session-canvas setup      # run the setup wizard again
session-canvas update     # get the newest version
session-canvas version    # which version is installed
session-canvas --dry-run  # test mode: buttons show the command instead of opening a window
```

If you want your own shell lines to run in every window the board opens (a window colour, an environment
variable), put them in `~/.session-canvas/data/before-session.zsh`.

The board lives at http://127.0.0.1:7788/ while it runs. Press **?** on the board for all shortcuts.

## Status reports (optional)

Off by default. Useful when you start many sessions (by hand or from scripts) and want one place that says
which ones wait on you. Turn it on under **?** → Settings → **Advanced settings**: give the folder that holds the
report files. The board then shows where each card stands, a **Status** layout (key `4`) and a **Your turn** list
(key `W`).

A report is a small text file, `<report folder>/<name>.md` or `<report folder>/<YYYY-MM-DD>/<name>.md`, that a
session writes when it stops. It starts with:

```
status: your-turn          (done | not-done | your-turn | question)
name: Reply to the customer
outcome: draft saved
left: you send it
```

Optional lines anywhere in the file: `sent: <link>` (what it waited for was sent, so the card is done; if
something else is still left for you, leave `sent:` out and say what is left in `left:`),
`replaces: other-report-name` and `replaced-by: other-report-name` (a newer session took over).

The board matches a report to its session in one of three ways: the session's first message contains the lines
`You are the helper "<name>"` and `Report file: <full path of the report>`; or the report's `name:` is the
session's title on the same day; or a `runs.tsv` in the day folder lists them (tab-separated: first 8 characters
of the session id, name, kind, model, skill, time, report path).

On the board you can also press **Sent**, **Mark done** or **Replaced by…** on a card yourself. The button writes into the
report file too (`status: done` plus a `sent:`, `replaced-by:` or `marked:` line), so whoever reads the reports sees it;
undo (Cmd+Z) puts the report back, unless the helper has rewritten it since.
A script can read what waits on you: `curl -s 'http://127.0.0.1:7788/api/waiting?format=text'`.

**Reminder** (also under Advanced settings): the full path of a script of yours. When a card has waited on you
for 30 minutes (you choose), the board runs the script once with one line of text as its only argument, between
08:00 and 20:00. What the script does with it (a notification, a chat message) is up to you.

## Uninstall

```sh
session-canvas uninstall
```

It removes the app, the command and the login item, and asks before deleting your board data (notes,
positions, settings in `~/.session-canvas/data`). Your Claude Code sessions (`~/.claude`) are never touched.

## Privacy and safety

- **Everything stays on your Mac.** Nothing about you or your sessions is sent to the internet; the page loads no
  outside resources. The only outside request is the update check: once a day the server asks GitHub's public
  API "what is the newest release?" (and downloads the zip when you update).
- An update is downloaded over HTTPS from this project's GitHub releases only, and checked to be a Session Canvas
  zip of the announced version before it is installed. It is not cryptographically signed.
- The server listens on **127.0.0.1 only**, so other computers can't reach it. Other user accounts logged in on
  the same Mac could open the address, so don't run it on a Mac you share with people you don't trust.
- Every action that changes something or opens a window needs a secret token that only the open page knows,
  and a same-origin check, so other websites can't press its buttons or show the board inside their own page.
- Claude Code's sessions are **read-only** to Session Canvas. It only writes its own data folder.
- Notes you send to Claude are passed as a single argument from a file, never typed into a shell.

## Known limits

- **It reads Claude Code's internal files** (`~/.claude/projects/*/*.jsonl` for sessions,
  `~/.claude/sessions/*.json` to know which sessions are open right now). These are not a public format and can
  change in a new Claude Code version. Session Canvas skips anything it can't read instead of failing; if a
  Claude Code update changes the format, some cards or links may be missing until Session Canvas is updated.
- macOS only.
- Keep one board tab open: two tabs overwrite each other's changes.

## For developers

```sh
/usr/bin/python3 -m unittest discover -s app/tests -v      # unit, API and installer tests (made-up data only)
/usr/bin/python3 app/tests/browser_check.py                # drives the page in headless Google Chrome
./make-release.sh                                          # builds dist/session-canvas-<version>-<date>.zip
./make-release.sh --publish                                # ... and tags v<version>, pushes, creates the GitHub release
```

This repository is the one source of Session Canvas. To ship a version: change the code, raise `VERSION`, add a
section to `CHANGELOG.md`, run the tests, commit, then `./make-release.sh --publish`. Every installed copy then
offers the update.

```sh
```

Python 3.9 standard library only, plain JavaScript, no build step.

## License

Proprietary. See [LICENSE](LICENSE).
