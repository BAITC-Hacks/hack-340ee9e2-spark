"""Bridge to the team's single local audio_module implementation."""
from copy import deepcopy
from functools import lru_cache
import os
from pathlib import Path
from threading import Lock
from backend.schemas import TranscriptionResult


class AudioUnavailableError(Exception):
    pass


class InvalidAudioError(Exception):
    pass


class NoSpeechError(Exception):
    pass


class AudioBusyError(Exception):
    pass


class TeamTranscriber:
    def __init__(self):
        self._lock = Lock()

    def transcribe(self, path: Path, *, language: str | None = None,
                   max_seconds: int | None = None) -> TranscriptionResult:
        if not self._lock.acquire(blocking=False):
            raise AudioBusyError()
        try:
            # Imports are lazy: /health, text analysis and export need no audio models.
            from audio_module import transcribe_mp3
            from audio_module.diarize import add_diarization
            options = {'language': language, 'max_seconds': max_seconds}
            configured = os.environ.get('WHISPER_MODEL_DIR') or os.environ.get('WHISPER_MODEL_PATH')
            if configured:
                options['model_dir'] = configured
            try:
                original = transcribe_mp3(path, **options)
            except (FileNotFoundError, ImportError):
                raise AudioUnavailableError('Локальная small или её зависимости недоступны. Проверьте WHISPER_MODEL_DIR и audio_module/CHECK.md.') from None
            except ValueError as exc:
                raise InvalidAudioError(str(exc)) from None
            if not original.get('segments'):
                raise NoSpeechError()
            diarization_options = {}
            for variable, argument in [('DIARIZATION_MODEL_DIR', 'model_dir'),
                                       ('DIARIZATION_PYTHON', 'python_executable')]:
                if os.environ.get(variable):
                    diarization_options[argument] = os.environ[variable]
            try:
                raw = add_diarization(path, original, **diarization_options)
            except Exception:
                # Even an unexpected worker/adapter failure must not erase ASR.
                raw = deepcopy(original)
                raw['diarization'] = {'status': 'failed', 'code': 'adapter_failed',
                    'reason': 'Диаризация завершилась ошибкой; транскрипт сохранён.'}
            diarization = raw.get('diarization', {'status': 'not_run'})
            available = diarization.get('status') == 'ok'
            segments = [dict(segment, speaker=segment.get('speaker') if available else None)
                        for segment in raw['segments']]
            warnings = list(raw.get('warnings', []))
            if not available:
                warnings.append(diarization.get('reason') or 'Диаризация не выполнена; говорящие не определены.')
            unknown = sum(segment['speaker'] is None for segment in segments)
            if unknown:
                warnings.append(f'Говорящий не определён у {unknown} сегментов. Проверьте запись; метки не подставлялись.')
            return TranscriptionResult(text=raw['text'], transcript=segments,
                language=raw.get('language'), diarization_available=available,
                diarization=diarization, processing=raw.get('processing', {}), warnings=warnings)
        finally:
            self._lock.release()


# Compatibility name only; this alias never creates another Whisper implementation.
LocalWhisperTranscriber = TeamTranscriber


@lru_cache(maxsize=1)
def get_transcriber():
    return TeamTranscriber()
