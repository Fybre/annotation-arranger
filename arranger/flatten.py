"""Flatten saved annotation appearances using qpdf, retaining vector page content."""

from io import BytesIO
from math import isfinite

import pikepdf

from .errors import ServiceError


def _appearance(annotation):
    appearance = annotation.get("/AP", {}).get("/N")
    if isinstance(appearance, pikepdf.Dictionary):
        appearance = appearance.get(annotation.get("/AS", "/Off"))
    return appearance if isinstance(appearance, pikepdf.Stream) else None


def _nonvisual(annotation):
    if int(annotation.get("/F", 0)) & 3:
        return True
    subtype = str(annotation.get("/Subtype", ""))
    if subtype == "/Popup":
        return _appearance(annotation) is None
    if subtype == "/Link" and _appearance(annotation) is None:
        border = annotation.get("/Border", [0, 0, 1])
        width = annotation.get("/BS", {}).get("/W", border[2] if len(border) > 2 else 1)
        return float(width) == 0
    return False


def _check_appearance(annotation, page_number):
    subtype = str(annotation.get("/Subtype", ""))
    # Invisible/hidden annotations and popup interaction have no page appearance to burn in.
    if _nonvisual(annotation):
        return
    appearance = _appearance(annotation)
    if appearance is None:
        raise ServiceError(
            "missing_appearance",
            f"Cannot flatten {subtype or 'annotation'} on page {page_number}: "
            "no saved appearance. Resave it in the PDF viewer first; nothing saved.",
        )
    for rectangle in (annotation.get("/Rect", []), appearance.get("/BBox", [])):
        values = list(map(float, rectangle))
        if (
            len(values) != 4
            or not all(map(isfinite, values))
            or values[2] <= values[0]
            or values[3] <= values[1]
        ):
            raise ServiceError(
                "invalid_annotation", "Annotation has an invalid appearance rectangle."
            )


def flatten_pdf(data: bytes) -> tuple[bytes, int]:
    """Burn appearances into pages and require zero remaining annotation objects."""
    with pikepdf.Pdf.open(BytesIO(data)) as pdf:
        count = sum(len(page.get("/Annots", [])) for page in pdf.pages)
        if count == 0:
            return data, 0
        form = pdf.Root.get("/AcroForm")
        if form is not None:
            if form.get("/XFA") is not None:
                raise ServiceError("xfa_form", "XFA forms cannot be safely flattened.")
            # qpdf creates appearances for supported form fields if missing or stale.
            pdf.generate_appearance_streams()
        # qpdf can discard annotations with missing appearances. Preflight prevents
        # silent loss of any visible marks it cannot render from saved PDF instructions.
        for page_number, page in enumerate(pdf.pages, 1):
            for annotation in page.get("/Annots", []):
                _check_appearance(annotation, page_number)
        pdf.flatten_annotations("all")
        for page in pdf.pages:
            # qpdf retains borderless links and popups. They have no page appearance;
            # explicitly remove those interactions, but never discard an unflattened mark.
            if any(not _nonvisual(a) for a in page.get("/Annots", [])):
                raise ServiceError(
                    "flatten_incomplete", "Not all annotations could be flattened; nothing saved."
                )
            if "/Annots" in page:
                del page["/Annots"]
        if "/AcroForm" in pdf.Root:
            del pdf.Root["/AcroForm"]
        output = BytesIO()
        pdf.save(output)
        result = output.getvalue()
    with pikepdf.Pdf.open(BytesIO(result)) as check:
        if any(page.get("/Annots", []) for page in check.pages):
            raise ServiceError("flatten_incomplete", "Flattened PDF verification failed.")
    return result, count
