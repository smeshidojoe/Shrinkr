import os
import json

# Данные приложения храним в отдельной папке в %APPDATA% (Windows),
# с запасным вариантом для других ОС.
_BASE = os.environ.get("APPDATA") or os.path.join(
    os.path.expanduser("~"), ".config")
APP_DIR     = os.path.join(_BASE, "Shrinkr")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


def defaults():
    return {
        "tray_icon":       "sparkle",  # имя файла в icons/ ("" => иконка по умолчанию)
        "theme":           "Glass",    # стартовая тема для нового пользователя
        "language":        "English",  # язык интерфейса
        "usage_mode":      "toggle",   # "toggle" (Pinned) | "focus" (Auto-hide)
        "allow_dragging":  False,      # разрешить перетаскивание окна
        "autostart":       False,      # запускать Shrinkr при старте Windows
        # Режим сжатия:
        #   "smart"    — минимальные видимые потери при максимальном сжатии
        #   "lossless" — только безпотерьная оптимизация (байты меняются, картинка нет)
        "compress_mode":   "smart",
        # Куда класть результат: "suffix" (name-min.ext рядом) | "overwrite" (заменить)
        "output_mode":     "suffix",
        "copy_result":     False,      # копировать сжатый файл в буфер обмена
        "quality":         87,         # качество smart-пережатия (60..95)
        "convert_to":      "keep",     # "keep" | "webp" | "avif"
        "strip_metadata":  False,      # удалять EXIF/вспомогательные чанки
        "context_menu":    False,      # пункт в меню Проводника (ПКМ)

        "update_notify":   True,       # уведомлять тостом о новых версиях
        "update_dismissed_version": "",  # версия, тост которой уже закрыли
    }


def load():
    """Читает настройки с диска, дополняя отсутствующие ключи дефолтами."""
    data = defaults()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            data.update(saved)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return data


def save(settings):
    """Сохраняет настройки на диск (тихо, без падений на ошибках ФС)."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
