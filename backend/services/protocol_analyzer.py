"""Local analysis adapter. No dependency on a teammate's untracked ai/ directory."""
import re
from backend.schemas import AnalyzeRequest, MeetingProtocol, TranscriptSegment
from backend.services.local_analysis import PERSON, extract_action_items, summarize_transcript

SPEAKER = re.compile(r'^(?P<speaker>(?i:Speaker|Спикер)\s*\d+|' + PERSON + r')\s*:\s*')


class EmptyTranscriptError(Exception):
    """A valid request contained speaker headings but no speech."""


def _segments_from_text(text: str) -> list[TranscriptSegment]:
    segments = []
    speaker = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = SPEAKER.match(line)
        if match:
            speaker = match['speaker']
            line = line[match.end():].strip()
        if line:
            segments.append(TranscriptSegment(speaker=speaker, text=line))
    if not segments:
        raise EmptyTranscriptError()
    return segments


def build_protocol(request: AnalyzeRequest) -> MeetingProtocol:
    segments = request.transcript if request.transcript is not None else _segments_from_text(request.text)
    return MeetingProtocol(title=request.title,
        summary=summarize_transcript('\n'.join(s.text for s in segments)),
        transcript=segments, action_items=extract_action_items(segments))


def analyze_transcript(text: str | list, title: str | None = None) -> dict:
    request = AnalyzeRequest(title=title, **({'transcript': text} if isinstance(text,list) else {'text': text}))
    return build_protocol(request).model_dump()
