"""
Понятный человеку лог сжатия. Заголовочные строки переводятся на язык
программы (i18n.tr), технические детали добавляются как есть. При ошибке лог
сохраняется в %APPDATA%/Shrinkr/logs.
"""

import os
import time

from core import i18n
from core.config import APP_DIR

LOG_DIR = os.path.join(APP_DIR, "logs")


class Log:
    def __init__(self, path=""):
        self._lines = []
        self.event("Shrinkr compression log")
        if path:
            self.info(f"File: {path}")

    def _stamp(self):
        return time.strftime("%H:%M:%S")

    def event(self, key):
        """Ключевое событие (переводится)."""
        self._lines.append(f"[{self._stamp()}] {i18n.tr(key)}")

    def info(self, text):
        self._lines.append(f"[{self._stamp()}] {text}")

    def raw(self, text):
        """Сырая строка (без перевода)."""
        if text:
            self._lines.append(text)

    def text(self):
        return "\n".join(self._lines)

    def save_error(self):
        """Сохраняет лог в %APPDATA%/Shrinkr/logs; возвращает путь (или '')."""
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(
                LOG_DIR, "error-" + time.strftime("%Y%m%d-%H%M%S") + ".log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text())
            return path
        except OSError:
            return ""
