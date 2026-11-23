"""Extract visible vector ink from a completed handwriting worksheet."""

from collections import defaultdict
import re

import pymupdf


MATCH_TOLERANCE = 0.2
BOX_TOLERANCE = 1.0
CAP_HEIGHT_EM = 0.72


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


def vector_word(paths, bounds, slot, sx, sy):
    _, top, _, height = slot["box"]
    width = bounds.width + 0.8
    left = bounds.x0 - 0.4
    markup = "\n".join(svg_path(path, sx, sy) for path in paths)
    scale = CAP_HEIGHT_EM / slot["letter_height"]
    return {
        "svg": (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="{left:.4f} {top:.4f} {width:.4f} {height:.4f}">\n{markup}\n</svg>\n'),
        "width": round(width * scale, 4),
        "height": round(height * scale, 4),
        "descender": round((height - slot["baseline"]) * scale, 4),
    }


def read_worksheet_ink(blank_path, filled_path, slots):
    rows = defaultdict(list)
    for slot in slots:
        if not slot.get("letter_height") or "baseline" not in slot:
            raise ValueError("Regenerate the worksheet map with letter height and baseline coordinates")
        rows[slot["page"]].append(slot)

    results = []
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
                touching = [(path, extent) for path, extent in paths if box.intersects(extent)]
                if not touching:
                    results.append((slot, [], None))
                    continue
                padded = box + (-BOX_TOLERANCE, -BOX_TOLERANCE, BOX_TOLERANCE, BOX_TOLERANCE)
                try:
                    if not all(padded.contains(extent) for _, extent in touching):
                        raise ValueError("ink crosses the writing box boundary")
                    groups = word_groups(touching, len(slot["text"].split()), slot["letter_height"])
                    words = [vector_word(group, extent, slot, sx, sy) for group, extent in groups]
                except ValueError as error:
                    results.append((slot, [], str(error)))
                else:
                    results.append((slot, words, None))
    return results
