import os
import sys

APP_NAME    = "Shrinkr"
APP_VERSION = "0.1.0"

# Репозиторий для проверки обновлений (релизы на GitHub).
GITHUB_REPO = "SmeshidoJoe/Shrinkr"

# Ссылка, открывающаяся по клику на имя разработчика в окне About.
DEVELOPER_URL = "https://github.com/SmeshidoJoe"

# В сборке PyInstaller ресурсы лежат во временной папке _MEIPASS; в разработке —
# в корне проекта.
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR  = os.path.join(BASE_DIR, "assets")
ICONS_DIR   = os.path.join(ASSETS_DIR, "icons")     # иконки трея (общие)
FONTS_DIR   = os.path.join(ASSETS_DIR, "fonts")
THEMES_DIR  = os.path.join(ASSETS_DIR, "Themes")    # глиф-иконки UI
PROFILE_IMG = os.path.join(ASSETS_DIR, "profile.png")

DEFAULT_THEME = "Glass"


def theme_dir(theme):
    """Папка ассетов конкретной темы (assets/Themes/<theme>)."""
    return os.path.join(THEMES_DIR, theme)


def _theme_names():
    try:
        from core.themes import enabled_themes
        return enabled_themes()
    except Exception:
        return [DEFAULT_THEME]


THEMES = _theme_names()

# Доступные языки интерфейса (см. core/i18n.py).
LANGUAGES = ["English", "Русский"]
DEFAULT_LANGUAGE = "English"
