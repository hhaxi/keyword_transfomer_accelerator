"""Materials and ttk controls for the KWT workbench."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk

BG, PANEL, INK, MUTED = "#e5ebf2", "#ebf0f6", "#182b3b", "#4c6072"
CARD, LINE, SIDEBAR = "#f4f6f9", "#d5dee8", "#dce8f2"
BLUE, GREEN, RED = "#2167ad", "#13713e", "#a03242"
FONT = "Microsoft YaHei UI"


def wallpaper():
    """Quiet, cool background shared by the sidebar and work area."""
    width, height = 560, 400
    base = Image.new("RGB", (width, height), "#e8edf3")
    paint = ImageDraw.Draw(base)
    paint.ellipse((-230, -205, 396, 231), fill="#c7dbe9")
    paint.ellipse((307, -157, 720, 276), fill="#f6f8fa")
    paint.ellipse((206, 206, 730, 680), fill="#d9e1ef")
    return base.filter(ImageFilter.GaussianBlur(55))


def button_image(top, bottom, rim):
    scale, width, height = 3, 44, 32
    size = (width * scale, height * scale)
    gradient = Image.new("RGB", size)
    paint = ImageDraw.Draw(gradient)
    first, last = ImageColor.getrgb(top), ImageColor.getrgb(bottom)
    for y in range(size[1]):
        amount = y / (size[1] - 1)
        color = tuple(round(a + (b - a) * amount) for a, b in zip(first, last))
        paint.line((0, y, size[0], y), fill=color)
    mask = Image.new("L", size)
    bounds = (1, 1, size[0] - 2, size[1] - 2)
    ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=8 * scale, fill=255)
    gradient.putalpha(mask)
    ImageDraw.Draw(gradient).rounded_rectangle(bounds, radius=8 * scale, outline=rim, width=scale)
    return gradient.resize((width, height), Image.Resampling.LANCZOS)


class WorkbenchTheme:
    def __init__(self, root):
        self.root = root
        self.art = wallpaper()
        self.frost = self.art.filter(ImageFilter.GaussianBlur(13))
        self.size = None
        self.images = []
        self.install_controls()

    def background(self, widget, *, frosted=False):
        size = max(1, self.root.winfo_width()), max(1, self.root.winfo_height())
        if size != self.size:
            self.wall = self.art.resize(size, Image.Resampling.BILINEAR)
            self.wall_frost = self.frost.resize(size, Image.Resampling.BILINEAR)
            self.size = size
        x = widget.winfo_rootx() - self.root.winfo_rootx()
        y = widget.winfo_rooty() - self.root.winfo_rooty()
        width, height = widget.winfo_width(), widget.winfo_height()
        source = self.wall_frost if frosted else self.wall
        return source.crop((x, y, x + width, y + height))

    def install_controls(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=PANEL)
        secondary = (
            ("#fbfcfd", "#f1f5f8", "#cfd9e4"),
            ("#edf1f5", "#ebeff4", "#dce3eb"),
            ("#e1ebf5", "#d7e5f3", "#a8bfd5"),
            ("#fcfdff", "#e8f0f7", "#b8cada"),
            ("#fbfcfd", "#eff5fa", BLUE),
        )
        primary = (
            ("#edf5fb", "#dbe8f4", "#bacddd"),
            ("#edf1f5", "#ebeff4", "#dce3eb"),
            ("#dae8f4", "#ccdeee", "#9ab8d4"),
            ("#f6fafd", "#deedf8", "#a6bed5"),
            ("#edf5fb", "#dbe8f4", BLUE),
        )
        for name, palette in (("TButton", secondary), ("Primary.TButton", primary)):
            images = [ImageTk.PhotoImage(button_image(*colors), master=self.root) for colors in palette]
            self.images.extend(images)
            default, disabled, pressed, hover, focus = images
            element = name + ".Surface"
            style.element_create(element, "image", default, ("disabled", disabled), ("pressed", pressed),
                                 ("focus", focus), ("active", hover), border=(9, 9),
                                 padding=(11, 5), sticky="nsew")
            style.layout(name, [(element, {"sticky": "nsew", "children": [
                ("Button.label", {"sticky": "nsew"})
            ]})])
            style.configure(name, font=(FONT, 9, "bold" if name.startswith("Primary") else "normal"),
                            background=PANEL, foreground="#185796" if name.startswith("Primary") else INK)
            style.map(name, foreground=[("disabled", "#637a96")])

        style.configure("TCombobox", padding=(8, 5), foreground=INK, fieldbackground="#f7f9fc",
                        background="#e4ecf4", bordercolor="#c3d0de", lightcolor="#f8fbfd",
                        darkcolor="#dde6f0", arrowcolor=MUTED, selectbackground="#d8e7f4",
                        selectforeground=INK, arrowsize=13)
        style.map("TCombobox", fieldbackground=[("disabled", "#e9eef4"), ("readonly", "#f7f9fc")],
                  foreground=[("disabled", "#637a96")],
                  bordercolor=[("focus", BLUE), ("!focus", "#c3d0de")])
        self.root.option_add("*TCombobox*Listbox.font", (FONT, 10))
        self.root.option_add("*TCombobox*Listbox.background", "#f5faff")
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#cfe3ff")
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)

        for name, color in (("trough", "#dbe5ee"), ("pbar", BLUE)):
            meter = Image.new("RGBA", (36, 18))
            ImageDraw.Draw(meter).rounded_rectangle((0, 0, 35, 17), radius=9 if name == "trough" else 0, fill=color)
            image = ImageTk.PhotoImage(meter.resize((12, 6), Image.Resampling.LANCZOS), master=self.root)
            self.images.append(image)
            style.element_create(f"Workbench.Progress.{name}", "image", image,
                                 border=(4, 2) if name == "trough" else 0, sticky="nsew")
        style.layout("Horizontal.TProgressbar", [("Workbench.Progress.trough", {"sticky": "nsew", "children": [
            ("Workbench.Progress.pbar", {"side": "left", "sticky": "ns"})
        ]})])
        style.configure("Treeview", font=(FONT, 9), rowheight=25, background=PANEL, fieldbackground=PANEL,
                        foreground=INK, borderwidth=0, relief="flat", lightcolor=PANEL, darkcolor=PANEL)
        style.configure("Treeview.Heading", font=(FONT, 9, "bold"), foreground=MUTED,
                        background="#dfe8f0", borderwidth=0, relief="flat", lightcolor="#dfe8f0",
                        darkcolor="#dfe8f0", padding=(5, 4))
        style.map("Treeview", background=[("selected", "#d5e4f1")], foreground=[("selected", INK)])
        style.map("Treeview.Heading", background=[("active", "#d4e1ee")])
        style.configure("Vertical.TScrollbar", background="#cbd8e4", troughcolor=PANEL,
                        bordercolor=PANEL, lightcolor="#cbd8e4", darkcolor="#cbd8e4", arrowcolor=MUTED)
        style.configure("Sidebar.Treeview", rowheight=30, font=(FONT, 10), background=SIDEBAR,
                        fieldbackground=SIDEBAR, lightcolor=SIDEBAR, darkcolor=SIDEBAR, bordercolor=SIDEBAR)
        style.map("Sidebar.Treeview", background=[("selected", "#c9dceb")],
                  foreground=[("selected", "#174e82")])
        blank = ImageTk.PhotoImage(Image.new("RGBA", (44, 32)), master=self.root)
        selected, hover, focus = [ImageTk.PhotoImage(button_image(*colors), master=self.root)
                                  for colors in (primary[0], secondary[3], primary[4])]
        self.images.extend((blank, selected, hover, focus))
        style.element_create("Workbench.Notebook.client", "image", blank, sticky="nsew")
        style.layout("TNotebook", [("Workbench.Notebook.client", {"sticky": "nsew"})])
        style.element_create("Workbench.Notebook.tab", "image", blank, ("focus", focus),
                             ("selected", selected), ("active", hover), border=(9, 9), padding=(13, 6))
        style.layout("TNotebook.Tab", [("Workbench.Notebook.tab", {"sticky": "nsew", "children": [
            ("Notebook.label", {"sticky": "nsew"})
        ]})])
        style.configure("TNotebook", background=PANEL, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", foreground=MUTED, font=(FONT, 10))
        style.map("TNotebook.Tab", foreground=[("selected", BLUE)])


class Surface(tk.Canvas):
    """Rounded shell with a tinted, legible inset for standard Tk controls."""

    def __init__(self, parent, theme, *, material=True, inset=(16, 12), color=PANEL, card=False, **kwargs):
        super().__init__(parent, background=BG, highlightthickness=0, borderwidth=0, **kwargs)
        self.theme = theme
        self.material = material
        self.inset = inset
        self.color = color
        self.card = card
        self.picture = None
        self.render_pending = False
        self.backdrop = self.create_image(0, 0, anchor="nw")
        if material:
            self.content = tk.Frame(self, bg=color)
            self.window = self.create_window(*inset, window=self.content, anchor="nw")
        self.bind("<Configure>", self.schedule_render)

    def fit_content(self):
        self.content.update_idletasks()
        self.configure(height=self.content.winfo_reqheight() + 2 * self.inset[1])

    def schedule_render(self, _=None):
        if not self.render_pending:
            self.render_pending = True
            self.after_idle(self.render)

    def render(self):
        self.render_pending = False
        width, height = self.winfo_width(), self.winfo_height()
        if width < 2 or height < 2:
            return
        background = Image.new("RGB", (width, height), PANEL) if self.card else self.theme.background(self)
        if self.material:
            horizontal, vertical = self.inset
            self.itemconfigure(self.window, width=max(1, width - 2 * horizontal),
                               height=max(1, height - 2 * vertical))
            bounds = (1, 1, width - 2, height - 2)
            radius = 12 if self.card else 16
            rim = ImageDraw.Draw(background)
            if self.card:
                rim.rounded_rectangle(bounds, radius=radius, fill=self.color, outline=LINE)
            else:
                mask = Image.new("L", background.size)
                ImageDraw.Draw(mask).rounded_rectangle(bounds, radius=radius, fill=255)
                blurred = self.theme.background(self, frosted=True)
                glass = Image.blend(blurred, Image.new("RGB", background.size, self.color), 0.78)
                interior = Image.new("L", background.size)
                ImageDraw.Draw(interior).rounded_rectangle((7, 4, width - 8, height - 5), radius=13, fill=255)
                glass.paste(self.color, mask=interior.filter(ImageFilter.GaussianBlur(5)))
                background.paste(glass, mask=mask)
                rim.rounded_rectangle(bounds, radius=radius, outline="#f9fbfd")
                rim.rounded_rectangle((2, 2, width - 3, height - 3), radius=15, outline="#d0dbe6")
        self.picture = ImageTk.PhotoImage(background, master=self)
        self.itemconfigure(self.backdrop, image=self.picture)
