"""Extract visible vector ink from a completed handwriting worksheet."""

from collections import defaultdict
import re

import pymupdf


MATCH_TOLERANCE = 0.2
# Ink that touches no box joins the nearest box within this many letter heights.
NEAREST_BOX_LETTER_HEIGHTS = 1.0
WORD_PADDING = 0.4
# Word sizes are in CSS ex, the x-height of the font the browser uses, so handwriting follows
# the text's size. The scale comes from the measured height of the small letters
# (measure_writing) and TYPE_BAND_EX.
# Older worksheet maps have no x_height. Small letters on them reached 0.4 of the capital height.
DEFAULT_X_HEIGHT_RATIO = 0.4
# Typed lowercase measured the same way as the writing (measure_writing) is a band 1.10 ex tall
# in EB Garamond: round letters overshoot the x-height and baseline, serifs add ink at both, and
# the font declares its x-height (which sets ex) slightly below the drawn one. The writing's band
# is scaled to the same height. Re-measure this if the site font changes.
TYPE_BAND_EX = 1.10
# Measuring the writing needs this many rows with ink; otherwise the printed guides are used.
MIN_MEASURED_ROWS = 3
PIXELS_PER_POINT = 4
MM = 72 / 25.4


def item_points(item):
    operator, *values = item
    if operator == "re":
        rect, direction = values
        points = [rect.tl, rect.tr, rect.br, rect.bl]
        return points if direction > 0 else points[::-1]
    if operator == "qu":
        quad, = values
        return [quad.ul, quad.ur, quad.lr, quad.ll]
    if operator in {"l", "c"}:
        return values
    raise ValueError(f"Unsupported PDF drawing operation {operator!r}")


def geometry(path, sx, sy):
    operators = []
    coordinates = []
    for item in path["items"]:
        operators.append(item[0])
        points = item_points(item)
        if item[0] == "re":
            points = sorted(points, key=lambda point: (point.x, point.y))
        elif len(path["items"]) == 1 and item[0] == "l":
            points = sorted(points, key=lambda point: (point.x, point.y))
        coordinates.extend(value for point in points for value in (point.x * sx, point.y * sy))
    return tuple(operators), coordinates


def subtract_drawings(original, exported, sx, sy):
    """Match template paths by geometry, allowing rounding and uniform PDF scaling."""
    remaining = defaultdict(list)
    for path in original:
        key, coordinates = geometry(path, 1, 1)
        remaining[key].append(coordinates)

    ink = []
    for path in exported:
        key, coordinates = geometry(path, sx, sy)
        candidates = remaining.get(key, [])
        match = next((index for index, candidate in enumerate(candidates)
                      if all(abs(a - b) <= MATCH_TOLERANCE
                             for a, b in zip(coordinates, candidate, strict=True))), None)
        if match is None:
            ink.append(path)
        else:
            candidates.pop(match)
    return ink, sum(map(len, remaining.values()))


def path_bounds(path, sx, sy):
    rect = path["rect"]
    padding = (path["width"] or 0) / 2
    return pymupdf.Rect((rect.x0 - padding) * sx, (rect.y0 - padding) * sy,
                        (rect.x1 + padding) * sx, (rect.y1 + padding) * sy)


def word_groups(paths, count, letter_height):
    """Use the largest horizontal gaps, declining close or competing boundaries."""
    clusters = []
    for path, bounds in sorted(paths, key=lambda item: item[1].x0):
        if clusters and bounds.x0 <= clusters[-1][1].x1:
            members, previous = clusters[-1]
            members.append(path)
            previous.include_rect(bounds)
        else:
            clusters.append(([path], pymupdf.Rect(bounds)))

    if len(clusters) < count:
        raise ValueError(f"found only {len(clusters)} separable groups for {count} words")
    gaps = sorted(((right.x0 - left.x1, index)
                   for index, ((_, left), (_, right)) in enumerate(zip(clusters, clusters[1:]), 1)),
                  reverse=True)
    if count > 1:
        smallest_split = gaps[count - 2][0]
        next_gap = gaps[count - 1][0] if len(gaps) >= count else 0
        if smallest_split < letter_height * 0.08 or next_gap >= smallest_split * 0.85:
            raise ValueError(f"could not confidently split the ink into {count} words")

    splits = sorted(index for _, index in gaps[:count - 1])
    words = []
    start = 0
    for end in [*splits, len(clusters)]:
        members = []
        extent = pymupdf.Rect(clusters[start][1])
        for items, bounds in clusters[start:end]:
            members.extend(items)
            extent.include_rect(bounds)
        words.append((sorted(members, key=lambda path: path["seqno"]), extent))
        start = end
    return words


def paint(color):
    if color is None:
        return "none"
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in color)


def svg_path(path, sx, sy):
    def coord(point):
        return f"{point.x * sx:.4f} {point.y * sy:.4f}"

    commands = []
    previous = None
    for item in path["items"]:
        op = item[0]
        points = item_points(item)
        if op in {"re", "qu"}:
            commands.extend([f"M {coord(points[0])}", *(f"L {coord(p)}" for p in points[1:]), "Z"])
            previous = None
            continue
        if points[0] != previous:
            if previous is not None and path["closePath"]:
                commands.append("Z")
            commands.append(f"M {coord(points[0])}")
        commands.append(("L " if op == "l" else "C ") + " ".join(map(coord, points[1:])))
        previous = points[-1]
    if previous is not None and path["closePath"]:
        commands.append("Z")

    style = [
        f'fill="{paint(path["fill"])}"',
        f'stroke="{paint(path["color"])}"',
    ]
    if path["fill"] is not None:
        rule = "evenodd" if path["even_odd"] else "nonzero"
        style.extend([f'fill-rule="{rule}"', f'fill-opacity="{path["fill_opacity"]:g}"'])
    if path["color"] is not None:
        cap = ("butt", "round", "square")[max(path["lineCap"])]
        join = ("miter", "round", "bevel")[int(path["lineJoin"])]
        style.extend([f'stroke-width="{path["width"] * sx:.4f}"', f'stroke-linecap="{cap}"',
                      f'stroke-linejoin="{join}"', f'stroke-opacity="{path["stroke_opacity"]:g}"'])
        if match := re.fullmatch(r"\[([\d. ]+)\]\s+([\d.]+)", path["dashes"] or ""):
            dashes = " ".join(f"{float(n) * sx:.4f}" for n in match[1].split())
            if dashes:
                style.extend([f'stroke-dasharray="{dashes}"',
                              f'stroke-dashoffset="{float(match[2]) * sx:.4f}"'])
    return f'<path d="{" ".join(commands)}" {" ".join(style)}/>'


def guide_x_height(slot):
    return slot.get("x_height") or slot["letter_height"] * DEFAULT_X_HEIGHT_RATIO


def measure_writing(rows):
    """Where the small letters actually sit, from how densely the ink covers each height.

    rows holds (slot, strokes, sx, sy) for every box with ink on one worksheet. The body of the
    small letters is the densest band of ink. Its edges, where the density falls to half,
    are the writing's own baseline and x-height. Returns (offset, x_height) in points, the
    offset being how far that baseline sits above the printed one, or None when there is too
    little writing or the result is implausible.
    """
    if len(rows) < MIN_MEASURED_ROWS:
        return None
    guide = guide_x_height(rows[0][0])
    below, above = 2 * guide, 3 * guide
    steps = round((below + above) * PIXELS_PER_POINT)
    profile = [0] * steps
    opaque = bytes(int(value >= 128) for value in range(256))
    for slot, strokes, sx, sy in rows:
        baseline = slot["box"][1] + slot["baseline"]
        left = min(extent.x0 for _, extent in strokes)
        width = max(extent.x1 for _, extent in strokes) - left
        markup = "".join(svg_path(path, sx, sy) for path, _ in strokes)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * PIXELS_PER_POINT:.2f}" '
               f'height="{steps}" viewBox="{left:.4f} {baseline - above:.4f} {width:.4f} '
               f'{below + above:.4f}">{markup}</svg>')
        with pymupdf.open(stream=svg.encode(), filetype="svg") as image:
            pixmap = image[0].get_pixmap(colorspace=pymupdf.csGRAY, alpha=True)
        samples, stride = pixmap.samples, pixmap.stride
        for row in range(min(pixmap.height, steps)):
            line = samples[row * stride:row * stride + 2 * pixmap.width]
            profile[row] += line[1::2].translate(opaque).count(1)

    def height(row):  # points above the printed baseline at the middle of a pixel row
        return above - (row + 0.5) / PIXELS_PER_POINT

    # Smooth over a tenth of the guide x-height, so a single thin row does not end the band.
    reach = max(1, round(0.05 * guide * PIXELS_PER_POINT))
    smooth = [sum(profile[max(0, i - reach):i + reach + 1]) / (2 * reach + 1) for i in range(steps)]
    core = sorted(value for row, value in enumerate(smooth) if 0.2 <= height(row) / guide <= 0.7)
    if not core or not core[len(core) // 2]:
        return None
    half = core[len(core) // 2] / 2
    middle = min(range(steps), key=lambda row: abs(height(row) - 0.45 * guide))
    top = bottom = middle
    while top > 0 and smooth[top - 1] >= half:
        top -= 1
    while bottom < steps - 1 and smooth[bottom + 1] >= half:
        bottom += 1
    lower = height(bottom) - 0.5 / PIXELS_PER_POINT
    x_height = height(top) + 0.5 / PIXELS_PER_POINT - lower
    if not 0.5 * guide <= x_height <= 1.5 * guide or abs(lower) > 0.5 * guide:
        return None
    return lower, x_height


def vector_word(paths, bounds, slot, sx, sy, measured):
    """An SVG of the word, sized in ex, with its baseline position and the worksheet guides.

    The baseline and ex come from the measured writing when available, else from the printed
    guides. The image spans exactly the ink, so a line on the site grows only where the
    writing reaches further above or below the baseline than the typed text does.
    """
    box_top, box_height = slot["box"][1], slot["box"][3]
    offset, x_height = measured or (0, guide_x_height(slot))
    baseline = box_top + slot["baseline"] - offset
    ex = x_height / TYPE_BAND_EX  # points of writing per ex on the site
    # The image reaches at least the baseline, so it can be aligned on it.
    top = min(bounds.y0, baseline) - WORD_PADDING
    bottom = max(bounds.y1, baseline) + WORD_PADDING
    width = bounds.width + 2 * WORD_PADDING
    left = bounds.x0 - WORD_PADDING
    markup = "\n".join(svg_path(path, sx, sy) for path in paths)
    return {
        "svg": (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="{left:.4f} {top:.4f} {width:.4f} {bottom - top:.4f}">\n{markup}\n</svg>\n'),
        "width": round(width / ex, 4),
        "height": round((bottom - top) / ex, 4),
        "descender": round((bottom - baseline) / ex, 4),
        # Where the worksheet's printed lines were, in ex from the writing's baseline.
        "guides": {"cap": round((slot["letter_height"] - offset) / ex, 4),
                   "x": round((guide_x_height(slot) - offset) / ex, 4),
                   "base": round(-offset / ex, 4),
                   "bottom": round((box_top + box_height - baseline) / ex, 4)},
    }


def nearest_box(extent, boxes):
    """The box the stroke overlaps most, else the closest one within reach, else None."""
    overlaps = [(abs(extent & box), index) for index, (_, box) in enumerate(boxes)
                if extent.intersects(box)]
    if overlaps:
        return max(overlaps)[1]
    distances = []
    for index, (slot, box) in enumerate(boxes):
        dx = max(box.x0 - extent.x1, extent.x0 - box.x1, 0)
        dy = max(box.y0 - extent.y1, extent.y0 - box.y1, 0)
        if (dx * dx + dy * dy) ** 0.5 <= slot["letter_height"] * NEAREST_BOX_LETTER_HEIGHTS:
            distances.append((dx * dx + dy * dy, index))
    return min(distances)[1] if distances else None


def read_worksheet_ink(blank_path, filled_path, slots, warnings):
    """Ink per writing box as (slot, words, problem). Notes go in warnings."""
    rows = defaultdict(list)
    for slot in slots:
        if not slot.get("letter_height") or "baseline" not in slot:
            raise ValueError("Regenerate the worksheet map with letter height and baseline coordinates")
        rows[slot["page"]].append(slot)

    results = []
    written = []  # (position in results, (slot, strokes, sx, sy)) for boxes with ink
    with pymupdf.open(blank_path) as blank, pymupdf.open(filled_path) as filled:
        if not blank.is_pdf or not filled.is_pdf:
            raise ValueError("Both worksheet files must be PDFs")
        if len(blank) != len(filled):
            raise ValueError("The completed PDF must have the same pages as the blank worksheet")
        if not rows or not set(rows) <= set(range(1, len(blank) + 1)):
            raise ValueError("The worksheet map references missing pages")
        for number, page_slots in sorted(rows.items()):
            original, exported = blank[number - 1], filled[number - 1]
            sx = original.rect.width / exported.rect.width
            sy = original.rect.height / exported.rect.height
            if original.rotation or exported.rotation or abs(sx / sy - 1) > 0.005:
                raise ValueError(f"Page {number} has a different orientation or aspect ratio")
            if exported.get_image_info():
                raise ValueError(f"Page {number} contains raster images. This importer needs a vector worksheet export")
            original_text = " ".join(original.get_text().split())
            exported_text = " ".join(exported.get_text().split())
            if exported_text and exported_text != original_text:
                raise ValueError(f"Page {number} does not match the blank worksheet text")
            template = original.get_drawings()
            ink, missing = subtract_drawings(template, exported.get_drawings(), sx, sy)
            if not template or missing:
                raise ValueError(f"Page {number} does not match the blank worksheet vector layout")
            paths = [(path, path_bounds(path, sx, sy)) for path in ink]
            boxes = [(slot, pymupdf.Rect(x, y, x + w, y + h))
                     for slot in page_slots for x, y, w, h in [slot["box"]]]
            for slot, box in boxes:
                if not original.rect.contains(box) or box.is_empty:
                    raise ValueError(f"Invalid writing box on page {number}")
            # Each stroke belongs to one box, so ink over an edge stays with the row it was written in.
            assigned = defaultdict(list)
            stray = 0
            for path, extent in paths:
                owner = nearest_box(extent, boxes)
                if owner is None:
                    stray += 1
                else:
                    assigned[owner].append((path, extent))
            if stray:
                warnings.append(f"Page {number}: ignored {stray} strokes away from every writing box.")
            for index, (slot, _) in enumerate(boxes):
                results.append((slot, [], None))
                if assigned[index]:
                    written.append((len(results) - 1, (slot, assigned[index], sx, sy)))

    # The whole worksheet is measured at once, then every word is placed with that measurement.
    measured = measure_writing([row for _, row in written])
    if measured:
        offset, x_height = measured
        guide = guide_x_height(written[0][1][0])
        warnings.append(f"Measured the writing: small letters {x_height / MM:.1f} mm tall "
                        f"(guide {guide / MM:.1f} mm), sitting {offset / MM:+.1f} mm from the baseline.")
    elif written:
        warnings.append("Too little writing to measure it; using the printed guides.")
    for position, (slot, strokes, sx, sy) in written:
        try:
            groups = word_groups(strokes, len(slot["text"].split()), slot["letter_height"])
            words = [vector_word(group, extent, slot, sx, sy, measured) for group, extent in groups]
        except ValueError as error:
            results[position] = (slot, [], str(error))
        else:
            results[position] = (slot, words, None)
    return results
