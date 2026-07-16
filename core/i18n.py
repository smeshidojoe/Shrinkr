"""
Лёгкая система локализации.

Ключ перевода — это английская строка (она же fallback). Любую видимую надпись
в UI оборачиваем в tr("English text"). Незнакомые/непереведённые строки
возвращаются как есть (английский).
"""

from core.constants import DEFAULT_LANGUAGE

_RU = {
    # --- Кнопки / разделы / общие ---
    "Settings": "Настройки",
    "About": "О программе",
    "Usage": "Режим работы",
    "General": "Общее",
    "Advanced": "Дополнительно",
    "Compression": "Сжатие",
    "Pinned": "Закреплено",
    "Auto-hide": "Автоскрытие",
    "Allow Dragging": "Перетаскивание окна",
    "Launch at startup": "Запускать при старте системы",
    "Menu Bar Icon": "Иконка в трее",
    "Theme": "Тема",
    "Language": "Язык",
    "Exit": "Выход",
    "Open": "Открыть",
    "Confirm": "Подтвердить",
    "Reset Settings": "Сбросить настройки",
    "Open Logs Folder": "Открыть папку логов",
    "Copy result to clipboard": "Копировать результат в буфер",
    "Check for Updates": "Проверить обновления",
    "Version": "Версия",
    "2026 Developed by ": "2026 Разработано ",
    "Checking…": "Проверка…",
    "Update available": "Доступно обновление",
    "You're up to date": "Установлена последняя версия",
    "Check failed — try later": "Не удалось проверить — попробуйте позже",
    "Download Update": "Скачать обновление",
    "Downloading update…": "Скачивание обновления…",
    "Downloading gifsicle…": "Скачивание gifsicle…",
    "Notify about updates": "Уведомлять об обновлениях",

    # --- Сжатие ---
    "Mode": "Режим",
    "Smart": "Умное",
    "Lossless": "Без потерь",
    "Quality": "Качество",
    "Max": "Макс",
    "Balanced": "Баланс",
    "Small": "Мини",
    "Custom": "Вручную",
    "Convert to": "Конвертировать в",
    "Keep format": "Исходный формат",
    "Strip metadata": "Удалять метаданные",
    "Explorer context menu": "Меню Проводника (ПКМ)",
    "Before": "До",
    "After": "После",
    "Drag the result out, or drop the next image":
        "Перетащите результат из окна или бросьте следующую картинку",
    "Removes EXIF (camera, GPS) and auxiliary chunks.\n"
    "Smaller files; color profile is kept when possible.":
        "Удаляет EXIF (камера, GPS) и вспомогательные чанки.\n"
        "Файлы меньше; цветовой профиль по возможности сохраняется.",
    "Adds “Compress with Shrinkr” to the right-click\n"
    "menu of images in Explorer.":
        "Добавляет «Compress with Shrinkr» в меню правой\n"
        "кнопки мыши для картинок в Проводнике.",
    "Output": "Результат",
    "Next to original": "Рядом с оригиналом",
    "Overwrite original": "Заменять оригинал",
    "Drop an image here\nor click to choose": "Перетащите картинку сюда\nили нажмите для выбора",
    "Choose image": "Выберите изображение",
    "Compressing…": "Сжатие…",
    "Saved": "Сохранено",
    "smaller": "меньше",
    "Already optimized": "Уже оптимально сжато",
    "Unsupported file type": "Формат не поддерживается",
    "Compression failed": "Не удалось сжать",
    "Compress another": "Сжать ещё",
    "Images only (JPEG, PNG, WebP, GIF)": "Только изображения (JPEG, PNG, WebP, GIF)",
    "One image at a time": "Одна картинка за раз",
    "Smart: tiny, invisible quality loss for maximum compression.\n"
    "Lossless: pixels stay identical, only the encoding is optimized.":
        "Умное: незаметные глазу потери ради максимального сжатия.\n"
        "Без потерь: пиксели не меняются, оптимизируется только кодирование.",

    # --- Подсказки ---
    "Pinned: the tray icon opens and closes the window.\n"
    "Auto-hide: the tray icon opens the window; it closes\n"
    "on Esc or when you click outside it.":
        "Закреплено: иконка в трее открывает и закрывает окно.\n"
        "Автоскрытие: иконка открывает окно; оно закрывается\n"
        "по Esc или при клике вне него.",
    "Drag the window by holding an empty area at the top.\n"
    "The position resets the next time the window is shown.":
        "Перетаскивайте окно за пустую область сверху.\n"
        "Позиция сбрасывается при следующем открытии окна.",
}

_TRANSLATIONS = {
    "English": {},
    "Русский": _RU,
}

_current = DEFAULT_LANGUAGE


def set_language(lang):
    global _current
    _current = lang if lang in _TRANSLATIONS else DEFAULT_LANGUAGE


def language():
    return _current


def available():
    return list(_TRANSLATIONS.keys())


def tr(key):
    """Перевод строки на текущий язык (с откатом на английский / сам ключ)."""
    table = _TRANSLATIONS.get(_current, {})
    return table.get(key) or key
