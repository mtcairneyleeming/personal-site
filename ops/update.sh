#!/usr/bin/env bash
# Checks what is out of date, builds the site and shows the diff. Nothing is deployed or committed.
#
#   ops/update.sh           report a newer Hugo, report how the vendored PaperMod differs from upstream, build
#   ops/update.sh --theme   also overwrite themes/PaperMod with upstream (review with git diff afterwards)
#
# The Hugo version lives only in ops/hugo-version (deploy.sh checks it). To change it: edit that file,
# install that release in ~/.local/bin, and tell the server's Hugo owner if they still build there.
set -euo pipefail
cd "$(dirname "$0")/.."

update_theme=false
[ "${1:-}" = "--theme" ] && update_theme=true

pinned=$(tr -d '[:space:]' <ops/hugo-version)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [ -n "$(git status --porcelain)" ]; then
  echo "WARNING: the working tree has uncommitted changes; they will be mixed into the diff below." >&2
fi

echo "== Hugo =="
have=$(hugo version | sed -n 's/^hugo v\([0-9][0-9.]*\).*/\1/p')
echo "pinned: $pinned, local: $have"
latest=$(curl -fsS https://api.github.com/repos/gohugoio/hugo/releases/latest | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -n 1 || true)
if [ -z "$latest" ]; then
  echo "could not read the latest release from GitHub"
elif [ "$latest" = "$pinned" ]; then
  echo "up to date ($latest)"
else
  echo "NEWER Hugo available: $latest (pinned $pinned). Release notes: https://github.com/gohugoio/hugo/releases/tag/v$latest"
fi

echo
echo "== PaperMod (vendored in themes/PaperMod) =="
if git clone -q --depth 1 https://github.com/adityatelange/hugo-PaperMod "$work/upstream"; then
  echo "upstream: $(git -C "$work/upstream" log -1 --format='%h %cs %s')"
  rm -rf "$work/upstream/.git"
  # Only the files the theme ships matter; ignore upstream's repo furniture that the vendored copy may lack.
  if diff -rq themes/PaperMod "$work/upstream" >"$work/theme.diff"; then
    echo "identical to upstream"
  else
    echo "differs from upstream in $(wc -l <"$work/theme.diff") files:"
    sed "s|$work/upstream|upstream|" "$work/theme.diff" | head -n 30
    echo "(rerun with --theme to take upstream; the site's own layouts/ override most of the theme, so check the build)"
    if $update_theme; then
      echo "Overwriting themes/PaperMod with upstream (--theme). Review with: git diff --stat themes"
      rsync -a --delete "$work/upstream/" themes/PaperMod/
    fi
  fi
else
  echo "could not fetch upstream PaperMod"
fi

echo
echo "== Build =="
hugo build --cleanDestinationDir -d "$work/public"
echo "$(find "$work/public" -type f | wc -l) files built"

echo
echo "== git diff --stat =="
git diff --stat
git status --short
echo
echo "Review, commit, then run ops/deploy.sh. Nothing was deployed or committed."
