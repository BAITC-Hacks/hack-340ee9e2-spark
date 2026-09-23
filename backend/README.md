# HackAlem AI backend

Local FastAPI backend for prepared transcript analysis, audio transcription, protocol
assembly, and DOCX export. No cloud AI, database, authentication, or meeting-platform
integration. Startup and text analysis do not import `ai/`, faster-whisper, or PyAV.

## Install and start

From the repository root, use Python 3.11 or 3.12 for audio dependency compatibility:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Activate an existing environment instead of recreating it. Keep Python, pip, and
Uvicorn in the same environment. For text/API/DOCX only, install
`requirements-backend.txt`; the audio model is optional. The shared requirements
retain the audio participant's faster-whisper dependency and existing httpx.

- Health: http://127.0.0.1:8000/health → HTTP 200 `{"status":"ok"}`
- Swagger: http://127.0.0.1:8000/docs
- Local schema: http://127.0.0.1:8000/openapi.json

Swagger's default JavaScript/CSS use a CDN. When fully disconnected, use curl or
the smoke script; meeting processing itself is local. If port 8000 is occupied,
use `--port 8001` and adjust URLs. No model is loaded by `/health`.

## Model provisioning, separate from meeting processing

Use an existing CTranslate2 faster-whisper directory, or explicitly download public
weights once before processing private recordings:

```bash
python backend/scripts/download_model.py --model small --output models/faster-whisper-small
export WHISPER_MODEL_DIR="$PWD/models/faster-whisper-small"
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
uvicorn backend.main:app --reload
```

The download script never reads meeting files. Do not enable HF_HUB_OFFLINE during
the initial download. For an isolated machine, transfer the complete model directory
and dependency wheels beforehand. No private token is required.

Runtime requires `model.bin`, `config.json`, and `tokenizer.json`; keep all model
vocabulary/configuration files too. A `.pt` checkpoint is not sufficient. The
adapter uses the explicit directory with `local_files_only=True`, disables ONNX
telemetry, and performs no model download. Missing/incomplete model → HTTP 503 for
audio only. CPU INT8, four CPU threads, one inference at a time. A concurrent audio
request gets 503 with Retry-After rather than starting another inference.

## Configuration

| Variable | Purpose |
|---|---|
| `WHISPER_MODEL_DIR` | Explicit local model directory for the default standalone adapter |
| `WHISPER_MODEL_PATH` | Fallback for standalone; required by the optional team adapter |
| `BACKEND_AUDIO_ADAPTER` | `standalone` (default) or `team` |
| `FRONTEND_ORIGINS` | Exact browser origins separated by commas; unset means use a same-origin proxy |
| `HF_HUB_OFFLINE` | Set to `1` during processing |
| `HF_HUB_DISABLE_TELEMETRY` | Set to `1` during processing |

`.env` is not automatically loaded. Set variables before starting the server and
restart it after changing configuration. No credentials are needed. Wildcard CORS
origins are rejected. Example:

```bash
export FRONTEND_ORIGINS='http://localhost:5173,http://127.0.0.1:5173'
```

## Text contract

`POST /analyze`, application/json. Supply exactly one source:

```json
{"text":"Айнур Каировна, проверьте договор с подрядчиком."}
```

or:

```json
{"title":"Совещание","transcript":[{"speaker":"Speaker 1","start":0.0,"end":5.0,"text":"Айнур Каировна, проверьте договор с подрядчиком."}]}
```

Text is nonblank, maximum 100,000 characters total. Up to 2,000 segments/nonblank
lines. `title` is optional/null, at most 200 characters. Speaker and timestamps may
be null or omitted. Timestamps are finite nonnegative seconds with end >= start.
Unknown fields and XML-invalid control characters are rejected with 422.

Response: HTTP 200, the MeetingProtocol itself:

```json
{
  "title": null,
  "summary": "Айнур Каировна, проверьте договор с подрядчиком.",
  "transcript": [{"speaker":null,"start":null,"end":null,"text":"Айнур Каировна, проверьте договор с подрядчиком."}],
  "action_items": [{"text":"Проверить договор с подрядчиком","responsible":"Айнур Каировна","deadline":null,"source_fragment":"Айнур Каировна, проверьте договор с подрядчиком.","confidence":0.75}]
}
```

Unknown responsible person and deadline are null, never inferred from the speaker.
No recognized assignments → action_items: []. Plain text recognizes Name:, Speaker
1:, and Спикер 1: prefixes; structured metadata is preserved. Source fragments may
join adjacent ASR chunks with spaces while retaining their words.

## Audio contract

`POST /transcribe` and `POST /analyze-audio` accept multipart/form-data, field `file`.
Uploads support `.mp3`, `.mpeg`, `.wav`, and `.m4a` (case-insensitive).
The file part may use `audio/mpeg` for both `.mp3` and `.mpeg`. The request itself
must remain `multipart/form-data`; when using browser FormData, let the browser
set Content-Type and its boundary. MIME type alone does not prove valid audio.
The backend stores `.mpeg` uploads temporarily as `.mp3` without changing bytes,
so adapters with MP3 filename checks remain compatible. The decoder validates
the content; a corrupt `.mpeg` is rejected rather than treated as recognized speech.
Optional query `language=ru` or `kk`;
omit it to auto-detect. `/analyze-audio` also accepts optional query `title`.

```bash
curl --fail-with-body 'http://127.0.0.1:8000/transcribe?language=ru' -F 'file=@/absolute/path/meeting.mp3'
curl --fail-with-body 'http://127.0.0.1:8000/analyze-audio?language=ru' -F 'file=@/absolute/path/meeting.mp3'
```

`/transcribe` response shape (illustrative text/times, not an inference result):

```json
{
  "text": "распознанный текст",
  "transcript": [{"speaker":null,"start":0.0,"end":5.0,"text":"распознанный текст"}],
  "language": "ru",
  "diarization_available": false,
  "warnings": ["Диаризация не подключена: speaker=null. Имена по голосу не определяются."]
}
```

`/analyze-audio` returns `{protocol: MeetingProtocol, language, diarization_available,
warnings}`. **Send only `response.protocol` to `/export-docx`, not the envelope.**
The standalone adapter does no diarization and always uses speaker=null. Warnings
also explain recognition and extraction limitations. Display them in the frontend.

Limits: file 32 MiB, complete multipart body 32 MiB + 64 KiB, other request bodies
2 MiB. Validation checks streamed bodies even without Content-Length. User filenames
are never used as storage paths. Temporary files and upload handles are cleaned up
on normal success and failure. Abrupt process termination can leave OS temporary
files; the server does not intentionally persist recordings or protocols.

| HTTP status | Meaning |
|---|---|
| 413 | File/body limit exceeded |
| 415 | Unsupported filename extension |
| 422 | Invalid JSON/query/metadata, empty or undecodable audio, no recognized speech |
| 503 | Missing model/dependency, unavailable selected adapter, or inference busy |
| 500 | Internal analysis, adapter, or export failure |

Errors have a `detail` string or validation list. Validation entries contain loc,
msg, type, not the submitted meeting text. Internal exception details are hidden.

## Export

`POST /export-docx` accepts the complete MeetingProtocol JSON. It returns DOCX bytes
with Content-Type `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
and `Content-Disposition: attachment; filename="meeting_protocol.docx"`.
The document contains title, summary, a four-column assignment table and transcript.
Missing owner/deadline/confidence displays as Не определено. Export uses python-docx
in memory. Invalid protocol → 422; internal export failure → 500.

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/analyze -H 'Content-Type: application/json' -d '{"text":"Айнур Каировна, проверьте договор с подрядчиком."}' -o /tmp/hackalem-protocol.json
curl --fail-with-body -sS http://127.0.0.1:8000/export-docx -H 'Content-Type: application/json' --data-binary @/tmp/hackalem-protocol.json -o /tmp/hackalem-protocol.docx
```

## Team boundaries

See [INTEGRATION.md](INTEGRATION.md) for the inspected audio participant's real
interface, the optional team bridge, and frontend usage. The backend defaults to
standalone and needs no untracked ai/ files. The current team module implements no
diarization. A future real adapter must preserve labels/timestamps and set the
availability flag truthfully. No synthetic speaker alternation is implemented.

## Verification

```bash
python -c 'from backend.main import app; print(app.title)'
python -m unittest discover -s tests -p 'test_backend*.py' -v
# Start the server before smoke tests:
python backend/scripts/smoke_test.py
python backend/scripts/smoke_test.py --audio '/absolute/path/meeting.mp3'
```

The smoke script writes protocol JSON and DOCX into a temporary directory outside
Git and prints its path. Inspect the result rather than treating HTTP 200 as proof
of accuracy. Backend discovery deliberately excludes the pre-existing AI/Ollama
`tests/test_analysis.py`; it and the other participant's files are unchanged.
The realistic sample expects Гульмира / 15 октября, Тимур / 30 сентября, Айнур / null.
See [TEST_REPORT.md](TEST_REPORT.md) for independently executed checks.

## Analyzer limits

Local finite rules recognize imperative verbs, explicit addressees/owner labels,
and selected Russian/Kazakh deadline phrases. The archive's broader vocabulary and
explicit adjacent metadata handling are integrated. A narrow additional rule handles
explicit “пусть Ерлан … подготовит” assignments, separating a following “а вы …”
clause so the first owner/deadline cannot leak into it. A conflicting pair of deadlines
in one fragment remains null. Relative dates stay relative (the leading до/к may
be removed); no calendar date/year is inferred. Summary selects up to three source
phrases, capped at 1,200 characters, rather than summarizing every meeting topic.

No inferred assignment from speakers, no general pronoun resolution, no reliable
cross-turn corrections. Adjacent fragments with the same speaker can be joined;
when speaker is unknown this can join unrelated phrases. Compound tasks may remain
one item. Negations/questions/conditions may be skipped; false positives and missed
tasks remain possible. Scores are heuristics, not calibrated probabilities. A few
Kazakh/mixed template tests do not establish full language support. Self-commitment
forms such as “я подготовлю” are not comprehensively supported.

Replace local_analysis through build_protocol for a future local LLM without
changing routes or MeetingProtocol. The backend is an MVP, not a completed team
product: actual UI integration and real diarization still require the teammates.
