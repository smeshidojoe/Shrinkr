import math
import time

from PySide6.QtCore import (
    Qt, QSize, QRectF, QPointF, QPoint, Signal, QEasingCurve, QTimer,
    QObject, QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPolygonF, QFontMetrics, QPixmap, QGuiApplication,
    QFont
)
from PySide6.QtWidgets import (
    QPushButton, QAbstractButton, QLabel, QWidget, QFrame
)

from ui import anim


class SmoothScroll(QObject):
    """Инерционная прокрутка колёсиком (как на macOS): щелчок колеса добавляет
    импульс к скорости, а таймер на ~120 fps двигает область с плавным затуханием
    (трение). Ставится один раз на QScrollArea."""

    def __init__(self, area, distance=115, friction=0.87, parent=None):
        super().__init__(parent or area)
        self._area = area
        self._vp = area.viewport()
        self._friction = friction
        self._impulse = distance * (1.0 - friction) / 120.0
        self._pos = 0.0
        self._vel = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._step)
        self._vp.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self._vp and ev.type() == QEvent.Wheel:
            try:
                self._on_wheel(ev.angleDelta().y())
            except RuntimeError:
                return False
            return True
        return super().eventFilter(obj, ev)

    def _on_wheel(self, delta):
        sb = self._area.verticalScrollBar()
        if not self._timer.isActive():
            self._pos = float(sb.value())
            self._vel = 0.0
        self._vel += -delta * self._impulse
        if not self._timer.isActive():
            self._timer.start()

    def _step(self):
        try:
            sb = self._area.verticalScrollBar()
        except RuntimeError:
            self._timer.stop()
            return
        self._pos += self._vel
        self._vel *= self._friction
        lo, hi = sb.minimum(), sb.maximum()
        if self._pos <= lo:
            self._pos, self._vel = float(lo), 0.0
        elif self._pos >= hi:
            self._pos, self._vel = float(hi), 0.0
        sb.setValue(int(round(self._pos)))
        if abs(self._vel) < 0.35:
            self._vel = 0.0
            self._timer.stop()


def _lerp_color(c0, c1, t):
    return QColor(
        int(c0.red()   + (c1.red()   - c0.red())   * t),
        int(c0.green() + (c1.green() - c0.green()) * t),
        int(c0.blue()  + (c1.blue()  - c0.blue())  * t),
    )


class WindowDragMixin:
    """
    Перетаскивание окна за пустую верхнюю область страницы. Подмешивается в
    QWidget-страницы ПЕРЕД QWidget в списке баз. Drag стартует только если под
    курсором нет дочернего виджета и точка в верхней зоне захвата.
    """

    def init_window_drag(self, app):
        self._drag_app = app
        self._dragging_window = False

    def mousePressEvent(self, event):
        app = getattr(self, "_drag_app", None)
        if (app is not None and event.button() == Qt.LeftButton
                and app.allow_dragging):
            pos = event.position().toPoint()
            win_y = pos.y() + self.y()
            if win_y < app.DRAG_ZONE_H and self.childAt(pos) is None:
                self._dragging_window = True
                app.window_drag_press(event.globalPosition().toPoint())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_dragging_window", False):
            self._drag_app.window_drag_move(event.globalPosition().toPoint())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, "_dragging_window", False):
            self._dragging_window = False
            self._drag_app.window_drag_release()
            return
        super().mouseReleaseEvent(event)


class IconButton(QPushButton):
    """Кнопка-иконка без фона: при наведении меняется только иконка."""

    def __init__(self, parent, icon_normal, icon_hover, size, on_click=None):
        super().__init__(parent)
        self._icon_normal = icon_normal
        self._icon_hover = icon_hover
        self._base_icon = size
        if icon_normal is not None:
            self.setIcon(icon_normal)
        self.setIconSize(QSize(size, size))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; outline: none; }"
        )
        self.clicked.connect(self._pop)   # тактильный отклик
        if on_click is not None:
            self.clicked.connect(on_click)

    def _pop(self):
        # Тактильный отклик: иконка сначала уменьшается, затем возвращается.
        base = self._base_icon
        def tick(p):
            f = 1.0 - 0.16 * math.sin(math.pi * p)
            sz = max(1, int(round(base * f)))
            self.setIconSize(QSize(sz, sz))
        anim.animate(self, 0.0, 1.0, 150, tick, easing=QEasingCurve.Linear,
                     on_finished=lambda: self.setIconSize(QSize(base, base)),
                     attr="_pop_anim")

    def set_icons(self, icon_normal, icon_hover):
        self._icon_normal = icon_normal
        self._icon_hover = icon_hover
        self.setIcon(icon_normal)

    def enterEvent(self, event):
        if self._icon_hover is not None:
            self.setIcon(self._icon_hover)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._icon_normal is not None:
            self.setIcon(self._icon_normal)
        super().leaveEvent(event)


class LinkButton(QPushButton):
    """
    Текстовая кнопка-«ссылка»: без фона, при наведении меняется цвет текста.
    Опционально при наведении подсвечивается еле заметная скруглённая подложка.
    """

    def __init__(self, parent, text, font, color, hover_color, on_click=None,
                 hover_bg=None, radius=6, base_bg=None, press_pop=False):
        super().__init__(text, parent)
        self._color = color
        self._hover = hover_color
        self._hover_bg = hover_bg
        self._base_bg = base_bg
        self._radius = radius
        self._press_pop = press_pop
        self.setFont(font)
        pt = font.pointSizeF()
        self._base_pt = pt if pt > 0 else float(font.pointSize())
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._apply(color, base_bg)
        if press_pop:
            self.clicked.connect(self._pop)
        if on_click is not None:
            self.clicked.connect(on_click)

    def _pop(self):
        base = self._base_pt
        f0 = QFont(self.font())
        def tick(p):
            ft = QFont(f0)
            ft.setPointSizeF(base * (1.0 + 0.16 * math.sin(math.pi * p)))
            self.setFont(ft)
        def fin():
            ft = QFont(f0); ft.setPointSizeF(base); self.setFont(ft)
        anim.animate(self, 0.0, 1.0, 150, tick, easing=QEasingCurve.Linear,
                     on_finished=fin, attr="_pop_anim")

    def _apply(self, color, bg):
        bg_css = f"background-color: {bg};" if bg else "background: transparent;"
        self.setStyleSheet(
            f"QPushButton {{ {bg_css} border: none; outline: none; color: {color}; "
            f"border-radius: {self._radius}px; }}"
        )

    def enterEvent(self, event):
        self._apply(self._hover, self._hover_bg or self._base_bg)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply(self._color, self._base_bg)
        super().leaveEvent(event)


class ClickableLabel(QLabel):
    """Лейбл-«ссылка»: смена цвета при наведении + сигнал clicked по клику."""

    clicked = Signal()

    def __init__(self, parent, text, color, hover_color):
        super().__init__(text, parent)
        self._color = color
        self._hover = hover_color
        self.setCursor(Qt.PointingHandCursor)
        self._apply(color)

    def _apply(self, color):
        self.setStyleSheet(f"color: {color}; background: transparent;")

    def enterEvent(self, event):
        self._apply(self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply(self._color)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CheckBox(QAbstractButton):
    """
    Чекбокс с залитым квадратом: неактивный — цвет off, активный — цвет on
    с белой галочкой. Текст рисуется справа от квадрата.
    """

    def __init__(self, parent, text, font, text_color,
                 off_color, on_color, box_size, radius):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._text = text
        self._font = font
        self._text_color = QColor(text_color)
        self._off = QColor(off_color)
        self._on = QColor(on_color)
        self._box = box_size
        self._radius = radius
        self._p = 1.0
        self._from_on = self.isChecked()
        self._to_on = self.isChecked()
        self.clicked.connect(self._animate_toggle)

    def setChecked(self, on):
        super().setChecked(on)
        self._from_on = self._to_on = bool(on)
        self._p = 1.0

    def setCheckedAnimated(self, on):
        on = bool(on)
        if self.isChecked() == on:
            return
        super().setChecked(on)
        self._animate_toggle()

    def _animate_toggle(self):
        self._to_on = self.isChecked()
        self._from_on = not self._to_on
        def tick(v):
            self._p = v
            self.update()
        def fin():
            self._p = 1.0
            self._from_on = self._to_on
            self.update()
        anim.animate(self, 0.0, 1.0, 240, tick,
                     easing=QEasingCurve.Linear, on_finished=fin, attr="_cb_anim")

    @staticmethod
    def _scale_of(p):
        # Сжатие -> overshoot -> возврат.
        if p <= 0.30:
            return 1.0 + (0.85 - 1.0) * (p / 0.30)
        if p <= 0.70:
            return 0.85 + (1.18 - 0.85) * ((p - 0.30) / 0.40)
        return 1.18 + (1.0 - 1.18) * ((p - 0.70) / 0.30)

    def _fill_amount(self):
        p = self._p
        if p <= 0.30:
            f = 0.0
        elif p <= 0.70:
            f = (p - 0.30) / 0.40
        else:
            f = 1.0
        a = 1.0 if self._from_on else 0.0
        b = 1.0 if self._to_on else 0.0
        return a + (b - a) * f

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        h = self.height()
        box = self._box * self._scale_of(self._p)
        inset = self._box * 0.20
        cx = inset + self._box / 2.0
        cy = h / 2.0
        rect = QRectF(cx - box / 2.0, cy - box / 2.0, box, box)
        radius = self._radius * (box / self._box)

        fill = self._fill_amount()
        p.setPen(Qt.NoPen)
        p.setBrush(_lerp_color(self._off, self._on, fill))
        p.drawRoundedRect(rect, radius, radius)

        if fill > 0.01:
            white = QColor(255, 255, 255, int(255 * min(1.0, fill)))
            pen = QPen(white, max(1.5, box * 0.12))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            x0 = rect.left()
            y0 = rect.top()
            p.drawPolyline([
                QPointF(x0 + box * 0.26, y0 + box * 0.52),
                QPointF(x0 + box * 0.44, y0 + box * 0.70),
                QPointF(x0 + box * 0.76, y0 + box * 0.32),
            ])

        p.setPen(self._text_color)
        p.setFont(self._font)
        text_x = self._box * 0.20 + self._box + self._box * 0.5
        text_rect = QRectF(text_x, 0, self.width() - text_x, h)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()


class SegmentedControl(QWidget):
    """
    Сегментированный переключатель из нескольких вариантов (как iOS/macOS).
    options — список (label, value). Выбранный сегмент заливается пилюлей.
    """

    changed = Signal(str)

    def __init__(self, parent, options, current, font,
                 bg_color, sel_color, text_color, sel_text_color, radius):
        super().__init__(parent)
        self._options = list(options)
        self._value = current
        self._font = font
        self._bg = QColor(bg_color)
        self._sel = QColor(sel_color)
        self._text = QColor(text_color)
        self._sel_text = QColor(sel_text_color)
        self._radius = radius
        self._pill_pos = float(self._current_index())
        self._scale = 1.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def value(self):
        return self._value

    def setValue(self, value):
        if value in [v for _, v in self._options] and value != self._value:
            self._value = value
            self._pill_pos = float(self._current_index())
            self.update()

    def _current_index(self):
        for i, (_, v) in enumerate(self._options):
            if v == self._value:
                return i
        return 0

    def mousePressEvent(self, event):
        n = len(self._options)
        if n == 0:
            return
        seg_w = self.width() / n
        idx = int(event.position().x() // seg_w)
        idx = max(0, min(n - 1, idx))
        new_value = self._options[idx][1]
        if new_value != self._value:
            frm = self._pill_pos
            self._value = new_value
            self.changed.emit(new_value)
            self._animate_pill(frm, idx)
        super().mousePressEvent(event)

    def _animate_pill(self, frm, to):
        def tick(p):
            self._pill_pos = frm + (to - frm) * p
            self._scale = 1.0 + 0.16 * math.sin(math.pi * p)
            self.update()
        def fin():
            self._pill_pos = float(to)
            self._scale = 1.0
            self.update()
        anim.animate(self, 0.0, 1.0, 300, tick,
                     easing=QEasingCurve.InOutCubic, on_finished=fin, attr="_pill_anim")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(self._font)

        w, h = self.width(), self.height()
        n = len(self._options)
        if n == 0:
            p.end()
            return

        mg = max(2, int(round(h * 0.10)))

        p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawRoundedRect(QRectF(mg, mg, w - 2 * mg, h - 2 * mg),
                          self._radius, self._radius)

        seg_w = (w - 2 * mg) / n
        seg_h = h - 2 * mg

        base_cx = mg + (self._pill_pos + 0.5) * seg_w
        base_cy = mg + seg_h / 2.0
        pw = seg_w * self._scale
        ph = seg_h * self._scale
        pill = QRectF(base_cx - pw / 2.0, base_cy - ph / 2.0, pw, ph)
        inner_r = max(1, self._radius - 1) * self._scale
        p.setBrush(self._sel)
        p.drawRoundedRect(pill, inner_r, inner_r)

        idx = self._current_index()
        for i, (label, _) in enumerate(self._options):
            rect = QRectF(mg + i * seg_w, 0, seg_w, h)
            p.setPen(self._sel_text if i == idx else self._text)
            p.drawText(rect, Qt.AlignCenter, label)
        p.end()


def _draw_chevrons(p, cx, h, chip_w, color):
    """Двойной шеврон (вверх/вниз) по центру «чипа» селектора."""
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    cy = h / 2.0
    hw = max(2.0, chip_w * 0.16)
    th = hw * 0.72
    gap = th + max(1.5, h * 0.07)
    up_cy = cy - gap
    p.drawPolygon(QPolygonF([
        QPointF(cx - hw, up_cy + th),
        QPointF(cx + hw, up_cy + th),
        QPointF(cx, up_cy - th),
    ]))
    dn_cy = cy + gap
    p.drawPolygon(QPolygonF([
        QPointF(cx - hw, dn_cy - th),
        QPointF(cx + hw, dn_cy - th),
        QPointF(cx, dn_cy + th),
    ]))


class Selector(QWidget):
    """
    Выпадающий список в стиле macOS: тёмное скруглённое поле + «чип» с двойным
    шевроном. При открытии всплывающий список появляется уже спозиционированным
    так, что текущий пункт оказывается ровно над полем.
    """

    changed = Signal(str)

    def __init__(self, parent, font, field_bg, chip_bg, text_color,
                 chevron_color, radius, chip_w,
                 accent="#3a77f0", border="#3a5068", on_accent="#ffffff"):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._font = font
        self._field_bg = QColor(field_bg)
        self._chip_bg = QColor(chip_bg)
        self._text_color = QColor(text_color)
        self._chevron = QColor(chevron_color)
        self._radius = radius
        self._chip_w = chip_w
        self._popup_accent = QColor(accent)
        self._popup_border = QColor(border)
        self._popup_on_accent = QColor(on_accent)
        self._items = []        # [(text, QPixmap|None)]
        self._current = 0
        self._popup = None

    # --- API ----------------------------------------------------------- #
    def add_item(self, text, icon=None):
        pm = None
        if isinstance(icon, QPixmap):
            pm = icon if not icon.isNull() else None
        elif icon:
            loaded = QPixmap(icon)
            if not loaded.isNull():
                pm = loaded
        self._items.append((text, pm))
        self.update()

    def clear(self):
        self._items = []
        self._current = 0
        self.update()

    def set_current(self, text):
        for i, (t, _) in enumerate(self._items):
            if t == text:
                self._current = i
                self.update()
                return

    def current(self):
        if 0 <= self._current < len(self._items):
            return self._items[self._current][0]
        return ""

    # --- поведение ----------------------------------------------------- #
    def mousePressEvent(self, event):
        self._open_popup()
        super().mousePressEvent(event)

    def _open_popup(self):
        if not self._items:
            return
        self._popup = _SelectorPopup(self)
        self._popup.open_over(self)

    def _on_pick(self, index):
        if index != self._current:
            self._current = index
            self.update()
            self.changed.emit(self._items[index][0])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        r = self._radius

        p.setPen(Qt.NoPen)
        p.setBrush(self._field_bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        chip = QRectF(w - self._chip_w, 0, self._chip_w, h)
        p.save()
        p.setClipRect(chip)
        p.setBrush(self._chip_bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        p.restore()
        _draw_chevrons(p, w - self._chip_w / 2.0, h, self._chip_w, self._chevron)

        text_x = r + 3
        if 0 <= self._current < len(self._items):
            text, pm = self._items[self._current]
            if pm is not None:
                isz = int(h * 0.55)
                iy = (h - isz) / 2.0
                p.drawPixmap(QRectF(text_x, iy, isz, isz).toRect(),
                             pm.scaled(isz, isz, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
                text_x += isz + 6
            p.setPen(self._text_color)
            p.setFont(self._font)
            avail = w - self._chip_w - text_x - 4
            p.drawText(QRectF(text_x, 0, avail, h),
                       Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class _SelectorPopup(QWidget):
    """Всплывающий список селектора (отдельное окно Qt.Popup со скруглением)."""

    def __init__(self, selector):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._sel = selector
        self._items = selector._items
        self._current = selector._current
        self._hover = selector._current
        self._hi_pos = float(selector._current)
        self._hi_alpha = 1.0
        self._font = selector._font
        self._field_bg = selector._field_bg
        self._text_color = selector._text_color
        self._accent = selector._popup_accent
        self._border = selector._popup_border
        self._on_accent = selector._popup_on_accent
        self._radius = selector._radius + 2

        fm = QFontMetrics(self._font)
        self._row_h = fm.height() + 12
        self._pad = 5
        self._has_icons = any(pm is not None for _, pm in self._items)
        self._check_w = fm.height()
        self._icon_sz = int(self._row_h * 0.6)

    # --- позиционирование ---------------------------------------------- #
    def open_over(self, selector):
        w = selector.width()
        h = self._pad * 2 + self._row_h * len(self._items)
        self.resize(w, h)

        field_tl = selector.mapToGlobal(QPoint(0, 0))
        row_top = self._pad + self._current * self._row_h
        x = field_tl.x()
        y = field_tl.y() - row_top

        avail = QGuiApplication.primaryScreen().availableGeometry()
        x = max(avail.left(), min(x, avail.right() - w + 1))
        y = max(avail.top(), min(y, avail.bottom() - h + 1))
        self.move(x, y)
        self._opened_at = time.monotonic()
        self.show()

    # --- мышь ----------------------------------------------------------- #
    def _row_at(self, y):
        idx = int((y - self._pad) // self._row_h)
        if 0 <= idx < len(self._items):
            return idx
        return -1

    def mouseMoveEvent(self, event):
        idx = self._row_at(event.position().y())
        if idx != self._hover:
            self._hover = idx
            self._animate_hi(idx)

    def _animate_hi(self, to_idx):
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

    def mouseReleaseEvent(self, event):
        if time.monotonic() - getattr(self, "_opened_at", 0.0) < 0.18:
            return
        idx = self._row_at(event.position().y())
        if idx >= 0:
            self._sel._on_pick(idx)
        self.close()

    # --- отрисовка ------------------------------------------------------ #
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        bg = QRectF(0.5, 0.5, w - 1, h - 1)
        p.setPen(QPen(self._border, 1))
        p.setBrush(self._field_bg)
        p.drawRoundedRect(bg, self._radius, self._radius)

        if self._hi_alpha > 0.01:
            hy = self._pad + self._hi_pos * self._row_h
            hrow = QRectF(self._pad, hy, w - 2 * self._pad, self._row_h)
            acc = QColor(self._accent)
            acc.setAlphaF(max(0.0, min(1.0, self._hi_alpha)))
            p.setPen(Qt.NoPen)
            p.setBrush(acc)
            p.drawRoundedRect(hrow, self._radius - 2, self._radius - 2)

        p.setFont(self._font)
        for i, (text, pm) in enumerate(self._items):
            ry = self._pad + i * self._row_h

            cover = max(0.0, 1.0 - abs(i - self._hi_pos)) * self._hi_alpha
            text_pen = _lerp_color(self._text_color, self._on_accent, cover)

            x = self._pad + 6
            if i == self._current:
                p.setPen(QPen(text_pen, max(1.4, self._check_w * 0.12)))
                cyc = ry + self._row_h / 2.0
                p.drawPolyline([
                    QPointF(x + self._check_w * 0.15, cyc),
                    QPointF(x + self._check_w * 0.40, cyc + self._check_w * 0.28),
                    QPointF(x + self._check_w * 0.80, cyc - self._check_w * 0.30),
                ])
            x += self._check_w + 4

            if self._has_icons:
                if pm is not None:
                    iy = ry + (self._row_h - self._icon_sz) / 2.0
                    p.drawPixmap(
                        QRectF(x, iy, self._icon_sz, self._icon_sz).toRect(),
                        pm.scaled(self._icon_sz, self._icon_sz,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))
                x += self._icon_sz + 6

            p.setPen(text_pen)
            p.drawText(QRectF(x, ry, w - x - self._pad, self._row_h),
                       Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class UpdateOverlay(QWidget):
    """
    Модальное затемнение всего окна + центральная карточка с заголовком и
    полосой прогресса (обновление приложения / докачка инструментов).
    Появление: карточка выезжает снизу вверх + проявляется по opacity.
    """

    def __init__(self, parent, app, title, title_font, corner_radius, palette):
        super().__init__(parent)
        s = app._s
        self.app = app
        self._corner = corner_radius
        self.setGeometry(0, 0, parent.width(), parent.height())

        cw, ch = s(300), s(100)
        cx = (self.width() - cw) // 2
        cy = (self.height() - ch) // 2
        self._card_y = cy

        self.card = QFrame(self)
        self.card.setGeometry(cx, cy, cw, ch)
        self.card.setStyleSheet(
            f"background-color: {palette['card_bg']};"
            f" border: 1px solid {palette['border']};"
            f" border-radius: {s(16)}px;"
        )

        self._lbl = QLabel(title, self.card)
        self._lbl.setFont(title_font)
        self._lbl.setStyleSheet(
            f"color: {palette['title']}; background: transparent; border: none;")
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setGeometry(0, s(22), cw, s(22))

        self.bar = ProgressBar(self.card, palette["prog_track"],
                               palette["download_bg"], s(8))
        self.bar.setGeometry(s(24), s(60), cw - s(48), s(24))

    def paintEvent(self, event):
        from PySide6.QtGui import QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                            self._corner, self._corner)
        p.fillPath(path, QColor(0, 0, 0, 166))   # ~0.65 затемнение
        p.end()

    def mousePressEvent(self, event):
        event.accept()   # блокируем клики по окну под оверлеем

    def set_progress(self, frac):
        self.bar.set_value(frac)

    def set_status(self, text):
        self._lbl.setText(text)

    def appear(self):
        start_y = self._card_y + self.app._s(28)
        self.card.move(self.card.x(), start_y)

        def tick(v):
            y = int(start_y + (self._card_y - start_y) * v)
            self.card.move(self.card.x(), y)

        anim.fade(self, 0.0, 1.0, 200)
        anim.fade(self.card, 0.0, 1.0, 300)
        anim.animate(self, 0.0, 1.0, 300, tick,
                     easing=QEasingCurve.OutCubic, attr="_slide_anim")

    def disappear(self, on_finished=None):
        anim.fade(self, 1.0, 0.0, 180, on_finished=on_finished)


class ProgressBar(QWidget):
    """Тонкая скруглённая полоса прогресса."""

    def __init__(self, parent, track, fill, radius):
        super().__init__(parent)
        self._frac = 0.0
        self._track = QColor(track)
        self._fill = QColor(fill)
        self._radius = radius

    def set_value(self, frac):
        self._frac = max(0.0, min(1.0, frac or 0.0))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        r = min(self._radius, h / 2.0)
        p.setPen(Qt.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        fw = w * self._frac
        if fw > 0:
            p.setBrush(self._fill)
            p.drawRoundedRect(QRectF(0, 0, max(fw, 2 * r), h), r, r)
        p.end()
