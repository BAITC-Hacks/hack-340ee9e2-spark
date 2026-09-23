# HackAlem AI: offline protocol API

Run commands from the repository root using Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

If `.venv` already exists, activate it rather than recreating it. Keep `python`,
`pip`, and `uvicorn` in that same environment; this machine has multiple Python
installations, and an unactivated `python3` may not have the installed packages.

Health: http://127.0.0.1:8000/health

Swagger: http://127.0.0.1:8000/docs

If port 8000 is occupied, use `--port 8001` and update the URLs accordingly.
The shared requirements include the audio team's dependencies; the backend itself
uses FastAPI, Uvicorn, Pydantic and python-docx. Tests also use httpx.
Processing uses local Python rules, with no AI API, Ollama server, model download,
database, or disk storage of meeting content. Package installation needs internet
unless dependencies are already available locally.

## API contract

All JSON bodies use `Content-Type: application/json`. Unknown properties are
rejected. Validation errors return HTTP 422 with `{"detail": [...]}`; error entries
contain `loc`, `msg`, and `type`, without the submitted meeting text.

### GET /health

HTTP 200, `application/json`:

```json
{"status": "ok"}
```

### POST /analyze

Send exactly one of `text` or `transcript`. `title` is optional and defaults to
null. A provided title must be nonblank.

```json
{"text": "Айнур Каировна, проверьте договор с подрядчиком."}
```

Alternatively, send structured segments:

```json
{
  "title": "Проверка договоров",
  "transcript": [
    {
      "speaker": "Speaker 1",
      "start": 0.0,
      "end": 5.0,
      "text": "Айнур Каировна, проверьте договор с подрядчиком."
    }
  ]
}
```

`text` is required within each segment. `speaker`, `start`, and `end` may be
omitted or null. Timestamps are finite nonnegative seconds; `end >= start` when
both are present. Text must be nonblank. The input limit is 100,000 text characters
in total and 2,000 structured segments. Oversized inputs are rejected, not truncated.

The first request returns HTTP 200 with this MeetingProtocol:

```json
{
  "title": null,
  "summary": "Айнур Каировна, проверьте договор с подрядчиком.",
  "transcript": [
    {
      "speaker": null,
      "start": null,
      "end": null,
      "text": "Айнур Каировна, проверьте договор с подрядчиком."
    }
  ],
  "action_items": [
    {
      "text": "Проверить договор с подрядчиком",
      "responsible": "Айнур Каировна",
      "deadline": null,
      "source_fragment": "Айнур Каировна, проверьте договор с подрядчиком.",
      "confidence": 0.75
    }
  ]
}
```

Absent owners and deadlines remain JSON null. Confidence is a heuristic score
between 0 and 1, not a calibrated probability. No recognized tasks returns
`action_items: []`. Structured segment metadata is preserved. Plain text is split
by lines; a recognized `Name:` prefix sets the speaker for subsequent lines until
the next recognized prefix. Plain text has no inferred timestamps.

### POST /export-docx

Send the complete MeetingProtocol returned by `/analyze` as the JSON body (no
wrapper). It may also contain user-reviewed corrections. `summary`, `transcript`,
and `action_items` are required. Each action requires nonblank `text` and
`source_fragment`; responsible, deadline, and confidence may be null.

HTTP 200 returns binary DOCX bytes, not JSON:

```text
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename="meeting_protocol.docx"
```

The document has the heading `Meeting Protocol`, numbered Summary, Action Items,
and Transcript sections, and a four-column assignment table. Missing owner or
deadline is displayed as `Не определено`. Export generation failures handled by
the endpoint return HTTP 500 with a generic `detail` string.

## Integration notes for the team

Audio developer: map `transcribe_audio()` output `full_text` to request `text`, or
map its `segments` to request `transcript`. Do not send the audio output dictionary
unchanged: fields such as `language`, `segments`, and `full_text` are not API input
keys. Send only the supported segment fields, with `speaker: null` if unavailable.
No audio upload or transcription happens in this API.

Frontend developer: use `/health` for availability, `/analyze` for protocol JSON,
and pass that protocol to `/export-docx` to download a Blob. Check HTTP status
before decoding a response or saving a file. For a frontend on another port, use
its local development proxy to this API; CORS is not configured. Display missing
values as `Не определено`, keeping the underlying JSON values null.

## Local verification

```bash
python -c 'from backend.main import app; print(app.title)'
python -m unittest discover -s tests -p test_backend_services.py -v
curl -f http://127.0.0.1:8000/health
```

Use the realistic three-task sample, then export the returned protocol:

```bash
python -c 'import json; from pathlib import Path; print(json.dumps({"text": Path("tests/sample_transcript.txt").read_text(encoding="utf-8")}, ensure_ascii=False))' > /tmp/hackalem-request.json
curl --fail-with-body -sS http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/hackalem-request.json -o /tmp/hackalem-protocol.json
curl --fail-with-body -sS http://127.0.0.1:8000/export-docx \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/hackalem-protocol.json -o /tmp/hackalem-protocol.docx
```

Expected assignments: Гульмира Сериковна / 15 октября; Тимур Болатович /
30 сентября; Айнур Каировна / null. These CLI examples explicitly save their
outputs locally; the server itself keeps document generation in memory.
Keep test discovery restricted to backend tests: the older `test_analysis.py`
targets another participant's previous Ollama implementation.

## Analyzer boundary and limitations

`backend.services.protocol_analyzer.build_protocol()` is the API adapter. It calls
`ai.summarization.summarize_transcript()` and
`ai.task_extraction.extract_action_items()`. A future local LLM adapter can replace
those calls while preserving MeetingProtocol and the routes. The current checkout
must include those local AI files; they were untracked when this backend was
verified, and must be supplied through the AI participant's normal integration.

The existing rules support a finite set of Russian/Kazakh verbs and date phrases.
They do not handle every paraphrase (for example, `представьте` and
`на следующей неделе` are not currently recognized). Relative deadlines such as
`до пятницы` stay as spoken; no meeting date or year is invented. Ambiguous,
negative, conditional, and question-like fragments may be skipped. Compound
assignments may remain one item, identical items may be deduplicated, and
cross-sentence corrections/coreference are not resolved. Regex extraction can
both miss tasks and produce false positives; review before treating a protocol
as authoritative. Summary selects up to three source sentences with a length cap;
it is not a semantic summary of the whole meeting.

Generated DOCX files and Python caches are ignored by Git. Do not commit private
meeting samples or credentials. No commits or pushes are part of the backend
verification workflow.
