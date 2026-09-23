# HackAlem AI backend

Local FastAPI backend for prepared transcript analysis, audio transcription, protocol
assembly, and DOCX export. No cloud AI, database, authentication, or meeting-platform
integration. Startup and text analysis do not import `ai/`, faster-whisper, or PyAV.

## Install and start

The integrated application uses Python 3.13.2 on Apple Silicon. Follow
[INTEGRATION.md](INTEGRATION.md) for setup, the real audio contract and tests.
The existing audio environments and models are reused without modification.

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
PYANNOTE_METRICS_ENABLED=0 OTEL_SDK_DISABLED=true \
.venv-integration/bin/python -m uvicorn backend.main:app \
  --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000/ for the frontend. `/health` returns `{"status":"ok"}`
but does not verify model availability. The frontend and API share one origin.
Swagger `/docs` uses CDN assets; the actual application uses only local assets.
Use `/openapi.json` or the application for disconnected checks.

## Local models and configuration

Processing calls `audio_module.transcribe_mp3`, then `add_diarization`. There is
no second recognizer and no dependency on the old `ai/transcription.py`.
Default paths are `audio_module/models/faster-whisper-small`,
`audio_module/models/community-1`, and `audio_module/.venv-diarization/bin/python`.
No runtime downloads. See [audio_module/CHECK.md](../audio_module/CHECK.md) for
initial model setup. Community-1 requires accepted Hugging Face terms for the
initial download, but no token during local processing.

| Variable | Purpose |
|---|---|
| `WHISPER_MODEL_DIR` | Override the existing local small directory |
| `WHISPER_MODEL_PATH` | Legacy fallback for WHISPER_MODEL_DIR |
| `DIARIZATION_MODEL_DIR` | Override the local Community-1 directory |
| `DIARIZATION_PYTHON` | Override the isolated pyannote Python executable |
| `FRONTEND_ORIGINS` | Optional explicit origins if using a separate frontend; unnecessary here |

Run one server process: its lock admits one audio request at a time; concurrent
requests return 503 with Retry-After. `.env` is not automatically loaded.

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
Uploads support `.mp3` and the `.mpeg` audio alias (case-insensitive).
The file part may use `audio/mpeg` for both `.mp3` and `.mpeg`. The request itself
must remain `multipart/form-data`; when using browser FormData, let the browser
set Content-Type and its boundary. MIME type alone does not prove valid audio.
The backend stores `.mpeg` uploads temporarily as `.mp3` without changing bytes,
so adapters with MP3 filename checks remain compatible. The decoder validates
the content; a corrupt `.mpeg` is rejected rather than treated as recognized speech.
Optional query `language=ru` or `kk`;
omit it to auto-detect. Both routes accept `max_seconds=60` for a bounded prefix
(1–600); omitted means the whole recording, limited to 10 minutes.
`/analyze-audio` also accepts optional query `title`.

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
  "diarization": {"status":"unavailable", "code":"model_missing"},
  "processing": {},
  "warnings": ["Локальная диаризация недоступна; транскрипт сохранён."]
}
```

`/analyze-audio` returns `{protocol, text, language, processing, diarization,
diarization_available, warnings}`. **Send only `response.protocol` to `/export-docx`.**
The availability flag is true exactly when `diarization.status == "ok"`.
Unavailable/failed diarization retains the transcript with null speakers.
Successful diarization can also leave ambiguous segments null; reasons are in
`diarization.assignments`. Text and timestamps are preserved.

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

See [INTEGRATION.md](INTEGRATION.md). Audio belongs to Malika, backend to Uldana,
and frontend to Aruzhan. The integration adapter now calls the real audio_module;
all original audio source files are unchanged. Technical labels are never names.

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
of accuracy. The realistic sample expects Гульмира / 15 октября, Тимур / 30 сентября, Айнур / null.
See [INTEGRATION_CHECK.md](INTEGRATION_CHECK.md) for the current integrated checks;
TEST_REPORT.md describes the earlier backend-only stage.

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
changing routes or MeetingProtocol. The current integration is a demonstration MVP; the language and analyzer
limitations above still require validation on representative recordings.
