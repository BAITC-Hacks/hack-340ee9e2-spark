# Integrated backend verification — 2026-09-23

Repository: /Users/uldanatolegenkyzy/Desktop/Hackhaton/hack-340ee9e2-spark
Branch checked before edits and during final verification: feature/backend-uldana.
No commit, push, merge, rebase, reset, branch switch or staging was performed.
The root README and untracked audio participant files were preserved.

## Candidate provenance

Inspected the user-provided backend-uldana-updated.zip and extracted directory.
ZIP integrity passed; selected extracted source/documentation files were byte-checked
against ZIP entries. The archive's earlier test report was read for context only.
The results below are independent checks of this integrated repository.

## Automated tests

Command: `python -m unittest discover -s tests -p 'test_backend*.py' -v`.
65 tests passed with Python 3.11 and Python 3.14 in available local environments.
This includes the integrated candidate's acceptance tests, retained backend tests,
and new integration regression tests. Old AI/Ollama tests are deliberately excluded.
A FastAPI/Starlette httpx deprecation warning was emitted; it did not fail tests.

Coverage includes clean startup with ai/faster_whisper/av imports blocked; health;
text/structured inputs; the three-task Russian sample; null unknown fields;
no assignment from speaker identity; explicit owner labels; relative and conflicting
deadlines; XML-safe/bounded inputs; validation errors without meeting text; internal
errors as 500; valid DOCX ZIP/OOXML and headers; multipart validation; body limits
with and without Content-Length; cleanup after success/failure; missing model/tokenizer;
explicit CORS; fake adapter metadata preservation; and team adapter mapping.

Fake adapter tests do NOT establish recognition quality or real diarization.
Text and DOCX were also exercised with Python socket.connect blocked.
The frontend example passed Node's module syntax check. git diff --check passed.
No model weights, recordings, generated DOCX, .env or Python bytecode are tracked.

## Live localhost HTTP

`uvicorn backend.main:app --reload` started from the repository root using the
available Python 3.11 environment. The server reached Application startup complete
on 127.0.0.1:8000. Verified /health, /analyze, /export-docx, /docs and /openapi.json.
Without model configuration, /transcribe returned 503 while text/export remained
operational. With the pre-existing local small model configured, the smoke script
uploaded the actual second MP3 to /analyze-audio and downloaded its DOCX over HTTP.
The verification server was stopped after the checks.

## Real inference, separate from fake tests

Used existing faster-whisper small weights from the supplied work directory and
actual Downloads/Совещание №1.mp3 and Совещание №2.mp3. No reference transcript or
hardcoded recognition output was substituted. No weights were downloaded in this task.

Both recordings were initially run through the integrated ASGI routes with real
model loading/inference, HF_HUB_OFFLINE=1, telemetry disabled, and Python outbound
socket.connect blocked. This is an application-level check, not an OS-wide network
audit of native libraries.

| Recording | Recognized segments | Transcript characters | Initial extracted items | DOCX bytes |
|---|---:|---:|---:|---:|
| №1 | 72 | 4106 | 7 | 40570 |
| №2 | 72 | 3531 | 2 | 40269 |

Both returned HTTP 200 through TestClient, and both DOCX containers passed ZIP
integrity checks. A corrupt file named .mp3 returned 422 with the real model loaded.

Review identified a missed explicit “Хорошо, пусть Ерлан … подготовит претензию”
assignment and a following “а вы …” clause. A narrow rule and regression tests were
added; owner/deadline do not transfer to the second clause. The second recording
was then independently re-recognized through the actual localhost HTTP server,
using automatic language detection. The final audio → protocol → DOCX check found
4 items. It did not replace audio with the earlier transcript.

Counts demonstrate execution, not precision/recall. The first recording contains
recognition errors in names (for example, Балатович versus the expected Болатович).
They were not silently replaced with reference names. Context-dependent tasks are
still missed; extraction completeness is not claimed. The first recording was
not re-recognized after the narrow “пусть” rule change.

Private derived JSON/DOCX outputs were saved only in system temporary verification
folders, never in the repository. Multipart/working audio copies were cleaned up.
A small inference-library session marker produced during a sandboxed check was
removed and excluded by .gitignore.

## Not verified / remaining limitations

- No fresh visual DOCX rendering or opening in Word/Pages was performed here.
  DOCX contents and ZIP/OOXML validity were independently checked; earlier visual
  rendering described by the candidate report is not counted as a new check.
- No full real inference through the optional TeamTranscriber bridge. Its inspected
  function contract is mapped and tested with fake output; standalone inference is real.
- The available team audio module has no diarization. Built-in transcription returns
  speaker=null and diarization_available=false. Metadata tests are not diarization.
- No browser/UI integration: the frontend is absent from this checkout.
- No claims of general Russian/Kazakh/mixed-language accuracy or complete task extraction.
- Existing environments were used; a fresh dependency installation on another machine
  or OS was not performed. The new multipart dependency was installed for verification.
- No cross-branch integration or team-wide product acceptance was performed.

See README.md and INTEGRATION.md for setup, API contracts, frontend client usage,
local model configuration, remaining teammate work, and repeatable commands.
