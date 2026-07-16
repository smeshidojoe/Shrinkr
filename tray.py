import os
import time

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QEasingCurve
from PySide6.QtGui import (
    QIcon, QPixmap, QImage, QPainter, QColor, QBrush, QPen, QPolygonF,
    QFontMetrics, QCursor, QGuiApplication,
)
from PySide6.QtWidgets import QSystemTrayIcon, QWidget, QApplication

from core.constants import ICONS_DIR
from core import themes, fonts, tools
from core.icons import tint_pixmap, raw_pixmap, COLORED_ICONS
from core.i18n import tr
from ui import anim


def _blend(c0, c1, t):
    """Линейная интерполяция двух QColor (t: 0 -> c0, 1 -> c1)."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(c0.red()   + (c1.red()   - c0.red())   * t),
        int(c0.green() + (c1.green() - c0.green()) * t),
        int(c0.blue()  + (c1.blue()  - c0.blue())  * t),
    )


# ------------------------------------------------------------------ #
#  Меню трея в стиле селектора (открывается по ПКМ)
# ------------------------------------------------------------------ #
class TrayMenu(QWidget):
    """Всплывающее меню трея, оформленное как выпадающий список-селектор:
    тёмное скруглённое поле + строки с плавной скользящей подсветкой.
    items — список (label, callback[, kind])."""

    def __init__(self, app, items):
        flags = (Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.Popup)
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._app = app
        # items: (label, callback[, kind]). kind="danger" — двухступенчатое
        # подтверждение (первый клик взводит: подпись -> Confirm, подсветка красная).
        self._items = [(it[0], it[1], it[2] if len(it) > 2 else None) for it in items]
        self._labels = [it[0] for it in self._items]
        self._armed = -1
        s = app._s
        pal = themes.palette(app.settings.get("theme", themes.DEFAULT_THEME))
        self._font = fonts.font(s(11), "Regular")
        self._field_bg = QColor(pal["field_bg"])
        self._text_color = QColor(pal["text"])
        self._accent = QColor(pal["seg_sel"])
        self._danger = QColor(pal.get("error", "#e05a5a"))
        self._cur_color = QColor(self._accent)
        self._border = QColor(pal["border"])
        self._on_accent = QColor(pal["on_accent"])
        self._radius = s(9)

        fm = QFontMetrics(self._font)
        self._row_h = fm.height() + s(14)
        self._pad = s(5)
        self._text_x = self._pad + s(10)
        widths = [fm.horizontalAdvance(lbl) for lbl in self._labels]
        widths.append(fm.horizontalAdvance(tr("Confirm")))
        self._w = max(widths, default=s(80)) + s(40)

        self._hover = -1
        self._hi_pos = 0.0
        self._hi_alpha = 0.0
        self._opened_at = 0.0

    # --- позиционирование / показ ------------------------------------- #
    def popup_at(self, gpos):
        h = self._pad * 2 + self._row_h * len(self._items)
        self.resize(self._w, h)

        avail = QGuiApplication.primaryScreen().availableGeometry()
        x = gpos.x()
        if gpos.y() + h > avail.bottom():   # снизу не помещается — вверх
            y = gpos.y() - h
        else:
            y = gpos.y()
        x = max(avail.left(), min(x, avail.right() - self._w + 1))
        y = max(avail.top(), min(y, avail.bottom() - h + 1))
        self.move(x, y)
        self._opened_at = time.monotonic()
        self.show()
        self.raise_()

    def _activate(self, idx):
        """Клик по пункту. danger-пункт при первом клике взводится (Confirm +
        красная подсветка), при втором — выполняется."""
        if idx < 0:
            self.close()
            return
        label, cb, kind = self._items[idx]
        if kind == "danger" and self._armed != idx:
            self._armed = idx
            self._labels[idx] = tr("Confirm")
            self._animate_color(self._danger)
            self.update()
            return
        self.close()
        if cb:
            QTimer.singleShot(0, cb)

    # --- мышь ---------------------------------------------------------- #
    def _row_at(self, y):
        idx = int((y - self._pad) // self._row_h)
        return idx if 0 <= idx < len(self._items) else -1

    def mouseMoveEvent(self, event):
        idx = self._row_at(event.position().y())
        if idx != self._hover:
            self._hover = idx
            self._animate_hi(idx)

    def mouseReleaseEvent(self, event):
        # «Хвост» открывающего клика игнорируем, чтобы меню не закрылось сразу.
        if time.monotonic() - self._opened_at < 0.18:
            return
        self._activate(self._row_at(event.position().y()))

    def _target_color(self, idx):
        return self._danger if (idx >= 0 and idx == self._armed) else self._accent

    def _animate_color(self, target):
        c0 = QColor(self._cur_color)
        tc = QColor(target)

        def tick(p):
            self._cur_color = _blend(c0, tc, p)
            self.update()
        anim.animate(self, 0.0, 1.0, 160, tick,
                     easing=QEasingCurve.OutCubic, attr="_col_anim")

    def _animate_hi(self, to_idx):
        self._animate_color(self._target_color(to_idx))
        frm = self._hi_pos
        a0 = self._hi_alpha
        if to_idx < 0:
            def tick(p):
                self._hi_alpha = a0 * (1.0 - p)
                self.update()
            anim.animate(self, 0.0, 1.0, 130, tick,
                         easing=QEasingCurve.OutCubic, attr="_hi_anim")
            return

        def tick(p):
            self._hi_pos = frm + (to_idx - frm) * p
            self._hi_alpha = a0 + (1.0 - a0) * p
            self.update()

        def fin():
            self._hi_pos = float(to_idx)
            self._hi_alpha = 1.0
            self.update()
        anim.animate(self, 0.0, 1.0, 190, tick,
                     easing=QEasingCurve.OutCubic, on_finished=fin, attr="_hi_anim")

    # --- отрисовка ----------------------------------------------------- #
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        p.setPen(QPen(self._border, 1))
        p.setBrush(self._field_bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)

        if self._hi_alpha > 0.01:
            hy = self._pad + self._hi_pos * self._row_h
            acc = QColor(self._cur_color)
            acc.setAlphaF(max(0.0, min(1.0, self._hi_alpha)))
            p.setPen(Qt.NoPen)
            p.setBrush(acc)
            p.drawRoundedRect(QRectF(self._pad, hy, w - 2 * self._pad, self._row_h),
                              self._radius - 2, self._radius - 2)

        p.setFont(self._font)
        for i, label in enumerate(self._labels):
            ry = self._pad + i * self._row_h
            cover = max(0.0, 1.0 - abs(i - self._hi_pos)) * self._hi_alpha
            p.setPen(_blend(self._text_color, self._on_accent, cover))
            p.drawText(QRectF(self._text_x, ry, w - self._text_x - self._pad, self._row_h),
                       Qt.AlignVCenter | Qt.AlignLeft, label)
        p.end()


# ------------------------------------------------------------------ #
#  Анимация иконки трея на время фонового сжатия
# ------------------------------------------------------------------ #
class TrayAnimator:
    """Пока идёт сжатие, иконка трея — вращающийся спиннер (или кольцо
    прогресса). По завершении: галочка/крестик -> плавно назад к иконке юзера.
    Все переходы — плавные (покадровая перерисовка по таймеру)."""

    RING_ORANGE = QColor("#ff9500")
    RING_GREEN  = QColor("#34c759")
    FAIL_RED    = QColor("#e05a5a")

    def __init__(self, tray):
        self._tray = tray
        self._size = 64
        self._timer = QTimer()
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._last_ring = -1.0

        self._phase = "idle"       # idle|start|ring|finish|hold|restore
        self._t = 0.0
        self._frac = 0.0
        self._draw_frac = 0.0
        self._base_pm = None
        self._check_pm = None
        self._spin = False
        self._angle = 0.0

    def is_active(self):
        return self._phase != "idle"

    # --- управление ---------------------------------------------------- #
    def start(self, spin=False):
        """spin=False — кольцо-прогресс (set_fraction). spin=True —
        неопределённый вращающийся спиннер."""
        self._base_pm = self._tray.base_pixmap(self._size)
        self._frac = 0.0
        self._draw_frac = 0.0
        self._spin = spin
        self._angle = 0.0
        self._phase = "start"
        self._t = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def set_fraction(self, frac):
        self._frac = max(0.0, min(1.0, frac or 0.0))

    def finish(self, success=True):
        if self._phase == "idle":
            return
        self._check_pm = self._check_pixmap(success)
        self._phase = "finish"
        self._t = 0.0
        if not self._timer.isActive():
            self._timer.start()

    # --- покадровая логика --------------------------------------------- #
    def _tick(self):
        dt = self._timer.interval()
        if self._spin:
            self._angle = (self._angle + 4) % 360
        if self._phase == "start":
            self._t += dt / 240.0
            self._draw_frac += (self._frac - self._draw_frac) * 0.25
            self._set(self._crossfade(self._base_pm, self._active_pixmap(),
                                      min(1.0, self._t)))
            if self._t >= 1.0:
                self._phase, self._t = "ring", 0.0
        elif self._phase == "ring":
            if self._spin:
                self._set(self._spin_pixmap(self._angle))
            else:
                self._draw_frac += (self._frac - self._draw_frac) * 0.20
                if abs(self._draw_frac - self._last_ring) >= 0.004:
                    self._last_ring = self._draw_frac
                    self._set(self._ring_pixmap(self._draw_frac))
        elif self._phase == "finish":
            self._t += dt / 280.0
            self._draw_frac += (1.0 - self._draw_frac) * 0.30
            self._set(self._crossfade(self._active_pixmap(), self._check_pm,
                                      min(1.0, self._t)))
            if self._t >= 1.0:
                self._phase, self._t = "hold", 0.0
        elif self._phase == "hold":
            self._t += dt / 560.0
            self._set(self._check_pm)
            if self._t >= 1.0:
                self._phase, self._t = "restore", 0.0
        elif self._phase == "restore":
            self._t += dt / 260.0
            self._set(self._crossfade(self._check_pm, self._base_pm, min(1.0, self._t)))
            if self._t >= 1.0:
                self._timer.stop()
                self._phase = "idle"
                self._tray.icon.setIcon(self._tray._resolve_icon())

    def _set(self, pm):
        self._tray.icon.setIcon(QIcon(pm))

    # --- рендер отдельных состояний ------------------------------------ #
    def _blank(self):
        img = QImage(self._size, self._size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        return img

    def _ring_pixmap(self, frac):
        sz = self._size
        img = self._blank()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = sz * 0.16
        rect = QRectF(m, m, sz - 2 * m, sz - 2 * m)
        pw = sz * 0.13

        track = QPen(QColor(255, 255, 255, 55), pw)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 0, 360 * 16)

        if frac > 0.004:
            col = _blend(self.RING_ORANGE, self.RING_GREEN, frac)
            pen = QPen(col, pw)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -int(360 * 16 * frac))
        p.end()
        return QPixmap.fromImage(img)

    def _active_pixmap(self):
        """Текущий «рабочий» кадр: спиннер (spin) или кольцо-прогресс."""
        return (self._spin_pixmap(self._angle) if self._spin
                else self._ring_pixmap(self._draw_frac))

    def _spin_pixmap(self, angle):
        """Неопределённый спиннер: дуга ~110°, вращается по кругу."""
        sz = self._size
        img = self._blank()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        m = sz * 0.16
        rect = QRectF(m, m, sz - 2 * m, sz - 2 * m)
        pw = sz * 0.13
        track = QPen(QColor(255, 255, 255, 55), pw)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 0, 360 * 16)
        arc = QPen(self.RING_ORANGE, pw)
        arc.setCapStyle(Qt.RoundCap)
        p.setPen(arc)
        p.drawArc(rect, int(-angle) * 16, 110 * 16)
        p.end()
        return QPixmap.fromImage(img)

    def _check_pixmap(self, success):
        sz = self._size
        img = self._blank()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = self.RING_GREEN if success else self.FAIL_RED
        m = sz * 0.16
        rect = QRectF(m, m, sz - 2 * m, sz - 2 * m)
        ring = QPen(col, sz * 0.13)
        ring.setCapStyle(Qt.RoundCap)
        p.setPen(ring)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 0, 360 * 16)

        mark = QPen(col, sz * 0.12)
        mark.setCapStyle(Qt.RoundCap)
        mark.setJoinStyle(Qt.RoundJoin)
        p.setPen(mark)
        if success:
            p.drawPolyline([QPointF(sz * 0.34, sz * 0.52),
                            QPointF(sz * 0.45, sz * 0.63),
                            QPointF(sz * 0.67, sz * 0.39)])
        else:
            p.drawLine(QPointF(sz * 0.39, sz * 0.39), QPointF(sz * 0.61, sz * 0.61))
            p.drawLine(QPointF(sz * 0.61, sz * 0.39), QPointF(sz * 0.39, sz * 0.61))
        p.end()
        return QPixmap.fromImage(img)

    def _crossfade(self, pm_a, pm_b, t):
        img = self._blank()
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if pm_a is not None and not pm_a.isNull():
            p.setOpacity(1.0 - t)
            p.drawPixmap(0, 0, pm_a.scaled(self._size, self._size,
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if pm_b is not None and not pm_b.isNull():
            p.setOpacity(t)
            p.drawPixmap(0, 0, pm_b.scaled(self._size, self._size,
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.end()
        return QPixmap.fromImage(img)


# ------------------------------------------------------------------ #
#  Кастомный тост у трея (надёжнее нативного балуна Windows)
# ------------------------------------------------------------------ #
class Toast(QWidget):
    """Небольшой тост в правом нижнем углу. Нативные уведомления Windows часто
    не показываются (Focus Assist / настройки), поэтому рисуем свой. Клик —
    выполнить действие, ✕ — закрыть, авто-скрытие через ~7 c."""

    def __init__(self, app, title, subtitle, on_click, sticky=False, on_dismiss=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.PointingHandCursor)
        self._app = app
        self._on_click = on_click
        self._sticky = sticky        # не гаснет по таймеру (напр., анонс обновления)
        self._on_dismiss = on_dismiss  # вызывается при закрытии ✕/ПКМ
        s = app._s
        pal = themes.palette(app.settings.get("theme", themes.DEFAULT_THEME))
        self._bg = QColor(pal["card_bg"])
        self._border = QColor(pal["border"])
        self._title_col = QColor(pal["title"])
        self._muted = QColor(pal["muted"])
        self._accent = QColor(pal["accent"])
        self._radius = s(12)
        self._title = title
        self._sub = subtitle
        self._title_font = fonts.font(s(12), "Semibold")
        self._sub_font = fonts.font(s(10), "Regular")
        self._w, self._h = s(252), s(62)
        self._pad = s(16)
        self._close_r = QRectF(self._w - s(24), s(6), s(18), s(18))
        self.resize(self._w, self._h)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(7000)
        self._timer.timeout.connect(self._dismiss)

    def show_at(self, mode="corner"):
        """mode='corner' — правый нижний угол монитора, на котором курсор;
        mode='cursor' — рядом с указателем. Учитывает мультимонитор."""
        cur = QCursor.pos()
        screen = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        m = self._app._s(14)
        if mode == "cursor":
            x = cur.x() + m
            y = cur.y() + m
            if x + self._w > avail.right():
                x = cur.x() - self._w - m
            if y + self._h > avail.bottom():
                y = cur.y() - self._h - m
        else:  # corner — угол того монитора, где мышь
            x = avail.right() - self._w - m
            y = avail.bottom() - self._h - m
        x = max(avail.left(), min(x, avail.right() - self._w))
        y = max(avail.top(), min(y, avail.bottom() - self._h))
        self.move(x, y)
        self.show()
        self.raise_()
        anim.fade(self, 0.0, 1.0, 200)
        if not self._sticky:            # sticky-тост висит, пока его не закроют
            self._timer.start()

    def _dismiss(self):
        self._timer.stop()
        anim.fade(self, 1.0, 0.0, 180, on_finished=self.close)

    def mouseReleaseEvent(self, event):
        self._timer.stop()
        # ПКМ — просто закрыть тост; ✕ — тоже закрыть; ЛКМ — запустить действие.
        if event.button() == Qt.RightButton or self._close_r.contains(event.position()):
            if self._on_dismiss:        # напр., запомнить «этот апдейт отклонили»
                self._on_dismiss()
            self._dismiss()
            return
        cb = self._on_click
        self.close()
        if cb:
            QTimer.singleShot(0, cb)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self._app._s
        w, h = self.width(), self.height()
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)
        # акцентная полоска слева
        p.setPen(Qt.NoPen)
        p.setBrush(self._accent)
        p.drawRoundedRect(QRectF(s(7), h / 2 - s(12), s(3), s(24)), s(1.5), s(1.5))
        tx = self._pad + s(2)
        p.setFont(self._title_font)
        p.setPen(self._title_col)
        p.drawText(QRectF(tx, s(9), w - tx - s(22), s(20)),
                   Qt.AlignVCenter | Qt.AlignLeft, self._title)
        p.setFont(self._sub_font)
        p.setPen(self._muted)
        fm = QFontMetrics(self._sub_font)
        sub = fm.elidedText(self._sub, Qt.ElideRight, int(w - tx - self._pad))
        p.drawText(QRectF(tx, s(31), w - tx - self._pad, s(18)),
                   Qt.AlignVCenter | Qt.AlignLeft, sub)
        # ✕
        cr = self._close_r
        xpen = QPen(self._muted, max(2.0, s(2.2)))
        xpen.setCapStyle(Qt.RoundCap)
        p.setPen(xpen)
        p.drawLine(QPointF(cr.left() + s(4), cr.top() + s(4)),
                   QPointF(cr.right() - s(4), cr.bottom() - s(4)))
        p.drawLine(QPointF(cr.right() - s(4), cr.top() + s(4)),
                   QPointF(cr.left() + s(4), cr.bottom() - s(4)))
        p.end()


# ------------------------------------------------------------------ #
#  Иконка в системном трее
# ------------------------------------------------------------------ #
class TrayIcon:
    def __init__(self, app):
        self.app = app
        self.icon = None
        self.animator = None
        self._menu_popup = None
        self._toast = None             # активный кастомный тост
        self._build_icon()

    def _default_icon(self):
        img = QImage(64, 64, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#3B82F6")))
        painter.drawEllipse(4, 4, 56, 56)
        painter.setBrush(QBrush(QColor("white")))
        # Стилизованная «сжимающая» стрелка вниз (маркер Shrinkr).
        tri = QPolygonF([QPointF(20, 24), QPointF(44, 24), QPointF(32, 44)])
        painter.drawPolygon(tri)
        painter.end()
        return QIcon(QPixmap.fromImage(img))

    def _resolve_icon(self):
        """Иконка из icons/<tray_icon>.png, перекрашенная под тему панели задач
        Windows (чёрная на светлой панели, белая на тёмной). Пусто -> дефолт."""
        name = self.app.settings.get("tray_icon", "")
        if name:
            path = os.path.join(ICONS_DIR, name + ".png")
            if os.path.isfile(path):
                if name in COLORED_ICONS:      # цветные — не перекрашиваем
                    pm = raw_pixmap(path, 64)
                else:
                    color = "#000000" if tools.windows_uses_light_theme() else "#ffffff"
                    pm = tint_pixmap(path, color, 64)
                if pm is not None and not pm.isNull():
                    return QIcon(pm)
        return self._default_icon()

    def base_pixmap(self, size):
        """Пиксмап текущей пользовательской иконки (для кроссфейда анимации)."""
        return self._resolve_icon().pixmap(size, size)

    def _build_icon(self):
        self.icon = QSystemTrayIcon(self._resolve_icon(), self.app)
        self.icon.setToolTip("Shrinkr")
        # Контекстное меню (ПКМ) рисуем сами — нативное QMenu не ставим.
        self.icon.activated.connect(self._on_activated)
        self.animator = TrayAnimator(self)

    def set_icon(self, name):
        """Сменить иконку трея на лету (name — имя файла без расширения)."""
        self.app.settings["tray_icon"] = name or ""
        if self.icon is not None and not (self.animator and self.animator.is_active()):
            self.icon.setIcon(self._resolve_icon())

    def notify(self, text, title="Shrinkr"):
        try:
            self.icon.showMessage(title, text, QSystemTrayIcon.Information, 3500)
        except Exception:
            pass

    def show_toast(self, title, subtitle, on_click=None, position="corner",
                   sticky=False, on_dismiss=None):
        """Показать кастомный тост (предыдущий закрывается). sticky=True — висит,
        пока не закроют (напр., анонс обновления)."""
        if self._toast is not None:
            try:
                self._toast.close()
            except Exception:
                pass
        self._toast = Toast(self.app, title, subtitle, on_click,
                            sticky=sticky, on_dismiss=on_dismiss)
        self._toast.show_at(position)

    # --- события трея -------------------------------------------------- #
    def _on_activated(self, reason):
        # ЛКМ (Trigger) — открыть/закрыть окно (режим Pinned/Auto-hide).
        # Быстрый повторный клик во время анимации Windows приходит как
        # DoubleClick — его тоже считаем кликом.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_app()
        elif reason == QSystemTrayIcon.Context:
            self._show_menu()

    def _menu_items(self):
        return [(tr("Open"), self._show_app),
                (tr("Exit"), self._quit_app)]

    def _show_menu(self):
        self._menu_popup = TrayMenu(self.app, self._menu_items())
        self._menu_popup.popup_at(QCursor.pos())

    # --- действия меню ------------------------------------------------- #
    def _toggle_app(self):
        self.app.toggle_window()

    def _show_app(self):
        self.app.show_near_tray()

    def _quit_app(self):
        self.icon.hide()
        QApplication.instance().quit()

    def run(self):
        self.icon.show()
