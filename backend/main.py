"""Run from repository root: uvicorn backend.main:app --reload."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from backend.schemas import AnalyzeRequest, AudioAnalysisResponse, MeetingProtocol, TranscriptionResult, Title
from backend.services.audio import (AudioBusyError, AudioUnavailableError, InvalidAudioError,
                                    NoSpeechError, get_transcriber)
from backend.services.docx_exporter import DOCX_MEDIA_TYPE, export_protocol_docx
from backend.services.protocol_analyzer import EmptyTranscriptError, build_protocol

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class BodyLimitMiddleware:
    """Bound bodies before multipart parsing; no unbounded temporary upload files."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST', 'PUT', 'PATCH'}:
            return await self.app(scope, receive, send)
        limit = MAX_UPLOAD_BYTES + 64 * 1024 if scope['path'] in {'/transcribe','/analyze-audio'} else 2 * 1024 * 1024
        headers = dict(scope['headers'])
        try:
            announced = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail':'Некорректный Content-Length.'},400)(scope,receive,send)
        if announced > limit:
            return await JSONResponse({'detail':'Превышен лимит размера запроса.'},413)(scope,receive,send)
        chunks = []
        total = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            total += len(message.get('body', b''))
            if total > limit:
                return await JSONResponse({'detail':'Превышен лимит размера запроса.'},413)(scope,receive,send)
            chunks.append(message)
            if not message.get('more_body',False):
                break
        iterator = iter(chunks)
        async def replay():
            return next(iterator, {'type':'http.request','body':b'','more_body':False})
        await self.app(scope,replay,send)


app = FastAPI(title='HackAlem AI — локальный протокол', version='0.2.0')
app.add_middleware(BodyLimitMiddleware)
# No wildcard and no credentials. A local frontend proxy also works without CORS.
origins = [s.strip() for s in os.environ.get('FRONTEND_ORIGINS','').split(',') if s.strip()]
if '*' in origins:
    raise ValueError('FRONTEND_ORIGINS requires explicit origins, not a wildcard.')
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins,
        allow_methods=['GET','POST'], allow_headers=['Content-Type'],
        expose_headers=['Content-Disposition'])


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    errors = [{'loc':e['loc'],'msg':e['msg'],'type':e['type']} for e in exc.errors()]
    return JSONResponse(status_code=422, content={'detail':errors})


@app.get('/health')
def health() -> dict:
    # Liveness only. Availability of local model is checked on audio requests.
    return {'status':'ok'}


def _analyze(request: AnalyzeRequest) -> MeetingProtocol:
    try:
        return build_protocol(request)
    except EmptyTranscriptError:
        raise HTTPException(422,'Транскрипт не содержит текста речи.') from None
    except Exception:
        # Do not mislabel internal Pydantic / analyzer failures as invalid user input.
        raise HTTPException(500,'Не удалось проанализировать транскрипт.') from None


@app.post('/analyze', response_model=MeetingProtocol)
def analyze(request: AnalyzeRequest) -> MeetingProtocol:
    return _analyze(request)


async def _transcribe(file: UploadFile, language: str | None, transcriber,
                      max_seconds: int | None = None) -> TranscriptionResult:
    suffix = Path(file.filename or '').suffix.lower()
    try:
        if suffix not in {'.mp3','.mpeg'}:
            raise HTTPException(415,'Поддерживаются MP3 и MPEG-аудио.')
        # Never use the supplied filename as a filesystem path.
        with TemporaryDirectory(prefix='hackalem-audio-') as directory:
            # MPEG audio may be named .mpeg. Normalize this alias for adapters
            # that require .mp3 filenames; actual decoding still checks the bytes.
            stored_suffix = '.mp3' if suffix == '.mpeg' else suffix
            path = Path(directory) / ('upload' + stored_suffix)
            size = 0
            with path.open('wb') as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413,'Размер аудио превышает 32 МиБ.')
                    target.write(chunk)
            if size == 0:
                raise HTTPException(422,'Аудиофайл пуст.')
            options = {'language': language}
            if max_seconds is not None:
                options['max_seconds'] = max_seconds
            result = await run_in_threadpool(transcriber.transcribe, path, **options)
            # Validate teammate adapter output; do not fabricate transcript/speakers.
            return TranscriptionResult.model_validate(result)
    except AudioUnavailableError as exc:
        raise HTTPException(503,str(exc)) from None
    except AudioBusyError:
        raise HTTPException(503,'Обрабатывается другая запись. Повторите позже.',headers={'Retry-After':'5'}) from None
    except InvalidAudioError as exc:
        raise HTTPException(422,str(exc)) from None
    except NoSpeechError:
        raise HTTPException(422,'Речь в записи не обнаружена.') from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500,'Не удалось обработать аудио.') from None
    finally:
        await file.close()


@app.post('/transcribe', response_model=TranscriptionResult)
async def transcribe(file: Annotated[UploadFile, File()],
                     language: Annotated[Literal['ru','kk'] | None, Query()] = None,
                     max_seconds: Annotated[int | None, Query(ge=1, le=600)] = None,
                     transcriber=Depends(get_transcriber)):
    return await _transcribe(file, language, transcriber, max_seconds)


@app.post('/analyze-audio', response_model=AudioAnalysisResponse)
async def analyze_audio(file: Annotated[UploadFile, File()],
                        language: Annotated[Literal['ru','kk'] | None, Query()] = None,
                        title: Annotated[Title | None, Query()] = None,
                        max_seconds: Annotated[int | None, Query(ge=1, le=600)] = None,
                        transcriber=Depends(get_transcriber)):
    result = await _transcribe(file, language, transcriber, max_seconds)
    request = AnalyzeRequest(title=title, transcript=result.transcript)
    protocol = await run_in_threadpool(_analyze, request)
    return AudioAnalysisResponse(protocol=protocol, text=result.text, language=result.language,
        diarization=result.diarization, processing=result.processing,
        diarization_available=result.diarization_available, warnings=[*result.warnings,
            'Проверьте поручения по расшифровке: анализ может пропустить задачи и ошибиться в ответственных и сроках.'])


@app.post('/export-docx', response_class=Response,
    responses={200:{'content':{DOCX_MEDIA_TYPE:{'schema':{'type':'string','format':'binary'}}}}})
def export_docx(protocol: MeetingProtocol) -> Response:
    try:
        content = export_protocol_docx(protocol)
    except Exception:
        raise HTTPException(500,'Не удалось сформировать DOCX.') from None
    return Response(content=content,media_type=DOCX_MEDIA_TYPE,
                    headers={'Content-Disposition':'attachment; filename="meeting_protocol.docx"'})


# Mount last: API routes take priority; only public frontend files are served.
app.mount('/', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'frontend', html=True), name='frontend')
