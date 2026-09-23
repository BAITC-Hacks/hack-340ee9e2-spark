"""Local audio processing; importing the module does not load a model."""

from .transcribe import transcribe_mp3, save_json

__all__ = ["transcribe_mp3", "save_json"]
