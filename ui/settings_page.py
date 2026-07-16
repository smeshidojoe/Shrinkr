import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QFrame, QScrollArea, QSlider

from core import fonts, themes, i18n
from core.constants import ICONS_DIR, THEMES, LANGUAGES, DEFAULT_LANGUAGE
from core.i18n import tr
from core.icons import themed_icon
from ui.widgets import (
    IconButton, LinkButton, CheckBox, SegmentedControl, Selector, WindowDragMixin,
    SmoothScroll
)


class SettingsPage(WindowDragMixin, QWidget):
    """Экран настроек: режим сжатия, режим окна, иконка трея, тема, язык."""

    MODE_TIP = ("Smart: tiny, invisible quality loss for maximum compression.\n"
                "Lossless: pixels stay identical, only the encoding is optimized.")
    USAGE_TIP = ("Pinned: the tray icon opens and closes the window.\n"
                 "Auto-hide: the tray icon opens the window; it closes\n"
                 "on Esc or when you click outside it.")
    DRAG_TIP = ("Drag the window by holding an empty area at the top.\n"
                "The position resets the next time the window is shown.")

    def __init__(self, parent, app, settings, width, height):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.width_ = width
        self.height_ = height
        self._checks = {}
        self._icon_map = {}        # {отображаемое имя: имя файла иконки трея}
        self._host = self
        self._load_theme()
        self.init_window_drag(app)
        self.resize(width, height)
        self._build()

    def _load_theme(self):
        p = themes.palette(self.settings.get("theme", themes.DEFAULT_THEME))
        self._pal = p
        self.CARD_BG       = p["card_bg"]
        self.TITLE_COLOR   = p["title"]
        self.SECTION_COLOR = p["icon"]
        self.TEXT_COLOR    = p["text"]
        self.MUTED_COLOR   = p["muted"]
        self.BORDER        = p["border"]
        self.LINK_HOVER    = p["link_hover"]
        self.CHOOSE        = p["choose"]
        self.CHOOSE_BG     = p["choose_bg"]
        self.CHOOSE_BG_H   = p["choose_bg_h"]
        self.CB_OFF        = p["cb_off"]
        self.CB_ON         = p["cb_on"]
        self.SEG_BG        = p["seg_bg"]
        self.SEG_SEL       = p["seg_sel"]
        self.ON_ACCENT     = p["on_accent"]

    # ------------------------------------------------------------------ #
    def _label(self, text, font, color, x, y):
        lbl = QLabel(text, self._host)
        lbl.setFont(font)
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        lbl.move(x, y)
        lbl.adjustSize()
        return lbl

    def _section_title(self, text, x, y):
        s = self.app._s
        self._label(text, fonts.font(s(10), "Medium"), self.SECTION_COLOR, x, y)

    def _build(self):
        s = self.app._s
        pad = s(16)
        card_w = self.width_ - 2 * pad
        self._host = self

        # --- заголовок + инфо-кнопка (статично) ------------------------- #
        self._label(tr("Settings"), fonts.font(s(14), "Semibold"),
                    self.TITLE_COLOR, pad, s(12))
        theme = self.settings.get("theme", themes.DEFAULT_THEME)
        ic_info   = themed_icon(theme, "info.png", self._pal["icon"], s(19))
        ic_info_h = themed_icon(theme, "info.png", self._pal["icon_hover"], s(19))
        info_x = self.width_ - pad - s(26)
        self.btn_about = IconButton(self, ic_info, ic_info_h, s(19),
                                    lambda: self.app.open_about("settings"))
        self.btn_about.setGeometry(info_x, s(10), s(26), s(26))

        # --- всё остальное — в прокручиваемой области -------------------- #
        area_top = s(42)
        self._build_scroll_area(area_top, pad, card_w)
        self._host = self

    def _build_scroll_area(self, top, pad, card_w):
        s = self.app._s
        area = QScrollArea(self)
        area.setWidgetResizable(False)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setFrameShape(QFrame.NoFrame)
        area.viewport().setStyleSheet("background: transparent;")
        area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }"
            f"QScrollBar::handle:vertical {{ background: {self.MUTED_COLOR};"
            "  border-radius: 3px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")
        area.setGeometry(0, top, self.width_, self.height_ - top)
        self._scroll_area = area
        self._smooth_scroll = SmoothScroll(area, parent=self)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._host = content

        y = s(2)
        # --- Сжатие ------------------------------------------------------ #
        self._section_title(tr("Compression"), pad, y)
        y += s(18)
        self._build_mode_row(pad, y)
        y += s(34) + s(6)
        self._build_quality_block(pad, y, card_w)
        y += s(30) + s(30) + s(6)
        self._build_convert_row(pad, y)
        y += s(34) + s(6)
        self._build_output_row(pad, y)
        y += s(34) + s(6)
        self._build_strip_checkbox(pad, y, card_w)
        y += s(30) + s(6)
        self._build_copy_checkbox(pad, y, card_w)
        y += s(30) + s(22)

        # --- Usage --------------------------------------------------------#
        self._section_title(tr("Usage"), pad, y)
        y += s(24)
        y += self._build_usage_card(pad, y, card_w) + s(14)
        self._build_select_row(tr("Menu Bar Icon"), pad, y, self._icon_values(),
                               self._current_icon_display(), self._on_icon_change,
                               icons=self._icon_icons())
        y += s(34)
        self._build_select_row(tr("Theme"), pad, y, list(THEMES),
                               self.settings.get("theme", THEMES[0]), self._on_theme_change)
        y += s(34)
        self._build_select_row(tr("Language"), pad, y, list(LANGUAGES),
                               self.settings.get("language", DEFAULT_LANGUAGE),
                               self._on_language_change)
        y += s(34) + s(22)

        # --- Advanced ----------------------------------------------------- #
        self._section_title(tr("Advanced"), pad, y)
        y += s(18)
        self._build_update_checkbox(pad, y, card_w)
        y += s(30) + s(6)
        self._build_context_menu_checkbox(pad, y, card_w)
        y += s(30) + s(6)
        self._build_autostart_checkbox(pad, y, card_w)
        y += s(30) + s(12)
        self._build_reset_button(pad, y, card_w)
        y += s(32) + s(30)

        content.resize(self.width_, y)
        area.setWidget(content)

    # --- строки блоков ------------------------------------------------- #
    def _build_mode_row(self, x, y):
        s = self.app._s
        rh = s(30)
        lbl = self._label(tr("Mode"), fonts.font(s(12), "Medium"),
                          self.TEXT_COLOR, x, y + s(6))
        lbl.setToolTip(tr(self.MODE_TIP))
        seg_w = s(210)
        seg = SegmentedControl(
            self._host, [(tr("Smart"), "smart"), (tr("Lossless"), "lossless")],
            self.settings.get("compress_mode", "smart"), fonts.font(s(11), "Medium"),
            self.SEG_BG, self.SEG_SEL, self.MUTED_COLOR, self.ON_ACCENT, s(9))
        seg.setGeometry(self.width_ - x - seg_w, y, seg_w, rh)
        seg.setToolTip(tr(self.MODE_TIP))
        seg.changed.connect(lambda v: self._set_value("compress_mode", v))
        self._mode_seg = seg

    # Пресеты качества: подпись -> значение слайдера.
    _QUALITY_PRESETS = [("Max", 92), ("Balanced", 87), ("Small", 78)]

    def _build_quality_block(self, x, y, card_w):
        """Строка «Quality»: пресеты справа, ниже — слайдер со значением.
        Влияет только на режим Smart (lossless качество не трогает)."""
        s = self.app._s
        rh = s(30)
        self._label(tr("Quality"), fonts.font(s(12), "Medium"),
                    self.TEXT_COLOR, x, y + s(6))
        # Сегменты пресетов + «Custom».
        seg_w = s(280)
        cur_q = int(self.settings.get("quality", 87))
        preset_value = next((str(val) for lbl, val in self._QUALITY_PRESETS
                             if val == cur_q), "custom")
        options = [(tr(lbl), str(val)) for lbl, val in self._QUALITY_PRESETS]
        options.append((tr("Custom"), "custom"))
        seg = SegmentedControl(
            self._host, options, preset_value, fonts.font(s(11), "Medium"),
            self.SEG_BG, self.SEG_SEL, self.MUTED_COLOR, self.ON_ACCENT, s(9))
        seg.setGeometry(self.width_ - x - seg_w, y, seg_w, rh)
        seg.changed.connect(self._on_quality_preset)
        self._quality_seg = seg

        # Слайдер (следующая строка) + числовое значение справа.
        sl_y = y + rh + s(4)
        val_w = s(34)
        sl = QSlider(Qt.Horizontal, self._host)
        sl.setMinimum(60)
        sl.setMaximum(95)
        sl.setValue(cur_q)
        sl.setStyleSheet(
            "QSlider::groove:horizontal { height: %dpx; background: %s; border-radius: %dpx; }"
            % (s(4), self._pal["field_bg"], s(2)) +
            "QSlider::sub-page:horizontal { background: %s; border-radius: %dpx; }"
            % (self.SEG_SEL, s(2)) +
            "QSlider::handle:horizontal { width: %dpx; height: %dpx; margin: -%dpx 0; "
            "background: %s; border-radius: %dpx; }"
            % (s(14), s(14), s(5), self.SEG_SEL, s(7)))
        sl.setGeometry(x, sl_y + s(4), card_w - val_w - s(8), s(18))
        self._quality_val = QLabel(str(cur_q), self._host)
        self._quality_val.setFont(fonts.font(s(11), "Medium"))
        self._quality_val.setStyleSheet(
            f"color: {self.MUTED_COLOR}; background: transparent;")
        self._quality_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._quality_val.setGeometry(x + card_w - val_w, sl_y, val_w, s(26))
        sl.valueChanged.connect(self._on_quality_slider)
        self._quality_slider = sl

    def _on_quality_preset(self, value):
        if value == "custom":
            return                       # «Custom» сам по себе ничего не меняет
        self._quality_slider.setValue(int(value))   # -> _on_quality_slider

    def _on_quality_slider(self, v):
        self._quality_val.setText(str(v))
        self.app.set_quality(v)
        # Подсветить пресет, если значение совпало, иначе «Custom».
        match = next((str(val) for _, val in self._QUALITY_PRESETS if val == v),
                     "custom")
        self._quality_seg.setValue(match)

    def _build_convert_row(self, x, y):
        from core import compressor
        values = [tr("Keep format"), "WebP"]
        self._convert_map = {tr("Keep format"): "keep", "WebP": "webp"}
        if compressor.HAVE_AVIF:
            values.append("AVIF")
            self._convert_map["AVIF"] = "avif"
        cur = self.settings.get("convert_to", "keep")
        cur_label = next((k for k, v in self._convert_map.items() if v == cur),
                         tr("Keep format"))
        self._build_select_row(tr("Convert to"), x, y, values, cur_label,
                               self._on_convert_change)

    def _on_convert_change(self, label):
        self.app.set_convert_to(self._convert_map.get(label, "keep"))

    def _build_strip_checkbox(self, x, y, card_w):
        s = self.app._s
        cb = CheckBox(self._host, tr("Strip metadata"), fonts.font(s(12), "Regular"),
                      self.TEXT_COLOR, self.CB_OFF, self.CB_ON, s(17), s(5))
        cb.setChecked(bool(self.settings.get("strip_metadata", False)))
        cb.setGeometry(x, y, card_w, s(30))
        cb.setToolTip(tr("Removes EXIF (camera, GPS) and auxiliary chunks.\n"
                         "Smaller files; color profile is kept when possible."))
        cb.toggled.connect(self.app.set_strip_metadata)
        self._checks["strip_metadata"] = cb

    def _build_output_row(self, x, y):
        s = self.app._s
        rh = s(30)
        self._label(tr("Output"), fonts.font(s(12), "Medium"),
                    self.TEXT_COLOR, x, y + s(6))
        seg_w = s(280)
        seg = SegmentedControl(
            self._host, [(tr("Next to original"), "suffix"),
                         (tr("Overwrite original"), "overwrite")],
            self.settings.get("output_mode", "suffix"), fonts.font(s(11), "Medium"),
            self.SEG_BG, self.SEG_SEL, self.MUTED_COLOR, self.ON_ACCENT, s(9))
        seg.setGeometry(self.width_ - x - seg_w, y, seg_w, rh)
        seg.changed.connect(lambda v: self._set_value("output_mode", v))
        self._output_seg = seg

    def _build_copy_checkbox(self, x, y, card_w):
        s = self.app._s
        cb = CheckBox(self._host, tr("Copy result to clipboard"),
                      fonts.font(s(12), "Regular"),
                      self.TEXT_COLOR, self.CB_OFF, self.CB_ON, s(17), s(5))
        cb.setChecked(bool(self.settings.get("copy_result", False)))
        cb.setGeometry(x, y, card_w, s(30))
        cb.toggled.connect(self.app.set_copy_result)
        self._checks["copy_result"] = cb

    def _build_usage_card(self, x, y, card_w):
        s = self.app._s
        card_h = s(38)   # повыше — чтобы пилюля segmented могла «выходить» за блок
        card = QFrame(self._host)
        card.setGeometry(x, y, card_w, card_h)
        card.setStyleSheet("background: transparent;")

        seg_w = card_w // 2 - s(6)
        seg = SegmentedControl(
            card,
            [(tr("Pinned"), "toggle"), (tr("Auto-hide"), "focus")],
            self.settings.get("usage_mode", "toggle"),
            fonts.font(s(11), "Medium"),
            self.SEG_BG, self.SEG_SEL,
            self.MUTED_COLOR, self.ON_ACCENT, s(9)
        )
        seg.setGeometry(0, 0, seg_w, card_h)
        seg.setToolTip(tr(self.USAGE_TIP))
        seg.changed.connect(self.app.set_usage_mode)
        self._usage_seg = seg

        drag_x = card_w // 2 + s(8)
        cb = CheckBox(card, tr("Allow Dragging"), fonts.font(s(12), "Regular"),
                      self.TEXT_COLOR, self.CB_OFF, self.CB_ON, s(17), s(5))
        cb.setChecked(bool(self.settings.get("allow_dragging", False)))
        cb.setGeometry(drag_x, 0, card_w - drag_x, card_h)
        cb.setToolTip(tr(self.DRAG_TIP))
        cb.toggled.connect(self.app.set_allow_dragging)
        self._checks["allow_dragging"] = cb

        return card_h

    def _build_update_checkbox(self, x, y, card_w):
        s = self.app._s
        cb = CheckBox(self._host, tr("Notify about updates"), fonts.font(s(12), "Regular"),
                      self.TEXT_COLOR, self.CB_OFF, self.CB_ON, s(17), s(5))
        cb.setChecked(bool(self.settings.get("update_notify", True)))
        cb.setGeometry(x, y, card_w, s(30))
        cb.toggled.connect(self.app.set_update_notify)
        self._checks["update_notify"] = cb

    def _build_context_menu_checkbox(self, x, y, card_w):
        s = self.app._s
        cb = CheckBox(self._host, tr("Explorer context menu"),
                      fonts.font(s(12), "Regular"),
                      self.TEXT_COLOR, self.CB_OFF, self.CB_ON, s(17), s(5))
        cb.setChecked(bool(self.settings.get("context_menu", False)))
        cb.setGeometry(x, y, card_w, s(30))
        cb.setToolTip(tr("Adds “Compress with Shrinkr” to the right-click\n"
                         "menu of images in Explorer."))
        cb.toggled.connect(self.app.set_context_menu)
        self._checks["context_menu"] = cb

    def _build_autostart_checkbox(self, x, y, card_w):
        s = self.app._s
        cb = CheckBox(self._host, tr("Launch at startup"), fonts.font(s(12), "Regular"),
                      self.TEXT_COLOR, self.CB_OFF, self.CB_ON, s(17), s(5))
        cb.setChecked(bool(self.settings.get("autostart", False)))
        cb.setGeometry(x, y, card_w, s(30))
        cb.toggled.connect(self.app.set_autostart)
        self._checks["autostart"] = cb

    def _build_reset_button(self, x, y, card_w):
        """Open Logs Folder + Reset Settings — две кнопки одинаковой ширины в один
        ряд, с равными отступами от краёв блока и друг от друга (три равных зазора)."""
        s = self.app._s
        font = fonts.font(s(11), "Semibold")
        bh = s(32)
        gap = s(12)
        bw = (card_w - 3 * gap) // 2
        logs_x = x + gap
        reset_x = x + 2 * gap + bw
        self.btn_logs = LinkButton(
            self._host, tr("Open Logs Folder"), font, self.CHOOSE, self.LINK_HOVER,
            self.app.open_logs_folder, hover_bg=self.CHOOSE_BG_H, radius=s(6),
            base_bg=self.CHOOSE_BG)
        self.btn_logs.setGeometry(logs_x, y, bw, bh)
        self._reset_armed = False
        self.btn_reset = LinkButton(
            self._host, tr("Reset Settings"), font, self._pal["error"], self.LINK_HOVER,
            self._on_reset_click, hover_bg=self.CHOOSE_BG_H, radius=s(6),
            base_bg=self.CHOOSE_BG)
        self.btn_reset.setGeometry(reset_x, y, bw, bh)

    def _on_reset_click(self):
        # Двухступенчатое подтверждение: первый клик взводит («Confirm»),
        # второй в течение пары секунд — выполняет сброс.
        from PySide6.QtCore import QTimer
        if not self._reset_armed:
            self._reset_armed = True
            self.btn_reset.setText(tr("Confirm"))
            QTimer.singleShot(2600, self._disarm_reset)
            return
        self._reset_armed = False
        self.app.reset_and_restart()

    def _disarm_reset(self):
        if not self._reset_armed:
            return
        self._reset_armed = False
        try:
            self.btn_reset.setText(tr("Reset Settings"))
        except RuntimeError:
            pass

    def _build_select_row(self, label, x, y, values, current, command, icons=None):
        s = self.app._s
        menu_w = s(140)
        lbl = QLabel(label, self._host)
        lbl.setFont(fonts.font(s(12), "Medium"))
        lbl.setStyleSheet(f"color: {self.TEXT_COLOR}; background: transparent;")
        lbl.move(x, y + s(5))
        lbl.adjustSize()
        combo = Selector(self._host, fonts.font(s(11), "Regular"),
                         self._pal["card_bg"], self._pal["sel_chip"], self.TEXT_COLOR,
                         self._pal["sel_chevron"], s(7), s(22),
                         accent=self._pal["seg_sel"], border=self._pal["border"],
                         on_accent=self._pal["on_accent"])
        for v in values:
            combo.add_item(v, icons.get(v) if icons else None)
        if current in values:
            combo.set_current(current)
        combo.setGeometry(self.width_ - x - menu_w, y, menu_w, s(26))
        combo.changed.connect(command)
        return combo

    # --- иконка трея / тема / язык -------------------------------------- #
    def _icon_values(self):
        self._icon_map = {}
        names = []
        if os.path.isdir(ICONS_DIR):
            for fname in sorted(os.listdir(ICONS_DIR)):
                stem, ext = os.path.splitext(fname)
                if ext.lower() in (".png", ".ico"):
                    disp = stem.replace("_", " ").title()
                    self._icon_map[disp] = stem
                    names.append(disp)
        if not names:
            self._icon_map["Default"] = ""
            names = ["Default"]
        return names

    def _icon_icons(self):
        from core import tools
        from core.icons import tint_pixmap, raw_pixmap, COLORED_ICONS
        color = "#000000" if tools.windows_uses_light_theme() else "#ffffff"
        result = {}
        for disp, stem in self._icon_map.items():
            if stem:
                path = os.path.join(ICONS_DIR, stem + ".png")
                pm = raw_pixmap(path, 48) if stem in COLORED_ICONS else tint_pixmap(path, color, 48)
                if pm is not None:
                    result[disp] = pm
        return result

    def _current_icon_display(self):
        stem = self.settings.get("tray_icon", "")
        for disp, st in self._icon_map.items():
            if st == stem:
                return disp
        return next(iter(self._icon_map), "Default")

    def _on_icon_change(self, choice):
        stem = self._icon_map.get(choice, "")
        self.settings["tray_icon"] = stem
        if self.app.tray is not None:
            self.app.tray.set_icon(stem)
        self.app.save_settings()

    def _on_theme_change(self, choice):
        if choice == self.settings.get("theme"):
            return
        self.settings["theme"] = choice
        self.app.save_settings()
        self.app.apply_appearance()

    def _on_language_change(self, choice):
        if choice == self.settings.get("language"):
            return
        self.settings["language"] = choice
        i18n.set_language(choice)
        self.app.save_settings()
        self.app.apply_appearance()

    def _set_value(self, key, value):
        self.settings[key] = value
        self.app.save_settings()
