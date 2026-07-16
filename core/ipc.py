"""
Передача файлов от второго инстанса первому (контекстное меню Проводника).

Второй инстанс (запущен с путём картинки в argv, мьютекс занят) дописывает
путь в файл-очередь и взводит именованное событие Windows. Первый инстанс
держит поток-слушатель на этом событии и забирает пути из очереди.
"""

import os
import threading

from core.config import APP_DIR

QUEUE_PATH = os.path.join(APP_DIR, "open.queue")
_EVENT_NAME = "Shrinkr-Open-Event"

_EVENT_ALL_ACCESS = 0x1F0003
_WAIT_OBJECT_0 = 0


def _kernel32():
    import ctypes
    return ctypes.windll.kernel32


def push(paths):
    """Дописать пути в очередь и разбудить первый инстанс. Вызывается из
    второго (умирающего) процесса."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(QUEUE_PATH, "a", encoding="utf-8") as f:
            for p in paths:
                f.write(os.path.abspath(p) + "\n")
        k = _kernel32()
        ev = k.OpenEventW(_EVENT_ALL_ACCESS, False, _EVENT_NAME)
        if not ev:
            ev = k.CreateEventW(None, False, False, _EVENT_NAME)
        if ev:
            k.SetEvent(ev)
            k.CloseHandle(ev)
        return True
    except Exception:
        return False


def drain():
    """Забрать и очистить очередь. Возвращает список путей."""
    try:
        if not os.path.isfile(QUEUE_PATH):
            return []
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        os.remove(QUEUE_PATH)
        return [p for p in lines if os.path.isfile(p)]
    except OSError:
        return []


class Listener(threading.Thread):
    """Поток: ждёт именованное событие и зовёт callback(paths) (из потока —
    вызывающий обязан переправить в GUI-поток, напр. через Qt-сигнал)."""

    def __init__(self, callback):
        super().__init__(daemon=True)
        self._callback = callback
        self._stop = threading.Event()

    def run(self):
        try:
            k = _kernel32()
            ev = k.CreateEventW(None, False, False, _EVENT_NAME)
            if not ev:
                return
            while not self._stop.is_set():
                # Просыпаемся каждые 500 мс — проверить флаг остановки.
                if k.WaitForSingleObject(ev, 500) == _WAIT_OBJECT_0:
                    paths = drain()
                    if paths:
                        self._callback(paths)
            k.CloseHandle(ev)
        except Exception:
            pass

    def stop(self):
        self._stop.set()
