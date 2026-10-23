"""Native desktop interpretation of Fast Order's static/styles.css (680b5a8)."""
import tkinter as tk
from tkinter import ttk


COLORS = {
    "bg": "#060b14", "surface": "#111e30", "strong": "#121d2e",
    "input": "#080f1c", "line": "#29394e", "text": "#f6f8fc",
    "muted": "#8e9bb0", "blue": "#6ea8ff", "cyan": "#4de1e8",
    "green": "#50e4a7", "red": "#ff6684", "amber": "#ffc96b",
}


def apply_theme(root):
    c = COLORS
    root.configure(background=c["bg"])
    root.option_add("*TCombobox*Listbox.background", c["input"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", "#25466d")
    root.option_add("*TCombobox*Listbox.selectForeground", c["text"])
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=c["surface"], foreground=c["text"],
                    font=("Microsoft YaHei UI", 10), bordercolor=c["line"],
                    lightcolor=c["line"], darkcolor=c["line"], focuscolor=c["blue"])
    style.configure("App.TFrame", background=c["bg"])
    style.configure("TLabel", background=c["surface"], foreground=c["text"])
    style.configure("Muted.TLabel", foreground=c["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("Eyebrow.TLabel", foreground=c["muted"], font=("Segoe UI", 8, "bold"))
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 19, "bold"))
    style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 13, "bold"))
    style.configure("Cyan.TLabel", foreground=c["cyan"], font=("Microsoft YaHei UI", 9))
    style.configure("Green.TLabel", foreground=c["green"], font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Amber.TLabel", foreground=c["amber"], font=("Microsoft YaHei UI", 9))
    style.configure("Notice.TLabel", background=c["bg"], foreground=c["muted"], font=("Microsoft YaHei UI", 9))
    style.configure("TButton", padding=(12, 7), background="#19293d", foreground=c["text"],
                    borderwidth=1, relief="flat")
    style.map("TButton", background=[("disabled", "#131f2e"), ("pressed", "#2a4261"), ("active", "#233b59")],
              foreground=[("disabled", "#64748a")], bordercolor=[("active", c["blue"])])
    style.configure("Primary.TButton", background="#4276dd", font=("Microsoft YaHei UI", 10, "bold"))
    style.map("Primary.TButton", background=[("disabled", "#1c3050"), ("pressed", "#3565bf"), ("active", "#5a8ff1")])
    for name, foreground, background, hover, disabled in (
            ("Buy", "#d8fff0", "#1c5748", "#25775c", "#162e2d"),
            ("Sell", "#ffe0e7", "#632a40", "#87364f", "#30202e")):
        style.configure(name + ".TButton", foreground=foreground, background=background,
                        padding=(10, 15), font=("Microsoft YaHei UI", 12, "bold"))
        style.map(name + ".TButton", background=[("disabled", disabled), ("pressed", background), ("active", hover)],
                  foreground=[("disabled", "#78858f")], bordercolor=[("active", c["green"] if name == "Buy" else c["red"])])
    style.configure("Danger.TButton", foreground=c["red"])
    style.configure("TEntry", fieldbackground=c["input"], foreground=c["text"],
                    insertcolor=c["text"], padding=(12, 9), borderwidth=1)
    style.map("TEntry", fieldbackground=[("disabled", "#121b2a")],
              foreground=[("disabled", "#65748a")], bordercolor=[("focus", c["blue"])])
    style.configure("Symbol.TEntry", font=("Segoe UI", 16, "bold"), padding=(14, 9))
    style.configure("TCombobox", fieldbackground=c["input"], background="#1b2d45",
                    foreground=c["text"], arrowcolor=c["blue"], padding=(9, 6))
    style.map("TCombobox", fieldbackground=[("readonly", c["input"])],
              foreground=[("readonly", c["text"])], selectbackground=[("readonly", c["input"])],
              selectforeground=[("readonly", c["text"])], bordercolor=[("focus", c["blue"])])
    style.configure("Segment.TRadiobutton", indicatoron=False, padding=(12, 9),
                    background=c["input"], foreground=c["muted"], relief="flat")
    style.layout("Segment.TRadiobutton", [('Radiobutton.padding', {'sticky':'nswe', 'children':[
        ('Radiobutton.label', {'sticky':'nswe'})]})])
    style.map("Segment.TRadiobutton", background=[("selected", "#254166"), ("active", "#1c304b")],
              foreground=[("selected", c["text"]), ("active", c["blue"])])
    style.configure("TNotebook", background=c["surface"], borderwidth=0, tabmargins=(0, 0, 0, 8))
    style.configure("TNotebook.Tab", background=c["input"], foreground=c["muted"], padding=(14, 8), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", "#203752"), ("active", "#1b2c42")],
              foreground=[("selected", c["cyan"]), ("active", c["text"])],
              lightcolor=[("selected", c["line"])], bordercolor=[("selected", c["line"])])
    style.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                    foreground=c["text"], rowheight=32, borderwidth=0, font=("Microsoft YaHei UI", 9))
    style.map("Treeview", background=[("selected", "#243f60")], foreground=[("selected", c["text"])])
    style.configure("Treeview.Heading", background=c["strong"], foreground=c["muted"],
                    padding=(6, 8), font=("Microsoft YaHei UI", 9), relief="flat", borderwidth=0)
    style.map("Treeview.Heading", background=[("active", "#213651")])
    style.configure("TScrollbar", background="#31425a", troughcolor=c["surface"],
                    arrowcolor=c["muted"], borderwidth=0, lightcolor="#31425a", darkcolor="#31425a", bordercolor=c["surface"])
    for orient in ('Vertical', 'Horizontal'):
        style.configure(orient + '.TScrollbar', background="#31425a", troughcolor=c["surface"],
                        arrowcolor=c["muted"], lightcolor="#31425a", darkcolor="#31425a", bordercolor=c["surface"], borderwidth=0)
        style.map(orient + '.TScrollbar', background=[('active', '#476487'), ('!active', '#31425a')],
                  lightcolor=[('active', '#476487'), ('!active', '#31425a')],
                  darkcolor=[('active', '#476487'), ('!active', '#31425a')])
    style.configure("TSeparator", background=c["line"])
    return style


class GlassCard(tk.Canvas):
    """Rounded, bordered card; its content remains native, accessible Tk widgets."""
    def __init__(self, parent, *, padding=16, **kwargs):
        super().__init__(parent, background=COLORS["bg"], highlightthickness=0, borderwidth=0, **kwargs)
        self.padding = padding
        self.body = ttk.Frame(self)
        self.shape = self.create_polygon(0, 0, 0, 0, smooth=True, splinesteps=24,
                                         fill=COLORS["surface"], outline=COLORS["line"], width=1)
        self.window = self.create_window(padding, padding, anchor="nw", window=self.body)
        self.bind("<Configure>", self._resize)

    def _resize(self, event):
        w, h, r = event.width - 1, event.height - 1, 22
        self.coords(self.shape, r, 1, w-r, 1, w, 1, w, r, w, h-r, w, h,
                    w-r, h, r, h, 1, h, 1, h-r, 1, r, 1, 1)
        self.itemconfigure(self.window, width=max(1, w - self.padding * 2),
                           height=max(1, h - self.padding * 2))


class ScrollableFields(ttk.Frame):
    """Keep trade actions visible even on short screens and at large DPI."""
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=COLORS['surface'], highlightthickness=0, width=270)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.window, width=event.width))

    def bind_wheel(self):
        def scroll(event):
            self.canvas.yview_scroll(int(-event.delta / 120), 'units')
            return 'break'
        def visit(widget):
            widget.bind('<MouseWheel>', scroll, add='+')
            for child in widget.winfo_children():
                visit(child)
        visit(self)


def dark_caption(window):
    """Windows title-bar preference; unsupported OS versions retain native chrome."""
    try:
        import ctypes
        from ctypes import wintypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = wintypes.BOOL(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20,
            ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass
