"""
Пункт «Compress with Shrinkr» в контекстном меню Проводника для картинок.

Пишем в HKCU\\Software\\Classes\\SystemFileAssociations\\<ext>\\shell\\Shrinkr —
без прав администратора, действует только для текущего пользователя.
"""

import os
import sys

_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_KEY_FMT = r"Software\Classes\SystemFileAssociations\{ext}\shell\Shrinkr"
_LABEL = "Compress with Shrinkr"


def _command():
    """Команда запуска: exe (frozen) либо python + main.py (dev)."""
    exe = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}" "%1"', exe
    main_py = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py")
    return f'"{exe}" "{main_py}" "%1"', exe


def is_enabled():
    try:
        import winreg
        key = _KEY_FMT.format(ext=_EXTS[0]) + r"\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            return True
    except OSError:
        return False


def set_enabled(on):
    """Регистрирует/удаляет пункт меню для всех поддерживаемых расширений.
    Возвращает True при успехе."""
    try:
        import winreg
        cmd, icon = _command()
        for ext in _EXTS:
            base = _KEY_FMT.format(ext=ext)
            if on:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
                    winreg.SetValueEx(k, None, 0, winreg.REG_SZ, _LABEL)
                    winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                      base + r"\command") as k:
                    winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)
            else:
                for sub in (base + r"\command", base):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                    except FileNotFoundError:
                        pass
        return True
    except OSError:
        return False
