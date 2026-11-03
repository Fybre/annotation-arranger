import time
import uuid
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Annotated

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .errors import ServiceError
from .logging import configure_logging, logger, request_id
from .pdf import Alignment
from .service import Arranger, Settings


class ArrangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    docNo: Annotated[int, Field(strict=True, gt=0)]
    token: SecretStr = Field(min_length=1, max_length=32768)
    username: str | None = Field(default=None, min_length=1, max_length=256)
    dryRun: bool = False
    alignment: Alignment | None = None
    flatten: bool = Field(default=False, strict=True)
    gap: float = Field(default=6, ge=0, le=72, allow_inf_nan=False)
    margin: float = Field(default=12, ge=0, le=144, allow_inf_nan=False)


def create_app(settings=None, service=None):
    @asynccontextmanager
    async def lifespan(app):
        logger.debug("Service started version=%s", version("annotation-arranger"))
        try:
            yield
        finally:
            logger.debug("Service stopped")

    app = FastAPI(
        title="Annotation Arranger", version=version("annotation-arranger"), lifespan=lifespan
    )
    arranger = service or Arranger(settings or Settings.from_env())

    configure_logging(arranger.settings.debug_logging)

    @app.middleware("http")
    async def log_request(request, call_next):
        context = request_id.set(uuid.uuid4().hex[:12])
        start = time.monotonic()
        logger.debug("HTTP request started method=%s", request.method)
        try:
            response = await call_next(request)
            route = request.scope.get("route")
            logger.debug(
                "HTTP request completed method=%s route=%s status=%s elapsedMs=%s",
                request.method,
                getattr(route, "path", "<unmatched>"),
                response.status_code,
                round((time.monotonic() - start) * 1000),
            )
            return response
        except Exception as exc:
            # Exception messages/traceback values may include upstream payloads or secrets.
            logger.error("HTTP request failed exceptionType=%s", type(exc).__name__)
            raise
        finally:
            request_id.reset(context)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        logger.warning("Request rejected code=%s status=%s", exc.code, exc.status)
        return JSONResponse(
            status_code=exc.status,
            content={"status": "error", "code": exc.code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        logger.warning("Request validation failed status=422")
        # FastAPI's default response echoes invalid input, potentially including a token.
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "code": "invalid_request",
                "message": "Check the request fields against /docs.",
            },
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/arrange-annotations")
    def arrange(body: ArrangeRequest):
        # A normal def runs in a worker thread; the response waits for the entire save.
        return arranger.process(
            body.docNo,
            body.token.get_secret_value(),
            body.username,
            body.dryRun,
            body.gap,
            body.margin,
            body.alignment,
            body.flatten,
        )

    return app
