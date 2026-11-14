#!/bin/zsh
# Removes Session Canvas. Your board data (notes, positions, settings) is deleted only if you say so.
# Claude Code's own sessions (~/.claude) are never touched.
#   uninstall.sh          ask before deleting the board data
#   uninstall.sh --yes    remove the app, keep the board data (nothing is asked)
#   uninstall.sh --purge  also delete the board data without asking
set -u
DEST=${SESSION_CANVAS_HOME:-${0:A:h}}
# Run from the unzipped download folder (it has install.sh): remove the installed copy, not the download.
[[ -z ${SESSION_CANVAS_HOME:-} && -f $DEST/install.sh ]] && DEST=$HOME/.session-canvas
DEST=${DEST:A}
YES=0; PURGE=0
for a in "$@"; do
  case $a in --yes|-y) YES=1 ;; --purge) PURGE=1; YES=1 ;; *) print -u2 "uninstall.sh: don't know '$a'"; exit 2 ;; esac
done
[[ -f $DEST/app/server.py || -f $DEST/bin/session-canvas ]] || { print -u2 "Nothing to remove: $DEST is not a Session Canvas install."; exit 1; }
LABEL=com.sessioncanvas.server
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
SESSION_CANVAS_HOME=$DEST "$DEST/bin/session-canvas" stop >/dev/null 2>&1
if [[ -f $PLIST ]]; then launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; fi
LINK=$HOME/.local/bin/session-canvas          # remove the command only if it is this install's (or points nowhere)
[[ -L $LINK && ( $(readlink "$LINK") == $DEST/bin/session-canvas || ! -e $LINK ) ]] && rm -f "$LINK"
rm -rf "$DEST/app" "$DEST/bin" "$DEST/VERSION" "$DEST/README.md" "$DEST/LICENSE" "$DEST/CHANGELOG.md"
keep=1
if (( PURGE )); then keep=0
elif (( ! YES )) && [[ -t 0 ]]; then
  read -r "a?Also delete your board data (notes, positions, settings) in $DEST/data? [y/N] "
  [[ $a == [yY]* ]] && keep=0
fi
if (( keep )); then
  print -r -- "Session Canvas removed. Your board data is kept in $DEST/data (installing again picks it up)."
else
  rm -rf "$DEST/data"
  print -r -- "Session Canvas and its board data removed."
fi
rm -f "$DEST/uninstall.sh"
rmdir "$DEST" 2>/dev/null
grep -qs 'session-canvas: PATH' "$HOME/.zshrc" && print -r -- "(The PATH line in ~/.zshrc marked 'session-canvas: PATH' is harmless; delete it if you like.)"
exit 0
