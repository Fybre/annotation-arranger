"""Only the Therefore operations required for document arrangement."""

import base64
import time

import httpx

from .errors import ServiceError
from .logging import logger


class Therefore:
    def __init__(self, base_url, tenant, token, username=None, deadline_seconds=120):
        self.deadline = time.monotonic() + deadline_seconds
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if tenant:
            headers["TenantName"] = tenant
        if username:
            encoded = base64.b64encode(f"{username}:{token}".encode()).decode()
            headers.update(Authorization=f"Basic {encoded}", UseToken="1")
        else:
            headers["Authorization"] = f"Bearer {token}"
        logger.debug(
            "Therefore client created tenantHeader=%s authMode=%s",
            bool(tenant),
            "connection-token" if username else "bearer",
        )
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.client.close()
        logger.debug("Therefore client closed")

    def post(self, operation, body):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ServiceError("timeout", "Processing deadline reached.", 504)
        start = time.monotonic()
        logger.debug("Therefore POST started operation=%s", operation)
        try:
            response = self.client.post(operation, json=body, timeout=min(remaining, 45))
        except httpx.TimeoutException as exc:
            logger.error("Therefore POST timed out operation=%s", operation)
            raise ServiceError(
                "therefore_timeout",
                f"Therefore timed out during {operation}. If saving, the outcome may be unknown.",
                504,
            ) from exc
        except httpx.HTTPError as exc:
            logger.error(
                "Therefore POST connection failed operation=%s exceptionType=%s",
                operation,
                type(exc).__name__,
            )
            raise ServiceError(
                "therefore_unavailable",
                f"Connection to Therefore failed during {operation}.",
                502,
            ) from exc
        logger.debug(
            "Therefore POST completed operation=%s status=%s elapsedMs=%s",
            operation,
            response.status_code,
            round((time.monotonic() - start) * 1000),
        )
        if response.status_code in (401, 403):
            raise ServiceError(
                "therefore_auth", "Therefore rejected the token or document permissions.", 403
            )
        if not response.is_success:
            # Do not forward arbitrary upstream response bodies: they may contain secrets.
            raise ServiceError(
                "therefore_error",
                f"Therefore rejected {operation} (HTTP {response.status_code}).",
                502,
            )
        try:
            return response.json()
        except ValueError as exc:
            logger.error("Therefore invalid JSON response operation=%s", operation)
            raise ServiceError(
                "therefore_response", "Invalid response from Therefore.", 502
            ) from exc

    def document(self, doc_no, data=False):
        return self.post(
            "GetDocument",
            {
                "DocNo": doc_no,
                "IsIndexDataValuesNeeded": True,
                "IsCheckOutStatusNeeded": True,
                "IsStreamsInfoNeeded": True,
                "IsStreamsInfoAndDataNeeded": data,
                "IsStreamDataBase64JSONNeeded": data,
            },
        )


def stream_bytes(stream):
    if stream.get("StreamDataBase64JSON") is not None:
        return base64.b64decode(stream["StreamDataBase64JSON"], validate=True)
    return bytes(stream.get("StreamData") or [])
