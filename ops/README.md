# Deploying the site

The site is built on this machine and uploaded to the server as a numbered release. The server never
runs git or Hugo. Every server command is appended to `ops/ssh-log.md`, which git ignores.

```sh
ops/deploy.sh                  # build, upload, switch, health check; switches back by itself if unhealthy
ops/deploy.sh --dry-run        # build and print what would happen on the server (no ssh)
ops/deploy.sh --status         # what is live, which releases exist, health check
ops/deploy.sh --rollback       # switch to the release before the live one
ops/deploy.sh --rollback <id>  # switch to a named release (ids: `--status`)
ops/update.sh                  # report newer Hugo / PaperMod upstream, build, git diff --stat
ops/update.sh --theme          # also overwrite themes/PaperMod with upstream
```

- Hugo is pinned in `ops/hugo-version` (0.170.1, the server's version). `deploy.sh` refuses another local
  version unless you pass `--any-hugo`. Install it with the release tarball from
  https://github.com/gohugoio/hugo/releases into `~/.local/bin`.
- A dirty working tree deploys with a warning and a `-dirty` suffix in the release id.
- Releases are `/srv/personal-site/releases/<YYYYmmdd-HHMMSS>-<shortsha>[-dirty]/`; the newest 5 are kept.
  Unchanged files are hard-linked to the live release (`rsync --link-dest`), so only changes are uploaded.
- `current` is switched atomically (`ln -sfn` to a temp name, then `mv -T`).
- The health check runs on the server: `curl -fsS --resolve maxcl.co.uk:443:127.0.0.1 https://maxcl.co.uk/`
  and `/publications/`.
- Each release has a `REVISION` file (sha, dirty flag, date, build host, Hugo version). Caddy would serve it
  at https://maxcl.co.uk/REVISION. That is harmless (no secrets), but the Caddyfile below hides it anyway.

## One-time server setup (as root on the server)

Run these in order. Nothing changes for visitors until the Caddy step, and that step serves the same files.

```sh
# 1. Directories
install -d -m 755 -o root -g root /srv/personal-site /srv/personal-site/releases

# 2. Seed the first release from what is live now, then point `current` at it
seed=20260101-000000-seed
cp -a /server/personal/www /srv/personal-site/releases/$seed
chown -R root:root /srv/personal-site/releases/$seed
find /srv/personal-site/releases/$seed -type d -exec chmod 755 {} +
find /srv/personal-site/releases/$seed -type f -exec chmod 644 {} +
ln -sfn releases/$seed /srv/personal-site/.current.tmp && mv -T /srv/personal-site/.current.tmp /srv/personal-site/current
ls -l /srv/personal-site/current
diff -r /server/personal/www /srv/personal-site/current && echo identical

# 3. Caddy: in the maxcl.co.uk site block, change the root and hide REVISION.
grep -n -B3 -A8 'server/personal/www' /etc/caddy/Caddyfile
```

In the Caddyfile, replace the `root * /server/personal/www` line (whatever it exactly says) with:

```caddy
	root * /srv/personal-site/current
	respond /REVISION 404
```

`respond` is evaluated before `file_server` only if it comes earlier in the directive order; Caddy orders
`respond` before `file_server` by default, so the two lines above work as they are. Then:

```sh
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
curl -fsS -o /dev/null -w '%{http_code}\n' https://maxcl.co.uk/       # 200
curl -s -o /dev/null -w '%{http_code}\n' https://maxcl.co.uk/REVISION  # 404
```

Requirements on the server: `rsync` (3.1 or newer, for `--chown`), `curl`, and root SSH access under the
name `hetzner` in `~/.ssh/config` on this machine. The old `/server/personal/personal-site` checkout and
`/server/personal/www` can stay as a fallback and be removed once a few deploys have worked. To undo the
Caddy change, put the old root line back and reload.

## Rolling back

`ops/deploy.sh --rollback` switches `current` to the previous release in one atomic step and health-checks it.
A failed deploy already switches back automatically. If Caddy itself is broken, on the server:
`ln -sfn releases/<id> /srv/personal-site/.current.tmp && mv -T /srv/personal-site/.current.tmp /srv/personal-site/current`.

## The old GitHub Pages workflow

`.github/workflows/hugo.yml` (Hugo 0.147.2, GitHub Pages) was removed. It never ran, there is no Pages site,
and it pins a different Hugo version from the one the site is built with.
