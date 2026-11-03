from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, RectangleObject

from arranger.errors import ServiceError
from arranger.pdf import _collides, _visual, arrange_pdf

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "stamped.pdf"


def annotations(reader):
    return [a.get_object() for a in reader.pages[0]["/Annots"]]


def write(writer):
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_separates_stamps_preserves_content_and_appearance_and_is_idempotent():
    original = SAMPLE.read_bytes()
    result = arrange_pdf(original)
    before = PdfReader(BytesIO(original))
    after = PdfReader(BytesIO(result.data))
    a, b = annotations(before), annotations(after)
    assert result.stamps == 2
    assert len(result.moves) == 1
    assert list(a[0]["/Rect"]) == list(b[0]["/Rect"])
    assert float(b[0]["/Rect"][1]) - float(b[1]["/Rect"][3]) == pytest.approx(6)
    assert before.pages[0].get_contents().get_data() == after.pages[0].get_contents().get_data()
    assert before.pages[0].extract_text() == after.pages[0].extract_text()
    for x, y in zip(a, b):
        assert x["/AP"]["/N"].get_data() == y["/AP"]["/N"].get_data()
        assert x["/NM"] == y["/NM"]
        assert x["/M"] == y["/M"]
        assert x["/Subtype"] == y["/Subtype"] == "/Stamp"
    again = arrange_pdf(result.data)
    assert again.moves == []
    assert again.data == result.data


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_auto_chooses_shortest_move_on_rotated_pages(rotation):
    writer = PdfWriter(clone_from=SAMPLE)
    writer.pages[0].rotate(rotation)
    result = arrange_pdf(write(writer))
    page = PdfReader(BytesIO(result.data)).pages[0]
    a, b = [_visual(x.get_object()["/Rect"], page.cropbox, rotation) for x in page["/Annots"]]
    assert not _collides(a, b, 6)
    distance = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    assert distance == pytest.approx(min(a[2] - a[0], a[3] - a[1]) + 6)


def test_wraps_to_top_if_no_room_below_and_rejects_if_nowhere_fits():
    writer = PdfWriter(clone_from=SAMPLE)
    for a in annotations(writer):
        a[NameObject("/Rect")] = RectangleObject([250, 12, 334, 41])
    result = arrange_pdf(write(writer))
    assert result.moves[0].after[1] > result.moves[0].before[1]
    writer.pages[0].cropbox = RectangleObject([240, 0, 350, 50])
    with pytest.raises(ServiceError, match="No room"):
        arrange_pdf(write(writer))


def test_non_stamp_annotation_is_untouched():
    writer = PdfWriter(clone_from=SAMPLE)
    annotations(writer)[1][NameObject("/Subtype")] = NameObject("/FreeText")
    data = write(writer)
    assert arrange_pdf(data).data == data


def test_protected_stamp_and_invalid_pdf_are_rejected():
    writer = PdfWriter(clone_from=SAMPLE)
    annotations(writer)[1][NameObject("/F")] = NumberObject(128)
    with pytest.raises(ServiceError, match="locked"):
        arrange_pdf(write(writer))
    with pytest.raises(ServiceError):
        arrange_pdf(b"not a PDF")


@pytest.mark.parametrize("alignment", ["left", "right", "top", "bottom"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_edge_alignment_respects_visible_page_margin_gap_and_repeated_requests(alignment, rotation):
    writer = PdfWriter(clone_from=SAMPLE)
    page = writer.pages[0]
    page.rotate(rotation)
    # Exercise unequal sizes and a non-zero crop origin.
    page.cropbox = RectangleObject([10, 20, 585, 825])
    annotations(writer)[1][NameObject("/Rect")] = RectangleObject([255, 407, 355, 447])
    data = write(writer)
    result = arrange_pdf(data, gap=9, margin=18, alignment=alignment)
    assert len(result.moves) == 2
    updated = PdfReader(BytesIO(result.data)).pages[0]
    rects = [
        _visual(a.get_object()["/Rect"], updated.cropbox, rotation) for a in updated["/Annots"]
    ]
    width = float(updated.cropbox.width if rotation in (0, 180) else updated.cropbox.height)
    height = float(updated.cropbox.height if rotation in (0, 180) else updated.cropbox.width)
    if alignment == "left":
        assert all(r[0] == pytest.approx(18) for r in rects)
    elif alignment == "right":
        assert all(r[2] == pytest.approx(width - 18) for r in rects)
    elif alignment == "top":
        assert all(r[1] == pytest.approx(18) for r in rects)
    else:
        assert all(r[3] == pytest.approx(height - 18) for r in rects)
    if alignment in ("left", "right"):
        assert rects[1][1] - rects[0][3] == pytest.approx(9)
    else:
        assert rects[1][0] - rects[0][2] == pytest.approx(9)
    assert arrange_pdf(result.data, gap=9, margin=18, alignment=alignment).moves == []
    original = PdfReader(BytesIO(data)).pages[0]
    assert original.get_contents().get_data() == updated.get_contents().get_data()
    for a, b in zip(original["/Annots"], updated["/Annots"]):
        assert a.get_object()["/AP"]["/N"].get_data() == b.get_object()["/AP"]["/N"].get_data()


def test_auto_chooses_shorter_horizontal_move_for_tall_stamps():
    writer = PdfWriter(clone_from=SAMPLE)
    for a in annotations(writer):
        a[NameObject("/Rect")] = RectangleObject([200, 300, 210, 400])
    result = arrange_pdf(write(writer), alignment="auto")
    move = result.moves[0]
    assert abs(move.after[0] - move.before[0]) == pytest.approx(16)
    assert move.after[1] == pytest.approx(move.before[1])


def test_auto_keeps_separated_stamps_exactly_where_they_are():
    result = arrange_pdf(SAMPLE.read_bytes())
    assert arrange_pdf(result.data, alignment="auto").data == result.data


@pytest.mark.parametrize("alignment", ["top", "bottom", "left", "right"])
def test_edge_alignment_rejects_insufficient_space(alignment):
    writer = PdfWriter(clone_from=SAMPLE)
    writer.pages[0].cropbox = RectangleObject([250, 400, 350, 445])
    with pytest.raises(ServiceError, match="No room"):
        arrange_pdf(write(writer), alignment=alignment)


def test_user_unit_scales_physical_margins_and_spacing():
    writer = PdfWriter(clone_from=SAMPLE)
    writer.pages[0][NameObject("/UserUnit")] = NumberObject(2)
    result = arrange_pdf(write(writer), alignment="top", margin=12, gap=6)
    page = PdfReader(BytesIO(result.data)).pages[0]
    a, b = [_visual(ref.get_object()["/Rect"], page.cropbox, 0) for ref in page["/Annots"]]
    assert a[1] == pytest.approx(6)
    assert b[0] - a[2] == pytest.approx(3)
