"""Arrange PDF stamps and optionally flatten all annotation appearances."""

from dataclasses import asdict, dataclass
from io import BytesIO
from math import isfinite
from typing import Literal

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, RectangleObject

from .errors import ServiceError
from .flatten import flatten_pdf

Alignment = Literal["left", "right", "top", "bottom", "auto"]


@dataclass
class Move:
    page: int
    annotation: str
    before: list[float]
    after: list[float]


@dataclass
class Arrangement:
    data: bytes
    stamps: int
    moves: list[Move]
    annotations_flattened: int = 0

    @property
    def changed(self):
        return bool(self.moves or self.annotations_flattened)

    def details(self):
        return [asdict(move) for move in self.moves]


def _visual(rect, box, rotation, inverse=False):
    """Map PDF rectangles to/from display coordinates (origin at top left)."""
    left, bottom, right, top = map(float, box)

    def point(x, y):
        if inverse:
            return {
                0: (left + x, top - y),
                90: (left + y, bottom + x),
                180: (right - x, bottom + y),
                270: (right - y, top - x),
            }[rotation]
        return {
            0: (x - left, top - y),
            90: (y - bottom, x - left),
            180: (right - x, y - bottom),
            270: (top - y, right - x),
        }[rotation]

    points = [point(x, y) for x in (rect[0], rect[2]) for y in (rect[1], rect[3])]
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs), max(ys)]


def _collides(a, b, gap):
    epsilon = 0.001
    return (
        a[0] < b[2] + gap - epsilon
        and a[2] > b[0] - gap + epsilon
        and a[1] < b[3] + gap - epsilon
        and a[3] > b[1] - gap + epsilon
    )


def _nearest(visual, placed, gap, margin, width, height):
    """Greedily choose the closest free rectangle; prefer downward movement on ties."""
    if not any(_collides(visual, other, gap) for other in placed):
        return visual
    w, h = visual[2] - visual[0], visual[3] - visual[1]
    max_x, max_y = width - margin - w, height - margin - h
    if max_x < margin or max_y < margin:
        return None
    xs = {visual[0], margin, max_x}
    ys = {visual[1], margin, max_y}
    for other in placed:
        xs.update((other[0] - gap - w, other[2] + gap))
        ys.update((other[1] - gap - h, other[3] + gap))
    candidates = []
    for x in xs:
        for y in ys:
            if x < margin - 0.001 or x > max_x + 0.001:
                continue
            if y < margin - 0.001 or y > max_y + 0.001:
                continue
            candidate = [x, y, x + w, y + h]
            if not any(_collides(candidate, other, gap) for other in placed):
                dx, dy = x - visual[0], y - visual[1]
                candidates.append(((round(dx * dx + dy * dy, 6), dy < 0, abs(dx), y, x), candidate))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _edge_layout(rectangles, alignment, gap, margin, width, height):
    targets = []
    cursor = margin
    for rect in rectangles:
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if alignment in ("left", "right"):
            x = margin if alignment == "left" else width - margin - w
            y = cursor
            cursor += h + gap
        else:
            x = cursor
            y = margin if alignment == "top" else height - margin - h
            cursor += w + gap
        target = [x, y, x + w, y + h]
        if x < margin - 0.001 or y < margin - 0.001:
            return None
        if target[2] > width - margin + 0.001 or target[3] > height - margin + 0.001:
            return None
        targets.append(target)
    return targets


def arrange_pdf(
    data: bytes,
    gap: float = 6,
    margin: float = 12,
    alignment: Alignment | None = None,
    flatten: bool = False,
) -> Arrangement:
    if alignment is None and not flatten:
        alignment = "auto"
    if alignment not in (None, "left", "right", "top", "bottom", "auto"):
        raise ServiceError(
            "invalid_alignment", "Alignment must be left, right, top, bottom, or auto."
        )
    try:
        return _arrange(data, gap, margin, alignment, flatten)
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError("invalid_pdf", "Cannot safely read or arrange this PDF.") from exc


def _arrange(
    data: bytes, gap: float, margin: float, alignment: Alignment | None, flatten: bool
) -> Arrangement:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ServiceError("encrypted_pdf", "Encrypted PDFs are not supported.")
    if len(reader.pages) > 200:
        raise ServiceError("too_many_pages", "PDF exceeds the 200-page processing limit.")
    # Rewriting a signed document would invalidate its signature.
    if reader.get_fields() and any(
        field.get("/FT") == "/Sig" and field.get("/V") for field in reader.get_fields().values()
    ):
        raise ServiceError("signed_pdf", "Signed PDFs cannot be rearranged.")
    if reader.trailer["/Root"].get("/Perms"):
        raise ServiceError("signed_pdf", "Certified PDFs cannot be rearranged.")

    if alignment is None:
        # Flatten alone never validates or changes stamp positioning.
        stamps = sum(
            ref.get_object().get("/Subtype") == "/Stamp"
            for page in reader.pages
            for ref in page.get("/Annots", [])
        )
        result, flattened = flatten_pdf(data)
        return Arrangement(result, stamps, [], flattened)

    writer = PdfWriter(clone_from=reader)
    moves = []
    stamps = 0
    for page_no, page in enumerate(writer.pages, 1):
        rotation = page.rotation % 360
        if rotation not in (0, 90, 180, 270):
            raise ServiceError("unsupported_rotation", "Unsupported PDF page rotation.")
        box = page.cropbox
        height = float(box.height if rotation in (0, 180) else box.width)
        width = float(box.width if rotation in (0, 180) else box.height)
        # Gap and margin are physical PDF points, even on PDFs with a custom UserUnit.
        unit = float(page.get("/UserUnit", 1))
        if not isfinite(unit) or unit <= 0:
            raise ServiceError("invalid_pdf", "Invalid PDF page units.")
        page_gap, page_margin = gap / unit, margin / unit
        page_stamps = []
        for index, ref in enumerate(page.get("/Annots", [])):
            annotation = ref.get_object()
            if annotation.get("/Subtype") != "/Stamp":
                continue
            stamps += 1
            original = list(map(float, annotation.get("/Rect", [])))
            if len(original) != 4 or not all(map(isfinite, original)):
                raise ServiceError("invalid_stamp", "Stamp has an invalid rectangle.")
            if original[2] <= original[0] or original[3] <= original[1]:
                raise ServiceError("invalid_stamp", "Stamp has an empty or reversed rectangle.")
            visual = _visual(original, box, rotation)
            if visual[0] < 0 or visual[1] < 0 or visual[2] > width or visual[3] > height:
                raise ServiceError(
                    "stamp_outside_page", "A stamp extends outside the visible page."
                )
            page_stamps.append((index, annotation, original, visual))
        targets = None
        if alignment != "auto":
            targets = _edge_layout(
                [stamp[3] for stamp in page_stamps], alignment, page_gap, page_margin, width, height
            )
            if targets is None:
                raise ServiceError(
                    "no_space", f"No room to align stamps on page {page_no}; nothing saved."
                )
        placed = []
        for position, (index, annotation, original, visual) in enumerate(page_stamps):
            target = (
                targets[position]
                if targets is not None
                else _nearest(visual, placed, page_gap, page_margin, width, height)
            )
            if target is None:
                raise ServiceError(
                    "no_space", f"No room to separate stamps on page {page_no}; nothing saved."
                )
            placed.append(target)
            if all(abs(a - b) < 0.001 for a, b in zip(visual, target)):
                continue
            # Do not move locked, read-only, hidden, or invisible annotations.
            if int(annotation.get("/F", 0)) & (1 | 2 | 32 | 64 | 128 | 512):
                raise ServiceError(
                    "protected_stamp", "A stamp that needs moving is hidden or locked."
                )
            appearance = annotation.get("/AP")
            if not appearance or not appearance.get_object().get("/N"):
                raise ServiceError("missing_appearance", "Stamp has no saved appearance.")
            after = _visual(target, box, rotation, inverse=True)
            annotation[NameObject("/Rect")] = RectangleObject(after)
            # A popup is an auxiliary annotation; translate it with its parent stamp.
            if annotation.get("/Popup"):
                popup = annotation["/Popup"].get_object()
                if popup.get("/Rect"):
                    dx, dy = after[0] - original[0], after[1] - original[1]
                    p = list(map(float, popup["/Rect"]))
                    popup[NameObject("/Rect")] = RectangleObject(
                        [p[0] + dx, p[1] + dy, p[2] + dx, p[3] + dy]
                    )
            moves.append(Move(page_no, str(annotation.get("/NM", index)), original, after))
    result = data
    if moves:
        output = BytesIO()
        writer.write(output)
        result = output.getvalue()
    flattened = 0
    if flatten:
        result, flattened = flatten_pdf(result)
    # Structural validation and idempotence are checked before submitting to Therefore.
    check = PdfReader(BytesIO(result))
    if len(check.pages) != len(reader.pages):
        raise ServiceError("verification_failed", "PDF page count changed unexpectedly.", 500)
    return Arrangement(result, stamps, moves, flattened)
