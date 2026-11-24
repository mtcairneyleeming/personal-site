#!/usr/bin/env bash
# Builds the site locally and publishes it to the server as a new release.
# Every server command is logged in ops/ssh-log.md.
#
#   ops/deploy.sh                 build, upload, switch `current`, health check (reverts on failure)
#   ops/deploy.sh --dry-run       build and print what would run on the server; no ssh at all
#   ops/deploy.sh --any-hugo      allow a local Hugo other than the one in ops/hugo-version
#   ops/deploy.sh --status        what is live, the releases, a health check
#   ops/deploy.sh --rollback [id] switch to the release before `current` (or to <id>)
#
# Server layout (set up once, see ops/README.md):
#   /srv/personal-site/releases/<YYYYmmdd-HHMMSS>-<shortsha>[-dirty]/   root:root, world-readable
#   /srv/personal-site/current -> releases/<id>                         Caddy serves this
set -euo pipefail
cd "$(dirname "$0")/.."

host=hetzner
base=/srv/personal-site
keep=5
domain=maxcl.co.uk
inner_page=/publications/
want_hugo=$(tr -d '[:space:]' <ops/hugo-version)

mode=deploy
any_hugo=false
dry=false
rollback_to=
while [ $# -gt 0 ]; do
  case $1 in
    --any-hugo) any_hugo=true ;;
    --dry-run) dry=true ;;
    --status) mode=status ;;
    --rollback) mode=rollback; if [ $# -gt 1 ] && [[ $2 != --* ]]; then rollback_to=$2; shift; fi ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Runs a command on the server through the log (or only prints it with --dry-run).
remote() {
  if $dry; then printf 'DRY RUN, would run on %s (%s): %s\n' "$host" "$1" "$2" >&2; return 0; fi
  ops/logged.sh "$1" ssh -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 "$host" "$2"
}

# The site and an inner page must answer on the server itself, through Caddy and TLS.
health_cmd="for p in / $inner_page; do curl -fsS -o /dev/null --max-time 15 --retry 2 --retry-delay 1 --resolve $domain:443:127.0.0.1 https://$domain\$p || exit 1; echo \"ok \$p\"; done"
health() { remote "Health check: $domain answers" "$health_cmd"; }

# Atomic switch: a new symlink under a temporary name, then rename over `current`.
switch_cmd() { echo "set -e; cd $base; [ -f releases/$1/index.html ] || { echo 'no such release: $1'; exit 1; }; ln -sfn releases/$1 .current.tmp; mv -T .current.tmp current; echo \"current -> \$(readlink current)\""; }

current_id() { remote "Which release is live" "readlink $base/current" | tail -n 1 | sed 's|.*/||'; }

if [ "$mode" = status ]; then
  remote "Status: live release and all releases" "cd $base; echo \"current -> \$(readlink current)\"; cat current/REVISION 2>/dev/null; echo; echo releases:; ls -1 releases"
  health
  exit 0
fi

if [ "$mode" = rollback ]; then
  now=$(current_id)
  if [ -z "$rollback_to" ]; then
    list=$(remote "List releases" "ls -1 $base/releases")
    rollback_to=$(printf '%s\n' "$list" | sort | grep -B1 -Fx "$now" | head -n 1 || true)
    if [ -z "$rollback_to" ] || [ "$rollback_to" = "$now" ]; then echo "No release older than $now to roll back to." >&2; exit 1; fi
  fi
  echo "Rolling back $now -> $rollback_to"
  remote "Rollback: switch current to $rollback_to" "$(switch_cmd "$rollback_to")"
  health || { echo "Health check failed after rollback; look at the server." >&2; exit 1; }
  exit 0
fi

# ---- deploy ----
dirty=""
if [ -n "$(git status --porcelain)" ]; then
  dirty=-dirty
  echo "WARNING: the working tree has uncommitted changes; deploying anyway (release id ends in -dirty)." >&2
fi

have_hugo=$(hugo version | sed -n 's/^hugo v\([0-9][0-9.]*\).*/\1/p')
if [ "$have_hugo" != "$want_hugo" ]; then
  if $any_hugo; then
    echo "WARNING: local Hugo is ${have_hugo:-unknown}, not $want_hugo (--any-hugo)." >&2
  else
    echo "Local Hugo is ${have_hugo:-unknown} but ops/hugo-version says $want_hugo (the server's version). Install that, or pass --any-hugo." >&2
    exit 1
  fi
fi

sha=$(git rev-parse --short HEAD)
id=$(date +%Y%m%d-%H%M%S)-$sha$dirty
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

python3 ops/handwriting.py prepare "$tmp/public"  # runs hugo build, then annotates
files=$(find "$tmp/public" -type f | wc -l)
{
  echo "sha: $(git rev-parse HEAD)"
  if [ -n "$dirty" ]; then echo "dirty: true"; else echo "dirty: false"; fi
  echo "date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "host: $(hostname)"
  echo "hugo: $have_hugo"
} >"$tmp/public/REVISION"
echo "Built $files files; release id: $id"

prev=
if ! $dry; then prev=$(current_id); fi
echo "Currently live: ${prev:-unknown}"

remote "Deploy: create release $id" "mkdir -p -m 755 $base/releases/$id"
# --link-dest reuses unchanged files from the live release (hard links), so only changes are sent.
rsync_args=(-rlptz --chown=root:root --chmod=D755,F644)
[ -n "$prev" ] && rsync_args+=("--link-dest=$base/releases/$prev")
if $dry; then
  printf 'DRY RUN, would run: rsync %s %s/public/ %s:%s/releases/%s/\n' "${rsync_args[*]}" "<tmp>" "$host" "$base" "$id" >&2
else
  ops/logged.sh "Deploy: upload release $id" rsync "${rsync_args[@]}" -e ssh "$tmp/public/" "$host:$base/releases/$id/"
fi
remote "Deploy: switch current to $id" "$(switch_cmd "$id")"

if ! health; then
  echo "Health check FAILED." >&2
  if [ -n "$prev" ]; then
    echo "Switching back to $prev" >&2
    remote "Deploy failed: switch back to $prev" "$(switch_cmd "$prev")"
    health || echo "Still unhealthy after switching back; look at the server." >&2
  else
    echo "No previous release to switch back to." >&2
  fi
  exit 1
fi

# Keep the newest $keep releases (ids sort by time); never remove the live one.
remote "Deploy: remove old releases, keep $keep" "cd $base/releases; live=\$(readlink ../current | sed 's|.*/||'); ls -1 | sort | head -n -$keep | while read -r r; do [ \"\$r\" = \"\$live\" ] || { rm -rf -- \"\$r\"; echo removed \$r; }; done; ls -1"
if $dry; then echo "Dry run finished: nothing was sent to the server."; else echo "Deployed $id."; fi
