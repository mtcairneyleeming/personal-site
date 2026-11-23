#!/usr/bin/env python3
"""Annotate rendered Hugo pages, make worksheets, and simulate an ink import."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
from math import isfinite
from pathlib import Path
import re

MANIFEST = Path("handwriting/ink.json")
RM2_PAGE_SIZE = (1404 * 72 / 226, 1872 * 72 / 226)
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
VOID = set("area base br col embed hr img input link meta param source track wbr".split())
SKIP = {"aside", "button", "code", "math", "pre", "script", "style", "svg", "table", "template"}
ENTITY = re.compile(r"&(?:#[xX][\da-fA-F]+|#\d+|[a-zA-Z][a-zA-Z0-9]*);")
BOUNDARY = re.compile(r"""[.!?]+[”’"')\]]*(?=\s|$)|[;:](?=\s)|\s[—–]\s""")
MARKER = re.compile(r'<span data-ink="[0-9a-f]{20}" data-ink-words="\d+:\d+">([^<]*)</span>')
ABBREVIATION = re.compile(r"(?:\b(?:[A-Z]|Dr|Mr|Mrs|Ms|Prof|vs|etc)|\b[ei]\.g)\.$")


def fingerprint(text):
    return sha256(text.encode()).hexdigest()


def normalize(text):
    return " ".join(text.split())


def passages(text, kind):
    """Yield character offsets for short writing prompts."""
    cuts = []
    if kind == "prose":
        for match in BOUNDARY.finditer(text):
            end = match.end()
            if not ABBREVIATION.search(text[:end]):
                cuts.append(end)
    start = 0
    for end in [*cuts, len(text)]:
        words = list(re.finditer(r"\S+", text[start:end]))
        while words:
            count = len(words)
            if kind == "prose" and count > 22:
                # Prefer a natural clause break to the fallback word limit.
                count = next((i for i in range(22, 7, -1)
                              if words[i - 1].group().endswith(",")), 18)
            yield start + words[0].start(), start + words[count - 1].end()
            words = words[count:]
        start = end


def decode_offsets(raw):
    """Keep HTML entities intact when mapping decoded text back into the file."""
    pieces = []
    offsets = [0]
    cursor = 0
    for match in ENTITY.finditer(raw):
        pieces.append(raw[cursor:match.start()])
        offsets.extend(range(cursor + 1, match.start() + 1))
        value = unescape(match.group())
        pieces.append(value)
        offsets.extend([match.start()] * (len(value) - 1) + [match.end()])
        cursor = match.end()
    pieces.append(raw[cursor:])
    offsets.extend(range(cursor + 1, len(raw) + 1))
    return "".join(pieces), offsets


@dataclass
class TextRun:
    offset: int
    text: str
    offsets: list[int]


@dataclass
class Block:
    kind: str
    scope: str
    runs: list[TextRun] = field(default_factory=list)
    skip: bool = False


class Page(HTMLParser):
    def __init__(self, source, route):
        super().__init__(convert_charrefs=False)
        self.route = route
        self.source = MARKER.sub(r"\1", source)
        self.lines = [0, *(match.end() for match in re.finditer("\n", self.source))]
        self.stack = []
        self.blocks = {}
        self.occurrences = Counter()
        self.entries = {}
        self.inserts = []
        self.text_end = 0
        self.feed(self.source)
        self.close()
        for block in self.blocks.values():
            if not block.skip:
                self.collect(block)

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, dict(attrs), self.source_offset()))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.handle_text()

    def handle_entityref(self, name):
        self.handle_text()

    def handle_charref(self, name):
        self.handle_text()

    def handle_text(self):
        tags = {tag for tag, _, _ in self.stack}
        if "main" not in tags or tags & (SKIP - {"code", "math"}):
            return

        block = self.find_block()
        offset = self.source_offset()
        if block is None or offset < self.text_end:
            return
        end = self.source.find("<", offset)
        self.text_end = len(self.source) if end == -1 else end
        decoded, positions = decode_offsets(self.source[offset:self.text_end])
        if tags & {"code", "math"} or "$" in decoded or r"\(" in decoded or r"\[" in decoded:
            block.skip = True
        block.runs.append(TextRun(offset, decoded, positions))

    def find_block(self):
        for index in range(len(self.stack) - 1, 0, -1):
            tag, attrs, offset = self.stack[index]
            parent_classes = self.stack[index - 1][1].get("class", "").split()
            if tag in HEADINGS:
                kind = "heading"
            elif tag == "a" and "button" in attrs.get("class", "").split():
                kind = "button"
            elif tag == "p" or (tag == "span" and "profile_inner" in parent_classes):
                kind = "prose"
            else:
                continue
            if offset not in self.blocks:
                scope = next((attrs["data-ink-source"] for _, attrs, _ in reversed(self.stack)
                              if "data-ink-source" in attrs), self.route)
                self.blocks[offset] = Block(kind, scope)
            return self.blocks[offset]
        return None

    def collect(self, block):
        text = "".join(run.text for run in block.runs)
        for left, right in passages(text, block.kind):
            prompt = normalize(text[left:right])
            if not any(char.isalpha() for char in prompt):
                continue
            key = (block.scope, block.kind, prompt)
            self.occurrences[key] += 1
            identity = fingerprint("\0".join((*key, str(self.occurrences[key]))))[:20]
            if self.mark_runs(block.runs, text, left, right, identity):
                self.entries[identity] = {
                    "id": identity, "text": prompt, "fingerprint": fingerprint(prompt),
                    "source": block.scope, "kind": block.kind,
                }

    def mark_runs(self, runs, text, left, right, identity):
        words = list(re.finditer(r"\S+", text[left:right]))
        marked = False
        start = 0
        for run in runs:
            end = start + len(run.text)
            # Leave tokens that cross an HTML tag boundary in their original markup.
            indexes = [i for i, word in enumerate(words)
                       if start <= left + word.start() and left + word.end() <= end]
            if indexes:
                first, last = indexes[0], indexes[-1]
                lo = left + words[first].start() - start
                hi = left + words[last].end() - start
                self.inserts.extend([
                    (run.offset + run.offsets[lo],
                     f'<span data-ink="{identity}" data-ink-words="{first}:{last + 1}">'),
                    (run.offset + run.offsets[hi], "</span>"),
                ])
                marked = True
            start = end
        return marked

    def markup(self):
        output = []
        start = 0
        for position, tag in sorted(self.inserts, key=lambda pair: pair[0]):
            output.extend([self.source[start:position], tag])
            start = position
        output.append(self.source[start:])
        return "".join(output)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(public, catalog):
    paths = sorted(public.rglob("*.html"), key=lambda path: (path != public / "index.html", path))
    if not (public / "index.html").is_file():
        raise ValueError(f"No Hugo homepage found in {public}")
    entries = {}
    for path in paths:
        route = "/" + path.relative_to(public).as_posix().removesuffix("index.html")
        source = path.read_text(encoding="utf-8")
        page = Page(source, route)
        for identity, entry in page.entries.items():
            entries.setdefault(identity, {**entry, "pages": []})["pages"].append(route)
        marked = page.markup()
        if marked != source:
            path.write_text(marked, encoding="utf-8")
    manifest = public / MANIFEST
    if not manifest.exists():
        write_json(manifest, {"demo": False, "entries": {}})
    current = read_json(manifest)
    if catalog:
        for entry in entries.values():
            ink = current["entries"].get(entry["id"], {})
            entry["pending"] = current["demo"] or ink.get("fingerprint") != entry["fingerprint"]
        write_json(catalog, list(entries.values()))
    print(f"Prepared {len(paths)} HTML files and collected {len(entries)} writing prompts.")


def worksheet(catalog, output, page, limit, letter_height_mm):
    # Only worksheet generation needs this dependency. Hugo deployment uses stdlib.
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import getAscentDescent, stringWidth
    from reportlab.pdfgen import canvas

    if not isfinite(letter_height_mm) or letter_height_mm <= 0:
        raise ValueError("Letter height must be a positive number of millimetres")
    entries = [entry for entry in read_json(catalog)
               if entry["pending"] and (page is None or page in entry["pages"])]
    if limit is not None:
        entries = entries[:limit]
    if not entries:
        raise ValueError("No pending writing prompts match this selection")

    width, height = RM2_PAGE_SIZE
    margin = 12 * mm
    panel_width = width - 2 * margin
    font = "Helvetica"
    letter_height = letter_height_mm * mm
    # Helvetica's ascent equals its cap height (718 units per em).
    ascent, descent = getAscentDescent(font, 1)
    font_size = letter_height / ascent
    descender_space = abs(descent) * font_size
    panel_baseline = letter_height + 1.2 * mm
    panel_height = panel_baseline + descender_space + 0.8 * mm
    first_row_top = 20 * mm
    last_row_bottom = height - 10 * mm
    prompt_baseline = 4 * mm + letter_height
    panel_offset = prompt_baseline + descender_space + 1.5 * mm
    row_height = panel_offset + panel_height + 3 * mm
    if first_row_top + row_height > last_row_bottom:
        raise ValueError("The letter height is too large for the reMarkable 2 worksheet")

    rows = []
    for entry in entries:
        longest_word = max(stringWidth(word, font, font_size) for word in entry["text"].split())
        if longest_word > panel_width - 4 * mm:
            raise ValueError(f'Use a smaller --letter-height-mm for prompt {entry["id"]}; '
                             "one word is wider than the writing box")
        # Leave some extra width for the same words in handwriting.
        lines = simpleSplit(entry["text"], font, font_size, max(panel_width * 0.9, longest_word))
        rows.append((entry, lines))

    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=RM2_PAGE_SIZE)
    pdf.setTitle("Website handwriting worksheet")
    pdf.setSubject("reMarkable worksheet for the personal website")
    slots = []
    page_number = 0

    def next_page():
        nonlocal page_number
        if page_number:
            pdf.showPage()
        page_number += 1
        pdf.setFillColor("#262a35")
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(margin, height - 8 * mm, "Website handwriting")
        pdf.setFont(font, 8)
        pdf.drawString(margin, height - 13 * mm,
                       f"Copy one line per box. The lower rule is the baseline. Capitals: {letter_height_mm:g} mm.")
        pdf.drawRightString(width - margin, 5 * mm, f"Page {page_number}")
        return first_row_top

    top = next_page()
    for entry, lines in rows:
        word_start = 0
        for index, line in enumerate(lines, 1):
            if top + row_height > last_row_bottom:
                top = next_page()
            pdf.setFillColor("#606979")
            pdf.setFont(font, 7)
            pdf.drawString(margin, height - top, f'{entry["source"]}   ·   {entry["id"]}')
            if len(lines) > 1:
                pdf.drawRightString(width - margin, height - top, f"{index}/{len(lines)}")
            pdf.setFont(font, font_size)
            pdf.setFillColor("#262a35")
            pdf.drawString(margin + 2 * mm, height - top - prompt_baseline, line)
            panel_top = top + panel_offset
            pdf.setStrokeColor("#a7abb3")
            pdf.setLineWidth(0.7)
            pdf.rect(margin, height - panel_top - panel_height, panel_width, panel_height, fill=0)
            pdf.setStrokeColor("#b3b3b3")
            pdf.setLineWidth(0.35)
            for guide in (panel_baseline - letter_height, panel_baseline):
                y = height - panel_top - guide
                pdf.line(margin, y, width - margin, y)
            slots.append({
                "id": entry["id"], "fingerprint": entry["fingerprint"], "text": line,
                "word_start": word_start, "page": page_number,
                "box": [margin, panel_top, panel_width, panel_height],
                "baseline": panel_baseline, "letter_height": letter_height,
            })
            word_start += len(line.split())
            top += row_height
    pdf.save()
    write_json(output.with_suffix(".json"), slots)
    print(f"Wrote {output} and its coordinate map ({len(entries)} prompts, {len(slots)} lines).")


def mock_export(worksheet_map, output):
    """Simulate cropped word boxes from a tablet PDF export."""
    words = []
    for slot in read_json(worksheet_map):
        x, y, width, height = slot["box"]
        tokens = slot["text"].split()
        letter_height = slot.get("letter_height", height / 2)
        baseline = slot.get("baseline", height * 0.75)
        units = sum(map(len, tokens)) + len(tokens) - 1
        unit = min(letter_height * 0.65, (width - 10) / units)
        left, top = x + 5, y + baseline - letter_height
        for word in tokens:
            size = unit * len(word)
            words.append({"page": slot["page"], "box": [left, top, size, letter_height], "text": word})
            left += size + unit
    write_json(output, words)
    print(f"Wrote mock export with {len(words)} word boxes.")


def import_mock(worksheet_map, export, output):
    """Match simulated word boxes to worksheet slots and validate against the prompts."""
    words = read_json(export)
    entries = {}
    for slot in read_json(worksheet_map):
        x, y, width, height = slot["box"]
        matches = []
        for word in words:
            left, top, word_width, word_height = word["box"]
            if (word["page"] == slot["page"] and word_width > 0 and word_height > 0
                    and x <= left and left + word_width <= x + width
                    and y <= top and top + word_height <= y + height):
                matches.append(word)
        matches.sort(key=lambda word: (word["box"][1], word["box"][0]))
        tokens = [word["text"] for word in matches]
        if tokens != slot["text"].split():
            raise ValueError(f'Mock handwriting does not match prompt {slot["id"]}')
        entry = entries.setdefault(slot["id"], {"fingerprint": slot["fingerprint"], "words": []})
        if (slot.get("word_start", 0) != len(entry["words"])
                or slot["fingerprint"] != entry["fingerprint"]):
            raise ValueError(f'Unexpected worksheet line order for prompt {slot["id"]}')
        entry["words"].extend({"text": token} for token in tokens)
    for identity, entry in entries.items():
        if fingerprint(" ".join(word["text"] for word in entry["words"])) != entry["fingerprint"]:
            raise ValueError(f"Incomplete worksheet lines for prompt {identity}")
    write_json(output, {"demo": True, "entries": entries})
    print(f"Imported demo ink for {len(entries)} writing prompts.")


def import_pdf(blank, filled, output, worksheet_map):
    import fcntl
    import os
    from tempfile import TemporaryDirectory

    try:
        from handwriting_pdf import read_worksheet_ink
    except ModuleNotFoundError as error:
        if error.name != "pymupdf":
            raise
        raise ValueError("PDF import requires PyMuPDF (uv run --with pymupdf python ...)") from error

    slots = read_json(worksheet_map or blank.with_suffix(".json"))
    prompts = {}
    for slot, words, problem in read_worksheet_ink(blank, filled, slots):
        prompts.setdefault(slot["id"], []).append((slot, words))
        if problem:
            print(f'Page {slot["page"]}, prompt {slot["id"]}, '
                  f'word {slot.get("word_start", 0) + 1}: {problem}.')

    entries = {}
    assets = {}
    blank_count = incomplete_count = 0
    for identity, rows in prompts.items():
        tokens = []
        digest = rows[0][0]["fingerprint"]
        for slot, _ in rows:
            if slot.get("word_start", 0) != len(tokens) or slot["fingerprint"] != digest:
                raise ValueError(f"Invalid worksheet line order for prompt {identity}")
            tokens.extend(slot["text"].split())
        if fingerprint(" ".join(tokens)) != digest:
            raise ValueError(f"The worksheet map is incomplete for prompt {identity}")
        if all(not words for _, words in rows):
            blank_count += 1
            continue
        if any(not words for _, words in rows):
            incomplete_count += 1
            continue

        words = []
        for index, (token, word) in enumerate(zip(tokens, (item for _, row in rows for item in row),
                                                 strict=True)):
            svg = word.pop("svg")
            name = f"{identity}-{index + 1}-{fingerprint(svg)[:16]}.svg"
            assets[name] = svg
            words.append({"text": token, "src": f"words/{name}", **word})
        entries[identity] = {"fingerprint": digest, "words": words}

    if entries:
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=output.parent) as scratch:
            staging = Path(scratch)
            for name, svg in assets.items():
                (staging / name).write_text(svg, encoding="utf-8")
            # Readers see the old manifest until every SVG for the new one is in place.
            directory = os.open(output.parent, os.O_RDONLY)
            try:
                fcntl.flock(directory, fcntl.LOCK_EX)
                current = read_json(output) if output.exists() else {"demo": False, "entries": {}}
                if current["demo"]:
                    raise ValueError("Use a separate manifest path for real ink instead of the demo")
                words_dir = output.parent / "words"
                words_dir.mkdir(exist_ok=True)
                for name in assets:
                    (staging / name).replace(words_dir / name)
                current["entries"].update(entries)
                write_json(staging / "manifest.json", current)
                (staging / "manifest.json").replace(output)
            finally:
                os.close(directory)

    print(f"Imported {len(entries)} prompts. Skipped {blank_count} without usable ink "
          f"and {incomplete_count} with incomplete rows.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare", help="Annotate a Hugo output directory")
    command.add_argument("public", type=Path)
    command.add_argument("--catalog", type=Path)
    command = commands.add_parser("worksheet", help="Create a PDF and a JSON coordinate map")
    command.add_argument("catalog", type=Path)
    command.add_argument("output", type=Path)
    command.add_argument("--page", help="Select prompts appearing on this route, e.g. /")
    command.add_argument("--limit", type=int)
    command.add_argument("--letter-height-mm", type=float, default=10,
                         help="Capital letter height in millimetres (default: 10)")
    command = commands.add_parser("mock-export", help="Simulate word boxes from the worksheet")
    command.add_argument("worksheet_map", type=Path)
    command.add_argument("output", type=Path)
    command = commands.add_parser("import-mock", help="Validate the simulated boxes and write demo ink")
    command.add_argument("worksheet_map", type=Path)
    command.add_argument("export", type=Path)
    command.add_argument("output", type=Path)
    command = commands.add_parser("import-pdf", help="Extract word SVGs from a vector worksheet export")
    command.add_argument("blank", type=Path, help="Original blank worksheet PDF")
    command.add_argument("filled", type=Path, help="Completed worksheet PDF export")
    command.add_argument("output", type=Path, help="Destination ink.json manifest")
    command.add_argument("--worksheet-map", type=Path, help="Defaults to the JSON beside the blank PDF")
    args = vars(parser.parse_args())
    action = args.pop("command")
    handlers = {"prepare": prepare, "worksheet": worksheet,
                "mock-export": mock_export, "import-mock": import_mock, "import-pdf": import_pdf}
    try:
        handlers[action](**args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
