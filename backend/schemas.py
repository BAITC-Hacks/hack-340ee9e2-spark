"""Shared JSON contracts; strict validation, bounded inputs, XML-safe export text."""
from typing import Annotated, Self
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_TRANSCRIPT_CHARS = 100_000


def xml_text(value: str) -> str:
    if any(not (c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF) for c in value):
        raise ValueError('Text contains unsupported control characters')
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=MAX_TRANSCRIPT_CHARS), AfterValidator(xml_text)]
Title = Annotated[Text, Field(max_length=200)]
Seconds = Annotated[float, Field(ge=0,allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)


class TranscriptSegment(StrictModel):
    speaker: Annotated[Text, Field(max_length=200)] | None = None
    start: Seconds | None = None
    end: Seconds | None = None
    text: Text

    @model_validator(mode='after')
    def ordered_timestamps(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError('end must be greater than or equal to start')
        return self


class ActionItem(StrictModel):
    text: Text
    responsible: Text | None = None
    deadline: Text | None = None
    source_fragment: Text
    confidence: Annotated[float, Field(ge=0,le=1,allow_inf_nan=False)] | None = None


def check_transcript(segments):
    if sum(len(s.text) for s in segments)>MAX_TRANSCRIPT_CHARS:
        raise ValueError('Transcript exceeds 100000 characters')


class MeetingProtocol(StrictModel):
    title: Title | None = None
    summary: Text
    transcript: Annotated[list[TranscriptSegment], Field(max_length=2000)]
    action_items: Annotated[list[ActionItem], Field(max_length=2000)]

    @model_validator(mode='after')
    def bounded_protocol(self) -> Self:
        check_transcript(self.transcript)
        if sum(len(i.text)+len(i.source_fragment)+len(i.responsible or '')+len(i.deadline or '') for i in self.action_items)>300_000:
            raise ValueError('Action items exceed export text limit')
        return self


class AnalyzeRequest(StrictModel):
    title: Title | None = None
    text: Text | None = None
    transcript: Annotated[list[TranscriptSegment], Field(min_length=1,max_length=2000)] | None = None

    @model_validator(mode='after')
    def one_source(self) -> Self:
        if (self.text is None)==(self.transcript is None):
            raise ValueError('Provide exactly one of text or transcript')
        if self.transcript:
            check_transcript(self.transcript)
        if self.text and sum(bool(s.strip()) for s in self.text.splitlines())>2000:
            raise ValueError('Transcript exceeds 2000 lines')
        return self


class TranscriptionResult(StrictModel):
    text: Text
    transcript: Annotated[list[TranscriptSegment],Field(min_length=1,max_length=2000)]
    language: Annotated[Text, Field(max_length=16)] | None = None
    diarization_available: bool = False
    diarization: dict = Field(default_factory=lambda: {'status': 'not_run'})
    processing: dict = Field(default_factory=dict)
    warnings: list[Text] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_transcription(self) -> Self:
        check_transcript(self.transcript)
        if self.diarization_available != (self.diarization.get('status') == 'ok'):
            raise ValueError('Diarization flag must match status == ok')
        if not self.diarization_available and any(s.speaker is not None for s in self.transcript):
            raise ValueError('Unavailable diarization must keep speaker null')
        return self


class AudioAnalysisResponse(StrictModel):
    protocol: MeetingProtocol
    text: str
    diarization: dict
    processing: dict
    language: str | None
    diarization_available: bool
    warnings: list[str]
