from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from core import fonts, themes
from core.i18n import tr
from core.icons import themed_icon
from ui.widgets import IconButton, LinkButton
from ui import anim


class BottomBar(QWidget):
    """Нижняя панель: слева шестерёнка (на главной) / стрелка «назад» (иначе),
    по центру — info (только на главной), справа — Exit."""

    def __init__(self, parent, app, settings, width=460, height=48):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self._mode = "main"
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._load_icons()
        self._build()

    def _load_icons(self):
        theme = self.settings.get("theme", themes.DEFAULT_THEME)
        p = themes.palette(theme)
        self._icon = p["icon"]
        self._icon_hover = p["icon_hover"]
        gz = self.app._s(24)   # шестерёнка/стрелка — крупнее
        self.ic_settings   = themed_icon(theme, "settings.png",   self._icon, gz)
        self.ic_settings_h = themed_icon(theme, "settings.png",   self._icon_hover, gz)
        self.ic_back       = themed_icon(theme, "back-black.png", self._icon, gz)
        self.ic_back_h     = themed_icon(theme, "back-black.png", self._icon_hover, gz)
        iz = self.app._s(20)   # info.png визуально плотнее — рисуем чуть мельче
        self.ic_info       = themed_icon(theme, "info.png",       self._icon, iz)
        self.ic_info_h     = themed_icon(theme, "info.png",       self._icon_hover, iz)

    def _build(self):
        s = self.app._s

        self.btn_settings = IconButton(
            self.app, self.ic_settings, self.ic_settings_h,
            s(24), self._on_left
        )
        self.btn_settings.resize(s(32), s(32))

        self.btn_info = IconButton(
            self.app, self.ic_info, self.ic_info_h,
            s(20), self._open_info
        )
        self.btn_info.resize(s(32), s(32))

        self.btn_exit = LinkButton(self.app, tr("Exit"), fonts.font(s(11), "Regular"),
                                   self._icon, self._icon_hover, self._exit_app)
        self.btn_exit.resize(s(48), s(32))

        # Кнопки привязаны к окну: при пересоздании панели (смена темы/языка)
        # новые виджеты надо показать явно.
        for b in (self.btn_settings, self.btn_info, self.btn_exit):
            b.show()

    def teardown(self):
        """Удаляет кнопки панели (они привязаны к окну, а не к самой панели)."""
        for w in (self.btn_settings, self.btn_info, self.btn_exit):
            w.setParent(None)
            w.deleteLater()

    def _on_left(self):
        self.app.on_left_button()

    def _open_info(self):
        self.app.open_about("main")

    def reposition(self):
        """Пересчитать позиции кнопок (после смены высоты окна)."""
        s = self.app._s
        bar_y = self.app.WIN_H - s(48)
        self.setGeometry(0, bar_y, self.app.WIN_W, s(48))

        btn_y = bar_y + s(8)
        self.btn_settings.move(s(12), btn_y)
        # info — ровно по центру (на месте папки в референсе).
        self.btn_info.move(self.app.WIN_W // 2 - s(16), btn_y)
        self.btn_exit.move(self.app.WIN_W - s(60), btn_y)

        self.btn_settings.raise_()
        if self._mode != "about":
            self.btn_exit.raise_()
        if self._mode == "main":
            self.btn_info.raise_()

    def set_page_mode(self, page):
        """
        main     — шестерёнка + info + Exit
        settings — стрелка назад + Exit
        about    — только стрелка назад
        """
        self._mode = page
        # Шестерёнка/стрелка переключаются мгновенно (без фейда).
        if page == "main":
            self.btn_settings.set_icons(self.ic_settings, self.ic_settings_h)
        else:
            self.btn_settings.set_icons(self.ic_back, self.ic_back_h)

        # Exit — с фейдом (когда окно видимо); в About его нет.
        self._set_btn_visible(self.btn_exit, page != "about")
        # info — только на главной.
        self._set_btn_visible(self.btn_info, page == "main")
        self.btn_settings.raise_()

    def _set_btn_visible(self, btn, visible):
        animate = self.app.isVisible()
        if visible:
            if not btn.isVisible():
                btn.show()
                btn.raise_()
                if animate:
                    anim.fade(btn, 0.0, 1.0, 180)
        else:
            if btn.isVisible():
                if animate:
                    anim.fade(btn, 1.0, 0.0, 160, on_finished=btn.hide)
                else:
                    btn.hide()

    def _exit_app(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()
