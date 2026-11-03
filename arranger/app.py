from importlib.metadata import version
from typing import Annotated

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .errors import ServiceError
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
    app = FastAPI(title="Annotation Arranger", version=version("annotation-arranger"))
    arranger = service or Arranger(settings or Settings.from_env())

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"status": "error", "code": exc.code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
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


app = create_app()
