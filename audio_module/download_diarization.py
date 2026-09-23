"""Explicit model download; token is read privately, never stored or logged."""

import getpass
import os
import sys

from .diarize import COMMUNITY_FILES, DEFAULT_DIARIZATION_MODEL


def main():
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    from huggingface_hub import HfApi, get_token, snapshot_download

    # Reuse an existing local login if present; never reveal its value.
    token = get_token()
    if not token:
        if not sys.stdin.isatty():
            print('Доступ не настроен. Запустите эту команду в своём терминале для скрытого ввода токена.')
            return 2
        token = getpass.getpass('Hugging Face read token (скрытый ввод, не сохраняется): ')
    if not token:
        print('Токен не введён. Ничего не скачано.')
        return 2
    try:
        repo = 'pyannote/speaker-diarization-community-1'
        api = HfApi(token=token)
        # Verify gated access to a tiny config before downloading weights.
        api.auth_check(repo_id=repo, repo_type='model')
        info = api.model_info(repo, files_metadata=True)
        sizes = {f.rfilename: f.size for f in info.siblings}
        selected = [sizes.get(name) for name in COMMUNITY_FILES]
        if any(size is None for size in selected) or sum(selected) > 100_000_000:
            print('Неизвестный размер модели или больше 100 МБ; загрузка отменена для проверки бюджета.')
            return 2
        print(f'Проверенный объём Community-1: {sum(selected) / 1_000_000:.1f} МБ.')
        snapshot_download(repo, revision=info.sha, token=token,
                          allow_patterns=list(COMMUNITY_FILES), local_dir=str(DEFAULT_DIARIZATION_MODEL))
        print('Community-1 сохранена локально. Токен не сохранён этой командой.')
        return 0
    except Exception as exc:
        # Never print HTTP objects/headers or exception strings containing credentials.
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        print('Загрузка не выполнена. Проверьте принятие условий Community-1, права токена и сеть.'
              + (f' HTTP {status}.' if status in (401, 403, 404) else ''))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
