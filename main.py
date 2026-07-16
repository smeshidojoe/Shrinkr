import multiprocessing
import os
import sys

from PySide6.QtWidgets import QApplication

from core import updater
from app import App
from tray import TrayIcon
from core.constants import APP_NAME

_INSTANCE_MUTEX = None


def _is_only_instance():
    """True — мы единственный инстанс; False — Shrinkr уже запущен (тогда выходим,
    чтобы не плодить иконки в трее). Именованный мьютекс живёт до конца процесса."""
    global _INSTANCE_MUTEX
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        _INSTANCE_MUTEX = k.CreateMutexW(None, False, "Shrinkr-Single-Instance-Mutex")
        return k.GetLastError() != 183          # ERROR_ALREADY_EXISTS
    except Exception:
        return True                              # не блокируем запуск при ошибке


def _set_app_identity(app):
    """Имя приложения для ОС (панель задач/уведомления группируются под Shrinkr,
    а не под «Python»)."""
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
    except Exception:
        pass


if __name__ == "__main__":
    # Дочерние процессы сжатия (spawn) в собранном exe: без этого вызова
    # каждый воркер запускал бы новую копию всего приложения.
    multiprocessing.freeze_support()

    # Самоприменение обновления: этот же exe (Shrinkr-new.exe) запущен с флагом
    # --apply-update <старый_exe> — ждём выхода старого, подменяем его собой и
    # запускаем. Обрабатываем ДО мьютекса — это не «второй инстанс».
    if "--apply-update" in sys.argv:
        try:
            i = sys.argv.index("--apply-update")
            updater.apply_self_update(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
        except Exception:
            pass
        sys.exit(0)

    # Пути картинок из argv (контекстное меню Проводника / drag на exe).
    _file_args = [a for a in sys.argv[1:] if os.path.isfile(a)]

    # Защита от нескольких запусков: если Shrinkr уже работает — передаём ему
    # файлы через очередь и тихо выходим.
    if not _is_only_instance():
        if _file_args:
            from core import ipc
            ipc.push(_file_args)
        sys.exit(0)

    # Страховка: если с прошлого запуска остался распакованный апдейт —
    # применяем то, что не заблокировано (сам exe заменяет внешний помощник).
    try:
        updater.apply_pending_update()
        updater.cleanup_applied()      # убрать Shrinkr-new.exe, если апдейт применён
    except Exception:
        pass

    app = QApplication(sys.argv)
    _set_app_identity(app)
    # Окно живёт в трее: не закрываем приложение, когда окно скрыто.
    app.setQuitOnLastWindowClosed(False)

    window = App()

    tray = TrayIcon(window)
    window.tray = tray
    tray.run()
    window.sync_autostart()       # привести реестр автозапуска к настройке
    window.sync_context_menu()    # актуализировать путь в меню Проводника
    window.start_update_watch()   # фоновая проверка обновлений + тост-анонс
    window.start_open_listener()  # приём файлов от второго инстанса (Проводник)

    # Тёплый воркер: поднимаем процесс сжатия заранее, чтобы первый файл
    # не платил за spawn+импорты.
    from PySide6.QtCore import QTimer
    from core import workers
    QTimer.singleShot(1200, workers.warm_up)

    # Файлы, переданные при запуске (ПКМ в Проводнике на незапущенном Shrinkr).
    if _file_args:
        QTimer.singleShot(600, lambda: window.open_files(_file_args))

    sys.exit(app.exec())
