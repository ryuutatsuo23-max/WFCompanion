"""Local presentation preferences and an inert support-planning page."""

from copy import deepcopy
import math
from pathlib import Path
import re
import struct
import tempfile
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk, font as tkfont

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None
import wave

from local_journal import LocalStore
from panel_artwork import PanelArtwork
import fantasy_style
from ui_layout import ScrollPage, WrapRow
from appearance_catalogue import FONT_CHOICES, THEMES, THEME_ART, ART_DIRECTORY


from display_settings import DEFAULT, validate_preferences


class PreferencesUI:
    def __init__(self, host, navigation, banner):
        self.host, self.navigation, self.banner = host, navigation, banner
        self.store = LocalStore(host.store.directory, "display_settings.json", DEFAULT, validate_preferences)
        self.page = ttk.Frame(host.tabs, style="Fantasy.TFrame", padding=6)
        host.tabs.add(self.page, text="Settings")
        self.unsaved_indicator = ttk.Button(self.page, command=self.save, style="Nav.TButton")
        self.unsaved_indicator.pack(anchor="w", padx=4, pady=(0, 4))
        self.scroll = ScrollPage(self.page)
        self.scroll.pack(fill="both", expand=True)
        p = self.scroll.inner
        self.heading = ttk.Label(p, text="Welcome! Choose your workspace" if not self.store.data["setup"] else "Settings",
                                 style="FantasyTitle.TLabel")
        self.heading.pack(fill="x")
        ttk.Label(p, text="Choose the tabs you want. Hiding a tab keeps its data and unfinished edits. "
                  "You can change these options here at any time.", wraplength=740, style="Muted.TLabel").pack(anchor="w", pady=8)
        self.tab_choices = {}
        ttk.Label(p, text="Workspace · visible tabs", style="FantasyHeading.TLabel").pack(fill="x", pady=(4, 6))
        choices = self.choices_row = WrapRow(p)
        self.choice_buttons = {}
        choices.pack(fill="x")
        self.pages = [(tab, host.tabs.tab(tab, "text")) for tab in host.tabs.tabs()]
        saved_order = self.store.data.get("order", [])
        self.order = [label for label in saved_order if label in dict((label, tab) for tab, label in self.pages)]
        self.order += [label for _, label in self.pages if label not in self.order]
        for index, (tab, label) in enumerate(self.pages):
            if label == "Settings":
                continue
            var = tk.BooleanVar(value=label not in self.store.data["hidden"])
            self.tab_choices[label] = var
            self.choice_buttons[label] = ttk.Checkbutton(choices, text=label, variable=var)
        choices.set_items(self.choice_buttons[label] for label in self.order if label in self.choice_buttons)
        ttk.Label(p, text="Tab order · select a section and move it up or down").pack(anchor="w", pady=(10, 2))
        order_frame = ttk.Frame(p)
        order_frame.pack(fill="x")
        self.order_list = tk.Listbox(order_frame, height=5, exportselection=False)
        self.order_list.pack(side="left", fill="both", expand=True)
        order_scroll = ttk.Scrollbar(order_frame, command=self.order_list.yview)
        order_scroll.pack(side="right", fill="y")
        self.order_list.configure(yscrollcommand=order_scroll.set)
        self.order_list.insert("end", *self.order)
        row = ttk.Frame(p)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Move up", command=lambda: self.move_tab(-1)).pack(side="left")
        ttk.Button(row, text="Move down", command=lambda: self.move_tab(1)).pack(side="left", padx=8)
        self.reset_order_button = ttk.Button(row, text="Reset tab order", command=self.reset_tab_order)
        self.reset_order_button.pack(side="left")
        self.theme = tk.StringVar(value=self.store.data["theme"])
        self.font_family = tk.StringVar(value=self.store.data.get("font_family", "Segoe UI"))
        self.ui_style = tk.StringVar(value=self.store.data.get("ui_style", "WoW"))
        self.background = tk.StringVar(value=self.store.data["background"])
        self.image_path = tk.StringVar(value=self.store.data["image"])
        self.show_artwork = tk.BooleanVar(value=self.store.data.get("show_artwork", True))
        self.artwork_mode = tk.StringVar(value=self.store.data.get("artwork_mode", "Header"))
        self.panel_transparency = tk.StringVar(value=str(self.store.data.get("panel_transparency", 0)))
        self.size = tk.StringVar(value=str(self.store.data["text_size"]))
        self.volume = tk.IntVar(value=self.store.data["volume"])
        host.sound.set(self.store.data["sound"])
        ttk.Label(p, text="Appearance", style="FantasyHeading.TLabel").pack(fill="x", pady=(12, 4))
        appearance_row = WrapRow(p)
        appearance_row.pack(fill="x")
        self.theme_category = tk.StringVar(value=self.category_for(self.theme.get()))
        appearance_items = []
        for label, var, values in (("Theme category", self.theme_category, ("General", "Places", "Classes", "Races")),
                                   ("Theme", self.theme, tuple(THEMES)),
                                   ("Interface style", self.ui_style, ("Standard", "WoW"))):
            group = ttk.Frame(appearance_row)
            ttk.Label(group, text=label).pack(anchor="w", pady=(8, 2))
            combo = ttk.Combobox(group, textvariable=var, values=values, state="readonly")
            combo.pack(anchor="w")
            if label == "Theme":
                self.theme_combo = combo
            elif label == "Theme category":
                combo.bind("<<ComboboxSelected>>", self.choose_category)
            appearance_items.append(group)
        appearance_row.set_items(appearance_items)
        self.refresh_theme_choices()
        installed_fonts = set(tkfont.families(host.root))
        font_row = ttk.Frame(p)
        font_row.pack(anchor="w")
        for col, (label, var, values) in enumerate((("Font style", self.font_family, tuple(f for f in FONT_CHOICES if f in installed_fonts)),
                                   ("Text size · points", self.size, tuple(str(x) for x in range(9, 19))))):
            ttk.Label(font_row, text=label).grid(row=0, column=col, sticky="w", pady=(10, 2), padx=(0, 12))
            ttk.Combobox(font_row, textvariable=var, values=values, state="readonly", width=22).grid(row=1, column=col, sticky="w", padx=(0, 12))
        ttk.Label(p, text="Themes include local Blizzard artwork and matching colours. Class/race themes use their own official backdrops. "
                  "Custom colour/picture fields override the theme; clear them to use its defaults.",
                  wraplength=740, style="Muted.TLabel").pack(anchor="w", pady=6)
        ttk.Checkbutton(p, text="Show theme artwork", variable=self.show_artwork).pack(anchor="w")
        ttk.Combobox(p, textvariable=self.artwork_mode, values=("Header", "Full background"),
                     state="readonly", width=22).pack(anchor="w", pady=4)
        ttk.Label(p, text="Full background fills the window; panel transparency reveals more artwork.",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Label(p, text="Panel transparency % · 0 = solid, 60 = most artwork").pack(anchor="w", pady=(6, 2))
        transparency_row = ttk.Frame(p)
        transparency_row.pack(anchor="w")
        self.transparency_position = tk.DoubleVar(value=float(self.panel_transparency.get()))
        self.transparency_slider = ttk.Scale(
            transparency_row, from_=0, to=60, variable=self.transparency_position,
            command=self.change_transparency, length=280)
        self.transparency_slider.pack(side="left", padx=(0, 12))
        self.transparency_slider.bind("<ButtonRelease-1>", lambda _event: self.preview(), add="+")
        self.transparency_slider.bind("<KeyRelease>", lambda _event: self.preview(), add="+")
        self.transparency_percentage = ttk.Label(transparency_row, width=5, anchor="e")
        self.transparency_percentage.pack(side="right")
        self.sync_transparency()
        self.panel_transparency.trace_add("write", self.sync_transparency)
        ttk.Label(p, text="Full background only. Labels blend with panels; framed headings, inputs and tables stay readable.",
                  style="Muted.TLabel", wraplength=740).pack(anchor="w", pady=4)
        row = ttk.Frame(p)
        row.pack(fill="x", pady=10)
        ttk.Checkbutton(row, text="Reminder sound", variable=host.sound).pack(side="left")
        ttk.Label(row, text="Volume %").pack(side="left", padx=10)
        ttk.Spinbox(row, from_=0, to=100, textvariable=self.volume, width=6).pack(side="left")
        ttk.Button(row, text="Test sound", command=self.test_sound).pack(side="left", padx=10)
        ttk.Label(p, text="Custom background · blank uses theme").pack(anchor="w")
        ttk.Entry(p, textvariable=self.background).pack(fill="x")
        ttk.Button(p, text="Choose colour", command=self.pick_colour).pack(anchor="w", pady=5)
        ttk.Label(p, text="Optional local background artwork · PNG / GIF").pack(anchor="w")
        ttk.Entry(p, textvariable=self.image_path).pack(fill="x")
        row = ttk.Frame(p)
        row.pack(fill="x", pady=5)
        ttk.Button(row, text="Choose picture", command=self.pick_image).pack(side="left")
        ttk.Button(row, text="Use theme picture", command=lambda: self.image_path.set("")).pack(side="left", padx=8)
        actions = ttk.Frame(p)
        actions.pack(anchor="w", pady=12)
        self.save_button = ttk.Button(actions, text="Save settings", command=self.save, style="Primary.TButton")
        self.save_button.pack(side="left")
        self.revert_button = ttk.Button(actions, text="Revert unsaved settings", command=self.revert)
        self.revert_button.pack(side="left", padx=8)
        self.defaults_button = ttk.Button(actions, text="Restore defaults", command=self.restore_defaults)
        self.defaults_button.pack(side="left")
        self.notice = ttk.Label(p, style="Muted.TLabel", wraplength=740)
        self.notice.pack(anchor="w")
        self.audio_dir = tempfile.TemporaryDirectory(prefix="wow-preview-sound-")
        self.audio_path = None
        self.photo = None
        self.background_source = None
        self.background_pil = None
        self.background_size = None
        self.background_pixels = None
        self.background_photo = None
        self.background_pending = None
        self.background_label = ttk.Label(banner.master, anchor="center")
        banner.master.bind("<Configure>", self.schedule_background, add="+")
        self.panel_artwork = PanelArtwork(host.root, host.style, banner.master)
        self.buttons = {}
        self.preview_pending = None
        self.suspend_preview = False
        self.runtime_data = deepcopy(self.store.data)
        host.tabs.bind("<<NotebookTabChanged>>", self.highlight, add="+")
        self.apply()
        for var in (*self.tab_choices.values(), self.theme, self.background, self.image_path,
                    self.size, self.volume, host.sound, self.font_family, self.ui_style, self.show_artwork, self.artwork_mode, self.panel_transparency):
            var.trace_add("write", self.schedule_preview)
        self.update_unsaved_indicator()
        if self.store.error:
            self.notice.configure(text=self.store.error)
            self.save_button.state(["disabled"])
        if not self.store.data["setup"]:
            host.tabs.select(self.page)

    def pick_colour(self):
        _, colour = colorchooser.askcolor(parent=self.host.root)
        if colour:
            self.background.set(colour)

    @staticmethod
    def category_for(theme):
        if theme.startswith("Class ·"):
            return "Classes"
        if theme.startswith("Race ·"):
            return "Races"
        if theme.startswith("Forever ·") or theme in ("Stormwind · Alliance", "Orgrimmar · Horde"):
            return "Places"
        return "General"

    def refresh_theme_choices(self):
        choices = tuple(name for name in THEMES if self.category_for(name) == self.theme_category.get())
        self.theme_combo.configure(values=choices)
        self.theme_combo.configure(width=max(len(name) for name in choices) + 2)

    def choose_category(self, _event=None):
        self.refresh_theme_choices()
        choices = self.theme_combo.cget("values")
        if self.theme.get() not in choices:
            self.theme.set(choices[0])

    def change_transparency(self, value):
        percent = max(0, min(60, int(float(value) + 0.5)))
        if self.panel_transparency.get() != str(percent):
            # Do not write the rounded display value back into the Scale's
            # continuous variable during its native pointer-drag calculation.
            self._slider_command = True
            try:
                self.panel_transparency.set(str(percent))
            finally:
                self._slider_command = False

    def sync_transparency(self, *_):
        """Keep slider and percentage aligned on load, preview and Revert."""
        try:
            percent = int(self.panel_transparency.get())
        except ValueError:
            return
        if not getattr(self, "_slider_command", False):
            self.transparency_position.set(percent)
        self.transparency_percentage.configure(text=f"{percent}%")

    def pick_image(self):
        path = filedialog.askopenfilename(parent=self.host.root, filetypes=[("Local artwork", "*.png *.gif")])
        if path:
            self.image_path.set(path)

    def save(self):
        try:
            self.cancel_preview()
            data = self.form_data()
            data["setup"] = True
            self.load_picture(data["image"])  # Validate before committing settings.
            self.store.save(data)
            self.apply()
            self.heading.configure(text="Settings")
            self.notice.configure(text="Settings saved. Character data and unfinished forms unchanged.")
            return True
        except (ValueError, OSError, tk.TclError) as exc:
            self.notice.configure(text=str(exc))
            return False
        finally:
            self.update_unsaved_indicator()

    def update_unsaved_indicator(self):
        """Compare editable choices only, not setup/version or support notes."""
        saved = self.store.data
        labels = [label for _, label in self.pages]
        saved_order = [label for label in saved.get("order", []) if label in labels]
        saved_order += [label for label in labels if label not in saved_order]
        try:
            current = self.form_data()
            dirty = (current["order"] != saved_order
                     or set(current["hidden"]) != set(saved["hidden"]).intersection(self.tab_choices)
                     or any(current[key] != saved.get(key, {"panel_transparency": 0, "artwork_mode": "Header"}.get(key, DEFAULT[key])) for key in
                            ("theme", "background", "image", "sound", "volume", "text_size", "show_artwork", "artwork_mode", "panel_transparency", "font_family", "ui_style")))
        except (ValueError, tk.TclError):
            # Incomplete entries still need attention even if preview is blocked.
            dirty = True
        self.unsaved_indicator.configure(text="Unsaved settings" if dirty else "No unsaved settings")
        self.unsaved_indicator.state(["!disabled"] if dirty and not self.store.error else ["disabled"])

    def form_data(self):
        data = deepcopy(self.store.data)
        data.update(version=5, font_family=self.font_family.get(), ui_style=self.ui_style.get(), panel_transparency=int(self.panel_transparency.get()), show_artwork=self.show_artwork.get(), artwork_mode=self.artwork_mode.get(), order=list(self.order),
                    hidden=[label for label, var in self.tab_choices.items() if not var.get()],
                    theme=self.theme.get(), background=self.background.get().strip(), image=self.image_path.get().strip(),
                    sound=self.host.sound.get(), volume=self.volume.get(), text_size=int(self.size.get()))
        validate_preferences(data)
        return data

    def cancel_preview(self):
        if self.preview_pending is not None:
            self.host.root.after_cancel(self.preview_pending)
            self.preview_pending = None

    def schedule_preview(self, *_):
        if not self.suspend_preview:
            self.update_unsaved_indicator()
        if not self.suspend_preview and self.preview_pending is None:
            self.preview_pending = self.host.root.after_idle(self.preview)

    def preview(self):
        self.cancel_preview()
        try:
            data = self.form_data()
            if data["image"] != self.runtime_data["image"]:
                self.load_picture(data["image"])
            self.apply(data)
            self.notice.configure(text="Preview only · Save settings to keep these changes, or Revert.")
        except (ValueError, OSError, tk.TclError) as exc:
            self.notice.configure(text=f"Finish the setting to preview it: {exc}")

    def move_tab(self, direction):
        selected = self.order_list.curselection()
        if not selected:
            return
        index = selected[0]
        target = index + direction
        if not 0 <= target < len(self.order):
            return
        self.order[index], self.order[target] = self.order[target], self.order[index]
        self.order_list.delete(0, "end")
        self.order_list.insert("end", *self.order)
        self.order_list.selection_set(target)
        self.order_list.see(target)
        self.schedule_preview()

    def reset_tab_order(self):
        """Restore presentation order only; saving remains explicit."""
        selected = self.order_list.curselection()
        label = self.order[selected[0]] if selected else None
        self.order = [name for _, name in self.pages]
        self.order_list.delete(0, "end")
        self.order_list.insert("end", *self.order)
        if label in self.order:
            index = self.order.index(label)
            self.order_list.selection_set(index)
            self.order_list.see(index)
        self.schedule_preview()

    def revert(self):
        self.load_form(self.store.data, "Unsaved settings reverted. Other unfinished forms are unchanged.")

    def restore_defaults(self):
        self.load_form(DEFAULT, "Default settings previewed. Save to keep them, or Revert to return to your saved settings.")

    def load_form(self, data, message):
        self.cancel_preview()
        self.suspend_preview = True
        try:
            for label, var in self.tab_choices.items():
                var.set(label not in data["hidden"])
            for var, key in ((self.theme, "theme"), (self.background, "background"), (self.image_path, "image"),
                             (self.size, "text_size"), (self.volume, "volume"), (self.host.sound, "sound"),
                             (self.show_artwork, "show_artwork"), (self.artwork_mode, "artwork_mode"),
                             (self.panel_transparency, "panel_transparency"), (self.font_family, "font_family"), (self.ui_style, "ui_style")):
                var.set(data.get(key, {"panel_transparency": 0, "artwork_mode": "Header"}.get(key, DEFAULT[key])))
            self.order = [label for label in data.get("order", []) if label in [name for _, name in self.pages]]
            self.order += [label for _, label in self.pages if label not in self.order]
            self.order_list.delete(0, "end")
            self.order_list.insert("end", *self.order)
            self.apply()
            self.notice.configure(text=message)
        finally:
            self.suspend_preview = False
            self.update_unsaved_indicator()

    def load_picture(self, path):
        if not path:
            return None
        file = Path(path)
        if not file.is_absolute() or file.suffix.lower() not in (".png", ".gif") or file.stat().st_size > 20_000_000:
            raise ValueError("Choose a local PNG/GIF up to 20 MB.")
        image = tk.PhotoImage(file=str(file), master=self.host.root)
        factor = max(1, math.ceil(image.width() / 800), math.ceil(image.height() / 100))
        return image.subsample(factor)

    def theme_picture(self, data):
        if data["image"]:
            return self.load_picture(data["image"])
        filename = THEME_ART.get(data["theme"])
        if not filename:
            return None
        file = ART_DIRECTORY / filename
        if not file.exists():
            self.notice.configure(text="Theme artwork is missing locally; colours remain available.")
            return None
        source = tk.PhotoImage(file=str(file), master=self.host.root)
        # A bounded viewport into the original image, not a modified asset.
        # Keep form text off the artwork and avoid increasing the minimum width.
        factor = max(1, math.ceil(source.width() / 900))
        width = min(source.width(), 820 * factor)
        height = min(source.height(), 140 * factor)
        x = (source.width() - width) // 2
        y = (source.height() - height) // 2
        picture = tk.PhotoImage(master=self.host.root)
        picture.tk.call(str(picture), "copy", str(source), "-from", x, y, x + width, y + height,
                        "-subsample", factor, factor)
        return picture

    def apply(self, data=None):
        data = self.store.data if data is None else data
        self.runtime_data = deepcopy(data)
        previous = getattr(self, "_applied_data", None)
        self._applied_data = deepcopy(data)
        # A slider drag only recomposites panels, preserving geometry, focus and
        # scroll position. It must not reload artwork or recreate navigation.
        if previous is not None and all(previous.get(key) == data.get(key) for key in
                ("hidden", "order", "theme", "background", "image", "text_size", "show_artwork", "artwork_mode", "font_family", "ui_style")):
            if previous.get("panel_transparency", 0) != data.get("panel_transparency", 0):
                percent = data.get("panel_transparency", 0)
                if percent == 0:
                    self.panel_artwork.clear()
                elif self.background_photo is not None:
                    self.panel_artwork.set_background(self.background_photo, percent, self.background_pixels)
            return
        self.theme_category.set(self.category_for(data["theme"]))
        self.refresh_theme_choices()
        for widget in self.navigation.winfo_children():
            widget.destroy()
        self.buttons.clear()
        rank = {label: i for i, label in enumerate(data.get("order", []))}
        ordered = sorted(self.pages, key=lambda pair: rank.get(pair[1], len(rank) + self.pages.index(pair)))
        visible = [(tab, label) for tab, label in ordered if label not in data["hidden"] or label == "Settings"]
        if self.host.tabs.select() not in [tab for tab, _ in visible]:
            self.host.tabs.select(self.page)
        for index, (tab, label) in enumerate(ordered):
            self.host.tabs.insert(index, tab)
            if (tab, label) in visible:
                self.host.tabs.add(tab)
            else:
                self.host.tabs.hide(tab)
        for index, (tab, label) in enumerate(visible):
            button = ttk.Button(self.navigation, text=label, command=lambda t=tab: self.host.tabs.select(t))
            self.buttons[tab] = button
        self.navigation.set_items(self.buttons.values())
        self.panel_artwork.clear()
        self.palette(data)
        try:
            self.background_label.place_forget()
            self.background_source = None
            self.background_pil = None
            self.background_size = None
            self.background_pixels = None
            self.background_photo = None
            self.background_label.configure(image="")
            full = data.get("show_artwork", True) and data.get("artwork_mode", "Header") == "Full background"
            self.photo = self.theme_picture(data) if data.get("show_artwork", True) and not full else None
            if full:
                path = data["image"] or (str(ART_DIRECTORY / THEME_ART[data["theme"]]) if data["theme"] in THEME_ART else "")
                if path and Path(path).is_file():
                    self.background_source = tk.PhotoImage(file=path, master=self.host.root)
                    if Image is not None:
                        with Image.open(path) as loaded:
                            self.background_pil = loaded.convert("RGB")
                    self.render_background()
            self.banner.configure(image=self.photo if self.photo else "")
            if self.photo:
                self.banner.pack(fill="x", pady=4, before=self.navigation)
            else:
                self.banner.pack_forget()
        except (ValueError, OSError, tk.TclError) as exc:
            self.banner.pack_forget()
            self.notice.configure(text=f"Artwork unavailable: {exc}")
        self.choices_row.set_items(self.choice_buttons[label] for label in self.order if label in self.choice_buttons)
        self.highlight()

    def schedule_background(self, _event=None):
        # Keep the last completed image while dragging. Rebuilding full-size
        # artwork and every tinted surface during native resize blocks Tk paint.
        # Preferences still render immediately through apply(); only geometry
        # changes wait briefly for the user to finish moving the window edge.
        if self.background_source is None:
            return
        parent = self.banner.master
        size = (max(1, parent.winfo_width()), max(1, parent.winfo_height()))
        if size == self.background_size:
            return
        if self.background_pending is not None:
            self.host.root.after_cancel(self.background_pending)
        self.background_pending = self.host.root.after(100, self.render_background)

    def render_background(self):
        if self.background_pending is not None:
            self.host.root.after_cancel(self.background_pending)
        self.background_pending = None
        source = self.background_source
        if source is None:
            return
        parent = self.banner.master
        width, height = max(1, parent.winfo_width()), max(1, parent.winfo_height())
        if self.background_size == (width, height):
            return
        self.background_size = (width, height)
        if self.background_pil is not None:
            resized = ImageOps.fit(self.background_pil, (width, height), method=Image.Resampling.BILINEAR)
            ppm = f"P6\n{width} {height}\n255\n".encode("ascii") + resized.tobytes()
        else:
            # Tk zoom/subsample applies integer sampling before enlargement and makes
            # fractional reductions blocky. Sample source pixels directly instead.
            scale = max(width / source.width(), height / source.height())
            left = (source.width() - width / scale) / 2
            top = (source.height() - height / scale) / 2
            raw = source.tk.call(str(source), "data", "-format", "ppm").split(b"\n", 3)[3]
            offsets = [min(source.width() - 1, int(left + x / scale)) * 3 for x in range(width)]
            rows = {}
            output = []
            stride = source.width() * 3
            for y in range(height):
                sy = min(source.height() - 1, int(top + y / scale))
                if sy not in rows:
                    row = raw[sy * stride:(sy + 1) * stride]
                    rows[sy] = b"".join(row[x:x + 3] for x in offsets)
                output.append(rows[sy])
            ppm = f"P6\n{width} {height}\n255\n".encode("ascii") + b"".join(output)
        if self.background_photo is None:
            self.background_photo = tk.PhotoImage(master=self.host.root)
        self.background_photo.configure(data=ppm, format="ppm")
        self.background_pixels = ppm.split(b"\n", 3)[3]
        self.background_label.configure(image=self.background_photo)
        self.background_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.background_label.lower()
        self.panel_artwork.set_background(self.background_photo, self.runtime_data.get("panel_transparency", 0),
                                          self.background_pixels)

    def palette(self, data=None):
        data = self.runtime_data if data is None else data
        bg, card, field, fg, muted, accent = THEMES[data["theme"]]
        bg = data["background"] or bg
        style = self.host.style
        size = data["text_size"]
        family = data.get("font_family", "Segoe UI")
        self.host.text_size = size
        self.host.theme_muted = muted
        self.host.theme_accent = accent
        style.configure(".", font=(family, size), background=bg, foreground=fg)
        for name in ("TFrame", "TLabel", "TCheckbutton", "TNotebook"):
            style.configure(name, background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg)])
        for name in ("Card.TFrame", "Card.TLabel", "Muted.Card.TLabel", "Value.Card.TLabel", "Heading.Card.TLabel"):
            style.configure(name, background=card, foreground=fg)
        style.configure("Muted.Card.TLabel", foreground=muted)
        style.configure("Muted.TLabel", foreground=muted)
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(name, fieldbackground=field, foreground=fg, insertcolor=fg, background=card, arrowcolor=fg)
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)])
        style.configure("TButton", background=card, foreground=fg)
        style.map("TButton", background=[("active", field)], foreground=[("disabled", muted)])
        style.configure("Nav.TButton", padding=(6, 3))
        style.configure("NavPrimary.TButton", padding=(6, 3), background=accent, foreground=bg)
        style.map("NavPrimary.TButton", background=[("active", accent)])
        style.configure("Primary.TButton", background=accent, foreground=bg)
        style.map("Primary.TButton", background=[("active", accent)])
        style.configure("Treeview", background=card, fieldbackground=card, foreground=fg, rowheight=size * 2 + 9)
        style.map("Treeview", background=[("selected", accent)], foreground=[("selected", bg)])
        style.configure("Treeview.Heading", background=field, foreground=fg)
        for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(name, background=card, troughcolor=bg, arrowcolor=muted)
        self.host.root.configure(background=bg)
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Listbox):
                    child.configure(background=field, foreground=fg, font=(family, size),
                                    selectbackground=accent, selectforeground=bg)
                elif isinstance(child, tk.Text):
                    child.configure(background=field, foreground=fg, insertbackground=fg, font=(family, size))
                elif isinstance(child, tk.Canvas):
                    child.configure(background=bg)
                elif isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Spinbox)):
                    child.configure(font=(family, size))
                elif isinstance(child, ttk.Label):
                    colour = str(child.cget("foreground")).lower()
                    mapping = {palette[index]: target for palette in THEMES.values()
                               for index, target in ((3, fg), (4, muted), (5, accent))}
                    if colour in mapping:
                        child.configure(foreground=mapping[colour])
                walk(child)
        walk(self.host.root)
        for meter in (self.host.own_meter, self.host.party_meter):
            meter.theme_accent = accent
            meter.theme_muted = muted
            meter.theme_red = "#aa263c" if data["theme"] == "Normal" else "#ff929e"
            meter.bar.configure(background=card)
            meter.bar.itemconfigure(meter.track_item, fill=field)
        self.fit_choices(self.host.root)
        self.host.root.option_add("*TCombobox*Listbox.font", (family, size))
        self.host.root.option_add("*TCombobox*Listbox.background", field)
        self.host.root.option_add("*TCombobox*Listbox.foreground", fg)
        fantasy_style.configure(style, bg, card, field, fg, size)
        fantasy_style.apply_workspace(self.host, self.page, data.get("ui_style", "WoW"), family, size)

    def fit_choices(self, parent):
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Combobox):
                popup_list = f"{widget}.popdown.f.l"
                if widget.tk.call("winfo", "exists", popup_list):
                    widget.tk.call(popup_list, "configure", "-font", widget.cget("font"),
                                   "-background", self.host.style.lookup("TCombobox", "fieldbackground"),
                                   "-foreground", self.host.style.lookup("TCombobox", "foreground"))
                values = widget.cget("values")
                if values:
                    font = tkfont.Font(root=self.host.root, font=widget.cget("font") or self.host.style.lookup("TCombobox", "font"))
                    width = math.ceil(max(font.measure(str(value)) for value in values) / max(1, font.measure("0"))) + 2
                    widget.configure(width=min(48, max(5, width)))
                    # Content-sized grid/pack choices must not stretch with a page.
                    if widget.winfo_manager() == "grid":
                        widget.grid_configure(sticky="w")
                    elif widget.winfo_manager() == "pack":
                        widget.pack_configure(fill="none", expand=False, anchor="w")
            self.fit_choices(widget)

    def highlight(self, _event=None):
        for tab, button in self.buttons.items():
            selected = tab == self.host.tabs.select()
            wow = self.runtime_data.get("ui_style", "WoW") == "WoW"
            button.configure(style=("Active.Fantasy.TButton" if selected else "Fantasy.TButton") if wow
                             else ("NavPrimary.TButton" if selected else "Nav.TButton"))
        self.navigation.schedule()

    def play_sound(self, volume=None):
        """Amplitude-scaled local WAV; never change the Windows mixer volume."""
        try:
            import winsound
            volume = self.runtime_data["volume"] if volume is None else volume
            if not 0 <= volume <= 100:
                raise ValueError("Volume must be 0–100.")
            if volume == 0:
                return
            path = Path(self.audio_dir.name) / f"reminder-{volume}.wav"
            if not path.exists():
                with wave.open(str(path), "wb") as stream:
                    stream.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                    frames = [int(12000 * volume / 100 * math.sin(2 * math.pi * 660 * i / 22050)
                                  * min(1, i / 220, (4409 - i) / 220)) for i in range(4410)]
                    stream.writeframes(struct.pack("<" + "h" * len(frames), *frames))
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except (ImportError, RuntimeError, OSError, ValueError, tk.TclError) as exc:
            self.notice.configure(text=f"Sound unavailable: {exc}")

    def test_sound(self):
        try:
            self.play_sound(self.volume.get())
        except tk.TclError:
            self.notice.configure(text="Volume must be a whole number from 0 to 100.")

    def close(self):
        self.panel_artwork.close()
        self.cancel_preview()
        if self.background_pending is not None:
            self.host.root.after_cancel(self.background_pending)
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except (ImportError, RuntimeError):
            pass
        self.audio_dir.cleanup()


class SupportUI:
    def __init__(self, host):
        self.host = host
        self.page = ttk.Frame(host.tabs)
        host.tabs.add(self.page, text="Auto-support")
        scroll = ScrollPage(self.page)
        scroll.pack(fill="both", expand=True)
        p = scroll.inner
        ttk.Label(p, text="Auto-support · planning only", style="Title.TLabel").pack(anchor="w")
        ttk.Label(p, text="Plan a class-neutral support idea for this character. No keypress backend is connected. "
                  "Healing, taunting and gathering interaction need separate live compatibility checks.",
                  wraplength=740, style="Muted.TLabel").pack(anchor="w", pady=10)
        self.kind = tk.StringVar(value="Healing")
        self.key = tk.StringVar()
        self.note = tk.StringVar()
        ttk.Combobox(p, textvariable=self.kind, values=("Healing", "Taunting", "Gathering interact", "Other"), state="readonly").pack(anchor="w")
        for label, var in (("Preferred binding · text only", self.key), ("Conditions / behaviour to explore", self.note)):
            ttk.Label(p, text=label).pack(anchor="w", pady=(10, 2))
            ttk.Entry(p, textvariable=var).pack(fill="x")
        ttk.Button(p, text="Save support idea", command=self.save).pack(anchor="w", pady=10)
        ttk.Button(p, text="Keypress sending unavailable", state="disabled").pack(anchor="w")
        self.notice = ttk.Label(p, wraplength=740, style="Muted.TLabel")
        self.notice.pack(anchor="w", pady=8)
        self.active = None
        self.drafts = {}

    def refresh(self):
        if self.active == self.host.profile.id:
            return
        if self.active:
            self.drafts[self.active] = dict(kind=self.kind.get(), key=self.key.get(), note=self.note.get())
        self.active = self.host.profile.id
        data = self.drafts.get(self.active, self.host.preferences.store.data["support"].get(self.active,
                               dict(kind="Healing", key="", note="")))
        for key, var in (("kind", self.kind), ("key", self.key), ("note", self.note)):
            var.set(data[key])
        self.notice.configure(text="Manual planning only. No keys are sent.")

    def save(self):
        try:
            data = deepcopy(self.host.preferences.store.data)
            data["support"][self.host.profile.id] = dict(kind=self.kind.get(), key=self.key.get(), note=self.note.get())
            validate_preferences(data)
            if not self.host.ensure_plan_profile():
                return False
            self.host.preferences.store.save(data)
            self.notice.configure(text="Support idea saved for this character. Keypress sending remains disabled.")
            return True
        except (ValueError, OSError) as exc:
            self.notice.configure(text=str(exc))
            return False
