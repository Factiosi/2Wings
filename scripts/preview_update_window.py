"""Show the update window through all its stages, with no download and no install.

    .venv\\Scripts\\python scripts\\preview_update_window.py [--error]
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.update_splash.app import run_update_window
from src.update_splash.worker import Job, Worker


class PreviewWorker(Worker):
    def __init__(self, *, fail: bool) -> None:
        super().__init__(Job("2.0.0", "1.5.8", "", "", Path("."), Path(".")))
        self._fail = fail

    def start(self) -> None:
        threading.Thread(target=self._play, daemon=True).start()

    def _bar(self, seconds: float, detail: str = "") -> None:
        for step in range(101):
            self._set(progress=step / 100, detail=detail)
            time.sleep(seconds / 100)

    def _play(self) -> None:
        self._set(stage="download", caption="Скачивание обновления", log="1.5.8 → 2.0.0")
        self._bar(3.0, "12,4 из 46,3 МБ · 8,1 МБ/с")
        self._set(stage="verify", caption="Проверка файла", progress=0.0, detail="SHA-256", log="Скачано 46,3 МБ")
        self._bar(0.8, "SHA-256")
        if self._fail:
            self._set(stage="error", caption="Обновление не удалось", detail="Сервер обновлений ответил 503", log="SHA-256 совпадает")
            return
        self._set(stage="install", caption="Установка файлов", progress=None, detail="Закрытие программы", log="SHA-256 совпадает")
        time.sleep(2.5)
        self._bar(2.0)
        self._set(stage="launch", caption="Запуск 2Wings", progress=None, detail="", log="Файлы установлены")
        time.sleep(2.5)
        self._set(stage="done", caption="2Wings 2.0.0 запущен", progress=1.0, log="Готово")


if __name__ == "__main__":
    run_update_window(PreviewWorker(fail="--error" in sys.argv))
