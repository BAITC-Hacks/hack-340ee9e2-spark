"""Run optional diarization in an isolated Python process; keep ASR usable."""

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_DIARIZATION_MODEL = MODULE_DIR / 'models' / 'community-1'
DEFAULT_DIARIZATION_PYTHON = MODULE_DIR / '.venv-diarization' / 'bin' / 'python'
COMMUNITY_FILES = (
    'config.yaml', 'embedding/pytorch_model.bin', 'segmentation/pytorch_model.bin',
    'plda/plda.npz', 'plda/xvec_transform.npz',
)


def offline_environment() -> dict[str, str]:
    return {
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
        'PYANNOTE_METRICS_ENABLED': '0', 'OTEL_SDK_DISABLED': 'true',
        'ORT_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
        'MPLCONFIGDIR': str(MODULE_DIR / '.cache' / 'matplotlib'),
        'HF_HOME': str(MODULE_DIR / '.cache' / 'huggingface'),
        'TORCH_HOME': str(MODULE_DIR / '.cache' / 'torch'),
    }


def diarization_status() -> dict:
    return {
        "status": "not_run",
        "reason": "Диаризация не запускалась; вызовите add_diarization отдельно.",
        "speakers": [],
    }


def add_diarization(
    mp3_path: str | Path, transcript: dict, *,
    model_dir: str | Path = DEFAULT_DIARIZATION_MODEL,
    python_executable: str | Path = DEFAULT_DIARIZATION_PYTHON,
    timeout_seconds: float = 600,
) -> dict:
    """Return a copy of the existing result, preserving text/timestamps/schema.

    Supports the transcript's prefix starting at zero, up to 600 seconds.
    On failure only diarization status changes; original segments survive.
    Run from the transcription environment (PyAV and NumPy are required).
    """
    from .align import align_segments
    from .transcribe import _decode_mp3

    if not isinstance(transcript, dict):
        raise ValueError('Транскрипт должен быть объектом JSON.')
    result = deepcopy(transcript)
    started = time.monotonic()

    def fail(status, code, reason):
        result['diarization'] = {
            'status': status, 'code': code, 'reason': reason, 'speakers': [],
            'elapsed_seconds': round(time.monotonic() - started, 3),
        }
        return result

    try:
        processing = transcript['processing']
        begin = float(processing['processed_start_seconds'])
        end = float(processing['processed_end_seconds'])
        if begin != 0 or not math.isfinite(end) or not 0 < end <= 600:
            raise ValueError
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError
        for segment in transcript['segments']:
            a, b = float(segment['start']), float(segment['end'])
            if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b <= end):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        return fail('failed', 'invalid_transcript', 'Ожидался транскрипт интервала от 0 до 600 секунд.')
    model = Path(model_dir).expanduser().resolve()
    if any(not (model / name).is_file() or (model / name).stat().st_size == 0
           for name in COMMUNITY_FILES):
        return fail('unavailable', 'model_missing', 'Локальная Community-1 отсутствует или неполна; скачайте модель отдельно.')
    python = Path(python_executable).expanduser().absolute()
    if not python.is_file():
        return fail('unavailable', 'environment_missing', 'Не найден Python отдельного окружения диаризации.')
    source = Path(mp3_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.mp3':
        return fail('unavailable', 'audio_missing', 'Локальный MP3 не найден или имеет неверное расширение.')
    try:
        import numpy as np

        waveform, _, _ = _decode_mp3(source, end)
        if abs(len(waveform) / 16000 - end) > 0.002:
            return fail('failed', 'interval_mismatch', 'Длительность аудио не соответствует интервалу транскрипта.')
        root = MODULE_DIR / 'results'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.diarization-', dir=root) as directory:
            temporary = Path(directory)
            audio_file = temporary / 'waveform.npy'
            output_file = temporary / 'turns.json'
            np.save(audio_file, waveform, allow_pickle=False)
            env = os.environ.copy()
            env.update(offline_environment())
            for key in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'PYANNOTEAI_API_KEY'):
                env.pop(key, None)
            completed = subprocess.run(
                [str(python), '-m', 'audio_module.diarize_worker',
                 '--model-dir', str(model), '--waveform', str(audio_file),
                 '--output', str(output_file)],
                cwd=MODULE_DIR.parent, env=env, timeout=timeout_seconds,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if not output_file.is_file():
                return fail('failed', 'process_failed', 'Процесс диаризации завершился без результата.')
            payload = json.loads(output_file.read_text(encoding='utf-8'))
        if payload.get('status') != 'ok' or completed.returncode != 0:
            code = payload.get('code')
            if code not in ('missing_dependency', 'invalid_model', 'inference_failed', 'network_blocked'):
                code = 'process_failed'
            return fail('unavailable' if code == 'missing_dependency' else 'failed', code,
                        'Диаризация не выполнена. Проверьте окружение и полноту локальной модели; транскрипт сохранён.')
        turns = payload['turns']
        exclusive = payload['exclusive_turns']
        for turn in [*turns, *exclusive]:
            if not 0 <= float(turn['start']) < float(turn['end']) <= end + 0.002:
                raise ValueError('invalid worker interval')
        # Validate exclusive turns too, but preserve overlap from regular turns.
        align_segments([], exclusive)
        aligned, assignments = align_segments(transcript['segments'], turns)
        result['segments'] = aligned
        result['diarization'] = {
            'status': 'ok' if turns else 'no_speech_detected', 'reason': None,
            'model': 'pyannote/speaker-diarization-community-1', 'device': 'cpu',
            'speakers': sorted({turn['speaker'] for turn in turns}),
            'processed_start_seconds': 0.0, 'processed_end_seconds': end,
            'turns': turns, 'exclusive_turns': exclusive, 'assignments': assignments,
            'unassigned_segments': sum(s['speaker'] is None for s in aligned),
            'elapsed_seconds': round(time.monotonic() - started, 3),
        }
        return result
    except subprocess.TimeoutExpired:
        return fail('failed', 'timeout', 'Превышено время диаризации; процесс остановлен, транскрипт сохранён.')
    except Exception:
        return fail('failed', 'processing_failed', 'Ошибка локальной обработки или формата результата; транскрипт сохранён.')
