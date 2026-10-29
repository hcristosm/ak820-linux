#!/usr/bin/env python3
"""Qt GUI for ak820.py: effects, per-key colors, screen image and clock."""
import json, os, sys, threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QSlider, QStackedWidget, QVBoxLayout,
                               QWidget)

import ak820

# keyboard drawing: rows break after ak820.ROW_ENDS; widths in key units (default 1)
WIDTH = dict(backspace=2, tab=1.5, backslash=1.5, capslock=1.75, enter=2.25, lshift=2.25, rshift=1.75,
             lctrl=1.25, win=1.25, lalt=1.25, space=6.25)
LABEL = dict(grave="`", minus="-", equal="=", lbracket="[", rbracket="]", backslash="\\", semicolon=";",
             quote="'", comma=",", period=".", slash="/", up="↑", down="↓", left="←", right="→",
             backspace="Back", capslock="Caps", lshift="Shift", rshift="Shift", lctrl="Ctrl",
             rctrl="Ctrl", lalt="Alt", ralt="Alt", delete="Del", pgup="PgUp", pgdn="PgDn")
U, GAP, PAD = 40, 3, 12  # pixels per key unit, gap between keys, keyboard card padding
FITS = ("crop", "pad")
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "ak820", "config.json")

BG, SURFACE, FG, ACCENT = "#16181d", "#1f2229", "#e6e6e6", "#22d3ee"
HOVER, LINE, MUTED = "#2a2e37", "#2e323b", "#8a8f98"
QSS = f"""
QWidget {{ background: {BG}; color: {FG}; font-size: 10pt; }}
QLabel, QCheckBox, QRadioButton, QSlider {{ background: transparent; }}
QLabel#title {{ font-size: 18pt; font-weight: bold; }}
QLabel#brand {{ font-size: 14pt; font-weight: bold; color: {ACCENT}; padding: 4px 8px 12px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#preview {{ background: black; border-radius: 12px; }}
QFrame#side, QFrame#card {{ background: {SURFACE}; }}
QFrame#card {{ border-radius: 12px; }}
QListWidget {{ background: transparent; border: none; outline: 0; font-size: 11pt; }}
QListWidget::item {{ padding: 10px; border-radius: 8px; }}
QListWidget::item:hover {{ background: {HOVER}; }}
QListWidget::item:selected {{ background: {BG}; color: {ACCENT}; }}
QPushButton {{ background: {HOVER}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {BG}; border: 2px solid {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {SURFACE}; }}
QPushButton#accent {{ background: {ACCENT}; color: {BG}; border: none; font-weight: bold; padding: 8px 22px; }}
QPushButton#accent:hover {{ background: #67e8f9; }}
QPushButton#mode {{ min-height: 44px; }}
QPushButton#key {{ padding: 0; border-radius: 6px; font-size: 8pt; }}
QPushButton#swatch {{ min-width: 44px; max-width: 44px; min-height: 26px; max-height: 26px; padding: 0; }}
QFrame#side QPushButton {{ padding: 6px 4px; }}
QComboBox {{ background: {BG}; border: 1px solid {LINE}; border-radius: 8px; padding: 5px 8px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; selection-background-color: {ACCENT}; selection-color: {BG}; }}
QSlider::groove:horizontal {{ height: 6px; background: {LINE}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::sub-page:horizontal:disabled {{ background: {LINE}; }}
QSlider::handle:horizontal {{ background: {FG}; width: 16px; margin: -5px 0; border-radius: 8px; }}
QSlider::handle:horizontal:disabled {{ background: {MUTED}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {MUTED}; background: {BG}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: {LINE}; }}
QCheckBox::indicator:checked:disabled {{ background: {MUTED}; border-color: {MUTED}; }}
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {{ color: {MUTED}; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; }}
QProgressBar {{ background: {LINE}; border: none; border-radius: 4px; max-height: 8px; min-width: 160px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
"""


def hexs(rgb):
    return "#%02x%02x%02x" % rgb


def load_config(path):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except OSError:
        return {}
    except ValueError:
        cfg = None
    if isinstance(cfg, dict):
        return cfg
    os.replace(path, path + ".bad")  # keep a broken file aside instead of overwriting the user's profiles
    return {}


def save_config(cfg, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(path + ".tmp", path)  # never leave a half-written config


def hbox(*widgets):
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        h.addWidget(w)
    h.addStretch()
    return h


def card(layout):
    f = QFrame(objectName="card")
    layout.addWidget(f)
    return f


def slider(value):
    s = QSlider(Qt.Horizontal, minimum=0, maximum=5, value=value)
    s.setFixedWidth(240)
    n = QLabel(str(value))
    s.valueChanged.connect(n.setNum)
    return s, n


def swatch(btn, rgb):
    btn.setStyleSheet(f"QPushButton {{ background: {hexs(rgb)}; }} QPushButton:disabled {{ background: {LINE}; }}")


class App(QMainWindow):
    done, progress, denied = Signal(str), Signal(int), Signal(str)  # worker thread -> UI

    def __init__(self, cfg_path=CONFIG):
        super().__init__()
        app = QApplication.instance()
        app.setApplicationName("ak820")  # X11 WM_CLASS; must match StartupWMClass in ak820.desktop
        app.setDesktopFileName("ak820")  # Wayland app_id, same purpose
        app.setStyle("Fusion")  # same look on every desktop; QSS does the rest
        app.setStyleSheet(QSS)
        pal = app.palette()  # Fusion draws the combobox arrow with these
        pal.setColor(QPalette.Button, QColor(BG))
        pal.setColor(QPalette.ButtonText, QColor(FG))
        app.setPalette(pal)
        self.busy, self.lighting, self.music_stop = False, "effect", None
        self.cfg_path, self.cfg = cfg_path, load_config(cfg_path)
        if not isinstance(self.cfg.get("profiles"), dict):
            self.cfg["profiles"] = {}
        self.setWindowTitle(f"AJAZZ AK820 Pro {ak820.__version__}")

        side = QFrame(objectName="side")
        side.setFixedWidth(200)
        sv = QVBoxLayout(side)
        sv.addWidget(QLabel("◆ AK820 Pro", objectName="brand"))
        self.nav, self.stack = QListWidget(), QStackedWidget()
        sv.addWidget(self.nav)
        for nav, title, fill, action, slot in (
                ("✦  Effects", "Effects", self.fill_effects, "Apply", self.apply_effect),
                ("⌨  Per-key colors", "Per-key colors", self.fill_keys, "Apply", self.apply_keys),
                ("▣  Screen", "Screen", self.fill_screen, "Send to screen", self.apply_screen),
                ("◷  Clock", "Clock", self.fill_clock, "Sync now", self.sync_clock),
                ("♫  Music", "Music", self.fill_music, "Start", self.toggle_music)):
            self.nav.addItem(nav)
            self.stack.addWidget(self.page(title, fill, action, slot))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        sv.addWidget(QLabel("Profile", objectName="muted"))
        self.profile = QComboBox(editable=True)
        self.profile.lineEdit().setPlaceholderText("name")
        sv.addWidget(self.profile)
        row = QHBoxLayout()
        for txt, slot in (("Load", self.load_profile), ("Save", self.save_profile), ("Delete", self.delete_profile)):
            b = QPushButton(txt)
            b.clicked.connect(slot)
            row.addWidget(b)
        sv.addLayout(row)

        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(body)

        self.bar = QProgressBar(textVisible=False)
        self.statusBar().addPermanentWidget(self.bar)
        self.done.connect(self.finish)
        self.denied.connect(self.offer_setup)
        self.progress.connect(self.bar.setValue)
        self.say("Ready.")
        self.refresh_profiles()
        if "last" in self.cfg:
            try:
                self.set_state(self.cfg["last"])
            except Exception as e:  # a bad hand-edited value must not stop the app from opening
                self.say(f"Ignored saved settings: {e}")

    def page(self, title, fill, action, slot):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(14)
        v.addWidget(QLabel(title, objectName="title"))
        fill(v)
        v.addStretch()
        b = QPushButton(action, objectName="accent")
        b.clicked.connect(slot)
        v.addWidget(b, alignment=Qt.AlignRight)
        return w

    def say(self, msg):
        self.statusBar().showMessage(msg)

    # --- settings: "last" is restored on start, profiles are named snapshots of the same state ---
    def get_state(self):
        return dict(mode=self.mode_id(), rainbow=self.rainbow.isChecked(), color=hexs(self.color),
                    brightness=self.bright.value(), speed=self.speed.value(), direction=self.dir_group.checkedId(),
                    keys={n: hexs(c) for n, c in self.key_colors.items()}, key_brightness=self.key_bright.value(),
                    lighting=self.lighting, image=self.image_path, fit=self.fit(),
                    music=dict(style=self.music_style.checkedId(), palette=self.music_pal.checkedId(),
                               colors=[hexs(c) for c in self.music_colors], sensitivity=self.music_sens.value()))

    def set_state(self, st):
        (self.modes.button(st.get("mode", 11)) or self.modes.button(11)).setChecked(True)
        self.rainbow.setChecked(st.get("rainbow", True))
        self.color = ak820.hexrgb(st.get("color", "#ff0000"))
        swatch(self.color_btn, self.color)
        self.bright.setValue(st.get("brightness", 5))
        self.speed.setValue(st.get("speed", 3))
        self.dir_group.button(1 if st.get("direction") == 1 else 0).setChecked(True)
        self.key_bright.setValue(st.get("key_brightness", 5))
        for n, c in st.get("keys", {}).items():
            if n in self.keys:
                self.paint_key(n, ak820.hexrgb(c))
        self.lighting = st.get("lighting", "effect")
        self.fit_group.button(FITS.index(st["fit"]) if st.get("fit") in FITS else 0).setChecked(True)
        img = st.get("image")
        self.image_path = img if img and os.path.exists(img) else None
        self.show_preview()
        self.update_effect_controls()
        m = st.get("music", {})
        (self.music_style.button(m.get("style", 0)) or self.music_style.button(0)).setChecked(True)
        (self.music_pal.button(m.get("palette", 0)) or self.music_pal.button(0)).setChecked(True)
        if len(m.get("colors", ())) == 2:
            self.music_colors = [ak820.hexrgb(c) for c in m["colors"]]
        self.music_sens.setValue(m.get("sensitivity", 2))
        self.update_music_opts()

    def persist(self):
        self.cfg["last"] = self.get_state()
        save_config(self.cfg, self.cfg_path)

    def closeEvent(self, e):
        if self.music_stop:
            self.music_stop.set()
        self.persist()
        super().closeEvent(e)

    def refresh_profiles(self, name=""):
        self.profile.clear()
        self.profile.addItems(sorted(self.cfg["profiles"]))
        self.profile.setCurrentText(name)

    def save_profile(self):
        name = self.profile.currentText().strip()
        if not name:
            return self.say("Type a profile name first.")
        self.cfg["profiles"][name] = self.get_state()
        self.persist()
        self.refresh_profiles(name)
        self.say(f"Profile '{name}' saved.")

    def load_profile(self):
        st = self.cfg["profiles"].get(self.profile.currentText())
        if not st:
            return self.say("Pick a saved profile.")
        self.set_state(st)
        (self.apply_keys if self.lighting == "keys" else self.apply_effect)()  # screen is not re-sent (slow)

    def delete_profile(self):
        name = self.profile.currentText()
        if name in self.cfg["profiles"] and QMessageBox.question(
                self, "Delete profile", f"Delete profile '{name}'?") == QMessageBox.Yes:
            del self.cfg["profiles"][name]
            self.persist()
            self.refresh_profiles()

    def pick_color(self, rgb, title):
        c = QColorDialog.getColor(QColor(*rgb), self, title)
        return c.getRgb()[:3] if c.isValid() else None

    # --- device work runs in a thread; results come back through the done/progress signals ---
    def run(self, label, fn):
        if self.busy:
            return
        self.busy = True
        self.say(label + "…")
        self.bar.setValue(0)

        def work():
            try:
                kb = ak820.Kbd()
                try:
                    fn(kb)
                finally:
                    os.close(kb.fd)
                    kb.lcd is not None and os.close(kb.lcd)
                msg = label + ": done."
            except ak820.NoPermission as e:
                return self.denied.emit(str(e))
            except (SystemExit, Exception) as e:  # find_hidraw exits with a message when the keyboard is missing
                msg = f"Error: {e}"
            self.done.emit(msg)

        threading.Thread(target=work, daemon=True).start()

    def offer_setup(self, msg):
        self.finish(f"Error: {msg}")
        if QMessageBox.question(self, "Keyboard access",
                                "Your user is not allowed to open the keyboard yet.\n\nInstall the udev rule that "
                                "allows it? You will be asked for your password.") != QMessageBox.Yes:
            return
        self.busy = True
        self.say("Setting up keyboard access…")

        def work():
            try:
                ak820.setup()
                msg = "Keyboard access set up. Try again (unplug and replug the keyboard if it still fails)."
            except (SystemExit, Exception) as e:
                msg = f"Error: {e}"
            self.done.emit(msg)

        threading.Thread(target=work, daemon=True).start()

    def finish(self, msg):
        if self.music_stop:
            self.music_stop = None
            self.music_btn.setText("Start")
        self.busy = False
        self.bar.setValue(100)
        self.say(msg)

    # --- Effects ---
    def fill_effects(self, v):
        grid = QGridLayout()
        grid.setSpacing(8)
        v.addLayout(grid)
        self.modes = QButtonGroup(self)
        for i, (name, _) in ak820.MODES.items():
            b = QPushButton(name.title(), objectName="mode", checkable=True)
            self.modes.addButton(b, i)
            grid.addWidget(b, i // 5, i % 5)
        self.modes.button(11).setChecked(True)  # vendor default_mode="11"
        self.modes.buttonClicked.connect(lambda _: self.update_effect_controls())

        self.color = (255, 0, 0)
        self.color_btn = QPushButton(objectName="swatch")
        swatch(self.color_btn, self.color)
        self.color_btn.clicked.connect(self.pick_effect_color)
        self.rainbow = QCheckBox("Rainbow", checked=True)
        self.rainbow.toggled.connect(lambda _: self.update_effect_controls())
        self.bright, bn = slider(5)
        self.speed, sn = slider(3)
        self.dir_group = QButtonGroup(self)
        for i, t in enumerate(("→ / ↓", "← / ↑")):
            self.dir_group.addButton(QPushButton(t, checkable=True), i)
        self.dir_group.button(0).setChecked(True)

        form = QGridLayout(card(v))
        form.setContentsMargins(18, 16, 18, 16)
        form.setVerticalSpacing(12)
        for r, (txt, row) in enumerate((("Color", hbox(self.color_btn, self.rainbow)),
                                        ("Brightness", hbox(self.bright, bn)), ("Speed", hbox(self.speed, sn)),
                                        ("Direction", hbox(*self.dir_group.buttons())))):
            form.addWidget(QLabel(txt), r, 0)
            form.addLayout(row, r, 1)
        self.update_effect_controls()

    def mode_id(self):
        return self.modes.checkedId()

    def update_effect_controls(self):
        flags = ak820.MODES[self.mode_id()][1]
        self.rainbow.setEnabled(bool(flags & 0x20))
        self.color_btn.setEnabled(bool(flags & 0x10 and not (flags & 0x20 and self.rainbow.isChecked())))
        self.bright.setEnabled(bool(flags & 0x01))
        self.speed.setEnabled(bool(flags & 0x02))
        for b in self.dir_group.buttons():
            b.setEnabled(bool(flags & 0x0C))  # 0x04 horizontal, 0x08 vertical (Scrolling)

    def pick_effect_color(self):
        c = self.pick_color(self.color, "Effect color")
        if c:
            self.color = c
            swatch(self.color_btn, c)

    def apply_effect(self):
        mode, flags = self.mode_id(), ak820.MODES[self.mode_id()][1]
        rgb = None if (flags & 0x20 and self.rainbow.isChecked()) or not flags & 0x10 else self.color
        args = (mode, rgb, self.bright.value(), self.speed.value(), self.dir_group.checkedId())
        self.lighting = "effect"
        self.run("Effect " + ak820.MODES[mode][0], lambda kb: kb.set_mode(*args))

    # --- Per-key colors ---
    def fill_keys(self, v):
        self.paint = (255, 0, 0)
        self.key_colors = {}
        self.paint_btn = QPushButton(objectName="swatch")
        swatch(self.paint_btn, self.paint)
        self.paint_btn.clicked.connect(self.pick_paint)
        all_btn = QPushButton("Paint all")
        all_btn.clicked.connect(self.paint_all)
        self.key_bright, kn = slider(5)
        v.addLayout(hbox(QLabel("Brush"), self.paint_btn, all_btn, QLabel("   Brightness"), self.key_bright, kn))

        board = card(v)
        board.setFixedSize(16 * U + GAP + 2 * PAD, 6 * U + GAP + 2 * PAD)
        self.keys = {}
        x = y = 0
        for name in ak820.KEYS:
            w = WIDTH.get(name, 1) * U
            b = QPushButton(LABEL.get(name, name.upper() if len(name) == 1 else name.title()), board,
                            objectName="key")
            b.setGeometry(int(PAD + x + GAP), PAD + y + GAP, int(w - GAP), U - GAP)
            b.clicked.connect(lambda _=False, n=name: self.paint_key(n))
            self.keys[name] = b
            self.paint_key(name, (0, 0, 0))
            x += w
            if name in ak820.ROW_ENDS:
                x, y = 0, y + U
        v.addWidget(QLabel("Click a key to paint it with the brush color.", objectName="muted"))

    def pick_paint(self):
        c = self.pick_color(self.paint, "Brush color")
        if c:
            self.paint = c
            swatch(self.paint_btn, c)

    def paint_key(self, name, color=None):
        color = color or self.paint
        self.key_colors[name] = color
        self.keys[name].setStyleSheet(f"background: {hexs(color)}; color: {'black' if sum(color) > 380 else 'white'};")

    def paint_all(self):
        for name in self.keys:
            self.paint_key(name)

    def apply_keys(self):
        colors = {ak820.KEYS[n]: c for n, c in self.key_colors.items()}
        b = self.key_bright.value()
        self.lighting = "keys"
        self.run("Per-key colors", lambda kb: kb.set_keys(colors, b))

    # --- Screen ---
    def fill_screen(self, v):
        self.image_path = None
        pick = QPushButton("Choose image or GIF…")
        pick.clicked.connect(self.pick_image)
        self.image_lbl = QLabel("No file selected", objectName="muted")
        v.addLayout(hbox(pick, self.image_lbl))
        self.preview = QLabel(objectName="preview", alignment=Qt.AlignCenter)
        self.preview.setFixedSize(256, 256)
        v.addWidget(self.preview)
        self.fit_group = QButtonGroup(self)
        for i, t in enumerate(("Crop to fill", "Fit with borders")):
            self.fit_group.addButton(QRadioButton(t), i)
        self.fit_group.button(0).setChecked(True)
        self.fit_group.buttonClicked.connect(lambda _: self.show_preview())
        v.addLayout(hbox(*self.fit_group.buttons()))

    def fit(self):
        return FITS[self.fit_group.checkedId()]

    def pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose image or GIF", "",
                                           "Images (*.gif *.png *.jpg *.jpeg *.bmp *.webp);;All files (*)")
        if p:
            self.image_path = p
            self.show_preview()

    def show_preview(self):
        if not self.image_path:
            self.preview.clear()
            return self.image_lbl.setText("No file selected")
        from PIL import Image, ImageOps
        try:
            im = Image.open(self.image_path)
            n = getattr(im, "n_frames", 1)
            first = im.convert("RGB")
        except OSError as e:  # includes PIL.UnidentifiedImageError
            self.image_path = None
            self.say(f"Can't open image: {e}")
            return self.show_preview()
        first = ImageOps.fit(first, (128, 128)) if self.fit() == "crop" else ImageOps.pad(first, (128, 128))
        data = first.tobytes()  # must outlive the QImage until fromImage copies it
        self.preview.setPixmap(QPixmap.fromImage(QImage(data, 128, 128, 384, QImage.Format_RGB888)).scaled(256, 256))
        extra = f" (only the first {ak820.MAX_FRAMES} will be sent)" if n > ak820.MAX_FRAMES else ""
        self.image_lbl.setText(f"{os.path.basename(self.image_path)} — {n} frame(s){extra}")

    def apply_screen(self):
        if not self.image_path:
            return self.say("Choose an image first.")
        path, fit = self.image_path, self.fit()

        def job(kb):
            blob = ak820.screen_blob(ak820.load_frames(path, fit))
            kb.upload_screen(blob, lambda i, n: self.progress.emit(int(100 * i / n)))
        self.run("Screen upload", job)

    # --- Clock ---
    def fill_clock(self, v):
        v.addWidget(QLabel("Sets the keyboard screen clock to this computer's time.", objectName="muted"))

    def sync_clock(self):
        self.run("Clock", lambda kb: kb.sync_time())

    # --- Music ---
    def fill_music(self, v):
        v.addWidget(QLabel("Lights the keys to whatever this computer is playing.\n"
                           "Your saved effect comes back by itself when you stop.", objectName="muted"))
        self.music_style, self.music_pal = QButtonGroup(self), QButtonGroup(self)
        for i, name in enumerate(ak820.STYLES):
            self.music_style.addButton(QPushButton(name.title(), checkable=True), i)
        for i, t in enumerate(("Classic", "Rainbow", "Custom")):
            self.music_pal.addButton(QRadioButton(t), i)
        self.music_style.button(0).setChecked(True)
        self.music_pal.button(0).setChecked(True)
        self.music_colors = [(0, 255, 255), (255, 0, 255)]
        self.music_swatches = [QPushButton(objectName="swatch") for _ in range(2)]
        for i, b in enumerate(self.music_swatches):
            swatch(b, self.music_colors[i])
            b.clicked.connect(lambda _=False, i=i: self.pick_music_color(i))
        self.music_sens, n = slider(2)
        form = QGridLayout(card(v))
        form.setContentsMargins(18, 16, 18, 16)
        form.setVerticalSpacing(12)
        colors_row = hbox(*self.music_pal.buttons(), *self.music_swatches)
        colors_row.setSpacing(12)  # radio labels otherwise touch the next indicator
        for r, (txt, row) in enumerate((("Style", hbox(*self.music_style.buttons())),
                                        ("Colors", colors_row),
                                        ("Sensitivity", hbox(self.music_sens, n)))):
            form.addWidget(QLabel(txt), r, 0)
            form.addLayout(row, r, 1)
        v.addWidget(QLabel("Spectrum needs numpy. Changes apply while the music mode is running.", objectName="muted"))
        self.music_style.buttonClicked.connect(self.update_music_opts)
        self.music_pal.buttonClicked.connect(self.update_music_opts)
        self.music_sens.valueChanged.connect(self.update_music_opts)
        self.update_music_opts()

    def update_music_opts(self, *_):
        pal = self.music_pal.checkedId()
        for b in self.music_swatches:
            b.setEnabled(pal == 2)
        # replaced whole, so the music thread always reads a consistent dict
        self.music_opts = dict(style=ak820.STYLES[self.music_style.checkedId()],
                               gain=(self.music_sens.value() + 1) / 3,  # slider 0..5 -> 0.33..2
                               colors=(None, "rainbow", tuple(self.music_colors))[pal])

    def pick_music_color(self, i):
        c = self.pick_color(self.music_colors[i], "Music color")
        if c:
            self.music_colors[i] = c
            swatch(self.music_swatches[i], c)
            self.update_music_opts()

    def toggle_music(self):
        if self.music_stop:
            return self.music_stop.set()
        if self.busy:
            return
        self.music_btn, stop = self.sender(), threading.Event()
        self.music_stop = stop
        self.music_btn.setText("Stop")
        self.run("Music", lambda kb: ak820.music(kb, lambda: self.music_opts, stop.is_set))


def selftest():
    """Settings survive close + reopen, bad inputs don't crash (temp config, no keyboard, no window)."""
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication([])
    d = tempfile.mkdtemp()
    path = os.path.join(d, "config.json")
    a = App(path)
    a.modes.button(10).setChecked(True); a.rainbow.setChecked(False); a.color = (1, 2, 3)
    a.dir_group.button(1).setChecked(True)
    a.paint = (9, 8, 7); a.paint_key("w"); a.lighting = "keys"
    a.music_style.button(2).setChecked(True); a.music_pal.button(2).setChecked(True)
    a.music_colors = [(1, 1, 1), (2, 2, 2)]; a.music_sens.setValue(4); a.update_music_opts()
    assert a.music_opts == dict(style="spectrum", gain=5 / 3, colors=((1, 1, 1), (2, 2, 2)))
    a.profile.setCurrentText("night"); a.save_profile()
    st = a.get_state()
    a.close()
    b = App(path)
    assert b.get_state() == st and b.cfg["profiles"]["night"] == st, (b.get_state(), st)
    # stale or hand-edited state: unknown mode, key and fit, image file gone
    b.set_state(dict(mode=99, keys={"bogus": "#ffffff"}, fit="zoom", image=os.path.join(d, "gone.gif")))
    assert (b.mode_id(), b.fit(), b.image_path) == (11, "crop", None)
    # a file that is not an image
    b.image_path = path
    b.show_preview()
    assert b.image_path is None and b.statusBar().currentMessage().startswith("Can't open image")
    # keyboard missing: the error is shown and the app is not stuck busy
    real, ak820.Kbd = ak820.Kbd, lambda: sys.exit("AK820 not found")
    try:
        b.run("Clock", lambda kb: None)
        while b.busy:
            app.processEvents()
    finally:
        ak820.Kbd = real
    assert b.statusBar().currentMessage() == "Error: AK820 not found", b.statusBar().currentMessage()
    # no permission: setup is offered; declining leaves the error shown, accepting runs ak820.setup
    def denied():
        raise ak820.NoPermission("no permission to open /dev/hidraw7")
    asked, ran = [], []
    real_q, real_setup = QMessageBox.question, ak820.setup
    ak820.Kbd, ak820.setup = denied, lambda: ran.append(1)
    try:
        for n, answer in enumerate((QMessageBox.No, QMessageBox.Yes), 1):
            QMessageBox.question = lambda *a, answer=answer: asked.append(1) or answer
            b.run("Clock", lambda kb: None)
            while len(asked) < n or b.busy:
                app.processEvents()
    finally:
        ak820.Kbd, ak820.setup, QMessageBox.question = real, real_setup, real_q
    assert asked == [1, 1] and ran == [1], (asked, ran)
    assert b.statusBar().currentMessage().startswith("Keyboard access set up"), b.statusBar().currentMessage()
    # music: Start runs until Stop, then the button and busy flag reset
    def fake_music(kb, opts, stop):
        assert opts()["style"] in ak820.STYLES
        while not stop():
            threading.Event().wait(0.01)
    real_kbd, real_music = ak820.Kbd, ak820.music
    ak820.Kbd = lambda: type("Kbd", (), dict(fd=os.open(os.devnull, os.O_RDONLY), lcd=None))()
    ak820.music = fake_music
    try:
        btn = b.stack.widget(4).findChild(QPushButton, "accent")
        btn.click()
        assert btn.text() == "Stop" and b.busy
        btn.click()
        while b.busy:
            app.processEvents()
        assert btn.text() == "Start" and b.statusBar().currentMessage() == "Music: done."
    finally:
        ak820.Kbd, ak820.music = real_kbd, real_music
    b.close()
    # a corrupted config is kept aside and the app starts with defaults
    with open(path, "w") as f:
        f.write("{not json")
    c = App(path)
    assert os.path.exists(path + ".bad") and c.cfg["profiles"] == {}
    c.close()
    # bad values in the saved state are skipped instead of stopping the app from opening
    save_config(dict(profiles={}, last=dict(color="red", mode=None)), path)
    c = App(path)
    assert c.statusBar().currentMessage().startswith("Ignored saved settings"), c.statusBar().currentMessage()
    c.close()
    # valid JSON of the wrong shape is kept aside like a broken file
    with open(path, "w") as f:
        f.write("[]")
    c = App(path)
    assert c.cfg["profiles"] == {}
    c.close()
    save_config(dict(profiles=None), path)
    App(path).close()
    # X11 WM_CLASS comes from the application name; must match StartupWMClass in ak820.desktop
    assert app.applicationName() == "ak820", app.applicationName()
    print("gui selftest ok")


def main():
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.realpath(__file__)), "ak820.png")))
    w = App()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
