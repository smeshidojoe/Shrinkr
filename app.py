import math
import os

from PySide6.QtCore import (
    Qt, QRectF, QPointF, QPoint, QEvent, QPropertyAnimation, QEasingCurve,
    QTimer, Signal
)
from PySide6.QtGui import (
    QPainter, QPainterPath, QRadialGradient, QColor, QPen, QBrush, QGuiApplication,
    QCursor
)
from PySide6.QtWidgets import QWidget, QApplication

import win32gui
import win32api
import win32process

from core import config
from core import fonts
from core import i18n
from core import themes
from ui import anim
from ui.bottom_bar import BottomBar
from ui.main_page import MainPage
from ui.settings_page import SettingsPage
from ui.about_page import AboutPage


class App(QWidget):

    # Файлы от второго инстанса (ipc.Listener живёт в чужом потоке —
    # сигнал переправляет вызов в GUI-поток).
    _files_received = Signal(list)

    def __init__(self):
        super().__init__()

        # Регистрируем кастомные шрифты до создания виджетов.
        fonts.load()

        # Настройки загружаются с диска (персистентность между сессиями).
        self.settings = config.load()
        i18n.set_language(self.settings.get("language", "English"))

        # Масштаб авто по разрешению экрана. Линейный пересчёт через две точки:
        # 1080p (raw 0.75) -> 0.85, 1440p (raw 1.0) -> 1.0  =>  scale = raw*0.6 + 0.4.
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        raw = min(geo.width() / 2560, geo.height() / 1440)
        scale = max(0.6, min(raw * 0.6 + 0.4, 1.4))
        avail_h = screen.availableGeometry().height()
        fit_cap = avail_h / 560.0
        self._base_scale = max(scale, min(0.95, fit_cap))
        self._recompute_dims()

        # Трей выставляется из main.py после создания окна.
        self.tray = None

        # Цвета окна — из палитры выбранной темы.
        self._load_window_colors()

        self.current_page = "main"
        self._nav_busy = False

        # Режим работы окна:
        #   "toggle" (Pinned)   — клик по иконке открывает/закрывает окно;
        #   "focus"  (Auto-hide)— клик открывает, закрытие по Esc / клику вне окна.
        self.usage_mode = self.settings.get("usage_mode", "toggle")
        self._suppress_autohide = False
        self._became_active = False

        # Перетаскивание окна (за верхнюю пустую область).
        self.allow_dragging = bool(self.settings.get("allow_dragging", False))
        self._drag_offset = None

        # Состояние показа окна (для устойчивости к быстрым кликам по трею).
        self._shown = False
        self._appearing = False
        self._final_pos = None
        self._win_pos_anim = None
        self._win_op_anim = None
        self._tray_edge = "top"   # где панель задач: top|bottom|left|right

        # Обновление / докачка инструментов (модальный оверлей блокирует окно).
        self._update_overlay = None
        self._update_worker = None
        self._updating = False
        self._setup_worker = None
        self._first_run_checked = False

        # Окно: безрамочное, всегда поверх, без кнопки на панели задач.
        self.setWindowTitle("Shrinkr")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIN_W, self.WIN_H)

        # Авто-скрытие в режиме Auto-hide: реакция на потерю активности
        # приложения (клик вне окна) и на Esc (через глобальный фильтр событий).
        QApplication.instance().applicationStateChanged.connect(self._on_app_state)
        QApplication.instance().installEventFilter(self)

        # Страницы создаются заранее и прячутся (показывается только активная).
        self._build_pages()

    # ------------------------------------------------------------------ #
    def _s(self, value):
        return int(value * self.scale)

    def save_settings(self):
        config.save(self.settings)

    # ------------------------------------------------------------------ #
    #  Построение страниц / применение темы и языка
    # ------------------------------------------------------------------ #
    def _recompute_dims(self):
        """Пересчёт всех размеров окна по масштабу (авто, по разрешению экрана)."""
        self.scale = self._base_scale

        self.WIN_W          = self._s(492)
        self.WIN_H_FULL     = self._s(480)
        self.WIN_H_SETTINGS = self.WIN_H_FULL + self._s(70)
        self.WIN_H_ABOUT    = self._s(480)
        self.WIN_H          = self.WIN_H_FULL
        self.CORNER_R       = self._s(14)
        self.BORDER_W       = max(2, self._s(3))
        self.BAR_H          = self._s(48)
        self.DRAG_ZONE_H    = self._s(64)

        self.content_x = self.BORDER_W
        self.content_y = self.BORDER_W
        self.content_w = self.WIN_W - 2 * self.BORDER_W
        self.content_h = self.WIN_H_SETTINGS - self.BAR_H - self.BORDER_W
        self.about_content_h = self.WIN_H_ABOUT - self.BAR_H - self.BORDER_W

    def _crossfade(self, snap):
        """Плавный кросс-фейд: поверх нового окна показываем снимок старого и гасим."""
        from PySide6.QtWidgets import QLabel
        ov = QLabel(self)
        ov.setPixmap(snap)
        ov.setGeometry(0, 0, snap.width(), snap.height())
        ov.raise_()
        ov.show()
        anim.fade(ov, 1.0, 0.0, 300, on_finished=ov.deleteLater)

    def _load_window_colors(self):
        """Цвета фона/рамки окна из палитры текущей темы."""
        pal = themes.palette(self.settings.get("theme", themes.DEFAULT_THEME))
        self.BORDER_COLOR = pal["border"]
        self.BG_COLOR     = pal["bg"]
        self.GRAD_CENTER  = pal["grad_center"]
        self.GRAD_EDGE    = pal["grad_edge"]
        self.PAGE_BG      = pal["page_bg"]
        self.SEP_COLOR    = pal["separator"]

    def _build_pages(self):
        """Создаёт страницы и нижнюю панель (вызывается при старте и при смене
        темы/языка — тогда старые виджеты предварительно удаляются)."""
        self.settings_page = SettingsPage(self, self, self.settings,
                                          self.content_w, self.content_h)
        self.settings_page.setGeometry(self.content_x, self.content_y,
                                       self.content_w, self.content_h)
        self.settings_page.hide()

        self.about_page = AboutPage(self, self, self.settings,
                                    self.content_w, self.about_content_h)
        self.about_page.setGeometry(self.content_x, self.content_y,
                                    self.content_w, self.about_content_h)
        self.about_page.hide()

        self.main_content_h = self.WIN_H_FULL - self.BAR_H - self.BORDER_W
        self.main_page = MainPage(self, self, self.settings,
                                  self.content_w, self.main_content_h)
        self.main_page.setGeometry(self.content_x, self.content_y,
                                   self.content_w, self.main_content_h)

        self.bottom_bar = BottomBar(self, self, self.settings,
                                    self.WIN_W, self.BAR_H)
        self.bottom_bar.reposition()

        self.settings_page.ensurePolished()
        self.about_page.ensurePolished()
        self.main_page.ensurePolished()

    def apply_appearance(self):
        """Применяет тему/язык немедленно: перестраивает страницы и
        перерисовывает окно. Перестроение откладываем на следующий тик —
        нельзя удалять страницу прямо внутри сигнала её же селектора."""
        QTimer.singleShot(0, self._apply_appearance_now)

    def _apply_appearance_now(self):
        if self._updating or self.main_page.is_busy():
            return
        snap = self.grab()                      # кадр старого вида для кросс-фейда
        i18n.set_language(self.settings.get("language", "English"))
        self._load_window_colors()

        self.bottom_bar.teardown()
        for w in (self.settings_page, self.about_page, self.main_page,
                  self.bottom_bar):
            w.setParent(None)
            w.deleteLater()

        self._build_pages()

        # Тему/язык меняют на странице настроек — на ней и остаёмся.
        self.current_page = "settings"
        self.set_window_height(self.WIN_H_SETTINGS)
        self.bottom_bar.set_page_mode("settings")
        self.settings_page.setGeometry(self.content_x, self.content_y,
                                       self.content_w, self.content_h)
        self.settings_page.show()
        self.settings_page.raise_()
        self.update()
        self._crossfade(snap)                   # плавный переход к новой теме

    # ------------------------------------------------------------------ #
    #  Отрисовка фона: скруглённый прямоугольник + радиальный градиент + рамка
    # ------------------------------------------------------------------ #
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        r = self.CORNER_R

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)

        cx, cy = w / 2.0, h / 2.0
        radius = math.hypot(cx, cy)
        grad = QRadialGradient(QPointF(cx, cy), radius)
        grad.setColorAt(0.0, QColor(self.GRAD_CENTER))
        grad.setColorAt(1.0, QColor(self.GRAD_EDGE))
        p.fillPath(path, QBrush(grad))

        bw = self.BORDER_W
        border_path = QPainterPath()
        border_path.addRoundedRect(
            QRectF(bw / 2.0, bw / 2.0, w - bw, h - bw),
            max(1, r - 2), max(1, r - 2)
        )
        pen = QPen(QColor(self.BORDER_COLOR), bw)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(border_path)

        # Тонкая разделительная линия над нижней панелью.
        sep_y = h - self.BAR_H
        sep_pen = QPen(QColor(self.SEP_COLOR), max(1, self._s(1)))
        p.setPen(sep_pen)
        p.drawLine(int(bw + self._s(6)), int(sep_y),
                   int(w - bw - self._s(6)), int(sep_y))
        p.end()

    # ------------------------------------------------------------------ #
    #  Навигация между экранами (главная -> настройки -> about).
    # ------------------------------------------------------------------ #
    def on_left_button(self):
        """Левая кнопка панели: шестерёнка на главной, иначе «назад»."""
        if self._nav_busy:
            return
        if self.current_page == "main":
            self.open_settings()
        elif self.current_page == "settings":
            self.close_settings()
        elif self.current_page == "about":
            self.close_about()

    def open_settings(self):
        if self.current_page != "main" or self._nav_busy:
            return
        self._nav_busy = True
        self.current_page = "settings"
        self.bottom_bar.set_page_mode("settings")
        self.about_page.hide()
        self.settings_page.setGeometry(self.content_x, self.content_y,
                                       self.content_w, self.content_h)
        self._animate_height(self.WIN_H_SETTINGS)   # Settings выше базовой
        self.settings_page.show()
        self.settings_page.raise_()
        anim.fade(self.main_page, 1.0, 0.0, 180, on_finished=self.main_page.hide)
        anim.fade(self.settings_page, 0.0, 1.0, 200, on_finished=self._nav_done)

    def close_settings(self):
        if self.current_page != "settings" or self._nav_busy:
            return
        self._nav_busy = True
        self.current_page = "main"
        self.bottom_bar.set_page_mode("main")
        target = self.WIN_H_FULL
        new_ch = target - self.BAR_H - self.BORDER_W
        self.main_page.setGeometry(self.content_x, self.content_y, self.content_w, new_ch)
        self.main_page.relayout(new_ch)
        self._animate_height(target)                 # одновременно с фейдом
        self.main_page.show()
        self.main_page.raise_()
        self.bottom_bar.btn_settings.raise_()
        self.bottom_bar.btn_info.raise_()
        self.bottom_bar.btn_exit.raise_()

        def done():
            self.settings_page.hide()
            self._nav_done()

        anim.fade(self.settings_page, 1.0, 0.0, 200, on_finished=done)
        anim.fade(self.main_page, 0.0, 1.0, 200)

    def open_about(self, origin="settings"):
        """About можно открыть с настроек (иконка «i» на странице) или с главной
        (иконка «i» в нижней панели). Запоминаем источник — назад вернёмся к нему."""
        if self._nav_busy:
            return
        if origin == "settings" and self.current_page != "settings":
            return
        if origin == "main" and self.current_page != "main":
            return
        self._nav_busy = True
        self._about_origin = origin
        src = self.settings_page if origin == "settings" else self.main_page
        self.current_page = "about"
        self.bottom_bar.set_page_mode("about")
        self._animate_height(self.WIN_H_ABOUT)       # одновременно с фейдом
        self.about_page.setGeometry(self.content_x, self.content_y,
                                    self.content_w, self.about_content_h)

        def after_out():
            src.hide()
            self.about_page.show()
            self.about_page.raise_()
            anim.fade(self.about_page, 0.0, 1.0, 200, on_finished=self._nav_done)

        anim.fade(src, 1.0, 0.0, 180, on_finished=after_out)

    def close_about(self):
        if self.current_page != "about" or self._nav_busy:
            return
        self._nav_busy = True
        if getattr(self, "_about_origin", "settings") == "main":
            self.current_page = "main"
            self.bottom_bar.set_page_mode("main")
            target = self.WIN_H_FULL
            new_ch = target - self.BAR_H - self.BORDER_W
            self.main_page.setGeometry(self.content_x, self.content_y,
                                       self.content_w, new_ch)
            self.main_page.relayout(new_ch)
            self._animate_height(target)
            dest = self.main_page
        else:
            self.current_page = "settings"
            self.bottom_bar.set_page_mode("settings")
            self._animate_height(self.WIN_H_SETTINGS)
            self.settings_page.setGeometry(self.content_x, self.content_y,
                                           self.content_w, self.content_h)
            dest = self.settings_page

        def after_out():
            self.about_page.hide()
            dest.show()
            dest.raise_()
            if dest is self.main_page:
                self.bottom_bar.btn_settings.raise_()
                self.bottom_bar.btn_info.raise_()
                self.bottom_bar.btn_exit.raise_()
            anim.fade(dest, 0.0, 1.0, 200, on_finished=self._nav_done)

        anim.fade(self.about_page, 1.0, 0.0, 180, on_finished=after_out)

    def _nav_done(self):
        self._nav_busy = False

    def _animate_height(self, target):
        """
        Плавно меняет высоту окна. Если панель задач снизу — окно растёт вверх
        (низ зафиксирован у трея), иначе вниз (верх зафиксирован).
        """
        start = self.height()
        if start == target:
            self.WIN_H = target
            return

        x0 = self.x()
        top0 = self.y()
        bottom0 = self.y() + start
        grow_up = (self._tray_edge == "bottom")

        def apply(h):
            self.WIN_H = h
            self.setFixedSize(self.WIN_W, h)
            self.move(x0, bottom0 - h if grow_up else top0)
            self.bottom_bar.reposition()
            self.update()

        anim.animate(self, start, target, 260, lambda v: apply(int(round(v))),
                     easing=QEasingCurve.OutCubic,
                     on_finished=lambda: apply(target), attr="_h_anim")

    def set_window_height(self, new_h):
        """Мгновенно меняет высоту окна (используется при скрытом окне)."""
        if new_h == self.WIN_H:
            return
        self.WIN_H = new_h
        self.setFixedSize(self.WIN_W, new_h)
        self.bottom_bar.reposition()
        self.update()

    # ------------------------------------------------------------------ #
    #  Режим работы окна + авто-скрытие (Auto-hide)
    # ------------------------------------------------------------------ #
    def set_usage_mode(self, mode):
        """Сменить режим окна (Pinned/Auto-hide) и сохранить выбор."""
        self.usage_mode = mode
        self.settings["usage_mode"] = mode
        self.save_settings()

    def set_allow_dragging(self, value):
        """Включить/выключить перетаскивание окна и сохранить выбор."""
        self.allow_dragging = bool(value)
        self.settings["allow_dragging"] = self.allow_dragging
        self.save_settings()

    def set_autostart(self, on):
        """Автозапуск при старте Windows (ключ реестра HKCU\\...\\Run)."""
        from core import autostart
        on = bool(on)
        autostart.set_enabled(on)
        self.settings["autostart"] = on
        self.save_settings()

    def sync_autostart(self):
        """Настройка — источник истины: на старте приводим реестр в соответствие
        галочке."""
        from core import autostart
        autostart.set_enabled(self.settings.get("autostart", False))

    def reset_and_restart(self):
        """Удаляет ТОЛЬКО config.json и перезапускает Shrinkr."""
        from core import updater
        try:
            if os.path.isfile(config.CONFIG_PATH):
                os.remove(config.CONFIG_PATH)
        except OSError:
            pass
        updater.relaunch_app()
        # Немедленно завершаемся, чтобы освободить мьютекс single-instance.
        os._exit(0)

    # ------------------------------------------------------------------ #
    #  Обновление приложения + докачка инструментов (модальный оверлей)
    # ------------------------------------------------------------------ #
    def _show_overlay(self, title, worker, on_done=None):
        """Показывает модальный оверлей с заголовком и полосой прогресса,
        привязанный к worker (signals: progress[, status], done(ok, err))."""
        if self._updating:
            return
        self._updating = True
        self.suppress_autohide(True)

        from ui.widgets import UpdateOverlay

        pal = themes.palette(self.settings.get("theme", themes.DEFAULT_THEME))
        ov = UpdateOverlay(self, self, title,
                           fonts.font(self._s(13), "Semibold"), self.CORNER_R, pal)
        ov.setGeometry(0, 0, self.width(), self.height())
        ov.show()
        ov.raise_()
        ov.appear()
        self._update_overlay = ov

        worker.progress.connect(ov.set_progress)
        if hasattr(worker, "status"):
            worker.status.connect(ov.set_status)
        worker.done.connect(lambda ok, err: self._finish_overlay(ok, err, on_done))
        self._update_worker = worker
        worker.start()

    def _finish_overlay(self, ok, err, on_done=None):
        ov = self._update_overlay
        if ov is not None:
            ov.set_progress(1.0)

        def finish():
            if ov is not None:
                ov.hide()
                ov.deleteLater()
            self._update_overlay = None
            self._update_worker = None
            self._updating = False
            self.suppress_autohide(False)
            if on_done is not None:
                on_done(ok, err)

        # Дать полосе «доехать» до 100%, затем плавно убрать оверлей.
        QTimer.singleShot(280, lambda: ov.disappear(finish) if ov else finish())

    def _maybe_first_run_setup(self):
        """После первого открытия окна: если gifsicle.exe нет — качаем его в
        блокирующем оверлее (по аналогии с yt-dlp/ffmpeg в Snatchr)."""
        from core import tools
        from core.i18n import tr
        # Окно успели закрыть до срабатывания таймера — повторим при следующем
        # открытии (чтобы блокирующий оверлей не возник на скрытом окне).
        if not self.isVisible():
            self._first_run_checked = False
            return
        if tools.have_gifsicle():
            return
        from core.workers import SetupWorker
        self._show_overlay(tr("Downloading gifsicle…"), SetupWorker(self))

    def start_app_update(self, url):
        """Скачивает обновление приложения (с прогрессом в оверлее), затем
        перезапускается через внешнего помощника, который заменит exe."""
        from core.workers import AppUpdateWorker
        from core.i18n import tr
        if not url:
            return
        self._show_overlay(tr("Downloading update…"), AppUpdateWorker(url, self),
                           on_done=self._on_app_update_downloaded)

    def _on_app_update_downloaded(self, ok, err):
        if not ok:
            return
        from core import updater
        if updater.restart_to_update():
            # Немедленно и жёстко выходим: onefile-процесс должен освободить exe,
            # чтобы помощник смог его подменить.
            if self.tray is not None:
                self.tray.icon.hide()
            os._exit(0)
        # Если не frozen (разработка) — апдейт применится при следующем ручном запуске.

    # ------------------------------------------------------------------ #
    #  Фоновая проверка обновлений + тост-анонс
    # ------------------------------------------------------------------ #
    def start_update_watch(self):
        """Тихая проверка новых версий: первая через ~8 c после старта, далее
        периодически (раз в 6 ч). Только для собранного exe."""
        from core import updater
        if not updater.is_frozen():
            return
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(6 * 60 * 60 * 1000)   # 6 часов
        self._update_timer.timeout.connect(self._check_update_bg)
        self._update_timer.start()
        QTimer.singleShot(8000, self._check_update_bg)

    def set_update_notify(self, on):
        self.settings["update_notify"] = bool(on)
        self.save_settings()

    def _check_update_bg(self):
        if not self.settings.get("update_notify", True):
            return
        from core.workers import UpdateCheckWorker
        self._upd_check = UpdateCheckWorker(self)
        self._upd_check.done.connect(self._on_update_check)
        self._upd_check.start()

    def _on_update_check(self, result):
        if not isinstance(result, dict) or result.get("status") != "available":
            return
        if not self.settings.get("update_notify", True):
            return
        version = result.get("version") or ""
        url = result.get("download_url")
        if not url:
            return
        if version and version == self.settings.get("update_dismissed_version", ""):
            return                       # этот апдейт уже отклонили
        self._pending_update = {"version": version, "url": url}
        if self.tray is not None:
            from core.i18n import tr
            self.tray.show_toast(tr("Update available"), version,
                                 on_click=self._on_update_toast_click,
                                 position="corner", sticky=True,
                                 on_dismiss=self._on_update_toast_dismiss)

    def _on_update_toast_click(self):
        pu = getattr(self, "_pending_update", None)
        if not pu:
            return
        self.show_near_tray()            # показать окно
        self.open_about("main")          # перейти на About
        # запустить скачивание с уже известным URL (как кнопка в About)
        QTimer.singleShot(350, lambda u=pu["url"]: self.start_app_update(u))

    def _on_update_toast_dismiss(self):
        pu = getattr(self, "_pending_update", None)
        v = pu.get("version") if pu else ""
        if v:
            self.settings["update_dismissed_version"] = v
            self.save_settings()

    # ------------------------------------------------------------------ #
    #  Приём файлов извне (контекстное меню Проводника / argv)
    # ------------------------------------------------------------------ #
    def start_open_listener(self):
        from core import ipc
        self._files_received.connect(self.open_files)
        self._ipc_listener = ipc.Listener(self._files_received.emit)
        self._ipc_listener.start()
        QApplication.instance().aboutToQuit.connect(self._ipc_listener.stop)

    def open_files(self, paths):
        """Показать окно и отправить первый файл в сжатие (по одному за раз)."""
        if not paths:
            return
        self.show_near_tray()
        # Дать окну появиться, затем принять файл (busy отбрасывает лишние).
        QTimer.singleShot(300, lambda p=paths[0]: self.main_page._accept_path(p))

    # ------------------------------------------------------------------ #
    #  Сеттеры настроек сжатия
    # ------------------------------------------------------------------ #
    def set_quality(self, value):
        self.settings["quality"] = max(60, min(95, int(value)))
        self.save_settings()

    def set_convert_to(self, value):
        self.settings["convert_to"] = value
        self.save_settings()

    def set_strip_metadata(self, on):
        self.settings["strip_metadata"] = bool(on)
        self.save_settings()

    def set_context_menu(self, on):
        """Пункт «Compress with Shrinkr» в меню Проводника (реестр HKCU)."""
        from core import shellmenu
        on = bool(on)
        shellmenu.set_enabled(on)
        self.settings["context_menu"] = on
        self.save_settings()

    def sync_context_menu(self):
        """На старте приводим реестр к настройке (актуализирует путь exe)."""
        if self.settings.get("context_menu", False):
            from core import shellmenu
            shellmenu.set_enabled(True)

    def open_logs_folder(self):
        """Открыть папку с логами (%APPDATA%/Shrinkr/logs)."""
        from core.logbook import LOG_DIR
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            os.startfile(LOG_DIR)
        except Exception:
            pass

    def set_copy_result(self, on):
        """Копировать ли сжатый файл в буфер обмена после успеха."""
        self.settings["copy_result"] = bool(on)
        self.save_settings()

    def copy_file_to_clipboard(self, path):
        """Кладёт файл в буфер как «файл» (Qt отдаёт CF_HDROP на Windows) —
        сразу вставляется (Ctrl+V) в мессенджер/проводник."""
        if not path or not os.path.isfile(path):
            return
        try:
            from PySide6.QtCore import QMimeData, QUrl
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(os.path.abspath(path))])
            QApplication.clipboard().setMimeData(mime)
        except Exception:
            pass

    def suppress_autohide(self, value):
        """Временно отключить авто-скрытие (например, на время диалога)."""
        self._suppress_autohide = bool(value)

    def _on_app_state(self, state):
        # В режиме Auto-hide прячем окно, когда приложение теряет активность
        # (клик мышью вне окна программы). Но если фокус ушёл из-за клика по
        # самой панели задач/трею — окно НЕ гасим.
        if state == Qt.ApplicationActive:
            self._became_active = True
            return
        if (self.usage_mode == "focus" and self.isVisible()
                and self._became_active
                and not self._suppress_autohide
                and not self._cursor_over_tray()
                and state == Qt.ApplicationInactive):
            self.hide_window()

    def _cursor_over_tray(self):
        """Курсор над областью значков трея? (Только сам трей, не вся панель.)"""
        try:
            pos = QCursor.pos()
            tb = win32gui.FindWindow("Shell_TrayWnd", None)
            if not tb:
                return False
            tray = win32gui.FindWindowEx(tb, 0, "TrayNotifyWnd", None) or tb
            l, t, r, b = win32gui.GetWindowRect(tray)
            return l <= pos.x() <= r and t <= pos.y() <= b
        except Exception:
            return False

    def eventFilter(self, obj, event):
        # Глобальный перехват Esc в режиме Auto-hide.
        if (self.usage_mode == "focus" and self.isVisible()
                and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Escape):
            if self._updating:
                return True   # во время обновления Esc не закрывает окно
            self.hide_window()
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ #
    #  Показ/скрытие у трея с анимацией (fade + сдвиг). Устойчиво к быстрым
    #  кликам: при перебивании анимация продолжается с текущей точки.
    # ------------------------------------------------------------------ #
    def toggle_window(self):
        if self._updating:
            return
        if self.usage_mode == "focus":
            # Auto-hide: иконка ОТКРЫВАЕТ скрытое окно. Если поймали во время
            # анимации появления — сворачиваем обратно (из текущей точки).
            if not self._shown:
                self.show_near_tray()
            elif self._appearing:
                self.hide_window()
            return
        # Pinned: обычный тогл открыть/закрыть.
        if self._shown:
            self.hide_window()
        else:
            self.show_near_tray()

    def _stop_win_anims(self):
        for a in (self._win_pos_anim, self._win_op_anim):
            if a is not None:
                a.stop()

    def _run_win_anim(self, p_from, p_to, o_from, o_to, on_finished=None):
        self._stop_win_anims()
        showing = o_to >= 1.0
        self._appearing = showing   # перебить кликом можно, пока окно появляется

        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(220)
        pos_anim.setStartValue(p_from)
        pos_anim.setEndValue(p_to)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        op_anim = QPropertyAnimation(self, b"windowOpacity", self)
        op_anim.setDuration(200)
        op_anim.setStartValue(float(o_from))
        op_anim.setEndValue(float(o_to))
        op_anim.setEasingCurve(QEasingCurve.OutCubic)

        def _fin():
            if showing:
                self._appearing = False
            if on_finished is not None:
                on_finished()

        op_anim.finished.connect(_fin)

        self._win_pos_anim = pos_anim
        self._win_op_anim = op_anim
        pos_anim.start()
        op_anim.start()

    def _slide_offset(self):
        # Снизу панель -> окно выезжает снизу вверх (старт ниже), иначе сверху вниз.
        rise = self._s(16)
        return rise if self._tray_edge == "bottom" else -rise

    def show_near_tray(self):
        self._shown = True
        fresh = not self.isVisible()

        if fresh:
            # Всегда открываемся на стартовой (главной) странице.
            self._reset_to_main()
            fx, fy = self._compute_tray_pos()  # выставляет self._tray_edge
            self._final_pos = QPoint(fx, fy)
            off = self._slide_offset()
            self.setWindowOpacity(0.0)
            self.move(fx, fy + off)
            self.show()
            self.repaint()        # отрисовать главное состояние, пока прозрачно
            start_pos = QPoint(fx, fy + off)
            start_op = 0.0
        else:
            # Перебиваем идущее скрытие — продолжаем с текущей точки к финалу.
            fx, fy = self._compute_tray_pos()
            self._final_pos = QPoint(fx, fy)
            start_pos = self.pos()
            start_op = self.windowOpacity()

        self._became_active = False
        self._run_win_anim(start_pos, QPoint(fx, fy), start_op, 1.0)
        self.raise_()
        # Фокус забираем только в режиме Auto-hide (нужен для Esc/клика-вне).
        if self.usage_mode == "focus":
            self.activateWindow()
            self.setFocus()
            self._force_foreground()
            self._became_active = True    # авто-скрытие вооружено сразу

        # Первое открытие окна -> через 0.5с проверяем/докачиваем gifsicle.
        if not self._first_run_checked:
            self._first_run_checked = True
            QTimer.singleShot(500, self._maybe_first_run_setup)

    def _force_foreground(self):
        """Надёжно делает окно активным (SetForegroundWindow с обходом блокировки)."""
        try:
            hwnd = int(self.winId())
            fg = win32gui.GetForegroundWindow()
            if fg == hwnd:
                return
            cur = win32api.GetCurrentThreadId()
            other = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
            if other and other != cur:
                win32process.AttachThreadInput(other, cur, True)
                try:
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    win32process.AttachThreadInput(other, cur, False)
            else:
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def hide_window(self):
        if self._updating:
            return
        if not self.isVisible():
            self._shown = False
            return
        self._shown = False
        cur = self.pos()              # текущая позиция (учитывает перетаскивание)
        off = self._slide_offset()

        def fin():
            # Финализируем только если за время анимации не запросили показ.
            if not self._shown:
                self.hide()
                self.setWindowOpacity(1.0)
                self.main_page.on_window_hidden()
                self._reset_to_main()

        self._run_win_anim(cur, QPoint(cur.x(), cur.y() + off),
                           self.windowOpacity(), 0.0, on_finished=fin)

    def _reset_to_main(self):
        """Сбросить навигацию на главную страницу (главная высота)."""
        if self.current_page != "main":
            self.current_page = "main"
            self.bottom_bar.set_page_mode("main")
        self.settings_page.setGraphicsEffect(None)
        self.about_page.setGraphicsEffect(None)
        self.main_page.setGraphicsEffect(None)
        self.settings_page.hide()
        self.about_page.hide()
        self.main_page.show()
        self.main_page.on_window_shown()
        self.main_page.raise_()
        self.bottom_bar.btn_settings.raise_()
        self.bottom_bar.btn_info.raise_()
        self.bottom_bar.btn_exit.raise_()
        target = self.WIN_H_FULL
        new_ch = target - self.BAR_H - self.BORDER_W
        self.main_page.setGeometry(self.content_x, self.content_y, self.content_w, new_ch)
        self.main_page.relayout(new_ch)
        if self.WIN_H != target:
            self.set_window_height(target)

    # ------------------------------------------------------------------ #
    #  Перетаскивание окна (если включено) за верхнюю пустую область.
    # ------------------------------------------------------------------ #
    def window_drag_press(self, global_pos):
        self._drag_offset = global_pos - self.frameGeometry().topLeft()

    def window_drag_move(self, global_pos):
        if self._drag_offset is None:
            return
        target = global_pos - self._drag_offset
        avail = QGuiApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        x = max(avail.left(), min(target.x(), avail.right() - w + 1))
        y = max(avail.top(), min(target.y(), avail.bottom() - h + 1))
        self.move(x, y)

    def window_drag_release(self):
        self._drag_offset = None

    def mousePressEvent(self, event):
        # Клики доходят сюда только для областей окна, не закрытых страницей.
        if (event.button() == Qt.LeftButton and self.allow_dragging
                and event.position().toPoint().y() < self.DRAG_ZONE_H
                and self.childAt(event.position().toPoint()) is None):
            self.window_drag_press(event.globalPosition().toPoint())
        else:
            self._drag_offset = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.window_drag_move(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _compute_tray_pos(self):
        w, h = self.WIN_W, self.WIN_H
        screen = QGuiApplication.primaryScreen().geometry()
        sw, sh = screen.width(), screen.height()

        taskbar = win32gui.FindWindow("Shell_TrayWnd", None)
        taskbar_rect = win32gui.GetWindowRect(taskbar)

        tb_left   = taskbar_rect[0]
        tb_top    = taskbar_rect[1]
        tb_right  = taskbar_rect[2]
        tb_bottom = taskbar_rect[3]
        tb_width  = tb_right - tb_left
        tb_height = tb_bottom - tb_top

        tray_hwnd = win32gui.FindWindowEx(taskbar, 0, "TrayNotifyWnd", None)
        toolbar   = win32gui.FindWindowEx(tray_hwnd, 0, "ToolbarWindow32", None)

        if toolbar:
            tray_rect = win32gui.GetWindowRect(toolbar)
        else:
            tray_rect = win32gui.GetWindowRect(tray_hwnd)

        tray_cx = (tray_rect[0] + tray_rect[2]) // 2
        tray_cy = (tray_rect[1] + tray_rect[3]) // 2

        margin = self._s(12)

        if tb_height < tb_width:
            position = "top" if tb_top < sh // 2 else "bottom"
        else:
            position = "left" if tb_left < sw // 2 else "right"

        self._tray_edge = position   # для направления анимаций/роста высоты

        if position == "bottom":
            x = tray_cx - w // 2
            y = tb_top - h - margin
        elif position == "top":
            x = tray_cx - w // 2
            y = tb_bottom + margin
        elif position == "left":
            x = tb_right + margin
            y = tray_cy - h // 2
        else:  # right
            x = tb_left - w - margin
            y = tray_cy - h // 2

        x = max(margin, min(x, sw - w - margin))
        y = max(margin, min(y, sh - h - margin))

        return x, y
