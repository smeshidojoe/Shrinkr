import atexit
import threading

from PySide6.QtCore import QThread, Signal

from core import compressor

# ------------------------------------------------------------------ #
#  «Тёплый» пул: один долгоживущий процесс-воркер. Первый файл не платит
#  ~1 c за spawn+импорты — процесс поднимается заранее (warm_up при старте).
# ------------------------------------------------------------------ #
_POOL = None
_POOL_LOCK = threading.Lock()


def _pool_warm_task():
    """Выполняется в дочернем процессе: прогревает импорты кодеков."""
    from core import compressor as _c  # noqa: F401
    return True


def get_pool():
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor
            ctx = mp.get_context("spawn")
            _POOL = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
        return _POOL


def _drop_pool():
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
            _POOL = None


def warm_up():
    """Поднять процесс-воркер заранее (вызывается после старта окна)."""
    try:
        get_pool().submit(_pool_warm_task)
    except Exception:
        pass


atexit.register(_drop_pool)


class CompressWorker(QThread):
    """Фоновое сжатие одного файла: done(dict) — см. compressor.compress.

    Сжатие выполняется в ОТДЕЛЬНОМ ПРОЦЕССЕ (тёплый пул): нативные кодеки
    (oxipng, imagequant) не отпускают GIL, и в обычном QThread долгая
    оптимизация большого файла замораживает весь интерфейс на секунды."""

    done = Signal(dict)

    def __init__(self, path, mode, output, quality=87, strip=False,
                 convert_to="keep", parent=None):
        super().__init__(parent)
        self._args = (path, mode, output)
        self._kwargs = {"quality": quality, "strip": strip,
                        "convert_to": convert_to}

    def run(self):
        try:
            result = get_pool().submit(
                compressor.compress, *self._args, **self._kwargs).result()
        except Exception:
            # Пул сломался (убитый процесс и т.п.) — пересоздаём и пробуем раз.
            _drop_pool()
            try:
                result = get_pool().submit(
                    compressor.compress, *self._args, **self._kwargs).result()
            except Exception:
                # Последний рубеж — прямо в потоке (UI может подлагивать).
                result = compressor.compress(*self._args, **self._kwargs)
        self.done.emit(result)


class UpdateCheckWorker(QThread):
    """Тихая фоновая проверка наличия новой версии на GitHub."""
    done = Signal(object)         # dict результата updater.check_update

    def run(self):
        from core import updater
        try:
            self.done.emit(updater.check_update())
        except Exception:
            self.done.emit({"status": "error"})


class AppUpdateWorker(QThread):
    """Скачивание обновления приложения (zip релиза) с прогрессом."""
    progress = Signal(float)
    done = Signal(bool, str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        from core import updater
        try:
            updater.download_update(self._url,
                                    on_progress=lambda f: self.progress.emit(float(f)))
            self.done.emit(True, "")
        except Exception as exc:
            self.done.emit(False, str(exc))


class SetupWorker(QThread):
    """Первый запуск: докачка gifsicle.exe в %APPDATA%/Shrinkr/tools."""
    progress = Signal(float)
    done = Signal(bool, str)

    def run(self):
        from core import tools
        try:
            tools.download_gifsicle(
                on_progress=lambda f: self.progress.emit(float(f)))
            self.done.emit(True, "")
        except Exception as exc:
            self.done.emit(False, str(exc))
