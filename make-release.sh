#!/bin/zsh
# Builds dist/session-canvas-<version>-<date>.zip from the committed files only (git archive), so nothing
# personal (board data, caches, screenshots, logs) can end up in it. Refuses to run with uncommitted changes.
set -eu
cd ${0:A:h}
[[ -z $(git status --porcelain) ]] || { print -u2 "make-release: commit or stash your changes first (git status)"; exit 1; }
V=$(cat VERSION)
NAME=session-canvas-$V
OUT=dist/$NAME-$(date +%Y%m%d).zip
mkdir -p dist
rm -f "$OUT"
git archive --format=zip --prefix="$NAME/" -o "$OUT" HEAD
# last line of defence: the zip must not contain personal data or caches
BAD=$(unzip -Z1 "$OUT" | grep -E '(^|/)(state\.json[^/]*|\.cache|data|screenshots|__pycache__|\.state)(/|$)|\.(log|bak|pyc|command)$|\.DS_Store$' || true)
[[ -z $BAD ]] || { rm -f "$OUT"; print -u2 "make-release: refusing, personal files in the zip:\n$BAD"; exit 1; }
print -r -- "$PWD/$OUT"
