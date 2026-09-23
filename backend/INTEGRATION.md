# Repository integration and team handoff

## Candidate comparison

The supplied backend-uldana-updated.zip was checked as a valid ZIP and its extracted
README, INTEGRATION.md, TEST_REPORT.md, implementation and tests were inspected.
Selected candidate backend code was integrated into the existing feature/backend-uldana
working tree. No repository replacement, branch switch, merge, reset, commit or push.

Retained existing public text/export routes, model field names, sample, and backend
regression tests. Adopted candidate local_analysis, stricter XML-safe schemas,
request limits, lazy audio adapter, specific error handling, expanded tests and DOCX
layout. Added conflict-deadline handling and an optional bridge to the real available
team function. Kept the team's dependency lines and root README changes. Added a
backend-only dependency list. Did not copy the candidate's old test report as proof
or its version constraints as a newly tested lock file.

## Audio participant

Inspected actual local `ai/transcription.py`:

```python
transcribe_audio(file_path: str) -> dict
# {"language": str, "segments": [{"start": float, "end": float, "text": str}],
#  "full_text": str}
```

It handles MP3/WAV, uses WHISPER_MODEL_PATH, runs faster-whisper locally with lazy
iteration, and implements no diarization. Its code is unchanged and remains under
the audio participant's ownership. It is not needed for backend startup.

Default mode: BACKEND_AUDIO_ADAPTER=standalone, WHISPER_MODEL_DIR=/complete/local/model.
Optional inspected-team mode:

```bash
export BACKEND_AUDIO_ADAPTER=team
export WHISPER_MODEL_PATH='/absolute/path/to/complete/local/model'
uvicorn backend.main:app --reload
```

Do not send a language query in team mode: the inspected function has no language
parameter, so the bridge returns 422 instead of silently ignoring the override.
Missing team module/model → 503. The team function conflates decoding and runtime
errors under RuntimeError; those failures produce a generic 500. The standalone
adapter distinguishes invalid decoded audio (422). The team function accepts
MP3/WAV filenames; the upload route also accepts `.mpeg` with `audio/mpeg` and
passes an unchanged temporary copy named `.mp3` to that function.

The bridge maps real segments to TranscriptSegment and retains supplied speaker,
start, end, text. Missing speaker stays null. An explicit diarization_available
flag is honored only when valid labels exist; the currently inspected module has
neither diarization nor that flag. Fake-adapter tests verify mapping, not diarization.

Alternatively, the teammate can call /analyze directly: map full_text → text or
segments → transcript, never both. Remove Whisper-specific extra keys. For a future
adapter, implement transcribe(path: Path, *, language: str | None) → TranscriptionResult
and select it through get_transcriber in backend/services/audio.py. Keep offline
loading, true labels, timestamps, warnings, and exception distinctions.

Remaining team work: provide real diarization if required, confirm actual branch
compatibility, and evaluate recognition on representative Kazakh/mixed recordings.
The untracked ai/ folder is only required when explicitly choosing team mode.

## Frontend participant

The backend includes a function-only client example in examples/frontend-api.js;
it is documentation, not a modification of the participant's UI. The default base
is /api, requiring a dev proxy stripping /api and forwarding to 127.0.0.1:8000.
Alternatively use http://127.0.0.1:8000 and set FRONTEND_ORIGINS to the browser origin.
Do not set multipart Content-Type manually; FormData supplies the boundary.

```javascript
import {analyzeAudio, analyzeText, downloadProtocol} from './frontend-api.js';

const result = await analyzeAudio(selectedFile, {language: 'ru'});
// Existing UI elements; use textContent, not HTML interpolation of meeting text.
warningsElement.textContent = result.warnings.join('\n');
summaryElement.textContent = result.protocol.summary;
// Render result.protocol.action_items and result.protocol.transcript in your UI.
await downloadProtocol(result.protocol); // only the nested protocol

const protocol = await analyzeText(transcriptText);
await downloadProtocol(protocol); // text response is already MeetingProtocol
```

Show the progress state during local CPU inference. Show all warnings and unknown
fields as Не определено while retaining null in JSON. Check HTTP errors before
saving files. A cancelled browser request does not guarantee cancellation of the
running synchronous inference. There is no persisted job queue. Frontend integration
has not been browser-tested because its code is not present in this checkout.
