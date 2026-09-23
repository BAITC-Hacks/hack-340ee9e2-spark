"""Optional local audio adapter. Model loading is lazy and never downloads files.

The teammate can implement transcribe(path: Path, *, language: str | None)
returning TranscriptionResult and expose it through get_transcriber().
"""
from functools import lru_cache
import os
from pathlib import Path
from threading import Lock
from backend.schemas import TranscriptSegment, TranscriptionResult


class AudioUnavailableError(Exception):
    pass


class InvalidAudioError(Exception):
    pass


class NoSpeechError(Exception):
    pass


class AudioBusyError(Exception):
    pass


class LocalWhisperTranscriber:
    def __init__(self):
        self._model = None
        self._lock = Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        configured = os.environ.get('WHISPER_MODEL_DIR', '') or os.environ.get('WHISPER_MODEL_PATH', '')
        if not configured:
            raise AudioUnavailableError('Укажите WHISPER_MODEL_DIR: папку локальной модели faster-whisper.')
        directory = Path(configured).expanduser().resolve()
        # tokenizer.json is mandatory here: otherwise the library can try to fetch it.
        for name in ('model.bin', 'config.json', 'tokenizer.json'):
            if not (directory / name).is_file():
                raise AudioUnavailableError('В WHISPER_MODEL_DIR отсутствуют файлы локальной модели. См. backend/README.md.')
        try:
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AudioUnavailableError('Установите requirements.txt для локального распознавания.') from exc
        try:
            model = WhisperModel(str(directory), device='cpu', compute_type='int8',
                                 local_files_only=True, cpu_threads=4, num_workers=1)
            if not model.model.is_multilingual:
                raise AudioUnavailableError('Нужна многоязычная модель, не English-only .en.')
        except Exception as exc:
            raise AudioUnavailableError('Не удалось загрузить локальную модель faster-whisper.') from exc
        self._model = model
        return model

    def transcribe(self, path: Path, *, language: str | None = None) -> TranscriptionResult:
        if not self._lock.acquire(blocking=False):
            raise AudioBusyError()
        try:
            model = self._load()
            from av.error import FFmpegError
            try:
                chunks, info = model.transcribe(str(path), language=language, beam_size=5,
                                               vad_filter=True, condition_on_previous_text=False)
                segments = []
                chars = 0
                for chunk in chunks:
                    text = chunk.text.strip()
                    if not text:
                        continue
                    chars += len(text) + bool(segments)
                    if len(segments) >= 2000 or chars > 100_000:
                        raise InvalidAudioError('Расшифровка превышает лимит. Разделите запись на части.')
                    segments.append(TranscriptSegment(speaker=None, start=float(chunk.start),
                                                      end=float(chunk.end), text=text))
            except FFmpegError as exc:
                raise InvalidAudioError('Не удалось прочитать аудио. Нужен корректный MP3, WAV или M4A.') from exc
            if not segments:
                raise NoSpeechError()
            return TranscriptionResult(text='\n'.join(s.text for s in segments), transcript=segments,
                language=info.language, diarization_available=False,
                warnings=['Диаризация не подключена: speaker=null. Имена по голосу не определяются.',
                          'Распознавание может ошибаться; проверьте текст, особенно имена и смешанную речь.'])
        finally:
            self._lock.release()


class TeamTranscriber:
    """Optional bridge to the actual inspected ai.transcription implementation.

    No ai imports occur unless BACKEND_AUDIO_ADAPTER=team and audio is requested.
    The team's function uses WHISPER_MODEL_PATH and auto-detects language.
    """
    def __init__(self):
        self._lock = Lock()

    def transcribe(self, path: Path, *, language: str | None = None) -> TranscriptionResult:
        if language is not None:
            raise InvalidAudioError('Текущий team adapter определяет язык автоматически; уберите параметр language.')
        if not self._lock.acquire(blocking=False):
            raise AudioBusyError()
        try:
            configured = os.environ.get('WHISPER_MODEL_PATH', '')
            if not configured or not all((Path(configured).expanduser() / name).is_file()
                                         for name in ('model.bin', 'config.json', 'tokenizer.json')):
                raise AudioUnavailableError('Для team adapter задайте WHISPER_MODEL_PATH с полной локальной моделью.')
            try:
                import onnxruntime
                onnxruntime.disable_telemetry_events()
                from ai.transcription import transcribe_audio
            except ImportError:
                raise AudioUnavailableError('Модуль ai.transcription или его зависимости отсутствуют; используйте standalone.') from None
            try:
                raw = transcribe_audio(str(path))
            except ValueError:
                raise InvalidAudioError('Аудиомодуль участницы принимает корректные MP3/WAV.') from None
            # RuntimeError from this interface conflates decoding/model failures;
            # leave it as an internal processing error, not invalid client JSON.
            segments = [TranscriptSegment(**{key: chunk.get(key) for key in ('speaker','start','end','text')})
                        for chunk in raw['segments']]
            if not segments:
                raise NoSpeechError()
            diarization = raw.get('diarization_available', False)
            warnings = list(raw.get('warnings', []))
            if not diarization:
                warnings.append('Диаризация не подключена к текущему модулю участницы.')
            return TranscriptionResult(text='\n'.join(s.text for s in segments), transcript=segments,
                language=raw.get('language'), diarization_available=diarization, warnings=warnings)
        finally:
            self._lock.release()


@lru_cache(maxsize=1)
def get_transcriber():
    """Single integration point for the audio teammate; used as a FastAPI dependency."""
    selected = os.environ.get('BACKEND_AUDIO_ADAPTER', 'standalone')
    if selected == 'standalone':
        return LocalWhisperTranscriber()
    if selected == 'team':
        return TeamTranscriber()
    from fastapi import HTTPException
    raise HTTPException(503, 'BACKEND_AUDIO_ADAPTER должен быть standalone или team.')
