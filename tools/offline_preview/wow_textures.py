"""Optional local WoW artwork; no downloads or third-party code at runtime."""

from pathlib import Path
import tkinter as tk

DIRECTORY = Path(__file__).resolve().parent / "theme_art" / "wow_ui"


class WoWTextures:
    def __init__(self, style):
        self.style = style
        self.images = []
        self.ready = False
        try:
            atlas = self.load("UI-DialogBox-Border.PNG").subsample(2)
            self.images.append(atlas)
            self.edges = [self.crop(atlas, i * 16, 0, 16, 16) for i in range(8)]
            # WoW stores top/bottom strips vertically in its backdrop atlas.
            for index in (2, 3):
                source = self.edges[index]
                rotated = tk.PhotoImage(master=style.master, width=16, height=16)
                for x in range(16):
                    for y in range(16):
                        rotated.tk.call(str(rotated), "copy", str(source),
                                        "-from", x, y, x + 1, y + 1, "-to", y, x)
                self.images.append(rotated)
                self.edges[index] = rotated
            ring = tk.PhotoImage(master=style.master, width=256, height=256)
            self.images.append(ring)
            self.draw_border(ring, 256, 256)
            style.element_create("WoWFrame", "image", ring, border=16, width=0, height=0, sticky="nswe")
            for name in ("Fantasy.TFrame", "FantasyCard.TFrame"):
                style.layout(name, [("Frame.border", {"sticky": "nswe", "children": [
                    ("WoWFrame", {"sticky": "nswe", "children": [
                        ("Frame.padding", {"sticky": "nswe"})]})]})])
            header = self.crop(self.load("UI-DialogBox-Header.PNG"), 58, 0, 139, 40)
            header = self.expand(header, 503, 64, (24, 19, 24, 20))
            style.element_create("WoWHeader", "image", header, border=(24, 19, 24, 20),
                                 width=0, height=0, sticky="nswe")
            style.layout("FantasyTitle.TLabel", [("WoWHeader", {"sticky": "nswe"}),
                ("Label.padding", {"sticky": "nswe", "children": [
                    ("Label.label", {"sticky": "nswe"})]})])
            up, down, disabled = [self.crop(self.load(f"UI-Panel-Button-{state}.PNG"), 0, 0, 80, 22)
                                   for state in ("Up", "Down", "Disabled")]
            up, down, disabled = [self.expand(image, 528, 64, (8, 10, 8, 11))
                                  for image in (up, down, disabled)]
            style.element_create("WoWButton", "image", up, ("disabled", disabled), ("pressed", down),
                                 border=(8, 10, 8, 11), width=0, height=0, sticky="nswe")
            for name in ("Fantasy.TButton", "FantasyPrimary.TButton"):
                style.layout(name, [("WoWButton", {"sticky": "nswe"}),
                    ("Button.focus", {"sticky": "nswe", "children": [
                        ("Button.padding", {"sticky": "nswe", "children": [
                            ("Button.label", {"sticky": "nswe"})]})]})])
            self.ready = True
        except (OSError, tk.TclError):
            # Missing local assets keep the original, usable native widget skin.
            for name in ("Fantasy.TFrame", "FantasyCard.TFrame"):
                style.layout(name, style.layout("TFrame"))
            style.layout("FantasyTitle.TLabel", style.layout("TLabel"))
            for name in ("Fantasy.TButton", "FantasyPrimary.TButton"):
                style.layout(name, style.layout("TButton"))

    def load(self, name):
        image = tk.PhotoImage(master=self.style.master, file=str(DIRECTORY / name))
        self.images.append(image)
        return image

    def crop(self, source, x, y, width, height):
        image = tk.PhotoImage(master=self.style.master)
        image.tk.call(str(image), "copy", str(source), "-from", x, y, x + width, y + height)
        self.images.append(image)
        return image

    def expand(self, source, width, height, border):
        """Pre-tile small atlas centres once, avoiding thousands of paint blits.

        Tk repeats rather than stretches image elements. A one-pixel centre
        makes every window resize expensive even when artwork is disabled.
        Preserve the original nine-slice appearance with a larger repeat tile.
        """
        image = tk.PhotoImage(master=self.style.master, width=width, height=height)
        self.images.append(image)
        left, top, right, bottom = border
        sx = (0, left, source.width() - right, source.width())
        sy = (0, top, source.height() - bottom, source.height())
        dx = (0, left, width - right, width)
        dy = (0, top, height - bottom, height)
        for x in range(3):
            for y in range(3):
                image.tk.call(str(image), "copy", str(source),
                              "-from", sx[x], sy[y], sx[x + 1], sy[y + 1],
                              "-to", dx[x], dy[y], dx[x + 1], dy[y + 1])
        return image

    def draw_border(self, image, width, height):
        if width < 32 or height < 32:
            return
        left, right, top, bottom, tl, tr, bl, br = self.edges
        for source, x, y, end_x, end_y in (
                (left, 0, 16, 16, height - 16), (right, width - 16, 16, width, height - 16),
                (top, 16, 0, width - 16, 16), (bottom, 16, height - 16, width - 16, height),
                (tl, 0, 0, 16, 16), (tr, width - 16, 0, width, 16),
                (bl, 0, height - 16, 16, height), (br, width - 16, height - 16, width, height)):
            if end_x > x and end_y > y:
                image.tk.call(str(image), "copy", str(source), "-to", x, y, end_x, end_y)


def apply(style):
    if not hasattr(style, "_wow_textures"):
        style._wow_textures = WoWTextures(style)
    if style._wow_textures.ready:
        for name in ("Fantasy.TButton", "FantasyPrimary.TButton"):
            style.configure(name, foreground="#ffdd70", padding=(12, 0))
            style.map(name, foreground=[("disabled", "#b0aaa0"), ("active", "#fff4cc")])
        style.configure("FantasyTitle.TLabel", padding=(24, 20), foreground="#ffdd70")
