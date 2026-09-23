"""Public contracts shared by analysis, the API, and DOCX export."""
from typing import Annotated, Self
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_TRANSCRIPT_CHARS = 100_000
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TranscriptText = Annotated[Text, Field(max_length=MAX_TRANSCRIPT_CHARS)]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TranscriptSegment(StrictModel):
    speaker: Text | None = None
    start: Seconds | None = None
    end: Seconds | None = None
    text: TranscriptText

    @model_validator(mode="after")
    def ordered_timestamps(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class ActionItem(StrictModel):
    text: Text
    responsible: Text | None = None
    deadline: Text | None = None
    source_fragment: Text
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None


class MeetingProtocol(StrictModel):
    title: Text | None = None
    summary: Text
    transcript: list[TranscriptSegment]
    action_items: list[ActionItem]


class AnalyzeRequest(StrictModel):
    title: Text | None = None
    text: TranscriptText | None = None
    transcript: Annotated[list[TranscriptSegment], Field(min_length=1, max_length=2000)] | None = None

    @model_validator(mode="after")
    def one_source(self) -> Self:
        if (self.text is None) == (self.transcript is None):
            raise ValueError("Provide exactly one of text or transcript")
        if self.transcript and sum(len(s.text) for s in self.transcript) > MAX_TRANSCRIPT_CHARS:
            raise ValueError(f"Transcript exceeds {MAX_TRANSCRIPT_CHARS} characters")
        return self
