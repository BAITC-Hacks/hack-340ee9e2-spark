"""Explicit status for the deferred diarization stage. No fake speakers."""


def diarization_status() -> dict:
    return {
        "status": "not_run",
        "reason": "Диаризация не запускалась: установка модели и зависимостей отложена.",
        "speakers": [],
    }
