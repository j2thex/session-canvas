# Changelog

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
