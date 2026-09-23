"""Separate explicit model download from strictly local transcription."""

import argparse
import os
from pathlib import Path
import sys

from .transcribe import DEFAULT_MODEL_DIR, MODEL_FILES, MODULE_DIR, save_json, transcribe_mp3


def download_model() -> None:
    # This subcommand only downloads public model weights, never meeting data.
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    from huggingface_hub import HfApi, snapshot_download

    repo = "Systran/faster-whisper-small"
    info = HfApi(token=False).model_info(repo, files_metadata=True)
    files = {entry.rfilename: entry.size for entry in info.siblings}
    sizes = [files.get(name) for name in MODEL_FILES]
    if any(size is None for size in sizes) or sum(sizes) > 1_000_000_000:
        raise ValueError("Размер модели неизвестен или превышает 1 ГБ. Загрузка отменена.")
    print(f"Загрузка публичной small: {sum(sizes) / 1_000_000:.1f} МБ.", flush=True)
    snapshot_download(
        repo_id=repo, revision=info.sha, allow_patterns=list(MODEL_FILES),
        local_dir=str(DEFAULT_MODEL_DIR), token=False,
    )
    print("Модель сохранена локально. Теперь можно отключить интернет.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Локальная транскрибация MP3 в JSON")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("download", help="Скачать только публичную small (меньше 1 ГБ)")
    command = commands.add_parser("transcribe", help="Распознать локальную MP3 без сети")
    command.add_argument("input", type=Path)
    command.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    command.add_argument("--max-seconds", type=float, default=None)
    command.add_argument("--language", choices=("auto", "ru", "kk"), default="auto")
    command.add_argument("--output", type=Path, default=MODULE_DIR / "results" / "transcript.json")
    args = parser.parse_args()
    try:
        if args.command == "download":
            download_model()
            return 0
        if args.output.suffix.lower() != ".json":
            raise ValueError("Укажите выходной файл с расширением .json.")
        result = transcribe_mp3(
            args.input, model_dir=args.model_dir, max_seconds=args.max_seconds,
            language=None if args.language == "auto" else args.language,
        )
        output = save_json(result, args.output)
        print(f"JSON: {output}")
        print(f"Статус: {result['status']}; сегментов: {len(result['segments'])}; "
              f"обработано секунд: {result['processing']['processed_end_seconds']}; "
              f"частичная запись: {result['processing']['is_partial']}")
        print("Диаризация: not_run; speaker: null. Текст в терминал не выводится.")
        return 0
    except (KeyboardInterrupt, Exception) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("Обработка прервана.", file=sys.stderr)
            return 130
        # Do not print third-party exception messages: they may contain sensitive content.
        message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else (
            f"Ошибка {type(exc).__name__}. Проверьте зависимости, модель и доступ к файлам."
        )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
