"""Synthetic PDF fixture and offline packaged-runtime verification. No tenant data."""

import json
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)


def synthetic_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=595.2756, height=841.8898)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 16 Tf 40 760 Td (Synthetic test invoice) Tj "
        b"0 -30 Td /F1 12 Tf (Generated example - no customer data) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Annots")] = ArrayObject()
    for label in ["APPROVED", "COMPLETED"]:
        appearance = DecodedStreamObject()
        appearance.set_data(
            f"q 0 .5 0 RG 1 w .5 .5 83 28 re S "
            f"BT /F1 10 Tf 0 .5 0 rg 7 11 Td ({label}) Tj ET Q".encode()
        )
        appearance.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): RectangleObject([0, 0, 84, 29]),
                NameObject("/Resources"): resources,
            }
        )
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Stamp"),
                NameObject("/Rect"): RectangleObject([255.6378, 406.8347, 339.6378, 435.8347]),
                NameObject("/F"): NumberObject(4),
                NameObject("/NM"): TextStringObject(label.lower()),
                NameObject("/M"): TextStringObject("D:20260101000000Z"),
                NameObject("/AP"): DictionaryObject(
                    {NameObject("/N"): writer._add_object(appearance)}
                ),
            }
        )
        page["/Annots"].append(writer._add_object(annotation))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def run():
    from .pdf import arrange_pdf

    source = synthetic_pdf()
    for alignment in [None, "auto", "left", "right", "top", "bottom"]:
        result = arrange_pdf(source, alignment=alignment, flatten=True)
        if result.annotations_flattened != 2:
            raise RuntimeError("PDF flattening self-test failed")
        page = PdfReader(BytesIO(result.data)).pages[0]
        if page.get("/Annots") or "APPROVED" not in page.extract_text():
            raise RuntimeError("PDF content verification self-test failed")
        if arrange_pdf(result.data, alignment=alignment, flatten=True).changed:
            raise RuntimeError("PDF idempotence self-test failed")
    # Exercise bundled CA certificates without sending anything over the network.
    import httpx

    with httpx.Client(trust_env=False):
        pass
    print(json.dumps({"status": "ok", "checks": ["alignment", "flatten", "pdf-content", "tls"]}))
