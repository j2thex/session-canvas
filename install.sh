#!/bin/zsh
# Session Canvas installer for macOS. Run it from the unzipped folder:   ./install.sh
# Running it again upgrades the app and keeps your board (positions, notes, settings).
#
#   ./install.sh                 ask the few questions (autostart, PATH) and open the board
#   ./install.sh --yes           accept the defaults without asking (autostart: no, PATH: yes)
#   options: --autostart / --no-autostart   --no-open   --no-start   --dir <folder> (default ~/.session-canvas)
#            --no-path (never touch ~/.zshrc; used by `session-canvas update`)
set -u
setopt null_glob
SRC=${0:A:h}
DEST=${SESSION_CANVAS_HOME:-$HOME/.session-canvas}
YES=0; AUTO=ask; OPEN=1; START=1; SETPATH=1
while (( $# )); do
  case $1 in
    --yes|-y) YES=1 ;;
    --autostart) AUTO=yes ;;
    --no-autostart) AUTO=no ;;
    --no-open) OPEN=0 ;;
    --no-start) START=0; OPEN=0 ;;
    --no-path) SETPATH=0 ;;
    --dir) shift; DEST=${1:?--dir needs a folder} ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) print -u2 "install.sh: don't know '$1' (try --help)"; exit 2 ;;
  esac
  shift
done
DEST=${DEST:A}
[[ $DEST == $SRC ]] && { print -u2 "install.sh: pick a --dir other than this folder"; exit 2; }
BIN=$HOME/.local/bin
LABEL=com.sessioncanvas.server
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
PY=/usr/bin/python3

say()  { print -r -- "  $*"; }
ok()   { print -r -- "  ✓ $*"; }
warn() { print -r -- "  ! $*"; }
die()  { print -u2 -r -- "  ✗ $*"; exit 1; }
ask() {   # ask "question" default(y|n) -> 0 = yes
  local q=$1 def=$2 a
  if (( YES )) || [[ ! -t 0 ]]; then [[ $def == y ]]; return; fi
  read -r "a?  $q [$( [[ $def == y ]] && print Y/n || print y/N )] "
  a=${a:-$def}; [[ $a == [yY]* ]]
}

print -r -- ""
print -r -- "Session Canvas $(cat "$SRC/VERSION" 2>/dev/null) — installer"
print -r -- ""

# 1. checks
[[ $(uname -s) == Darwin ]] || die "Session Canvas runs on macOS only."
# On a brand-new Mac /usr/bin/python3 is only a placeholder until Apple's Command Line Tools are installed.
[[ -x $PY ]] && xcode-select -p >/dev/null 2>&1 || die "Python 3 is not set up on this Mac yet. Run: xcode-select --install   (a box appears: click Install and wait a few minutes), then run ./install.sh again."
$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null || die "Python 3.9 or newer is needed (/usr/bin/python3 is older). Update macOS or the Command Line Tools."
ok "macOS and Python $($PY -c 'import platform; print(platform.python_version())')"
[[ -f $SRC/app/server.py && -f $SRC/bin/session-canvas ]] || die "Run this from the unzipped Session Canvas folder (app/ and bin/ are missing here)."
CLAUDE=""
for c in "$(command -v claude 2>/dev/null)" $HOME/.local/bin/claude $HOME/.claude/local/claude /opt/homebrew/bin/claude /usr/local/bin/claude; do
  [[ -n $c && -x $c ]] && { CLAUDE=$c; break; }
done
if [[ -n $CLAUDE ]]; then ok "Claude Code found: $CLAUDE"
else warn "Claude Code was not found. The board still works, but Resume needs it: https://docs.claude.com/claude-code"; fi
if [[ -d $HOME/.claude/projects ]]; then ok "Claude Code sessions folder found"
else warn "No Claude Code sessions yet (~/.claude/projects). They appear on the board once you use Claude Code."; fi

# 2. stop a running copy before replacing it
UPGRADE=0
[[ -f $DEST/app/server.py ]] && UPGRADE=1
if (( UPGRADE )) && [[ -x $DEST/bin/session-canvas ]]; then
  SESSION_CANVAS_HOME=$DEST "$DEST/bin/session-canvas" stop >/dev/null 2>&1
fi

# 3. copy the app (atomically: new copy next to the old one, then swap). Your data/ is never touched.
mkdir -p "$DEST" || die "Cannot create $DEST"
STAGE=$(mktemp -d "$DEST/.install.XXXXXX") || die "Cannot write to $DEST"
for item in app bin VERSION README.md LICENSE CHANGELOG.md uninstall.sh; do
  [[ -e $SRC/$item ]] && cp -R "$SRC/$item" "$STAGE/"
done
rm -rf "$STAGE/app/tests" "$STAGE/app/.cache" "$STAGE/app/state.json"* "$STAGE/app/screenshots"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null
chmod 755 "$STAGE/bin/session-canvas" "$STAGE/uninstall.sh" 2>/dev/null
for item in app bin VERSION README.md LICENSE CHANGELOG.md uninstall.sh; do
  [[ -e $STAGE/$item ]] || continue
  rm -rf "$DEST/$item.old"
  [[ -e $DEST/$item ]] && mv "$DEST/$item" "$DEST/$item.old"
  mv "$STAGE/$item" "$DEST/$item"
done
rm -rf "$STAGE" "$DEST"/*.old
mkdir -p "$DEST/data/cache"
chmod 700 "$DEST/data"
if (( UPGRADE )); then ok "Upgraded in $DEST (your board and settings are kept)"; else ok "Installed in $DEST"; fi

# 4. the command
mkdir -p "$BIN"
ln -sf "$DEST/bin/session-canvas" "$BIN/session-canvas"
ok "Command: session-canvas  (in $BIN)"
if (( SETPATH )) && [[ ":$PATH:" != *":$BIN:"* ]]; then
  RC=$HOME/.zshrc
  if grep -qs 'session-canvas: PATH' "$RC"; then
    say "Open a new terminal window to use the session-canvas command."
  elif ask "Add $BIN to your PATH (one line at the end of ~/.zshrc)?" y; then
    [[ -s $RC && -n $(tail -c1 "$RC") ]] && print >> "$RC"        # the file did not end with a new line
    print -r -- 'export PATH="$HOME/.local/bin:$PATH"   # session-canvas: PATH' >> "$RC"
    ok "Added to ~/.zshrc. Open a new terminal window to use the session-canvas command."
  else
    say "Run it with the full path: $BIN/session-canvas"
  fi
fi

# 5. start at login (optional)
want_auto=0
if [[ $AUTO == yes ]]; then want_auto=1
elif [[ $AUTO == ask ]]; then
  if [[ -f $PLIST ]]; then want_auto=1                  # keep what was chosen before
  elif ask "Start Session Canvas by itself when you log in?" n; then want_auto=1; fi
fi
if (( want_auto )); then
  mkdir -p "${PLIST:h}"
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>$DEST/app/server.py</string>
    <string>--port</string><string>7788</string>
    <string>--state</string><string>$DEST/data/state.json</string>
    <string>--cache</string><string>$DEST/data/cache</string>
  </array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>$DEST/data/cache/server.log</string>
  <key>StandardErrorPath</key><string>$DEST/data/cache/server.log</string>
</dict></plist>
PL
  ok "Starts by itself at login (turn off: session-canvas uninstall, or delete $PLIST)"
elif [[ $AUTO == no && -f $PLIST ]]; then
  launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; ok "Autostart turned off"
fi

# 6. start and open
if (( START )); then
  if (( OPEN )); then SESSION_CANVAS_HOME=$DEST "$DEST/bin/session-canvas" || die "It did not start. See $DEST/data/cache/server.log"
  else SESSION_CANVAS_HOME=$DEST "$DEST/bin/session-canvas" --no-open || die "It did not start. See $DEST/data/cache/server.log"; fi
fi
print -r -- ""
if (( START )); then print -r -- "Done. The board opens in your browser; a short setup wizard asks 3 questions the first time."
else print -r -- "Done. Not started (--no-start). Run: session-canvas"; fi
print -r -- "Later: session-canvas (open) · session-canvas stop · session-canvas update · session-canvas uninstall"
