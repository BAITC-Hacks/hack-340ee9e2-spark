"""MP3 -> timestamped transcript. Inference uses local files only."""

import json
import math
import os
from pathlib import Path
import tempfile
import time

from .diarize import diarization_status

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = MODULE_DIR / "models" / "faster-whisper-small"
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
SAMPLE_RATE = 16000
MAX_FULL_SECONDS = 600


def _decode_mp3(path: Path, limit: float | None):
    """Read at most the requested prefix (+1 sample to detect truncation)."""
    import av
    import numpy as np

    max_samples = int((limit if limit is not None else MAX_FULL_SECONDS) * SAMPLE_RATE)
    chunks = []
    count = 0
    source_duration = None
    try:
        # A file object and explicit format prevent URL/playlist input handling.
        with path.open("rb") as source, av.open(source, format="mp3") as container:
            if not container.streams.audio:
                raise ValueError("В файле нет аудиодорожки.")
            if container.duration is not None:
                source_duration = float(container.duration / av.time_base)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

            def collect(frames):
                nonlocal count
                for frame in frames:
                    samples = frame.to_ndarray().reshape(-1)
                    samples = samples[: max_samples + 1 - count]
                    chunks.append(samples.copy())
                    count += samples.size

            for frame in container.decode(audio=0):
                collect(resampler.resample(frame))
                if count > max_samples:
                    break
            else:
                collect(resampler.resample(None))
    except (av.FFmpegError, OSError) as exc:
        raise ValueError("Не удалось прочитать MP3: файл повреждён или недоступен.") from exc
    if not count:
        raise ValueError("Аудиофайл пуст или не содержит декодируемых отсчётов.")
    truncated = count > max_samples
    if limit is None and truncated:
        raise ValueError("Запись длиннее 10 минут. Для проверки укажите --max-seconds 60 или 120.")
    audio = np.concatenate(chunks)[:max_samples].astype(np.float32) / 32768.0
    return audio, source_duration, truncated


def transcribe_mp3(
    mp3_path: str | Path,
    *,
    model_dir: str | Path = DEFAULT_MODEL_DIR,
    max_seconds: float | None = None,
    language: str | None = None,
) -> dict:
    """Return a JSON-compatible dict; language is None (auto), 'ru' or 'kk'.

    max_seconds selects a prefix from time zero, at most 600 seconds.
    None processes the entire recording, rejecting recordings over 10 minutes.
    No audio/text is uploaded and no model is downloaded by this function.
    """
    started = time.monotonic()
    path = Path(mp3_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("MP3 не найден. Проверьте локальный путь к записи.")
    if path.suffix.lower() != ".mp3":
        raise ValueError("Первый этап поддерживает только файлы .mp3.")
    if language not in (None, "ru", "kk"):
        raise ValueError("Язык: ru, kk или автоматическое определение.")
    if max_seconds is not None and (
        not math.isfinite(max_seconds) or not 0 < max_seconds <= MAX_FULL_SECONDS
    ):
        raise ValueError("max_seconds должен быть больше 0 и не больше 600.")
    model_path = Path(model_dir).expanduser().resolve()
    if any(not (model_path / name).is_file() for name in MODEL_FILES):
        raise FileNotFoundError("Локальная модель неполная или отсутствует. Сначала выполните download.")

    # Set before importing HF-related libraries; never silently download at inference.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    import onnxruntime

    onnxruntime.disable_telemetry_events()
    from faster_whisper import WhisperModel

    audio, source_duration, truncated = _decode_mp3(path, max_seconds)
    duration = len(audio) / SAMPLE_RATE
    model = WhisperModel(
        str(model_path), device="cpu", compute_type="int8",
        cpu_threads=4, num_workers=1, local_files_only=True,
    )
    segment_iterator, info = model.transcribe(
        audio, language=language, task="transcribe", beam_size=5,
        vad_filter=True, condition_on_previous_text=False,
    )
    segments = []
    previous_end = 0.0
    for segment in segment_iterator:
        text = segment.text.strip()
        start = min(duration, max(previous_end, float(segment.start), 0.0))
        end = min(duration, max(start, float(segment.end)))
        if not text or end <= start:
            continue
        segments.append({
            "start": round(start, 3), "end": round(end, 3),
            "text": text, "speaker": None,
        })
        previous_end = end
    return {
        "schema_version": 1,
        "status": "ok" if segments else "no_speech_detected",
        "model": "Systran/faster-whisper-small",
        "device": "cpu", "compute_type": "int8",
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "processing": {
            "mode": "prefix" if max_seconds is not None else "full",
            "requested_max_seconds": max_seconds,
            "processed_start_seconds": 0.0,
            "processed_end_seconds": round(duration, 3),
            "source_duration_seconds_estimate": source_duration,
            "is_partial": truncated,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        },
        "diarization": diarization_status(),
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "warnings": [
            "Текст и временные метки требуют проверки; качество смешанной речи не гарантируется.",
            *(["Обработано только начало записи; остальная часть не распознавалась."] if truncated else []),
        ],
    }


def save_json(result: dict, output_path: str | Path) -> Path:
    """Atomically save UTF-8 JSON. Caller must choose a private, gitignored path."""
    path = Path(output_path).expanduser().resolve()
    if path.suffix.lower() != ".json":
        raise ValueError("Результат должен сохраняться в файл .json.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
