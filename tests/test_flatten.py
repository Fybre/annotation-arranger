import shutil
import subprocess
from io import BytesIO

import pikepdf
import pytest
from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, RectangleObject

from arranger.errors import ServiceError
from arranger.pdf import arrange_pdf
from tests.test_pdf import SAMPLE


def saved(pdf):
    out = BytesIO()
    pdf.save(out)
    return out.getvalue()


def mixed_annotations():
    """Visible marks of several subtypes with real, independently rendered appearances."""
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(600, 800))
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
        )
    )
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    page.Contents = pdf.make_stream(b"BT /F1 16 Tf 30 760 Td (Base document text) Tj ET")
    page.Annots = pikepdf.Array()
    subtypes = ["Stamp", "FreeText", "Highlight", "Ink", "Square", "Circle", "Line", "Text"]
    for index, subtype in enumerate(subtypes):
        y = 680 - index * 70
        appearance = pdf.make_stream(
            f"q 0 .6 0 RG 2 w 1 1 198 38 re S "
            f"BT /F1 12 Tf 10 14 Td ({subtype} mark) Tj ET Q".encode()
        )
        appearance.Type = pikepdf.Name.XObject
        appearance.Subtype = pikepdf.Name.Form
        appearance.BBox = pikepdf.Array([0, 0, 200, 40])
        appearance.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        annotation = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name("/" + subtype),
                Rect=pikepdf.Array([30, y, 230, y + 40]),
                F=4,
                AP=pikepdf.Dictionary(N=appearance),
            )
        )
        annotation.Contents = f"{subtype} mark"
        if subtype == "FreeText":
            annotation.DA = "/F1 12 Tf 0 g"
        elif subtype == "Highlight":
            annotation.QuadPoints = pikepdf.Array([30, y + 40, 230, y + 40, 30, y, 230, y])
            annotation.C = pikepdf.Array([1, 1, 0])
            appearance.Resources.ExtGState = pikepdf.Dictionary(
                GS0=pikepdf.Dictionary(Type=pikepdf.Name.ExtGState, BM=pikepdf.Name.Multiply)
            )
            appearance.write(
                b"q /GS0 gs 1 1 0 rg 0 0 200 40 re f 0 g "
                b"BT /F1 12 Tf 10 14 Td (Highlight mark) Tj ET Q"
            )
        elif subtype == "Ink":
            annotation.InkList = pikepdf.Array([pikepdf.Array([30, y, 230, y + 40])])
        elif subtype == "Line":
            annotation.L = pikepdf.Array([30, y, 230, y + 40])
        page.Annots.append(annotation)
    page.Annots.append(
        pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([30, 740, 200, 760]),
                Border=pikepdf.Array([0, 0, 0]),
                A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI="https://example.com"),
            )
        )
    )
    page.Annots.append(
        pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.Popup,
                Rect=pikepdf.Array([260, 50, 500, 150]),
                Parent=page.Annots[7],
                Open=False,
            )
        )
    )
    data = saved(pdf)
    pdf.close()
    return data


def test_flatten_alone_preserves_overlapping_stamp_positions_and_moves_no_stamps():
    result = arrange_pdf(SAMPLE.read_bytes(), flatten=True)
    assert result.moves == []
    assert result.stamps == 2
    assert result.annotations_flattened == 2
    assert result.changed
    reader = PdfReader(BytesIO(result.data))
    assert not reader.pages[0].get("/Annots")
    assert "APPROVED" in reader.pages[0].extract_text()
    assert "COMPLETED" in reader.pages[0].extract_text()
    # Coordinates in the content stream retain the original rectangle.
    assert b"255.6378" in reader.pages[0].get_contents().get_data()
    again = arrange_pdf(result.data, flatten=True)
    assert not again.changed and again.data == result.data


@pytest.mark.parametrize("alignment", ["auto", "left", "right", "top", "bottom"])
def test_align_then_flatten_and_repeating_is_noop(alignment):
    result = arrange_pdf(SAMPLE.read_bytes(), alignment=alignment, flatten=True)
    assert len(result.moves) == (1 if alignment == "auto" else 2)
    assert result.annotations_flattened == 2
    assert not PdfReader(BytesIO(result.data)).pages[0].get("/Annots")
    assert not arrange_pdf(result.data, alignment=alignment, flatten=True).changed


def test_flattens_other_annotations_and_removes_links_and_popup_interactivity():
    data = mixed_annotations()
    result = arrange_pdf(data, flatten=True)
    assert result.stamps == 1
    assert result.moves == []
    assert result.annotations_flattened == 10
    page = PdfReader(BytesIO(result.data)).pages[0]
    assert not page.get("/Annots")
    text = page.extract_text()
    for label in [
        "Base document text",
        "Stamp",
        "FreeText",
        "Highlight",
        "Ink",
        "Square",
        "Circle",
        "Line",
        "Text",
    ]:
        assert label in text


def test_missing_visible_appearance_fails_instead_of_losing_annotation():
    with pikepdf.Pdf.open(BytesIO(mixed_annotations())) as pdf:
        del pdf.pages[0].Annots[2]["/AP"]
        data = saved(pdf)
    with pytest.raises(ServiceError, match="no saved appearance"):
        arrange_pdf(data, flatten=True)


def test_form_value_is_burned_in_and_field_removed():
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page()
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica
            )
        )
        widget = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.Widget,
                FT=pikepdf.Name.Tx,
                T="name",
                V="FORM VALUE",
                F=4,
                Rect=pikepdf.Array([40, 100, 240, 125]),
                DA="/F1 12 Tf 0 g",
            )
        )
        page.Annots = pikepdf.Array([widget])
        pdf.Root.AcroForm = pikepdf.Dictionary(
            Fields=pikepdf.Array([widget]),
            NeedAppearances=True,
            DR=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)),
            DA="/F1 12 Tf 0 g",
        )
        data = saved(pdf)
    result = arrange_pdf(data, flatten=True)
    reader = PdfReader(BytesIO(result.data))
    assert result.annotations_flattened == 1
    assert "FORM VALUE" in reader.pages[0].extract_text()
    assert not reader.pages[0].get("/Annots")
    assert not reader.get_fields()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_flatten_handles_rotated_cropped_pages_and_no_stamp_movement(rotation):
    writer = PdfWriter(clone_from=SAMPLE)
    page = writer.pages[0]
    page.rotate(rotation)
    page.cropbox = RectangleObject([10, 20, 585, 825])
    page[NameObject("/UserUnit")] = NumberObject(2)
    buf = BytesIO()
    writer.write(buf)
    result = arrange_pdf(buf.getvalue(), flatten=True)
    output = PdfReader(BytesIO(result.data)).pages[0]
    assert output.rotation == rotation
    assert list(output.cropbox) == list(page.cropbox)
    assert output.get("/UserUnit") == 2
    assert not output.get("/Annots")
    assert result.moves == []


def test_flatten_rejects_signed_and_encrypted_pdfs():
    writer = PdfWriter(clone_from=SAMPLE)
    writer._root_object[NameObject("/Perms")] = DictionaryObject(
        {NameObject("/DocMDP"): NumberObject(1)}
    )
    buf = BytesIO()
    writer.write(buf)
    with pytest.raises(ServiceError, match="Certified"):
        arrange_pdf(buf.getvalue(), flatten=True)
    writer = PdfWriter(clone_from=SAMPLE)
    writer.encrypt("password")
    buf = BytesIO()
    writer.write(buf)
    with pytest.raises(ServiceError, match="Encrypted"):
        arrange_pdf(buf.getvalue(), flatten=True)


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="Poppler is needed for visual comparison")
@pytest.mark.parametrize("case", ["stamps", "bottom", "mixed"])
def test_flatten_preserves_rendered_page_appearance(tmp_path, case):
    source = mixed_annotations() if case == "mixed" else SAMPLE.read_bytes()
    if case == "bottom":
        source = arrange_pdf(source, alignment="bottom").data
    flattened = arrange_pdf(source, flatten=True).data
    images = []
    for name, data in [("source", source), ("flattened", flattened)]:
        path = tmp_path / f"{name}.pdf"
        path.write_bytes(data)
        subprocess.run(
            [
                "pdftoppm",
                "-scale-to",
                "1100",
                "-singlefile",
                "-png",
                str(path),
                str(tmp_path / name),
            ],
            check=True,
            capture_output=True,
        )
        images.append(Image.open(tmp_path / f"{name}.png").convert("RGB"))
    assert images[0].size == images[1].size
    difference = ImageStat.Stat(ImageChops.difference(*images))
    assert sum(difference.mean) / 3 < 0.01


def test_selected_checkbox_appearance_state_is_flattened():
    with pikepdf.Pdf.open(BytesIO(mixed_annotations())) as pdf:
        widget = pdf.pages[0].Annots[0]
        on = widget.AP.N
        off = pdf.make_stream(b"")
        off.BBox = on.BBox
        widget.Subtype = pikepdf.Name.Widget
        widget.FT = pikepdf.Name.Btn
        widget.T = "consent"
        widget.V = pikepdf.Name.Yes
        widget.AS = pikepdf.Name.Yes
        widget.AP.N = pikepdf.Dictionary(Yes=on, Off=off)
        pdf.pages[0].Annots = pikepdf.Array([widget])
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([widget]))
        data = saved(pdf)
    result = arrange_pdf(data, flatten=True)
    reader = PdfReader(BytesIO(result.data))
    assert result.annotations_flattened == 1
    assert "Stamp mark" in reader.pages[0].extract_text()
    assert not reader.pages[0].get("/Annots")
