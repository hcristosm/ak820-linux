#!/usr/bin/env python3
"""Tk GUI for ak820.py: effects, per-key colors, screen image and clock."""
import os, queue, threading, tkinter as tk
from tkinter import colorchooser, filedialog, ttk

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


def hexs(rgb):
    return "#%02x%02x%02x" % rgb


class App:
    def __init__(self, root):
        self.root, self.jobs, self.busy = root, queue.Queue(), False
        root.title("AJAZZ AK820 Pro")
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for title, build in (("Efeitos", self.tab_effects), ("Cores por tecla", self.tab_keys),
                             ("Tela", self.tab_screen), ("Relógio", self.tab_clock)):
            f = ttk.Frame(nb, padding=10)
            build(f)
            nb.add(f, text=title)
        self.status = tk.StringVar(value="Pronto.")
        self.bar = ttk.Progressbar(root, maximum=100)
        self.bar.pack(fill="x", padx=8)
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=8, pady=(2, 8))
        root.after(100, self.poll)

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
                msg = label + ": pronto."
            except SystemExit as e:  # find_hidraw exits with a message when the keyboard is missing
                msg = f"Erro: {e}"
            except Exception as e:
                msg = f"Erro: {e}"
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

    # --- Efeitos ---
    def tab_effects(self, f):
        names = [f"{i:2d}  {n}" for i, (n, _) in ak820.MODES.items()]
        self.mode = ttk.Combobox(f, values=names, state="readonly", width=24)
        self.mode.current(11)  # vendor default_mode="11"
        self.mode.bind("<<ComboboxSelected>>", lambda e: self.update_effect_controls())
        self.rainbow = tk.BooleanVar(value=True)
        self.color = (255, 0, 0)
        self.bright, self.speed, self.direction = tk.IntVar(value=5), tk.IntVar(value=3), tk.IntVar(value=0)

        ttk.Label(f, text="Efeito").grid(row=0, column=0, sticky="w")
        self.mode.grid(row=0, column=1, sticky="w", pady=4)
        self.rainbow_cb = ttk.Checkbutton(f, text="Arco-íris", variable=self.rainbow,
                                          command=self.update_effect_controls)
        self.rainbow_cb.grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="Cor").grid(row=2, column=0, sticky="w")
        self.color_btn = tk.Button(f, width=6, bg=hexs(self.color), command=self.pick_effect_color)
        self.color_btn.grid(row=2, column=1, sticky="w", pady=4)
        self.scales = {}
        for r, (txt, var) in enumerate((("Brilho", self.bright), ("Velocidade", self.speed)), start=3):
            ttk.Label(f, text=txt).grid(row=r, column=0, sticky="w")
            s = tk.Scale(f, from_=0, to=5, orient="horizontal", variable=var, length=200)
            s.grid(row=r, column=1, sticky="w")
            self.scales[txt] = s
        ttk.Label(f, text="Direção").grid(row=5, column=0, sticky="w")
        d = ttk.Frame(f)
        d.grid(row=5, column=1, sticky="w", pady=4)
        self.dir_rbs = [ttk.Radiobutton(d, text=t, value=v, variable=self.direction)
                        for v, t in ((0, "→ / ↓"), (1, "← / ↑"))]
        for rb in self.dir_rbs:
            rb.pack(side="left", padx=(0, 10))
        ttk.Button(f, text="Aplicar", command=self.apply_effect).grid(row=6, column=1, sticky="w", pady=10)
        self.update_effect_controls()

    def mode_id(self):
        return int(self.mode.get().split()[0])

    def update_effect_controls(self):
        flags = ak820.MODES[self.mode_id()][1]
        on = lambda bit: "normal" if flags & bit else "disabled"
        self.rainbow_cb.configure(state=on(0x20))
        has_color = flags & 0x10 and not (flags & 0x20 and self.rainbow.get())
        self.color_btn.configure(state="normal" if has_color else "disabled")
        self.scales["Brilho"].configure(state=on(0x01))
        self.scales["Velocidade"].configure(state=on(0x02))
        for rb in self.dir_rbs:
            rb.configure(state=on(0x0C))  # 0x04 horizontal, 0x08 vertical (Scrolling)

    def pick_effect_color(self):
        c = colorchooser.askcolor(hexs(self.color), title="Cor do efeito")[0]
        if c:
            self.color = tuple(int(x) for x in c)
            self.color_btn.configure(bg=hexs(self.color))

    def apply_effect(self):
        mode, flags = self.mode_id(), ak820.MODES[self.mode_id()][1]
        rgb = None if (flags & 0x20 and self.rainbow.get()) or not flags & 0x10 else self.color
        args = (mode, rgb, self.bright.get(), self.speed.get(), self.direction.get())
        self.run("Efeito " + ak820.MODES[mode][0], lambda kb: kb.set_mode(*args))

    # --- Cores por tecla ---
    def tab_keys(self, f):
        self.paint = (255, 0, 0)
        self.key_colors = {name: (0, 0, 0) for name in ak820.KEYS}
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Pincel").pack(side="left")
        self.paint_btn = tk.Button(top, width=6, bg=hexs(self.paint), command=self.pick_paint)
        self.paint_btn.pack(side="left", padx=6)
        ttk.Button(top, text="Pintar todas", command=self.paint_all).pack(side="left", padx=6)
        ttk.Label(top, text="Brilho").pack(side="left", padx=(12, 0))
        self.key_bright = tk.IntVar(value=5)
        tk.Scale(top, from_=0, to=5, orient="horizontal", variable=self.key_bright,
                 length=120).pack(side="left")
        ttk.Button(top, text="Aplicar", command=self.apply_keys).pack(side="right")

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
        ttk.Label(f, text="Clique numa tecla para pintá-la com a cor do pincel.").pack(anchor="w", pady=(6, 0))

    def pick_paint(self):
        c = colorchooser.askcolor(hexs(self.paint), title="Cor do pincel")[0]
        if c:
            self.paint = tuple(int(x) for x in c)
            self.paint_btn.configure(bg=hexs(self.paint))

    def paint_key(self, name):
        self.key_colors[name] = self.paint
        r, t = self.rects[name]
        self.canvas.itemconfigure(r, fill=hexs(self.paint))
        self.canvas.itemconfigure(t, fill="black" if sum(self.paint) > 380 else "white")

    def paint_all(self):
        for name in self.key_colors:
            self.paint_key(name)

    def apply_keys(self):
        colors = {ak820.KEYS[n]: c for n, c in self.key_colors.items()}
        b = self.key_bright.get()
        self.run("Cores por tecla", lambda kb: kb.set_keys(colors, b))

    # --- Tela ---
    def tab_screen(self, f):
        self.image_path, self.preview = None, None
        self.fit = tk.StringVar(value="crop")
        ttk.Button(f, text="Escolher imagem ou GIF…", command=self.pick_image).grid(row=0, column=0, sticky="w")
        self.image_lbl = ttk.Label(f, text="Nenhum arquivo")
        self.image_lbl.grid(row=0, column=1, sticky="w", padx=8)
        self.preview_lbl = tk.Label(f, width=256, height=256, bg="black")
        self.preview_lbl.grid(row=1, column=0, columnspan=2, pady=8)
        fr = ttk.Frame(f)
        fr.grid(row=2, column=0, columnspan=2, sticky="w")
        for v, t in (("crop", "Recortar para preencher"), ("pad", "Encaixar com bordas")):
            ttk.Radiobutton(fr, text=t, value=v, variable=self.fit, command=self.show_preview).pack(side="left",
                                                                                                    padx=(0, 10))
        ttk.Button(f, text="Enviar para a tela", command=self.apply_screen).grid(row=3, column=0, sticky="w",
                                                                                pady=10)

    def pick_image(self):
        p = filedialog.askopenfilename(filetypes=[("Imagens", "*.gif *.png *.jpg *.jpeg *.bmp *.webp"),
                                                  ("Todos", "*")])
        if p:
            self.image_path = p
            self.show_preview()

    def show_preview(self):
        if not self.image_path:
            return
        from PIL import Image, ImageOps, ImageTk
        im = Image.open(self.image_path)
        n = getattr(im, "n_frames", 1)
        first = im.convert("RGB")
        first = ImageOps.fit(first, (128, 128)) if self.fit.get() == "crop" else ImageOps.pad(first, (128, 128))
        self.preview = ImageTk.PhotoImage(first.resize((256, 256), Image.NEAREST))
        self.preview_lbl.configure(image=self.preview, width=256, height=256)
        extra = f" (só os primeiros {ak820.MAX_FRAMES} serão enviados)" if n > ak820.MAX_FRAMES else ""
        self.image_lbl.configure(text=f"{os.path.basename(self.image_path)} — {n} quadro(s){extra}")

    def apply_screen(self):
        if not self.image_path:
            return self.status.set("Escolha uma imagem primeiro.")
        path, fit = self.image_path, self.fit.get()

        def job(kb):
            blob = ak820.screen_blob(ak820.load_frames(path, fit))
            kb.upload_screen(blob, lambda i, n: self.jobs.put(("progress", 100 * i / n)))
        self.run("Envio da tela", job)

    # --- Relógio ---
    def tab_clock(self, f):
        ttk.Label(f, text="Ajusta o relógio da tela do teclado para a hora deste computador.").pack(anchor="w")
        ttk.Button(f, text="Sincronizar agora", command=lambda: self.run("Relógio", lambda kb: kb.sync_time())
                   ).pack(anchor="w", pady=10)


if __name__ == "__main__":
    root = tk.Tk(className="ak820")  # matches StartupWMClass in ak820.desktop
    root.iconphoto(True, tk.PhotoImage(file=os.path.join(os.path.dirname(os.path.realpath(__file__)), "ak820.png")))
    App(root)
    root.mainloop()
