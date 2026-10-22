"""Fantasy styling with optional, separately stored local WoW textures."""

from tkinter import ttk, font as tkfont
import wow_textures
from control_textures import ControlTextures


def configure(style, background, card, field, foreground, size):
    # Antique brass is deliberately independent of the selected theme palette.
    brass, highlight, shadow = "#a8864c", "#d4b777", "#51402b"
    title_bg, title_fg = "#29231c", "#f2db9c"
    for name, fill in (("Fantasy.TFrame", background), ("FantasyCard.TFrame", card)):
        style.configure(name, background=fill, borderwidth=2, relief="ridge",
                        bordercolor=brass, lightcolor=highlight, darkcolor=shadow)
    style.configure("FantasyTitle.TLabel", background=title_bg, foreground=title_fg,
                    font=("Georgia", size + 3, "bold"), padding=(12, 7),
                    borderwidth=2, relief="ridge", bordercolor=brass,
                    lightcolor=highlight, darkcolor=shadow)
    style.configure("FantasyHeading.TLabel", background=title_bg, foreground=title_fg,
                    font=("Georgia", size, "bold"), padding=(8, 4))
    for name, fill, ink in (("Fantasy.TButton", card, foreground),
                            ("FantasyPrimary.TButton", "#68302a", "#fff0cc")):
        style.configure(name, background=fill, foreground=ink, borderwidth=2,
                        relief="raised", bordercolor=brass, lightcolor=highlight,
                        darkcolor=shadow, padding=(12, 6), font=("Segoe UI", size))
        style.map(name, background=[("disabled", field), ("pressed", shadow),
                                    ("active", "#493c29")],
                  foreground=[("disabled", "#948a7a"), ("active", "#fff0cc")],
                  relief=[("pressed", "sunken")], bordercolor=[("focus", highlight)])
    wow_textures.apply(style)


def style_buttons(parent):
    """Only opt-in pages receive these styles; commands and bindings are kept."""
    for widget in parent.winfo_children():
        if isinstance(widget, ttk.Button):
            current = str(widget.cget("style"))
            widget.configure(style="FantasyPrimary.TButton" if "Primary" in current else "Fantasy.TButton")
        style_buttons(widget)


def apply_workspace(host, settings_page, mode, family, size):
    """Switch the whole workspace without recreating controls or their drafts."""
    style = host.style
    style._interface_mode = mode
    textures = getattr(style, "_wow_textures", None)
    if textures and textures.ready:
        if not hasattr(style, "_control_textures"):
            style._control_textures = ControlTextures(style, textures)
        style._control_textures.apply(mode)
    aliases = {"Fantasy.TFrame": "TFrame", "FantasyCard.TFrame": "Card.TFrame",
               "FantasyTitle.TLabel": "Title.TLabel", "FantasyHeading.TLabel": "Heading.Card.TLabel",
               "Fantasy.TButton": "TButton", "FantasyPrimary.TButton": "Primary.TButton"}
    if not hasattr(style, "_skin_layouts"):
        style._skin_layouts = {name: style.layout(name) for name in aliases}
    for name, base in aliases.items():
        style.layout(name, style._skin_layouts[name] if mode == "WoW" else style.layout(base))
    for name, points, weight in (
            ("Title.TLabel", size + 8, "bold"), ("Heading.Card.TLabel", size + 1, "bold"),
            ("Value.Card.TLabel", size + 18, "bold"), ("FantasyTitle.TLabel", size + 3, "bold"),
            ("FantasyHeading.TLabel", size, "bold"), ("Fantasy.TButton", size, "normal"),
            ("FantasyPrimary.TButton", size, "normal")):
        style.configure(name, font=(family, points, weight))
    style.configure("Active.Fantasy.TButton", font=(family, size, "bold"),
                    foreground="#fff6d6")
    pages = set(host.tabs.tabs())
    page_names = {host.tabs.tab(page, "text") for page in pages}

    def walk(parent):
        for widget in parent.winfo_children():
            if isinstance(widget, (ttk.Frame, ttk.Label, ttk.Button)):
                if not hasattr(widget, "_plain_style"):
                    current = str(widget.cget("style"))
                    widget._plain_style = aliases.get(current, current)
                    widget._skin_style = current if current in aliases else None
                plain = widget._plain_style
                target = plain
                if mode == "WoW":
                    if widget._skin_style:
                        target = widget._skin_style
                    elif isinstance(widget, ttk.Button):
                        target = "FantasyPrimary.TButton" if "Primary" in plain else "Fantasy.TButton"
                    elif isinstance(widget, ttk.Frame):
                        if str(widget) in pages:
                            target = "Fantasy.TFrame"
                        elif plain == "Card.TFrame":
                            target = "FantasyCard.TFrame"
                    elif plain == "Title.TLabel" or str(widget.cget("text")) in page_names:
                        target = "FantasyTitle.TLabel"
                widget.configure(style=target)
                if isinstance(widget, ttk.Label):
                    if not hasattr(widget, "_plain_font"):
                        widget._plain_font = (tkfont.Font(root=host.root, font=widget.cget("font")).actual()
                                              if str(widget.cget("font")) else None)
                    if target == "FantasyTitle.TLabel":
                        widget.configure(font="")
                    elif widget._plain_font:
                        actual = widget._plain_font
                        widget.configure(font=(family, max(9, size + actual["size"] - 10), actual["weight"]))
            walk(widget)
    walk(host.root)
