import base64
import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arranger.app import create_app
from arranger.errors import ServiceError
from arranger.service import Arranger, Settings
from arranger.therefore import Therefore
from tests.test_flatten import mixed_annotations

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "stamped.pdf"


class FakeTherefore:
    def __init__(self):
        self.document_data = {
            "IndexData": {
                "CategoryNo": 392,
                "VersionNo": 3,
                "LastChangeTimeISO8601": "2026-11-03T00:00:00Z",
                "IndexDataItems": [{"StringIndexData": {"DataValue": "test"}}],
            },
            "CheckOutStatus": {"CheckOutState": 0},
            "StreamsInfo": [
                {
                    "StreamNo": 0,
                    "FileName": "invoice.pdf",
                    "AnnotationPage": -1,
                    "StreamDataBase64JSON": base64.b64encode(SAMPLE.read_bytes()).decode(),
                },
                {"StreamNo": 1, "FileName": "attachment.txt", "StreamData": [65, 66]},
            ],
        }
        self.calls = []
        self.fail_save = False
        self.change_on_checkout = False

    def document(self, doc_no, data=False):
        return copy.deepcopy(self.document_data)

    def close(self):
        pass

    def post(self, operation, body):
        self.calls.append((operation, body))
        if operation == "CheckOutDocument":
            self.document_data["CheckOutStatus"]["CheckOutState"] = 1
            if self.change_on_checkout:
                self.document_data["IndexData"]["VersionNo"] += 1
            return {"CheckOutSucceeded": True}
        if operation == "UndoCheckOutDocument":
            self.document_data["CheckOutStatus"]["CheckOutState"] = 0
            return {}
        if operation == "UpdateDocument":
            if self.fail_save:
                raise ServiceError("timeout", "timeout", 504)
            for stream in body["StreamsToUpdate"]:
                existing = next(
                    s
                    for s in self.document_data["StreamsInfo"]
                    if s["StreamNo"] == stream["StreamNo"]
                )
                existing["StreamDataBase64JSON"] = stream["FileDataBase64JSON"]
            self.document_data["IndexData"]["VersionNo"] += 1
            self.document_data["CheckOutStatus"]["CheckOutState"] = 0
            return {"CurrentDocVersion": self.document_data["IndexData"]["VersionNo"]}
        raise AssertionError(operation)


@pytest.fixture
def service(tmp_path):
    fake = FakeTherefore()
    settings = Settings("https://example.test/restun", "test", frozenset({392}), tmp_path)
    return Arranger(settings, lambda *args: fake), fake


def test_synchronous_save_preserves_attachments_and_noop_retry(service):
    arranger, fake = service
    result = arranger.process(123, "secret")
    assert result["status"] == "updated"
    assert result["version"] == 4
    update = next(body for op, body in fake.calls if op == "UpdateDocument")
    assert [s["StreamNo"] for s in update["StreamsToUpdate"]] == [0]
    assert update["IndexData"]["IndexDataItems"] == []
    assert fake.document_data["StreamsInfo"][1]["StreamData"] == [65, 66]
    assert len(list(arranger.settings.backup_dir.rglob("*.pdf"))) == 1
    assert arranger.process(123, "secret")["status"] == "unchanged"
    assert sum(op == "UpdateDocument" for op, _ in fake.calls) == 1


def test_preview_never_checks_out_or_saves(service):
    arranger, fake = service
    assert arranger.process(123, "secret", dry_run=True)["annotationsMoved"] == 1
    assert fake.calls == []


def test_category_and_existing_checkout_block_all_writes(service):
    arranger, fake = service
    fake.document_data["IndexData"]["CategoryNo"] = 999
    with pytest.raises(ServiceError, match="category"):
        arranger.process(123, "secret")
    fake.document_data["IndexData"]["CategoryNo"] = 392
    fake.document_data["CheckOutStatus"]["CheckOutState"] = 1
    with pytest.raises(ServiceError, match="checked out"):
        arranger.process(123, "secret")
    assert fake.calls == []


def test_conflicting_edit_releases_own_checkout_without_save(service):
    arranger, fake = service
    fake.change_on_checkout = True
    with pytest.raises(ServiceError, match="changed"):
        arranger.process(123, "secret")
    assert [op for op, _ in fake.calls] == ["CheckOutDocument", "UndoCheckOutDocument"]


def test_ambiguous_save_is_not_retried_or_undone(service):
    arranger, fake = service
    fake.fail_save = True
    with pytest.raises(ServiceError) as err:
        arranger.process(123, "secret")
    assert err.value.code == "save_outcome_unknown"
    assert [op for op, _ in fake.calls] == ["CheckOutDocument", "UpdateDocument"]


def test_http_response_waits_for_save_and_never_echoes_token(service):
    arranger, fake = service
    client = TestClient(create_app(service=arranger))
    r = client.post("/arrange-annotations", json={"docNo": 123, "token": "secret"})
    assert r.status_code == 200 and r.json()["version"] == 4
    assert fake.document_data["CheckOutStatus"]["CheckOutState"] == 0
    bad = client.post("/arrange-annotations", json={"docNo": -1, "token": "secret"})
    assert bad.status_code == 422
    assert "secret" not in bad.text


def test_connection_token_uses_basic_and_use_token_header():
    client = Therefore("https://example.test", "tenant", "token", "user")
    try:
        assert client.client.headers["UseToken"] == "1"
        assert client.client.headers["Authorization"] == "Basic dXNlcjp0b2tlbg=="
    finally:
        client.close()


@pytest.mark.parametrize("alignment", ["left", "right", "top", "bottom", "auto"])
def test_alignment_passes_through_http_save_verification_and_repeat(service, alignment):
    arranger, fake = service
    client = TestClient(create_app(service=arranger))
    body = {"docNo": 123, "token": "secret", "alignment": alignment}
    preview = client.post("/arrange-annotations", json={**body, "dryRun": True})
    assert preview.status_code == 200
    assert preview.json()["alignment"] == alignment
    assert fake.calls == []
    saved = client.post("/arrange-annotations", json=body)
    assert saved.status_code == 200
    assert saved.json()["status"] == "updated"
    repeat = client.post("/arrange-annotations", json=body)
    assert repeat.status_code == 200
    assert repeat.json()["status"] == "unchanged"
    assert sum(op == "UpdateDocument" for op, _ in fake.calls) == 1


def test_invalid_alignment_is_rejected_without_remote_writes(service):
    arranger, fake = service
    client = TestClient(create_app(service=arranger))
    response = client.post(
        "/arrange-annotations", json={"docNo": 123, "token": "secret", "alignment": "middle"}
    )
    assert response.status_code == 422
    assert "secret" not in response.text
    assert fake.calls == []


@pytest.mark.parametrize("alignment", [None, "auto", "left", "right", "top", "bottom"])
def test_http_flatten_alone_or_combined_dry_run_save_and_repeat(service, alignment):
    arranger, fake = service
    client = TestClient(create_app(service=arranger))
    body = {"docNo": 123, "token": "secret", "flatten": True}
    if alignment is not None:
        body["alignment"] = alignment
    preview = client.post("/arrange-annotations", json={**body, "dryRun": True})
    assert preview.status_code == 200
    assert preview.json()["annotationsFlattened"] == 2
    assert preview.json()["annotationsMoved"] == (
        0 if alignment is None else 1 if alignment == "auto" else 2
    )
    assert preview.json()["alignment"] == alignment
    assert fake.calls == []
    saved = client.post("/arrange-annotations", json=body)
    assert saved.status_code == 200
    assert saved.json()["status"] == "updated"
    assert saved.json()["flatten"] is True
    assert saved.json()["annotationsFlattened"] == 2
    repeated = client.post("/arrange-annotations", json=body)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "unchanged"
    assert repeated.json()["annotationsFlattened"] == 0
    assert sum(op == "UpdateDocument" for op, _ in fake.calls) == 1


def test_flatten_saves_pdf_without_stamps_and_preserves_other_attachments(service):
    arranger, fake = service
    from io import BytesIO

    import pikepdf

    with pikepdf.Pdf.open(BytesIO(mixed_annotations())) as pdf:
        del pdf.pages[0].Annots[0]
        out = BytesIO()
        pdf.save(out)
    fake.document_data["StreamsInfo"][0]["StreamDataBase64JSON"] = base64.b64encode(
        out.getvalue()
    ).decode()
    result = arranger.process(123, "secret", flatten=True)
    assert result["status"] == "updated"
    assert result["annotationsMoved"] == 0
    assert result["annotationsFlattened"] == 9
    assert fake.document_data["StreamsInfo"][1]["StreamData"] == [65, 66]


def test_flatten_requires_boolean(service):
    arranger, fake = service
    client = TestClient(create_app(service=arranger))
    response = client.post(
        "/arrange-annotations", json={"docNo": 123, "token": "secret", "flatten": "false"}
    )
    assert response.status_code == 422
    assert fake.calls == []
