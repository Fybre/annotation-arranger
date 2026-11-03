import base64
import hashlib
import json
import os
import threading
import time

from .config import Settings
from .errors import ServiceError
from .pdf import arrange_pdf
from .therefore import Therefore, stream_bytes


def fingerprint(document):
    index = document["IndexData"]
    return (index.get("VersionNo"), index.get("LastChangeTimeISO8601"), index.get("LastChangeTime"))


class Arranger:
    def __init__(self, settings: Settings, client_factory=Therefore):
        self.settings = settings
        self.client_factory = client_factory
        # Fixed lock stripes avoid an unbounded dictionary of document numbers.
        self.locks = [threading.Lock() for _ in range(64)]

    def _check_document(self, document):
        if document.get("CheckOutStatus", {}).get("CheckOutState", 0) != 0:
            raise ServiceError("document_checked_out", "Document is already checked out.", 409)

    def _backup(self, doc_no, version, originals):
        if self.settings.backup_dir is None:
            return
        folder = self.settings.backup_dir / str(doc_no) / str(version)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        entries = []
        for stream, data in originals:
            digest = hashlib.sha256(data).hexdigest()
            path = folder / f"stream-{stream['StreamNo']}-{digest[:16]}.pdf"
            if not path.exists():
                # Exclusive creation ensures an earlier original is never overwritten.
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            entries.append(
                {
                    "streamNo": stream["StreamNo"],
                    "fileName": stream["FileName"],
                    "sha256": digest,
                    "path": path.name,
                }
            )
        manifest = folder / "manifest.json"
        manifest.write_text(json.dumps(entries, indent=2))

    def process(
        self,
        doc_no,
        token,
        username=None,
        dry_run=False,
        gap=6,
        margin=12,
        alignment=None,
        flatten=False,
    ):
        if alignment is None and not flatten:
            alignment = "auto"
        lock = self.locks[doc_no % len(self.locks)]
        if not lock.acquire(blocking=False):
            raise ServiceError("document_busy", "This document is already being processed.", 409)
        client = None
        owned_checkout = False
        save_started = False
        start = time.monotonic()
        try:
            client = self.client_factory(
                self.settings.base_url,
                self.settings.tenant,
                token,
                username,
                self.settings.deadline_seconds,
            )
            # Check checkout status before downloading document content.
            initial = client.document(doc_no)
            self._check_document(initial)
            document = client.document(doc_no, data=True)
            self._check_document(document)
            if fingerprint(initial) != fingerprint(document):
                raise ServiceError("document_changed", "Document changed during retrieval.", 409)
            streams = document.get("StreamsInfo") or []
            total = 0
            details, changes, originals = [], [], []
            for stream in streams:
                if not str(stream.get("FileName", "")).lower().endswith(".pdf"):
                    continue
                if stream.get("AnnotationPage", -1) not in (-1, None):
                    raise ServiceError(
                        "annotation_stream", "Separate annotation streams unsupported."
                    )
                data = stream_bytes(stream)
                total += len(data)
                if total > self.settings.max_bytes:
                    raise ServiceError("too_large", "PDF content exceeds the 20 MB limit.", 413)
                arrangement = arrange_pdf(data, gap, margin, alignment, flatten)
                details.append(
                    {
                        "streamNo": stream["StreamNo"],
                        "fileName": stream["FileName"],
                        "stamps": arrangement.stamps,
                        "moves": arrangement.details(),
                        "annotationsFlattened": arrangement.annotations_flattened,
                    }
                )
                if arrangement.changed:
                    # Assert a second arrangement would do nothing before any remote change.
                    if arrange_pdf(arrangement.data, gap, margin, alignment, flatten).changed:
                        raise ServiceError("unstable_layout", "Layout verification failed.", 500)
                    changes.append(
                        {
                            "StreamNo": stream["StreamNo"],
                            "FileName": stream["FileName"],
                            "FileDataBase64JSON": base64.b64encode(arrangement.data).decode(),
                        }
                    )
                    originals.append((stream, data))
            if not details:
                raise ServiceError("no_pdf", "Document contains no supported PDF streams.")
            result = {
                "docNo": doc_no,
                "alignment": alignment,
                "flatten": flatten,
                "status": "dry_run" if dry_run else "unchanged",
                "version": document["IndexData"]["VersionNo"],
                "annotationsMoved": sum(len(s["moves"]) for s in details),
                "annotationsFlattened": sum(s["annotationsFlattened"] for s in details),
                "streams": details,
            }
            if changes and not dry_run:
                if self.settings.backup_dir is not None:
                    self._backup(doc_no, result["version"], originals)
                checkout = client.post("CheckOutDocument", {"DocNo": doc_no})
                if not checkout.get("CheckOutSucceeded"):
                    raise ServiceError("checkout_failed", "Could not check out the document.", 409)
                owned_checkout = True
                current = client.document(doc_no)
                if fingerprint(current) != fingerprint(document):
                    raise ServiceError("document_changed", "Document changed before saving.", 409)
                index = document["IndexData"]
                payload = {
                    "DocNo": doc_no,
                    "CheckInComments": (
                        f"Annotation Arranger: alignment={alignment or 'none'}; flatten={flatten}"
                    ),
                    "IndexData": {
                        "IndexDataItems": [],
                        "LastChangeTimeISO8601": index["LastChangeTimeISO8601"],
                    },
                    "StreamsToUpdate": changes,
                }
                save_started = True
                saved = client.post("UpdateDocument", payload)
                # A new retrieval confirms both persisted bytes and released checkout.
                verified = client.document(doc_no, data=True)
                by_no = {s["StreamNo"]: s for s in verified.get("StreamsInfo") or []}
                for changed in changes:
                    actual = stream_bytes(by_no[changed["StreamNo"]])
                    expected = base64.b64decode(changed["FileDataBase64JSON"])
                    if actual != expected:
                        raise ServiceError(
                            "save_unverified", "Saved document could not be verified.", 502
                        )
                if verified.get("CheckOutStatus", {}).get("CheckOutState", 0) != 0:
                    raise ServiceError(
                        "save_unverified", "Document is still checked out after saving.", 502
                    )
                owned_checkout = False
                result.update(status="updated", version=saved["CurrentDocVersion"])
            result["elapsedMs"] = round((time.monotonic() - start) * 1000)
            return result
        except ServiceError as exc:
            if save_started:
                raise ServiceError(
                    "save_outcome_unknown",
                    "Save was attempted but could not be confirmed. Inspect the document before retrying.",
                    exc.status,
                ) from exc
            raise
        except Exception as exc:
            if save_started:
                raise ServiceError(
                    "save_outcome_unknown",
                    "Save could not be confirmed. Inspect the document before retrying.",
                    502,
                ) from exc
            raise ServiceError(
                "processing_failed", "Document processing failed before saving.", 500
            ) from exc
        finally:
            try:
                if owned_checkout and not save_started:
                    # Release only a checkout acquired by this request, before any save attempt.
                    client.post("UndoCheckOutDocument", {"DocNo": doc_no})
            finally:
                if client:
                    client.close()
                lock.release()
