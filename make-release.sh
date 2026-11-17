#!/bin/zsh
# Builds dist/session-canvas-<version>-<date>.zip from the committed files only (git archive), so nothing
# personal (board data, caches, screenshots, logs) can end up in it. Refuses to run with uncommitted changes.
#
#   ./make-release.sh             build the zip
#   ./make-release.sh --publish   build it, then tag v<version>, push, and create the GitHub release with the
#                                 zip attached (needs the gh command, logged in). It never changes VERSION:
#                                 set VERSION and CHANGELOG.md yourself and commit first.
#
# Privacy: if a file .privacy-words exists here (one word per line, never committed), the release stops when
# any tracked file or the zip contains one of those words.
set -eu
cd ${0:A:h}
PUBLISH=0
for a in "$@"; do
  case $a in --publish) PUBLISH=1 ;; *) print -u2 "make-release: don't know '$a'"; exit 2 ;; esac
done
[[ -z $(git status --porcelain) ]] || { print -u2 "make-release: commit or stash your changes first (git status)"; exit 1; }
V=$(cat VERSION)
[[ $V == <->.<->.<-> ]] || { print -u2 "make-release: VERSION must look like 1.2.3 (it is '$V')"; exit 1; }
NAME=session-canvas-$V
grep -q "^## $V " CHANGELOG.md || { print -u2 "make-release: CHANGELOG.md has no section for $V"; exit 1; }
if [[ -f .privacy-words ]]; then
  HITS=$(git grep -n -i -I -F -f .privacy-words -- . || true)
  [[ -z $HITS ]] || { print -u2 "make-release: refusing, private words in tracked files:\n$HITS"; exit 1; }
  NAMES=$(git ls-files | grep -i -F -f .privacy-words || true)
  [[ -z $NAMES ]] || { print -u2 "make-release: refusing, private words in file names:\n$NAMES"; exit 1; }
fi
OUT=dist/$NAME-$(date +%Y%m%d).zip
mkdir -p dist
rm -f "$OUT"
git archive --format=zip --prefix="$NAME/" -o "$OUT" HEAD
# last line of defence: the zip must not contain personal data or caches
BAD=$(unzip -Z1 "$OUT" | grep -E '(^|/)(state\.json[^/]*|\.cache|data|screenshots|__pycache__|\.state|\.privacy-words)(/|$)|\.(log|bak|pyc|command)$|\.DS_Store$' || true)
[[ -z $BAD ]] || { rm -f "$OUT"; print -u2 "make-release: refusing, personal files in the zip:\n$BAD"; exit 1; }
/usr/bin/python3 -I -c 'import sys; sys.path.insert(0, "app"); import updater; updater.check_zip(sys.argv[1], sys.argv[2])' "$OUT" "$V" \
  || { print -u2 "make-release: the zip would be refused by the updater"; exit 1; }
print -r -- "$PWD/$OUT"
(( PUBLISH )) || exit 0

command -v gh >/dev/null || { print -u2 "make-release: --publish needs the gh command (https://cli.github.com)"; exit 1; }
TAG=v$V
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  [[ $(git rev-parse "$TAG^{commit}") == $(git rev-parse HEAD) ]] || { print -u2 "make-release: tag $TAG exists on another commit. Raise VERSION instead of moving a tag."; exit 1; }
else
  git tag -a "$TAG" -m "Session Canvas $V"
fi
git push origin HEAD
git push origin "$TAG"
# the release notes = this version's section of CHANGELOG.md
NOTES=$(mktemp)
awk -v v="$V" '$0 ~ "^## "v" " {on=1; next} /^## / {on=0} on' CHANGELOG.md > "$NOTES"
if gh release view "$TAG" >/dev/null 2>&1; then
  gh release upload "$TAG" "$OUT" --clobber
else
  gh release create "$TAG" "$OUT" --title "Session Canvas $V" --notes-file "$NOTES" --verify-tag
fi
rm -f "$NOTES"
gh release view "$TAG" --json url --jq .url
