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

## Previewing handwriting

Run these commands from the site directory with Hugo, Python 3, and `uv` available.

```sh
preview_dir=$(mktemp -d)
hugo build --baseURL http://127.0.0.1:8321/ -d "$preview_dir/site"
python3 ops/handwriting.py prepare "$preview_dir/site" --catalog "$preview_dir/catalog.json"
uv run --with reportlab python ops/handwriting.py worksheet \
  "$preview_dir/catalog.json" "$preview_dir/worksheet.pdf" --page / --limit 12 --letter-height-mm 10
python3 ops/handwriting.py mock-export "$preview_dir/worksheet.json" "$preview_dir/mock-export.json"
python3 ops/handwriting.py import-mock "$preview_dir/worksheet.json" \
  "$preview_dir/mock-export.json" "$preview_dir/site/handwriting/ink.json"
python3 -m http.server 8321 --bind 127.0.0.1 --directory "$preview_dir/site"
```

Open the preview at http://127.0.0.1:8321/ and use the **Handwriting** switch in the top right. The
PDF is at `$preview_dir/worksheet.pdf`. Use `--page /notes/` for notes prompts or omit
`--page` for sitewide coverage. The PDF matches the reMarkable 2 display proportions and size.
`--letter-height-mm` sets the height of the prompt's capital letters and the spacing between the
writing guides. Each box fits one line. Wide prompts continue in numbered boxes, and the JSON
records each box in PDF points from the top left of its page.

Preparation inserts inline markers into the built HTML. It derives each ID from the source
page, prompt text and repeat number. Copies of a news item share its IDs across views, while
separate occurrences receive their own IDs. Changing a prompt returns that passage to typed
display until matching ink is available. Homepage button labels are included. Long prose is split
at sentence and clause boundaries
where possible. Paragraphs containing code or math and text inside tables stay typed.

The mock export simulates word boxes and emits demo ink for the browser. The deployment script
runs preparation with the Python standard library.

### Importing a completed reMarkable worksheet

Keep the blank PDF and its sibling JSON file. Export the annotated copy from reMarkable as a PDF
with the same pages. Use a freshly prepared local build with an empty ink manifest for the first
real import.

```sh
uv run --with pymupdf python ops/handwriting.py import-pdf \
  "$preview_dir/worksheet.pdf" /path/to/completed.pdf "$preview_dir/site/handwriting/ink.json"
```

The importer subtracts the blank worksheet vectors, uses the existing writing boxes and
baselines, and writes an SVG per word next to the manifest. Refresh the local site and check the
result with **Handwriting**. Use the same destination for subsequent imports. Completed prompts
are merged into the manifest. Empty boxes are fine, and a prompt stays typed until every row
in that prompt is present in an export. Keep the earlier writing on the same worksheet if you
plan to finish a prompt later.

The importer reports rows with ink outside their boxes or ambiguous word gaps. It uses the typed
prompt to count the expected words, so check that the writing appears under the right words in
the preview. It currently expects a vector export whose page layout matches the original PDF.
Once reviewed, a real manifest and its word SVGs can live under `static/handwriting/`.

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
