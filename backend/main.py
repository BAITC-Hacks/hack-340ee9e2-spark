"""Run from the project root: uvicorn backend.main:app --reload."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from backend.schemas import AnalyzeRequest, MeetingProtocol
from backend.services.docx_exporter import DOCX_MEDIA_TYPE, export_protocol_docx
from backend.services.protocol_analyzer import build_protocol

app = FastAPI(title="HackAlem AI — локальный протокол", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    # Omit input values and exception context so errors do not echo meeting text.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", response_model=MeetingProtocol)
def analyze(request: AnalyzeRequest) -> MeetingProtocol:
    try:
        return build_protocol(request)
    except ValueError:
        raise HTTPException(status_code=422, detail="Транскрипт не содержит текста речи.") from None


@app.post(
    "/export-docx", response_class=Response,
    responses={200: {"content": {DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}}},
)
def export_docx(protocol: MeetingProtocol) -> Response:
    try:
        content = export_protocol_docx(protocol)
    except (ValueError, OSError):
        raise HTTPException(status_code=500, detail="Не удалось сформировать DOCX.") from None
    return Response(
        content=content, media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="meeting_protocol.docx"'},
    )
