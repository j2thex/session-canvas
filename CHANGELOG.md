# Changelog

## 1.2.3 (2026-11-17)

- **Sent / Mark done / Replaced by now write into the report file** (`status: done` plus a `sent:`, `replaced-by:`
  or `marked:` line), so helpers, your planner and the board all read the same thing. Undo puts the report back,
  unless the helper rewrote it in the meantime. Only files inside your report folders are touched; never in test mode.

## 1.2.2 (2026-11-17)

- Fix: a board tab left open from an older version could wipe your Advanced settings (report folders,
  reminder) when it saved. Settings are now merged on save, never replaced.

## 1.2.1 (2026-11-17)

- Your own shell lines can run in every window the board opens: put them in
  `~/.session-canvas/data/before-session.zsh` (for example a window colour).

## 1.2.0 (2026-11-17)

Updates, and everything built since 1.0.1 in one place.

- **Updates**: `session-canvas update` gets the newest version from GitHub and keeps your board, notes and
  settings. The board looks for a new version once a day and shows a small "Update to v…" note at the bottom;
  one click updates and asks you to reload. Versions are published on the GitHub Releases page.
- **Go to window**: Resume on a session that is already open brings its window to the front (Ghostty and
  Terminal; iTerm comes to the front without picking the tab).
- **Clearer cards**: each card shows the end of its last message; double-click a card's name to rename it; the
  version is shown at the bottom of the board.
- **Status reports (optional, off by default)**: if your sessions write small report files, cards show where
  they stand (needs your answer, your turn, running, stopped, done, replaced). New **Status** layout (key 4),
  **Your turn** list (key W), and Sent / Mark done / Replaced by buttons. `GET /api/waiting` lists what waits
  on you for scripts.
  A report that two sessions share is listed once (under the newer session). A `sent:` line always closes
  the card, so a report with something still left for you must not carry one.
- **Reminder (optional, off by default)**: runs a script of yours when a card has waited on you for 30 minutes.
- Both are set under **?** → Settings → Advanced settings. Without them the board looks and works as before.
- `make-release.sh --publish` tags the version and creates the GitHub release with the zip.

## 1.0.1 (2026-11-14)

Fixes from an independent review.

- Safety: other websites can no longer show the board inside a frame (clickjacking), and the page only runs its
  own script files (Content-Security-Policy). The cache folder is readable by you only, however it was created.
- Installer: clear message on a Mac without Apple's Command Line Tools; the PATH line no longer sticks to the last
  line of a `~/.zshrc` that has no final new line.
- Uninstaller: run from the download folder it now removes the installed copy (not the download), and it leaves a
  `session-canvas` command that belongs to another install alone.
- Two messages still named an old start script; an odd session title or artifact link can no longer break the board.

## 1.0.0 (2026-11-14)

First packaged release.

- Board of every Claude Code session: Tree, Timeline and Free views, minimap, zoom, search with typo tolerance.
- Links found automatically: continued, fork, handover, helper, worktree; draw your own.
- Resume, Fork, New session, sticky notes sent to a new or existing session.
- Knows which sessions are open right now and warns before opening one twice; offers to copy the note instead.
- **+ Session** (key `S`) with quick-start commands.
- First-run setup wizard: default folder, terminal (Terminal, iTerm, Ghostty), quick-start commands.
- `install.sh` (upgrade-safe, optional start at login), `session-canvas` command, `uninstall.sh`.
