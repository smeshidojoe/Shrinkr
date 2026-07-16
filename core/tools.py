"""Внешние инструменты (gifsicle) + системные хелперы.

gifsicle.exe хранится в %APPDATA%/Shrinkr/tools и докачивается при первом
запуске (по аналогии с yt-dlp/ffmpeg в Snatchr)."""

import os
import subprocess

from core.config import APP_DIR

TOOLS_DIR = os.path.join(APP_DIR, "tools")
GIFSICLE_EXE = os.path.join(TOOLS_DIR, "gifsicle.exe")

# Источники win-сборки gifsicle (по порядку): прямой exe из репозитория
# imagemin/gifsicle-bin (GitHub, стабильный TLS), затем zip eternallybored.
GIFSICLE_SOURCES = [
    ("https://raw.githubusercontent.com/imagemin/gifsicle-bin/"
     "main/vendor/win/x64/gifsicle.exe", "exe"),
    ("https://eternallybored.org/misc/gifsicle/releases/"
     "gifsicle-1.95-win64.zip", "zip"),
]

# Не показывать консольное окно при вызове exe (Windows).
CREATE_NO_WINDOW = 0x08000000


def have_gifsicle():
    return os.path.isfile(GIFSICLE_EXE)


def gifsicle_path():
    return GIFSICLE_EXE if have_gifsicle() else None


def run_gifsicle(args, input_bytes=None, timeout=120):
    """Запуск gifsicle с данными через stdin/stdout. Возвращает stdout (bytes)
    или None при ошибке/отсутствии бинарника."""
    exe = gifsicle_path()
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe] + list(args), input=input_bytes,
            capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except Exception:
        pass
    return None


def _fetch(url, on_progress, timeout):
    """Скачивает url в память с прогрессом. Возвращает bytes."""
    import io
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Shrinkr"})
    buf = io.BytesIO()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 64)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            if on_progress and total:
                on_progress(done / total)
    return buf.getvalue()


def download_gifsicle(on_progress=None, timeout=60):
    """Скачивает gifsicle.exe в TOOLS_DIR (источники по порядку: прямой exe с
    GitHub, затем zip eternallybored). on_progress(frac 0..1). Бросает при сбое
    всех источников."""
    import io
    import zipfile

    os.makedirs(TOOLS_DIR, exist_ok=True)
    last_err = None
    for url, kind in GIFSICLE_SOURCES:
        try:
            raw = _fetch(url, on_progress, timeout)
            if kind == "zip":
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    pick = next((n for n in zf.namelist()
                                 if os.path.basename(n).lower() == "gifsicle.exe"),
                                None)
                    if pick is None:
                        raise RuntimeError("gifsicle.exe not found in archive")
                    data = zf.read(pick)
            else:
                data = raw
            if not data or data[:2] != b"MZ":       # валидный PE-файл
                raise RuntimeError("downloaded file is not an exe")
            tmp = GIFSICLE_EXE + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, GIFSICLE_EXE)
            return True
        except Exception as exc:                     # пробуем следующий источник
            last_err = exc
    raise last_err or RuntimeError("no gifsicle sources")


def windows_uses_light_theme():
    """Светлая ли тема панели задач Windows (для цвета иконки в трее).
    True — светлая панель (иконки должны быть чёрными), False — тёмная (белыми).
    Ключ SystemUsesLightTheme отвечает именно за панель задач/трей."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except Exception:
        return False   # по умолчанию — тёмная панель (белые иконки)
