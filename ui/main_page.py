import os

from PySide6.QtCore import Qt, QRect, QRectF, QTimer, QMimeData, QUrl, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFontMetrics, QPixmap, QPainterPath, QDrag
)
from PySide6.QtWidgets import QWidget, QFileDialog, QApplication

from PySide6.QtCore import QEasingCurve

from core import fonts, themes, compressor
from core.i18n import tr
from core.workers import CompressWorker
from ui import anim
from ui.widgets import WindowDragMixin


def _human(n):
    """Размер файла в удобных единицах."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


class MainPage(WindowDragMixin, QWidget):
    """Главный экран: DnD-зона на одну картинку. Принял файл — сжал — положил
    результат рядом с исходником, показал экономию."""

    def __init__(self, parent, app, settings, width, height):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.width_ = width
        self.height_ = height
        self._drag_hover = False
        self._press_pos = None
        self._state = "idle"          # idle | busy | done | error
        self._busy_name = ""          # имя сжимаемого файла
        self._result = None           # dict из compressor.compress
        self._error_text = ""
        self._worker = None
        self._angle = 0.0             # спиннер busy-состояния
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(16)
        self._spin_timer.timeout.connect(self._spin_tick)
        # Авто-возврат к DnD: результат/ошибка висит несколько секунд и плавно
        # перетекает обратно в зону перетаскивания.
        self._content_alpha = 1.0
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.setInterval(5000)
        self._reset_timer.timeout.connect(self._fade_to_idle)
        # Превью до/после (маленькие пиксмапы, грузятся вне busy-пути).
        self._orig_thumb = None
        self._new_thumb = None
        self._drag_out_active = False
        self._load_theme()
        self.init_window_drag(app)
        self.setAcceptDrops(True)
        self.resize(width, height)

    def _load_theme(self):
        p = themes.palette(self.settings.get("theme", themes.DEFAULT_THEME))
        self._pal = p
        self.TITLE_COLOR = p["title"]
        self.TEXT_COLOR  = p["text"]
        self.MUTED_COLOR = p["muted"]
        self.BORDER      = p["border"]
        self.ACCENT      = p["accent"]
        self.OK          = p["ok"]
        self.ERR         = p["error"]
        self.TRACK       = p["prog_track"]

    # --- совместимость с App (пересборка страниц/relayout) -------------- #
    def relayout(self, new_h):
        self.height_ = new_h
        self.update()

    def expand_extra(self):
        return 0

    def is_busy(self):
        return self._state == "busy"

    def on_window_shown(self):
        pass

    def on_window_hidden(self):
        # Результат/ошибку сбрасываем при скрытии окна (busy не трогаем).
        if self._state in ("done", "error"):
            self._reset()

    # --- приём файла ----------------------------------------------------- #
    def _accept_path(self, path):
        if self._state == "busy":
            return
        self._reset_timer.stop()
        self._content_alpha = 1.0
        path = os.path.abspath(path or "")
        if not os.path.isfile(path):
            return
        if not compressor.is_supported(path):
            self._state = "error"
            self._error_text = tr("Unsupported file type") + "\n" + \
                tr("Images only (JPEG, PNG, WebP, GIF)")
            self.update()
            self._reset_timer.start()
            return
        self._busy_name = os.path.basename(path)
        self._state = "busy"
        self._result = None
        # Миниатюра исходника — ДО сжатия (в overwrite оригинал будет заменён).
        self._orig_thumb = self._load_thumb(path)
        self._new_thumb = None
        self._spin_timer.start()
        self.update()
        # Спиннер в трее на время сжатия.
        if self.app.tray is not None:
            self.app.tray.animator.start(spin=True)
        self._worker = CompressWorker(
            path,
            self.settings.get("compress_mode", "smart"),
            self.settings.get("output_mode", "suffix"),
            quality=int(self.settings.get("quality", 87)),
            strip=bool(self.settings.get("strip_metadata", False)),
            convert_to=self.settings.get("convert_to", "keep"),
            parent=self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _load_thumb(self, path, max_side=380):
        """Маленький пиксмап для превью (ограничен по стороне)."""
        try:
            pm = QPixmap(path)
            if pm.isNull():
                return None
            if max(pm.width(), pm.height()) > max_side:
                pm = pm.scaled(max_side, max_side, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
            return pm
        except Exception:
            return None

    def _on_done(self, result):
        self._worker = None
        self._spin_timer.stop()
        ok = bool(result.get("ok"))
        if self.app.tray is not None:
            self.app.tray.animator.finish(ok)
        if ok:
            self._state = "done"
            self._result = result
            self._new_thumb = self._load_thumb(result.get("out_path", ""))
            # Скопировать результат в буфер (как файл), если включено и есть выигрыш.
            if (self.settings.get("copy_result", False)
                    and result.get("new_size", 0) < result.get("orig_size", 0)):
                self.app.copy_file_to_clipboard(result.get("out_path"))
        else:
            self._state = "error"
            self._error_text = tr("Compression failed")
            # Лог ошибки в %APPDATA%/Shrinkr/logs (для диагностики).
            try:
                from core import logbook
                log = logbook.Log(self._busy_name)
                log.event("Compression failed")
                log.raw(str(result.get("error") or ""))
                log.save_error()
            except Exception:
                pass
        self.update()
        self._reset_timer.start()      # подержать результат и вернуться к DnD

    def _reset(self):
        self._reset_timer.stop()
        self._state = "idle"
        self._result = None
        self._error_text = ""
        self._busy_name = ""
        self._content_alpha = 1.0
        self._orig_thumb = None
        self._new_thumb = None
        self.update()

    def _fade_to_idle(self):
        """Плавный переход результата/ошибки обратно в DnD-зону: контент гаснет,
        затем DnD проявляется."""
        if self._state not in ("done", "error"):
            return
        # Курсор над окном (разглядывает превью / тянет drag-out) — не убираем.
        if self.underMouse() or self._drag_out_active:
            self._reset_timer.start()
            return

        def out_tick(v):
            self._content_alpha = 1.0 - v
            self.update()

        def out_done():
            self._state = "idle"
            self._result = None
            self._error_text = ""
            self._busy_name = ""

            def in_tick(v):
                self._content_alpha = v
                self.update()

            def in_done():
                self._content_alpha = 1.0
                self.update()
            anim.animate(self, 0.0, 1.0, 260, in_tick,
                         easing=QEasingCurve.OutCubic, on_finished=in_done,
                         attr="_fade_anim")

        anim.animate(self, 0.0, 1.0, 220, out_tick,
                     easing=QEasingCurve.InCubic, on_finished=out_done,
                     attr="_fade_anim")

    def _spin_tick(self):
        self._angle = (self._angle + 4.0) % 360
        self.update()

    def _pick_file(self):
        self.app.suppress_autohide(True)
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("Choose image"), os.path.expanduser("~"),
                "Images (*.jpg *.jpeg *.png *.webp *.gif)")
        finally:
            self.app.suppress_autohide(False)
        if path:
            self._accept_path(path)

    # --- DnD ----------------------------------------------------------- #
    def dragEnterEvent(self, e):
        if self._state != "busy" and e.mimeData().hasUrls():
            self._drag_hover = True
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drag_hover = False
        self.update()

    def dropEvent(self, e):
        self._drag_hover = False
        urls = e.mimeData().urls()
        if urls:
            # Одна картинка за раз — берём первую.
            self._accept_path(urls[0].toLocalFile())
        e.acceptProposedAction()

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Drag-out результата: в состоянии done потянули из зоны — отдаём файл
        # как перетаскивание (в Telegram/почту/проводник).
        if (self._state == "done" and (event.buttons() & Qt.LeftButton)
                and self._press_pos is not None
                and (event.position().toPoint() - self._press_pos)
                    .manhattanLength() >= QApplication.startDragDistance()
                and self._dnd_rect().contains(self._press_pos)):
            r = self._result or {}
            out = r.get("out_path", "")
            if out and os.path.isfile(out):
                self._drag_out_active = True
                drag = QDrag(self)
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(os.path.abspath(out))])
                drag.setMimeData(mime)
                if self._new_thumb is not None:
                    drag.setPixmap(self._new_thumb.scaled(
                        96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                drag.exec(Qt.CopyAction)
                self._drag_out_active = False
                self._press_pos = None
                self._reset_timer.start()     # после дропа — обычный авто-возврат
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        dragging = getattr(self, "_dragging_window", False)
        super().mouseReleaseEvent(event)
        if (dragging or event.button() != Qt.LeftButton
                or self._press_pos is None
                or (event.position().toPoint() - self._press_pos)
                    .manhattanLength() >= 6
                or not self._dnd_rect().contains(event.position().toPoint())):
            return
        if self._state == "idle":
            self._pick_file()          # клик по DnD-зоне = выбор файла
        elif self._state in ("done", "error"):
            self._reset()              # клик по результату = сжать ещё

    def _dnd_rect(self):
        s = self.app._s
        top = s(48)
        return QRect(s(16), top, self.width_ - 2 * s(16),
                     self.height_ - top - s(16))

    # --- отрисовка ----------------------------------------------------- #
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self.app._s
        pad = s(16)

        # Заголовок «Shrinkr».
        f_title = fonts.font(s(14), "Semibold")
        p.setFont(f_title)
        p.setPen(QColor(self.TITLE_COLOR))
        base = s(12) + QFontMetrics(f_title).ascent()
        p.drawText(pad, base, "Shrinkr")

        area = QRectF(self._dnd_rect())

        # Кроссфейд авто-возврата: контент состояния гаснет/проявляется.
        p.setOpacity(max(0.0, min(1.0, self._content_alpha)))
        if self._state == "busy":
            self._paint_busy(p, area, s)
        elif self._state == "done":
            self._paint_done(p, area, s)
        elif self._state == "error":
            self._paint_error(p, area, s)
        else:
            self._paint_idle(p, area, s)
        p.end()

    def _paint_idle(self, p, area, s):
        pen = QPen(QColor(self.ACCENT if self._drag_hover else self.BORDER),
                   max(1.4, s(1.6)))
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        if self._drag_hover:
            bg = QColor(self.ACCENT); bg.setAlpha(24); p.setBrush(bg)
        else:
            p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(area, s(14), s(14))
        p.setPen(QColor(self.MUTED_COLOR))
        p.setFont(fonts.font(s(12), "Regular"))
        p.drawText(area, Qt.AlignCenter, tr("Drop an image here\nor click to choose"))

    def _paint_busy(self, p, area, s):
        # Вращающееся кольцо по центру + имя файла + «Сжатие…».
        cx, cy = area.center().x(), area.center().y() - s(14)
        r = s(22)
        ring = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        track = QPen(QColor(self.TRACK), s(5))
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.setBrush(Qt.NoBrush)
        p.drawArc(ring, 0, 360 * 16)
        arc = QPen(QColor(self.ACCENT), s(5))
        arc.setCapStyle(Qt.RoundCap)
        p.setPen(arc)
        p.drawArc(ring, int(-self._angle) * 16, 110 * 16)

        p.setPen(QColor(self.TITLE_COLOR))
        f = fonts.font(s(12), "Semibold")
        p.setFont(f)
        name = QFontMetrics(f).elidedText(self._busy_name, Qt.ElideMiddle,
                                          int(area.width() - s(40)))
        p.drawText(QRectF(area.left(), cy + r + s(14), area.width(), s(20)),
                   Qt.AlignHCenter | Qt.AlignTop, name)
        p.setPen(QColor(self.MUTED_COLOR))
        p.setFont(fonts.font(s(11), "Regular"))
        p.drawText(QRectF(area.left(), cy + r + s(36), area.width(), s(18)),
                   Qt.AlignHCenter | Qt.AlignTop, tr("Compressing…"))

    def _draw_thumb(self, p, pm, cell, s):
        """Пиксмап по центру ячейки со скруглением и тонкой рамкой."""
        if pm is None:
            return
        scaled = pm.scaled(int(cell.width()), int(cell.height()),
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = cell.x() + (cell.width() - scaled.width()) / 2.0
        y = cell.y() + (cell.height() - scaled.height()) / 2.0
        rect = QRectF(x, y, scaled.width(), scaled.height())
        path = QPainterPath()
        path.addRoundedRect(rect, s(8), s(8))
        p.save()
        p.setClipPath(path)
        p.drawPixmap(rect.toRect(), scaled)
        p.restore()
        p.setPen(QPen(QColor(self.BORDER), max(1, s(1))))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, s(8), s(8))

    def _paint_done(self, p, area, s):
        r = self._result or {}
        orig = r.get("orig_size", 0)
        new = r.get("new_size", 0)
        saved = orig - new

        if saved > 0:
            pct = 100.0 * saved / max(1, orig)
            headline = f"−{pct:.0f}% ({_human(orig)} → {_human(new)})"
        else:
            headline = tr("Already optimized")
        sub = os.path.basename(r.get("out_path", ""))

        # Заголовок-результат сверху зоны.
        p.setPen(QColor(self.TITLE_COLOR))
        f = fonts.font(s(14), "Semibold")
        p.setFont(f)
        head_y = area.top() + s(10)
        p.drawText(QRectF(area.left(), head_y, area.width(), s(24)),
                   Qt.AlignHCenter | Qt.AlignTop, headline)

        # Превью до/после — две ячейки по центру.
        gap = s(14)
        top = head_y + s(36)
        bottom = area.bottom() - s(76)
        cell_h = max(s(80), bottom - top)
        cell_w = (area.width() - 3 * gap) / 2.0
        left_cell = QRectF(area.left() + gap, top, cell_w, cell_h)
        right_cell = QRectF(area.left() + 2 * gap + cell_w, top, cell_w, cell_h)
        self._draw_thumb(p, self._orig_thumb, left_cell, s)
        self._draw_thumb(p, self._new_thumb, right_cell, s)

        # Подписи размеров под превью.
        p.setFont(fonts.font(s(10), "Medium"))
        p.setPen(QColor(self.MUTED_COLOR))
        lab_y = top + cell_h + s(6)
        p.drawText(QRectF(left_cell.left(), lab_y, left_cell.width(), s(16)),
                   Qt.AlignHCenter | Qt.AlignTop,
                   f"{tr('Before')} · {_human(orig)}")
        p.setPen(QColor(self.OK if saved > 0 else self.MUTED_COLOR))
        p.drawText(QRectF(right_cell.left(), lab_y, right_cell.width(), s(16)),
                   Qt.AlignHCenter | Qt.AlignTop,
                   f"{tr('After')} · {_human(new)}")

        # Имя файла + подсказка внизу.
        p.setPen(QColor(self.TEXT_COLOR))
        f2 = fonts.font(s(11), "Regular")
        p.setFont(f2)
        sub = QFontMetrics(f2).elidedText(sub, Qt.ElideMiddle,
                                          int(area.width() - s(40)))
        p.drawText(QRectF(area.left(), lab_y + s(22), area.width(), s(18)),
                   Qt.AlignHCenter | Qt.AlignTop, sub)
        p.setPen(QColor(self.MUTED_COLOR))
        p.setFont(fonts.font(s(10), "Regular"))
        p.drawText(QRectF(area.left(), area.bottom() - s(24), area.width(), s(18)),
                   Qt.AlignHCenter | Qt.AlignTop,
                   tr("Drag the result out, or drop the next image"))

    def _paint_error(self, p, area, s):
        cx, cy = area.center().x(), area.center().y() - s(24)
        rad = s(22)
        ring = QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad)
        col = QColor(self.ERR)
        pen = QPen(col, s(5))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(ring, 0, 360 * 16)
        mark = QPen(col, s(4))
        mark.setCapStyle(Qt.RoundCap)
        p.setPen(mark)
        from PySide6.QtCore import QPointF
        k = rad * 0.45
        p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
        p.drawLine(QPointF(cx + k, cy - k), QPointF(cx - k, cy + k))

        p.setPen(QColor(self.ERR))
        p.setFont(fonts.font(s(12), "Semibold"))
        p.drawText(QRectF(area.left(), cy + rad + s(16), area.width(), s(44)),
                   Qt.AlignHCenter | Qt.AlignTop, self._error_text)
        p.setPen(QColor(self.MUTED_COLOR))
        p.setFont(fonts.font(s(10), "Regular"))
        p.drawText(QRectF(area.left(), area.bottom() - s(34), area.width(), s(18)),
                   Qt.AlignHCenter | Qt.AlignTop, tr("Compress another"))
