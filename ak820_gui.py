#!/usr/bin/env python3
"""Tk GUI for ak820.py: effects, per-key colors, screen image and clock."""
import json, os, queue, sys, threading, tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import ak820

# keyboard drawing: rows break after these keys; widths in key units (default 1)
ROW_ENDS = {"delete", "home", "pgup", "pgdn", "up", "right"}
WIDTH = dict(backspace=2, tab=1.5, backslash=1.5, capslock=1.75, enter=2.25, lshift=2.25, rshift=1.75,
             lctrl=1.25, win=1.25, lalt=1.25, space=6.25)
LABEL = dict(grave="`", minus="-", equal="=", lbracket="[", rbracket="]", backslash="\\", semicolon=";",
             quote="'", comma=",", period=".", slash="/", up="↑", down="↓", left="←", right="→",
             backspace="Back", capslock="Caps", lshift="Shift", rshift="Shift", lctrl="Ctrl",
             rctrl="Ctrl", lalt="Alt", ralt="Alt", delete="Del", pgup="PgUp", pgdn="PgDn")
U, GAP = 40, 3  # pixels per key unit, gap between keys
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "ak820", "config.json")


def hexs(rgb):
    return "#%02x%02x%02x" % rgb


def load_config(path):
    try:
        with open(path) as f:
            return json.load(f)
    except OSError:
        return {}
    except ValueError:  # keep a broken file aside instead of overwriting the user's profiles
        os.replace(path, path + ".bad")
        return {}


def save_config(cfg, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(path + ".tmp", path)  # never leave a half-written config


class App:
    def __init__(self, root, cfg_path=CONFIG):
        self.root, self.jobs, self.busy = root, queue.Queue(), False
        self.cfg_path, self.cfg, self.lighting = cfg_path, load_config(cfg_path), "effect"
        self.cfg.setdefault("profiles", {})
        root.title(f"AJAZZ AK820 Pro {ak820.__version__}")
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(bar, text="Profile").pack(side="left")
        self.profile = ttk.Combobox(bar, width=20)
        self.profile.pack(side="left", padx=6)
        for txt, cmd in (("Load", self.load_profile), ("Save", self.save_profile), ("Delete", self.delete_profile)):
            ttk.Button(bar, text=txt, command=cmd).pack(side="left", padx=2)
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for title, build in (("Effects", self.tab_effects), ("Per-key colors", self.tab_keys),
                             ("Screen", self.tab_screen), ("Clock", self.tab_clock)):
            f = ttk.Frame(nb, padding=10)
            build(f)
            nb.add(f, text=title)
        self.status = tk.StringVar(value="Ready.")
        self.bar = ttk.Progressbar(root, maximum=100)
        self.bar.pack(fill="x", padx=8)
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=8, pady=(2, 8))
        self.profile["values"] = sorted(self.cfg["profiles"])
        if "last" in self.cfg:
            self.set_state(self.cfg["last"])
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self.poll)

    # --- settings: "last" is restored on start, profiles are named snapshots of the same state ---
    def get_state(self):
        return dict(mode=self.mode_id(), rainbow=self.rainbow.get(), color=hexs(self.color),
                    brightness=self.bright.get(), speed=self.speed.get(), direction=self.direction.get(),
                    keys={n: hexs(c) for n, c in self.key_colors.items()}, key_brightness=self.key_bright.get(),
                    lighting=self.lighting, image=self.image_path, fit=self.fit.get())

    def set_state(self, st):
        self.mode.current(st.get("mode", 11))  # combobox index == mode id
        self.rainbow.set(st.get("rainbow", True))
        self.color = ak820.hexrgb(st.get("color", "#ff0000"))
        self.color_btn.configure(bg=hexs(self.color))
        self.bright.set(st.get("brightness", 5))
        self.speed.set(st.get("speed", 3))
        self.direction.set(st.get("direction", 0))
        self.key_bright.set(st.get("key_brightness", 5))
        for n, c in st.get("keys", {}).items():
            if n in self.rects:
                self.paint_key(n, ak820.hexrgb(c))
        self.lighting = st.get("lighting", "effect")
        self.fit.set(st.get("fit", "crop"))
        img = st.get("image")
        self.image_path = img if img and os.path.exists(img) else None
        self.show_preview()
        self.update_effect_controls()

    def persist(self):
        self.cfg["last"] = self.get_state()
        save_config(self.cfg, self.cfg_path)

    def quit(self):
        try:
            self.persist()
        finally:
            self.root.destroy()

    def save_profile(self):
        name = self.profile.get().strip()
        if not name:
            return self.status.set("Type a profile name first.")
        self.cfg["profiles"][name] = self.get_state()
        self.persist()
        self.profile["values"] = sorted(self.cfg["profiles"])
        self.status.set(f"Profile '{name}' saved.")

    def load_profile(self):
        st = self.cfg["profiles"].get(self.profile.get())
        if not st:
            return self.status.set("Pick a saved profile.")
        self.set_state(st)
        (self.apply_keys if self.lighting == "keys" else self.apply_effect)()  # screen is not re-sent (slow)

    def delete_profile(self):
        name = self.profile.get()
        if name in self.cfg["profiles"] and messagebox.askyesno("Delete profile", f"Delete profile '{name}'?"):
            del self.cfg["profiles"][name]
            self.persist()
            self.profile["values"] = sorted(self.cfg["profiles"])
            self.profile.set("")

    # --- device work runs in a thread; UI updates go through self.jobs ---
    def run(self, label, fn):
        if self.busy:
            return
        self.busy = True
        self.status.set(label + "…")
        self.bar["value"] = 0

        def work():
            try:
                kb = ak820.Kbd()
                try:
                    fn(kb)
                finally:
                    os.close(kb.fd)
                    kb.lcd is not None and os.close(kb.lcd)
                msg = label + ": done."
            except SystemExit as e:  # find_hidraw exits with a message when the keyboard is missing
                msg = f"Error: {e}"
            except Exception as e:
                msg = f"Error: {e}"
            self.jobs.put(("done", msg))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        while not self.jobs.empty():
            kind, val = self.jobs.get()
            if kind == "progress":
                self.bar["value"] = val
            else:
                self.busy = False
                self.bar["value"] = 100
                self.status.set(val)
        self.root.after(100, self.poll)

    # --- Effects ---
    def tab_effects(self, f):
        names = [f"{i:2d}  {n}" for i, (n, _) in ak820.MODES.items()]
        self.mode = ttk.Combobox(f, values=names, state="readonly", width=24)
        self.mode.current(11)  # vendor default_mode="11"
        self.mode.bind("<<ComboboxSelected>>", lambda e: self.update_effect_controls())
        self.rainbow = tk.BooleanVar(value=True)
        self.color = (255, 0, 0)
        self.bright, self.speed, self.direction = tk.IntVar(value=5), tk.IntVar(value=3), tk.IntVar(value=0)

        ttk.Label(f, text="Effect").grid(row=0, column=0, sticky="w")
        self.mode.grid(row=0, column=1, sticky="w", pady=4)
        self.rainbow_cb = ttk.Checkbutton(f, text="Rainbow", variable=self.rainbow,
                                          command=self.update_effect_controls)
        self.rainbow_cb.grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="Color").grid(row=2, column=0, sticky="w")
        self.color_btn = tk.Button(f, width=6, bg=hexs(self.color), command=self.pick_effect_color)
        self.color_btn.grid(row=2, column=1, sticky="w", pady=4)
        self.scales = {}
        for r, (txt, var) in enumerate((("Brightness", self.bright), ("Speed", self.speed)), start=3):
            ttk.Label(f, text=txt).grid(row=r, column=0, sticky="w")
            s = tk.Scale(f, from_=0, to=5, orient="horizontal", variable=var, length=200)
            s.grid(row=r, column=1, sticky="w")
            self.scales[txt] = s
        ttk.Label(f, text="Direction").grid(row=5, column=0, sticky="w")
        d = ttk.Frame(f)
        d.grid(row=5, column=1, sticky="w", pady=4)
        self.dir_rbs = [ttk.Radiobutton(d, text=t, value=v, variable=self.direction)
                        for v, t in ((0, "→ / ↓"), (1, "← / ↑"))]
        for rb in self.dir_rbs:
            rb.pack(side="left", padx=(0, 10))
        ttk.Button(f, text="Apply", command=self.apply_effect).grid(row=6, column=1, sticky="w", pady=10)
        self.update_effect_controls()

    def mode_id(self):
        return int(self.mode.get().split()[0])

    def update_effect_controls(self):
        flags = ak820.MODES[self.mode_id()][1]
        on = lambda bit: "normal" if flags & bit else "disabled"
        self.rainbow_cb.configure(state=on(0x20))
        has_color = flags & 0x10 and not (flags & 0x20 and self.rainbow.get())
        self.color_btn.configure(state="normal" if has_color else "disabled")
        self.scales["Brightness"].configure(state=on(0x01))
        self.scales["Speed"].configure(state=on(0x02))
        for rb in self.dir_rbs:
            rb.configure(state=on(0x0C))  # 0x04 horizontal, 0x08 vertical (Scrolling)

    def pick_effect_color(self):
        c = colorchooser.askcolor(hexs(self.color), title="Effect color")[0]
        if c:
            self.color = tuple(int(x) for x in c)
            self.color_btn.configure(bg=hexs(self.color))

    def apply_effect(self):
        mode, flags = self.mode_id(), ak820.MODES[self.mode_id()][1]
        rgb = None if (flags & 0x20 and self.rainbow.get()) or not flags & 0x10 else self.color
        args = (mode, rgb, self.bright.get(), self.speed.get(), self.direction.get())
        self.lighting = "effect"
        self.run("Effect " + ak820.MODES[mode][0], lambda kb: kb.set_mode(*args))

    # --- Per-key colors ---
    def tab_keys(self, f):
        self.paint = (255, 0, 0)
        self.key_colors = {name: (0, 0, 0) for name in ak820.KEYS}
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Brush").pack(side="left")
        self.paint_btn = tk.Button(top, width=6, bg=hexs(self.paint), command=self.pick_paint)
        self.paint_btn.pack(side="left", padx=6)
        ttk.Button(top, text="Paint all", command=self.paint_all).pack(side="left", padx=6)
        ttk.Label(top, text="Brightness").pack(side="left", padx=(12, 0))
        self.key_bright = tk.IntVar(value=5)
        tk.Scale(top, from_=0, to=5, orient="horizontal", variable=self.key_bright,
                 length=120).pack(side="left")
        ttk.Button(top, text="Apply", command=self.apply_keys).pack(side="right")

        self.canvas = tk.Canvas(f, width=16 * U + GAP, height=6 * U + GAP, highlightthickness=0)
        self.canvas.pack()
        self.rects = {}
        x = y = 0
        for name in ak820.KEYS:
            w = WIDTH.get(name, 1) * U
            r = self.canvas.create_rectangle(x + GAP, y + GAP, x + w, y + U, fill="#000000", outline="#666")
            t = self.canvas.create_text(x + (w + GAP) / 2, y + (U + GAP) / 2, fill="white",
                                        text=LABEL.get(name, name.upper() if len(name) == 1 else name.title()),
                                        font=("TkDefaultFont", 8))
            for item in (r, t):
                self.canvas.tag_bind(item, "<Button-1>", lambda e, n=name: self.paint_key(n))
            self.rects[name] = (r, t)
            x += w
            if name in ROW_ENDS:
                x, y = 0, y + U
        ttk.Label(f, text="Click a key to paint it with the brush color.").pack(anchor="w", pady=(6, 0))

    def pick_paint(self):
        c = colorchooser.askcolor(hexs(self.paint), title="Brush color")[0]
        if c:
            self.paint = tuple(int(x) for x in c)
            self.paint_btn.configure(bg=hexs(self.paint))

    def paint_key(self, name, color=None):
        color = color or self.paint
        self.key_colors[name] = color
        r, t = self.rects[name]
        self.canvas.itemconfigure(r, fill=hexs(color))
        self.canvas.itemconfigure(t, fill="black" if sum(color) > 380 else "white")

    def paint_all(self):
        for name in self.key_colors:
            self.paint_key(name)

    def apply_keys(self):
        colors = {ak820.KEYS[n]: c for n, c in self.key_colors.items()}
        b = self.key_bright.get()
        self.lighting = "keys"
        self.run("Per-key colors", lambda kb: kb.set_keys(colors, b))

    # --- Screen ---
    def tab_screen(self, f):
        self.image_path, self.preview = None, None
        self.fit = tk.StringVar(value="crop")
        ttk.Button(f, text="Choose image or GIF…", command=self.pick_image).grid(row=0, column=0, sticky="w")
        self.image_lbl = ttk.Label(f, text="No file selected")
        self.image_lbl.grid(row=0, column=1, sticky="w", padx=8)
        self.preview_lbl = tk.Label(f, width=256, height=256, bg="black")
        self.preview_lbl.grid(row=1, column=0, columnspan=2, pady=8)
        fr = ttk.Frame(f)
        fr.grid(row=2, column=0, columnspan=2, sticky="w")
        for v, t in (("crop", "Crop to fill"), ("pad", "Fit with borders")):
            ttk.Radiobutton(fr, text=t, value=v, variable=self.fit, command=self.show_preview).pack(side="left",
                                                                                                    padx=(0, 10))
        ttk.Button(f, text="Send to screen", command=self.apply_screen).grid(row=3, column=0, sticky="w",
                                                                                pady=10)

    def pick_image(self):
        p = filedialog.askopenfilename(filetypes=[("Images", "*.gif *.png *.jpg *.jpeg *.bmp *.webp"),
                                                  ("All files", "*")])
        if p:
            self.image_path = p
            self.show_preview()

    def show_preview(self):
        if not self.image_path:
            self.preview_lbl.configure(image="")
            return self.image_lbl.configure(text="No file selected")
        from PIL import Image, ImageOps, ImageTk
        im = Image.open(self.image_path)
        n = getattr(im, "n_frames", 1)
        first = im.convert("RGB")
        first = ImageOps.fit(first, (128, 128)) if self.fit.get() == "crop" else ImageOps.pad(first, (128, 128))
        self.preview = ImageTk.PhotoImage(first.resize((256, 256), Image.NEAREST))
        self.preview_lbl.configure(image=self.preview, width=256, height=256)
        extra = f" (only the first {ak820.MAX_FRAMES} will be sent)" if n > ak820.MAX_FRAMES else ""
        self.image_lbl.configure(text=f"{os.path.basename(self.image_path)} — {n} frame(s){extra}")

    def apply_screen(self):
        if not self.image_path:
            return self.status.set("Choose an image first.")
        path, fit = self.image_path, self.fit.get()

        def job(kb):
            blob = ak820.screen_blob(ak820.load_frames(path, fit))
            kb.upload_screen(blob, lambda i, n: self.jobs.put(("progress", 100 * i / n)))
        self.run("Screen upload", job)

    # --- Clock ---
    def tab_clock(self, f):
        ttk.Label(f, text="Sets the keyboard screen clock to this computer's time.").pack(anchor="w")
        ttk.Button(f, text="Sync now", command=lambda: self.run("Clock", lambda kb: kb.sync_time())
                   ).pack(anchor="w", pady=10)


def selftest():
    """Settings survive close + reopen (uses a temp config, no keyboard needed)."""
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "config.json")
    a = App(tk.Tk(), path)
    a.mode.current(10); a.rainbow.set(False); a.color = (1, 2, 3); a.direction.set(1)
    a.paint = (9, 8, 7); a.paint_key("w"); a.lighting = "keys"
    a.profile.set("night"); a.save_profile()
    st = a.get_state()
    a.quit()
    b = App(tk.Tk(), path)
    assert b.get_state() == st and b.cfg["profiles"]["night"] == st, (b.get_state(), st)
    b.root.destroy()
    print("gui selftest ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    root = tk.Tk(className="ak820")  # matches StartupWMClass in ak820.desktop
    root.iconphoto(True, tk.PhotoImage(file=os.path.join(os.path.dirname(os.path.realpath(__file__)), "ak820.png")))
    App(root)
    root.mainloop()
