# Локальная интеграция команды Spark

Рабочая ветка: `integration`, созданная от `origin/main`. Три ветки перенесены
последовательно через `git merge --squash`: audio → backend-uldana → frontend-aruzhan.
Проверки выполнены до фиксации объединённого приложения единым интеграционным
коммитом. Обычные merge-коммиты не создавались. На втором шаге
Git потребовал сначала снять результаты предыдущего squash с индекса; файлы
были сохранены, конфликтов содержимого и записей unmerged не было.
Интеграция публикуется отдельной веткой; её слияние в main требует отдельного решения.

## Запуск на текущем компьютере

Из корня репозитория:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
PYANNOTE_METRICS_ENABLED=0 OTEL_SDK_DISABLED=true \
.venv-integration/bin/python -m uvicorn backend.main:app \
  --host 127.0.0.1 --port 8000 --no-access-log
```

Откройте http://127.0.0.1:8000/. Используется один сервер и один адрес.
Один процесс Uvicorn, без `--workers`: блокировка одновременных аудиозапросов
действует внутри процесса. `/health` проверяет живость сервера, не готовность моделей.
В интерфейсе по умолчанию обрабатываются первые 60 секунд; можно выбрать всю
запись до 10 минут. Интервал и предупреждение о частичной обработке показаны явно.
Дата и число участников не отправлялись в прежний API; неработающие поля убраны.

На этом компьютере создано отдельное `.venv-integration` с Python 3.13.2 arm64.
Исходные `audio_module/.venv` и `.venv-diarization` не изменялись, модели не копировались.
Для воспроизведения установки (сначала нужен интернет только для пакетов):

```bash
audio_module/.venv/bin/python -m venv .venv-integration
.venv-integration/bin/python -m pip install --only-binary=:all: -r requirements.txt
```

Требуются существующие каталоги:

- `audio_module/models/faster-whisper-small` — локальная multilingual small;
- `audio_module/models/community-1` — локальная Community-1;
- `audio_module/.venv-diarization/bin/python` — отдельный процесс pyannote.

Первичная подготовка моделей на другом компьютере описана в
[audio_module/CHECK.md](../audio_module/CHECK.md). При обработке ничего не
скачивается, токен Hugging Face не нужен. Не запускайте старый отдельный
`backend/scripts/download_model.py` для интеграции: готовая small уже используется.
Можно переопределить пути переменными `WHISPER_MODEL_DIR`, `DIARIZATION_MODEL_DIR`
и `DIARIZATION_PYTHON`. Интерпретатор VS Code менять не требуется.

## Реальный путь данных

1. Браузер отправляет `POST /analyze-audio?max_seconds=60`, multipart `file`.
2. Backend вызывает `audio_module.transcribe_mp3(path, max_seconds=60)`.
3. Затем вызывает `audio_module.diarize.add_diarization(path, transcript)`.
4. Готовые сегменты поступают в существующий `build_protocol` Улданы.
5. Браузер показывает результат и отправляет только `result.protocol` в
   `POST /export-docx` при нажатии кнопки скачивания.

Второй WhisperModel в backend отсутствует. Старый `ai.transcription` не вызывается.
`LocalWhisperTranscriber` оставлен только как совместимое имя того же TeamTranscriber.
`BACKEND_AUDIO_ADAPTER` больше не переключает обработчики.

Ответ `/analyze-audio` содержит:

- `text` — исходный общий текст;
- `protocol.summary`, `protocol.transcript`, `protocol.action_items`;
- сегменты `protocol.transcript`: `start`, `end`, `text`, `speaker` без изменения
  текста и границ аудиомодуля;
- `language`, `processing`, `diarization`, `warnings`;
- `diarization_available` равен `diarization.status == "ok"`.

При отсутствии/ошибке диаризации запрос всё равно возвращает транскрипт,
`diarization_available: false` и все `speaker: null`. При успешной диаризации
отдельные неоднозначные сегменты также остаются null; причины находятся в
`diarization.assignments`, например `speaker_change_within_segment`.
Имена не придумываются и техническая метка говорящего не становится ответственным.

UI обращается только к `GET /health`, `POST /analyze-audio` и `POST /export-docx`.
Опрос `/api/meetings/...` отсутствует. Во время запроса отображается
«Обрабатываем аудио…», повторная отправка и смена файла заблокированы.
Прогресс отдельных этапов не имитируется таймерами.

## Проверки

```bash
.venv-integration/bin/python -m unittest discover -s tests -p 'test_backend*.py' -v
audio_module/.venv/bin/python -m unittest audio_module.test_alignment -v
.venv-integration/bin/python -m pip check
audio_module/.venv/bin/python -m pip check
audio_module/.venv-diarization/bin/python -m pip check
```

Реальная проверка в установленном Google Chrome через Playwright, без скачивания
другого браузера. Playwright — зависимость только теста, не приложения:

```bash
.venv-integration/bin/python -m pip install 'playwright==1.63.0'
.venv-integration/bin/python tests/smoke_frontend.py \
  '/Users/malika/Desktop/Hackhton доки просто/Совещание №1.mp3'
```

Сервер должен работать. Тест выполняет настоящую обработку первых 60 секунд,
проверяет блокировку дубля, метки и null, отсутствие старых маршрутов, мобильную
ширину и DOCX. Внешние запросы страницы запрещены. JSON/DOCX сохраняются только
в игнорируемом `audio_module/results`, в терминал выводятся только показатели.
Результаты конкретного запуска см. в [INTEGRATION_CHECK.md](INTEGRATION_CHECK.md).

## Ограничения демонстрации

Анализ поручений использует локальные правила Улданы, не Ollama/LLM. Он может
пропускать задачи и ошибаться; даты остаются относительными. Редактор протокола,
сохранение правок, фоновая очередь и опрос статусов пока отсутствуют. Остановка
запроса в браузере не гарантирует отмену вычисления на сервере.
Проверка русской записи не доказывает качество казахской и смешанной речи.
DOCX проверяется по структуре и содержимому; визуальную проверку в Word нужно
выполнить отдельно. `.vscode`, окружения, модели, аудио и результаты исключены из Git.
