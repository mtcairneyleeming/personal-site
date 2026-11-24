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

Everything here runs locally, with no deploy. Run these commands from the site directory with
Hugo, Python 3, and `uv` available. Local files go in `handwriting-worksheets/`, which git ignores.

```sh
python3 ops/handwriting.py prepare    # hugo build into handwriting-worksheets/site, then annotate
python3 -m http.server 8321 --bind 127.0.0.1 --directory handwriting-worksheets/site
```

`prepare` replaces the previous preview build each time. It also writes
`handwriting-worksheets/catalog.json`, which lists the prompts that do not have ink yet. Open the
preview at http://127.0.0.1:8321/ and use the **Handwriting** switch in the top right. Run
`prepare` again after editing the site or importing ink. `worksheet` also runs it first. With a
directory argument (as `ops/deploy.sh` uses it), `prepare` builds for the real domain and writes
no catalog.

`uv run ops/handwriting.py` installs the worksheet and import dependencies (ReportLab, PyMuPDF)
from the header of the script. To try the browser side with simulated ink:

```sh
# The mock folder is outside blank/, so rm-sync leaves it alone.
uv run ops/handwriting.py worksheet handwriting-worksheets/mock/worksheet.pdf --page / --limit 12
python3 ops/handwriting.py mock-export handwriting-worksheets/mock/worksheet.json \
  handwriting-worksheets/mock/mock-export.json
python3 ops/handwriting.py import-mock handwriting-worksheets/mock/worksheet.json \
  handwriting-worksheets/mock/mock-export.json handwriting-worksheets/site/handwriting/ink.json
```

The demo ink lasts until the next `prepare`. `--page` takes the path of one page: `/` is the
homepage and `/notes/` is the notes list, not the notes themselves. Omit it to cover every page.
`--limit` caps the number of prompts. The PDF matches the reMarkable 2 display proportions and
size. `--letter-height-mm` (default 7) sets the capital rule at the top of each box, and
`--x-height-mm` (default 4) the dashed guide for small letters such as n and m. Small letters
reached 4 mm on the first worksheets. The space below the baseline is one x-height.

The importer does not rely on the guides alone. It measures where the small letters actually
sit on each worksheet: the body of the lowercase is the densest band of ink, and the band's
edges give the writing's own baseline and x-height. With fewer than 3 rows of writing, or an
implausible result, it uses the printed guides; older worksheet maps without the dashed guide
assume 0.4 of the capital height. The site sizes each word in CSS `ex`, so it follows the
x-height of whichever font the browser uses. Typed EB Garamond measured the same way has a band
1.10 ex tall (overshoot and serifs), so the writing's band is scaled to that.
`TYPE_BAND_EX` in `ops/handwriting_pdf.py` holds this value; re-measure it if the font
changes.

Add `?handwriting=debug` to a page URL to see each word's image box, the font's baseline,
x-height and capital height, and the worksheet's baseline, dashed line, capital rule and box
bottom as scaled.
`--text-height-mm` (default 7) sets the capital height of the typed prompt, and so how many
words go in each box. Lower it if you could fit more on a line. Each box fits one line. Wide
prompts continue in numbered boxes, and the JSON records each box in PDF points from the top
left of its page.

Preparation inserts inline markers into the built HTML. It derives each ID from the source
page, prompt text and repeat number. Copies of a news item share its IDs across views, while
separate occurrences receive their own IDs. Changing a prompt returns that passage to typed
display until matching ink is available. Homepage button labels are included. Long prose is split
at sentence and clause boundaries
where possible. Paragraphs containing code or math and text inside tables stay typed.

The mock export simulates word boxes and emits demo ink for the browser. `prepare` needs only
the Python standard library and Hugo.

### Importing a completed reMarkable worksheet

Keep the blank PDF and its sibling JSON file. Put real worksheets in
`handwriting-worksheets/blank/`. `src/sync.py handwriting` in `~/scripts/rm-sync` uploads
each new blank PDF once to the **Handwriting** folder on the reMarkable. After you write on a
worksheet, the sync exports it to `handwriting-worksheets/filled/` under the same file name, and
again after each change. The sync deletes nothing. Trash a finished worksheet on the reMarkable,
and the sync will not upload it again. If you change a blank after uploading it, save it under a
new name.

```sh
uv run ops/handwriting.py worksheet --page /    # e.g. handwriting-worksheets/blank/2026-11-24-home.pdf
(cd ~/scripts/rm-sync && uv run src/sync.py handwriting)   # upload; run again after writing
uv run ops/handwriting.py import-pdf    # every filled worksheet; or name one, e.g. 2026-11-24-home
python3 ops/handwriting.py prepare    # rebuild the preview with the new ink
```

Without an output path, `worksheet` names the PDF after the date and `--page`. The name ends in
`home` for `/`, `notes` for `/notes/`, or `all` without `--page`. It adds `-2`, `-3`, and so on
rather than replace an existing worksheet. The JSON map goes beside the PDF.

Without names, `import-pdf` imports every PDF in `filled/` that has its blank and map in
`blank/`, oldest worksheet first, so ink for a prompt redrawn on a later worksheet wins. It
merges the ink into `static/handwriting/ink.json` (`--output` for another manifest). To import
one worksheet, name it by its blank or filled PDF, or just its file name. For a completed PDF
kept elsewhere, pass the blank and `--filled`. The ink lives
in `static/`, not `data/` or `content/`, because the browser fetches the manifest and each word's
SVG as files. Hugo copies `static/` into the site unchanged. It reads `data/` only during the
build, and `content/` holds pages. Every build includes the ink, but nothing goes live until you
deploy. Check the preview, then commit the manifest and its `words/` SVGs, or discard them with
git. `ops/deploy.sh` ships uncommitted ink too, with its usual `-dirty` warning. Because the
catalog leaves out prompts that already have ink, the next worksheet covers only the remaining
prompts.

The importer subtracts the blank worksheet vectors, uses the existing writing boxes and
baselines, and writes an SVG per word next to the manifest. Completed prompts are merged into
the manifest. Empty boxes are fine, and a prompt stays typed until every row in that prompt is
present in an export. Keep the earlier writing on the same worksheet if you plan to finish a
prompt later.

Writing over the edge of a box is fine. Each stroke goes to the box it overlaps most, or to the
nearest box within one capital height when it touches none, and the word keeps the overhanging
ink. On the site, each word image spans its ink, so a line grows only as far as its writing
reaches above or below the typed text. The importer reports strokes further from every
box, which it ignores, and rows whose word gaps are ambiguous. It uses the typed prompt to count
the expected words, so check that the writing appears under the right words in the preview. It currently expects a vector export whose page layout matches the original PDF.

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
