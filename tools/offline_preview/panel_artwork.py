"""Cached, aligned artwork surfaces; geometry refreshes coalesce after layout."""

import tkinter as tk
from tkinter import ttk


class PanelArtwork:
    def __init__(self, root, style, shell):
        self.root, self.style, self.shell = root, style, shell
        self.records = {}
        self.text_records = {}
        self.layout_pending = None
        self.surfaces = {}
        self.source = None
        self.pixels = None
        self.percent = 0
        self.pending = None
        self.revision = 0
        self.prepared = False
        self.bindings = [(event, root.bind(event, self.schedule, add="+"))
                         for event in ("<Map>", "<<NotebookTabChanged>>")]
        self.bindings.append(("<Configure>", root.bind("<Configure>", self.schedule_layout, add="+")))
        self.bindings.append(("<<PreviewPageScrolled>>", root.bind("<<PreviewPageScrolled>>", self.scroll_changed, add="+")))

    def set_background(self, image, percent, pixels=None):
        self.source = image
        self.pixels = pixels
        self.percent = percent
        self.revision += 1
        if not self.prepared and percent:
            self.prepare_styles(self.shell)
            self.prepared = True
        self.schedule()

    def schedule(self, _event=None):
        # Throttle scroll/map updates; resize-driven layouts retain their debounce.
        if self.source is not None and self.percent and self.pending is None:
            self.pending = self.root.after(16, self.render)

    def schedule_layout(self, event):
        if self.source is None or not self.percent:
            return
        if not isinstance(event.widget, (ttk.Label, ttk.Checkbutton, ttk.Frame)):
            return
        if self.layout_pending is not None:
            self.root.after_cancel(self.layout_pending)
        self.layout_pending = self.root.after(150, self.refresh_layout)

    def refresh_layout(self):
        self.layout_pending = None
        self.render()

    def clear(self):
        self.prepared = False
        if self.layout_pending is not None:
            self.root.after_cancel(self.layout_pending)
            self.layout_pending = None
        for widget, record in self.text_records.items():
            if widget.winfo_exists():
                widget.configure(style=record["original"])
            record["key"] = None
            record.pop("layout_key", None)
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.source = None
        self.pixels = None
        for widget, record in self.records.items():
            if widget.winfo_exists():
                widget.configure(style=record["original"])
            record["key"] = None

    def prepare_styles(self, parent):
        """Batch all theme mutations before interaction, including hidden tabs.

        ttk style changes broadcast ThemeChanged to the whole widget tree.
        Creating styles lazily while mapping a page repeatedly restarts layout
        and drawing; cached styles avoid that work on every first tab visit.
        """
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Frame):
                self.prepare_frame(widget)
            elif isinstance(widget, (ttk.Label, ttk.Checkbutton)):
                self.prepare_text(widget)
            self.prepare_styles(widget)

    def prepare_frame(self, widget):
        record = self.records.get(widget)
        current = str(widget.cget("style"))
        original = record["original"] if record and current == record["style"] else current
        colour = self.style.lookup(original or "TFrame", "background")
        # All nested frames sample the same artwork origin. Restarting the
        # image at each frame created visible horizontal bands behind text.
        if record is None:
            photo = tk.PhotoImage(master=self.root)
            element = f"PanelCrop{len(self.records)}"
            self.style.element_create(element, "image", photo, width=1, height=1, sticky="nw")
            record = dict(original=original, style=f"LocalPanel{len(self.records)}.TFrame",
                          photo=photo, element=element)
            self.records[widget] = record
        record["original"] = original
        key = (original, colour, getattr(self.style, "_interface_mode", "WoW"))
        if record.get("key") != key:
            layout = [(record["element"], {"sticky": "nswe"})]
            textures = getattr(self.style, "_wow_textures", None)
            if original.startswith("Fantasy") and textures and textures.ready and key[2] == "WoW":
                layout.append(("WoWFrame", {"sticky": "nswe"}))
            self.style.layout(record["style"], layout)
            # Keep widget padding/geometry independent of the artwork.
            record["key"] = key
        if current != record["style"]:
            widget.configure(style=record["style"])
        return record

    def render(self):
        if self.pending is not None:
            self.root.after_cancel(self.pending)
        self.pending = None
        if self.source is None or not self.percent:
            return
        width, height = self.source.width(), self.source.height()
        raw = self.pixels

        def paint(widget):
            nonlocal raw
            record = self.records.get(widget)
            current = str(widget.cget("style"))
            original = record["original"] if record and current == record["style"] else current
            colour = self.style.lookup(original or "TFrame", "background")
            surface = self.surfaces.get(colour)
            if surface is None:
                photo = tk.PhotoImage(master=self.root)
                surface = dict(photo=photo, revision=None)
                self.surfaces[colour] = surface
            if surface["revision"] != self.revision:
                if raw is None:
                    raw = self.source.tk.call(str(self.source), "data", "-format", "ppm").split(b"\n", 3)[3]
                rgb = tuple(v // 257 for v in self.root.winfo_rgb(colour))
                pixels = bytearray(len(raw))
                for c in range(3):
                    table = bytes((v * self.percent + rgb[c] * (100 - self.percent)) // 100 for v in range(256))
                    pixels[c::3] = raw[c::3].translate(table)
                ppm = f"P6\n{width} {height}\n255\n".encode("ascii") + pixels
                surface["photo"].configure(data=ppm, format="ppm")
                surface["revision"] = self.revision
            if record is None or record.get("key") is None:
                record = self.prepare_frame(widget)
            x = widget.winfo_rootx() - self.shell.winfo_rootx()
            y = widget.winfo_rooty() - self.shell.winfo_rooty()
            w, h = max(1, widget.winfo_width()), max(1, widget.winfo_height())
            crop_key = (self.revision, colour, x, y, w, h)
            changed = record.get("crop_key") != crop_key
            if changed:
                self.copy_region(record["photo"], surface["photo"], x, y, w, h, colour)
                record["crop_key"] = crop_key
            # Photo pixels alone do not invalidate every ttk image element on Windows.
            # Invalidate pixels without changing styles or starting another layout.
            if current != record["style"]:
                widget.configure(style=record["style"])
            elif changed:
                widget.event_generate("<Expose>", width=w, height=h, count=0, when="now")

        def visit(parent):
            for widget in parent.winfo_children():
                if (not widget.winfo_ismapped() or widget.winfo_width() < 2
                        or widget.winfo_height() < 2):
                    continue
                if isinstance(widget, ttk.Frame):
                    paint(widget)
                elif isinstance(widget, (ttk.Label, ttk.Checkbutton)):
                    self.paint_text(widget)
                visit(widget)
        visit(self.shell)

    def scroll_changed(self, event):
        self.render()
        self.repaint_window(event.widget)

    def repaint_window(self, parent):
        """Repaint native controls too, after Canvas moves its child windows.

        The Windows Canvas scroll copy can leave old pixels inside newly moved
        child controls. Image updates only invalidate our artwork styles, not
        Listbox/Entry/Scale windows. Deliver Expose through Tk now so every
        visible child schedules its paint in the same idle cycle.
        """
        def expose(widget):
            if not widget.winfo_viewable():
                return
            widget.event_generate("<Expose>", width=widget.winfo_width(),
                                  height=widget.winfo_height(), count=0, when="now")
            for child in widget.winfo_children():
                expose(child)
        expose(parent)

    @staticmethod
    def copy_region(photo, source, x, y, w, h, colour):
        """Fill offscreen extents and crop visible pixels without resampling."""
        if photo.width() != w or photo.height() != h:
            photo.configure(width=w, height=h)
        if x < 0 or y < 0 or x + w > source.width() or y + h > source.height():
            photo.put(colour, to=(0, 0, w, h))
        left, top = max(0, x), max(0, y)
        right, bottom = min(x + w, source.width()), min(y + h, source.height())
        if right > left and bottom > top:
            photo.tk.call(str(photo), "copy", str(source), "-from", left, top, right, bottom,
                          "-to", left - x, top - y)

    def prepare_text(self, widget):
        parent_record = self.records.get(widget.master)
        if not parent_record:
            return
        record = self.text_records.get(widget)
        current = str(widget.cget("style"))
        original = record["original"] if record and current == record["style"] else current
        # Intentional framed titles retain their WoW artwork and contrast.
        if "FantasyTitle" in original or "FantasyHeading" in original:
            return
        base = original or ("TCheckbutton" if isinstance(widget, ttk.Checkbutton) else "TLabel")
        if record is None:
            photo = tk.PhotoImage(master=self.root)
            element = f"TextSurface{len(self.text_records)}"
            self.style.element_create(element, "image", photo, width=0, height=0, sticky="nw")
            record = dict(photo=photo, element=element)
            self.text_records[widget] = record
        name = f"ArtworkText{record['element']}.{base}"
        record.update(original=original, style=name)
        layout_key = (base, self.style.lookup(base, "padding"), self.style.lookup(base, "borderwidth"))
        if record.get("layout_key") != layout_key:
            self.configure_text_layout(widget, record, name, base)
            # Stable palette ink avoids colour flashes and global ThemeChanged
            # broadcasts while artwork moves under text or opacity changes.
            self.style.configure(name, foreground=self.style.lookup(base, "foreground"))
            record["layout_key"] = layout_key
        if current != record["style"]:
            widget.configure(style=record["style"])
        return record

    def paint_text(self, widget):
        parent_record = self.records.get(widget.master)
        record = self.text_records.get(widget)
        if parent_record is None or record is None:
            return
        current = str(widget.cget("style"))
        name = record["style"]
        base = record["original"] or ("TCheckbutton" if isinstance(widget, ttk.Checkbutton) else "TLabel")
        x, y = widget.winfo_x(), widget.winfo_y()
        w, h = max(1, widget.winfo_width()), max(1, widget.winfo_height())
        source = parent_record["photo"]
        key = (self.revision, parent_record.get("crop_key"), x, y, w, h, str(source), base)
        changed = record.get("key") != key
        if changed:
            photo = record["photo"]
            colour = self.style.lookup(parent_record["original"] or "TFrame", "background")
            self.copy_region(photo, source, x, y, w, h, colour)
            record["key"] = key
        if current != name:
            widget.configure(style=name)
        elif changed:
            widget.event_generate("<Expose>", width=w, height=h, count=0, when="now")

    def configure_text_layout(self, widget, record, name, base):
        if isinstance(widget, ttk.Label):
            # Clam's Label.border reserves two pixels even when borderwidth
            # is unspecified. Preserve those insets after removing its fill;
            # otherwise toggling transparency shrinks every label by 4px.
            border = widget.cget("borderwidth") or self.style.lookup(base, "borderwidth") or 2
            border = self.root.winfo_pixels(border)
            padding = self.root.tk.splitlist(self.style.lookup(base, "padding"))
            padding = [self.root.winfo_pixels(v) for v in padding] or [0]
            if len(padding) == 1:
                padding *= 4
            elif len(padding) == 2:
                padding *= 2
            elif len(padding) == 3:
                padding.append(padding[1])
            self.style.configure(name, padding=tuple(v + border for v in padding))
            layout = [("Label.padding", {"sticky": "nswe", "children": [("Label.label", {"sticky": "nswe"})]})]
        else:
            layout = self.style.layout(base)
        self.style.layout(name, [(record["element"], {"sticky": "nswe"}), *layout])

    def close(self):
        self.clear()
        for event, binding in self.bindings:
            self.root.unbind(event, binding)
