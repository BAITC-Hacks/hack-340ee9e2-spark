"""Adapt offline analysis to the public protocol contract."""
import re

from ai.summarization import summarize_transcript
from ai.task_extraction import NAME, extract_action_items
from backend.schemas import AnalyzeRequest, MeetingProtocol, TranscriptSegment

SPEAKER = re.compile(r"^(?P<speaker>" + NAME + r"(?:\s+" + NAME + r"){0,2}):\s*")


def _segments_from_text(text: str) -> list[TranscriptSegment]:
    segments = []
    speaker = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = SPEAKER.match(line)
        if match:
            speaker = match["speaker"]
            line = line[match.end():].strip()
        if line:
            segments.append(TranscriptSegment(speaker=speaker, text=line))
    if not segments:
        raise ValueError("Transcript contains no speech")
    return segments


def build_protocol(request: AnalyzeRequest) -> MeetingProtocol:
    """Keep the API independent of the replaceable local analysis functions."""
    segments = request.transcript if request.transcript is not None else _segments_from_text(request.text)
    return MeetingProtocol(
        title=request.title,
        summary=summarize_transcript("\n".join(segment.text for segment in segments)),
        transcript=segments,
        action_items=extract_action_items(segments),
    )


def analyze_transcript(text: str | list, title: str | None = None) -> dict:
    """Entry point used by the existing AI module and its CLI."""
    request = AnalyzeRequest(title=title, **({"transcript": text} if isinstance(text, list) else {"text": text}))
    return build_protocol(request).model_dump()
