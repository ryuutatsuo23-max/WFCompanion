"""Window-only persistence and reversible Settings layout regressions."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
from app import PreviewApp
from window_placement import WindowPlacement, visible_rect
from preferences_ui import DEFAULT


class PlacementTests(unittest.TestCase):
    def test_restore_geometry_and_preserve_external_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            placement = WindowPlacement(root, folder)
            root.geometry("1000x820+60+70")
            root.update()
            placement.close()
            root.destroy()
            path = Path(folder) / "window_placement.json"
            data = json.loads(path.read_text())
            self.assertEqual(data["normal"], [1000, 820, 60, 70])
            root = tk.Tk()
            placement = WindowPlacement(root, folder)
            root.update()
            self.assertEqual(root.geometry(), "1000x820+60+70")
            external = path.read_bytes() + b" "
            path.write_bytes(external)
            root.geometry("1050x830+80+90")
            root.update()
            placement.close()
            root.destroy()
            self.assertEqual(path.read_bytes(), external)

    def test_missing_monitor_and_negative_monitor_coordinates(self):
        self.assertEqual(visible_rect([1200, 900, 9000, 8000], [(0, 0, 1920, 1080)]),
                         [1200, 900, 720, 180])
        self.assertEqual(visible_rect([1000, 820, -1500, 60],
                                     [(-1920, 0, 0, 1080), (0, 0, 1920, 1080)]),
                         [1000, 820, -1500, 60])


class SettingsLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = PreviewApp(self.root, Path(self.temp.name))
        self.p = self.app.preferences
        self.p.show_artwork.set(False)
        self.p.preview()
        self.app.tabs.select(self.p.page)
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_wrap_order_fixed_slider_and_adjacent_actions(self):
        p = self.p
        p.order = list(reversed(p.order))
        p.apply(p.form_data())
        self.root.geometry("900x850")
        self.root.update()
        narrow_rows = len({w.winfo_y() for w in p.choice_buttons.values()})
        slider_width = p.transparency_slider.winfo_width()
        self.root.geometry("1500x950")
        self.root.update()
        self.assertLess(len({w.winfo_y() for w in p.choice_buttons.values()}), narrow_rows)
        expected = [name for name in p.order if name in p.choice_buttons]
        actual = sorted(p.choice_buttons, key=lambda name: (p.choice_buttons[name].winfo_y(), p.choice_buttons[name].winfo_x()))
        self.assertEqual(actual, expected)
        self.assertEqual(p.transparency_slider.winfo_width(), slider_width)
        self.assertEqual(p.save_button.winfo_y(), p.revert_button.winfo_y())
        self.assertEqual(p.save_button.winfo_y(), p.defaults_button.winfo_y())
        self.assertLess(p.revert_button.winfo_x(), p.defaults_button.winfo_x())

    def test_theme_categories_and_navigation_wrap_without_stretching(self):
        p = self.p
        p.theme_category.set("Classes")
        p.choose_category()
        self.root.update()
        self.assertTrue(all(name.startswith("Class ·") for name in p.theme_combo.cget("values")))
        self.assertTrue(p.theme.get().startswith("Class ·"))
        self.root.geometry("900x850")
        self.root.update()
        buttons = list(p.buttons.values())
        widths = [b.winfo_width() for b in buttons]
        rows = len({b.winfo_y() for b in buttons})
        combo_width = p.theme_combo.winfo_width()
        self.root.geometry("1500x950")
        self.root.update()
        self.assertEqual(widths, [b.winfo_width() for b in buttons])
        self.assertLess(len({b.winfo_y() for b in buttons}), rows)
        self.assertEqual(p.theme_combo.winfo_width(), combo_width)
        p.revert()
        self.assertEqual(p.theme_category.get(), "General")
        self.assertEqual(p.theme.get(), DEFAULT['theme'])

    def test_transparency_repaints_without_mouse_and_label_crops_match(self):
        p = self.p
        p.theme.set("Race · Troll")
        p.show_artwork.set(True)
        p.panel_transparency.set("60")
        p.preview()
        self.root.update()
        self.root.after(350, self.root.quit)
        self.root.mainloop()
        art = p.panel_artwork
        if not art.text_records:
            self.skipTest("Optional local artwork is unavailable")
        widget, record = next((w, r) for w, r in art.text_records.items()
                              if w.master in art.records and w.winfo_width() > 10 and w.winfo_height() > 10)
        source = art.records[widget.master]["photo"]
        self.assertEqual(record["photo"].get(2, 2), source.get(widget.winfo_x() + 2, widget.winfo_y() + 2))
        panel = widget.master
        with patch.object(panel, "event_generate", wraps=panel.event_generate) as repaint:
            p.panel_transparency.set("30")
            p.preview()
            self.root.after(100, self.root.quit)
            self.root.mainloop()
            self.assertTrue(any(call.args == ("<Expose>",) and
                                call.kwargs.get("width", 0) > 0 and
                                call.kwargs.get("height", 0) > 0
                                for call in repaint.call_args_list))
            self.assertEqual(art.percent, 30)
        original = record["original"]
        p.panel_transparency.set("0")
        p.preview()
        self.assertEqual(str(widget.cget("style")), original)

    def test_transparency_keeps_layout_and_fractional_drag_position(self):
        p = self.p
        p.theme.set("Race · Troll")
        p.show_artwork.set(True)
        p.preview()
        self.root.update()
        self.root.after(350, self.root.quit)
        self.root.mainloop()
        positions = []
        for value in (0, 1, 20, 60, 0):
            p.panel_transparency.set(str(value))
            p.preview()
            self.root.update()
            self.root.after(200, self.root.quit)
            self.root.mainloop()
            positions.append((p.transparency_slider.winfo_rootx(),
                              p.transparency_slider.winfo_rooty(), p.theme_combo.winfo_width()))
        self.assertTrue(all(position == positions[0] for position in positions))
        p.transparency_position.set(33.4)
        p.change_transparency("33.4")
        self.assertEqual(p.panel_transparency.get(), "33")
        self.assertAlmostEqual(p.transparency_position.get(), 33.4)
        p.panel_transparency.set("20")
        self.assertEqual(p.transparency_position.get(), 20)

    def test_nested_frames_share_artwork_origin(self):
        p = self.p
        p.theme.set("Race · Troll")
        p.show_artwork.set(True)
        p.panel_transparency.set("60")
        p.preview()
        self.root.update()
        self.root.after(350, self.root.quit)
        self.root.mainloop()
        art = p.panel_artwork
        if p.choices_row not in art.records:
            self.skipTest("Optional local artwork is unavailable")
        child, parent = p.choices_row, p.choices_row.master
        child_photo, parent_photo = art.records[child]["photo"], art.records[parent]["photo"]
        self.assertEqual(child_photo.get(3, 3), parent_photo.get(child.winfo_x() + 3, child.winfo_y() + 3))
        # Scrolling realigns the image without changing the child's dimensions.
        size = (child.winfo_width(), child.winfo_height())
        p.scroll.canvas.yview_moveto(.1)
        self.root.update()
        art.render()
        self.assertEqual(child_photo.get(3, 3), parent_photo.get(child.winfo_x() + 3, child.winfo_y() + 3))
        self.assertEqual(size, (child.winfo_width(), child.winfo_height()))

    def test_defaults_are_preview_only_and_revert_preserves_other_edits(self):
        p = self.p
        p.theme.set("Class · Warrior")
        p.volume.set(70)
        p.tab_choices["Crafting"].set(False)
        self.assertTrue(p.save())
        saved = p.store.path.read_bytes()
        self.app.profession_pages.goal_name.set("Unfinished draft")
        p.restore_defaults()
        self.assertEqual(p.theme.get(), DEFAULT["theme"])
        self.assertEqual(p.volume.get(), DEFAULT["volume"])
        self.assertTrue(p.tab_choices["Crafting"].get())
        self.assertEqual(p.store.path.read_bytes(), saved)
        p.revert()
        self.assertEqual(p.theme.get(), "Class · Warrior")
        self.assertFalse(p.tab_choices["Crafting"].get())
        self.assertEqual(self.app.profession_pages.goal_name.get(), "Unfinished draft")
        self.assertEqual(p.store.path.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
