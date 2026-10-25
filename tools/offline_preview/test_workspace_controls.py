"""Coin entry, reversible live settings and nested wheel routing."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest

from app import PreviewApp
from local_journal import coin_price
from preferences_ui import DEFAULT, validate_preferences
from ui_layout import ScrollPage


class CoinTests(unittest.TestCase):
    def test_conversion_unknown_zero_bounds_and_invalid_values(self):
        self.assertIsNone(coin_price("", " ", ""))
        self.assertEqual(coin_price("0", "", ""), 0)
        self.assertEqual(coin_price("12", "34", "56"), 123456)
        self.assertEqual(coin_price("", "3", ""), 300)
        for parts in (("-1", "", ""), ("1.5", "", ""), ("", "100", ""), ("", "", "100"),
                      ("100000000", "", "1"), ("abc", "", "")):
            with self.assertRaises(ValueError):
                coin_price(*parts)

    def test_old_preferences_remain_readable(self):
        old = deepcopy(DEFAULT)
        old["version"] = 1
        del old["order"]
        del old["show_artwork"]
        del old["artwork_mode"]
        del old["panel_transparency"]
        del old["font_family"]
        del old["ui_style"]
        validate_preferences(old)
        for version in (2, 3):
            legacy = deepcopy(DEFAULT)
            legacy["version"] = version
            del legacy["panel_transparency"]
            del legacy["font_family"]
            del legacy["ui_style"]
            if version == 2:
                del legacy["show_artwork"]
                del legacy["artwork_mode"]
            validate_preferences(legacy)
        bad = deepcopy(DEFAULT)
        bad["order"] = ["Settings", "Settings"]
        with self.assertRaises(ValueError):
            validate_preferences(bad)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PreviewApp(self.root, Path(self.temp.name))

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_artwork_preview_save_and_revert_preserve_other_drafts(self):
        p = self.app.preferences
        image = tk.PhotoImage(width=80, height=60)
        image.put("#887744", to=(0, 0, 80, 60))
        path = Path(self.temp.name) / "art.png"
        image.write(str(path), format="png")
        self.assertTrue(p.save())
        saved = p.store.path.read_bytes()
        self.app.profession_pages.goal_name.set("Unfinished material")
        p.image_path.set(str(path))
        p.artwork_mode.set("Full background")
        self.root.update_idletasks()
        self.assertIsNotNone(p.background_source)
        self.assertEqual(p.background_label.winfo_manager(), "place")
        self.assertEqual(p.store.path.read_bytes(), saved)
        p.show_artwork.set(False)
        self.root.update_idletasks()
        self.assertIsNone(p.background_source)
        self.assertFalse(p.background_label.winfo_manager())
        self.assertFalse(p.banner.winfo_manager())
        self.assertTrue(p.save())
        stored = json.loads(p.store.path.read_text(encoding="utf-8"))
        self.assertFalse(stored["show_artwork"])
        self.assertEqual(stored["artwork_mode"], "Full background")
        p.show_artwork.set(True)
        self.root.update_idletasks()
        p.revert()
        self.assertFalse(p.show_artwork.get())
        self.assertEqual(self.app.profession_pages.goal_name.get(), "Unfinished material")

    def test_panel_transparency_preview_restart_and_solid_fallback(self):
        p = self.app.preferences
        p.theme.set('Dark')
        image = tk.PhotoImage(width=80, height=60)
        image.put("#ff0000", to=(0, 0, 80, 60))
        path = Path(self.temp.name) / "panel.png"
        image.write(str(path), format="png")
        self.root.deiconify()
        self.root.geometry("1040x840")
        self.root.update()
        self.assertTrue(p.save())
        original = p.store.path.read_bytes()
        self.app.profession_pages.goal_name.set("Draft untouched")
        p.image_path.set(str(path))
        p.artwork_mode.set("Full background")
        p.transparency_slider.set(39.6)
        self.root.update_idletasks()
        self.assertEqual(p.transparency_percentage.cget("text"), "40%")
        p.panel_artwork.render()
        record = p.panel_artwork.records[p.page]
        self.assertEqual(record["photo"].get(20, 20), (111, 13, 20))
        self.assertEqual(p.store.path.read_bytes(), original)
        self.assertEqual(p.unsaved_indicator.cget("text"), "Unsaved settings")
        self.assertEqual(float(self.root.attributes("-alpha")), 1.0)
        background = p.background_photo
        buttons = dict(p.buttons)
        p.transparency_slider.set(45)
        self.root.update_idletasks()
        self.assertIs(p.background_photo, background)
        self.assertEqual(p.buttons, buttons)
        self.assertEqual(p.runtime_data["panel_transparency"], 45)
        p.revert()
        self.assertEqual(p.panel_transparency.get(), "20")
        self.assertEqual(p.transparency_slider.get(), 20)
        self.assertEqual(p.transparency_percentage.cget("text"), "20%")
        self.assertEqual(str(p.page.cget("style")), record["original"])
        p.image_path.set(str(path))
        p.artwork_mode.set("Full background")
        p.panel_transparency.set("40")
        self.root.update_idletasks()
        self.assertTrue(p.save())
        self.assertEqual(self.app.profession_pages.goal_name.get(), "Draft untouched")
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PreviewApp(self.root, Path(self.temp.name))
        p = self.app.preferences
        self.assertEqual(p.panel_transparency.get(), "40")
        self.assertEqual(p.transparency_slider.get(), 40)
        self.assertEqual(p.transparency_percentage.cget("text"), "40%")
        p.show_artwork.set(False)
        self.root.update_idletasks()
        self.assertIsNone(p.panel_artwork.source)
        self.assertEqual(p.panel_transparency.get(), "40")
        p.panel_transparency.set("61")
        self.assertFalse(p.save())
        self.assertEqual(p.store.data["panel_transparency"], 40)

    def test_preview_does_not_save_and_revert_restores_saved_values(self):
        p = self.app.preferences
        self.assertTrue(p.save())
        saved = p.store.path.read_bytes()
        self.app.profession_pages.goal_name.set("Unfinished")
        p.theme.set("Normal")
        p.size.set("14")
        p.volume.set(17)
        p.tab_choices["Gathering"].set(False)
        self.root.update_idletasks()
        self.assertEqual(self.app.text_size, 14)
        self.assertEqual(p.runtime_data["volume"], 17)
        self.assertEqual(self.app.tabs.tab(self.app.gathering, "state"), "hidden")
        self.assertEqual(p.store.path.read_bytes(), saved)
        self.app.support_page.key.set("F2")
        self.assertTrue(self.app.support_page.save())
        self.assertEqual(p.store.data["theme"], DEFAULT['theme'])
        p.revert()
        self.assertEqual(self.app.text_size, 10)
        self.assertEqual(self.app.tabs.tab(self.app.gathering, "state"), "normal")
        self.assertEqual(self.app.profession_pages.goal_name.get(), "Unfinished")

    def test_order_previews_and_survives_restart_without_saving_other_forms(self):
        p = self.app.preferences
        index = p.order.index("Auction Journal")
        p.order_list.selection_set(index)
        p.move_tab(-1)
        self.root.update_idletasks()
        ordered = [self.app.tabs.tab(tab, "text") for tab in p.buttons]
        self.assertEqual(ordered, p.order)
        self.assertFalse(p.store.path.exists())
        order = list(p.order)
        self.assertTrue(p.save())
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PreviewApp(self.root, Path(self.temp.name))
        self.assertEqual(self.app.preferences.order, order)
        self.assertEqual([self.app.tabs.tab(tab, "text") for tab in self.app.preferences.buttons], order)

    def test_invalid_preview_keeps_last_valid_appearance_and_file(self):
        p = self.app.preferences
        p.theme.set("Forest")
        self.root.update_idletasks()
        p.background.set("#12")
        self.root.update_idletasks()
        self.assertEqual(p.runtime_data["theme"], "Forest")
        self.assertEqual(p.runtime_data["background"], "")
        self.assertFalse(p.save())
        self.assertFalse(p.store.path.exists())
        p.background.set("#123456")
        self.root.update_idletasks()
        self.assertEqual(self.root.cget("background"), "#123456")

    def test_coin_drafts_are_per_character_and_saved_as_integer_copper(self):
        journal = self.app.price_journal
        journal.name.set("Ore")
        journal.gold.set("2")
        journal.silver.set("3")
        journal.copper.set("4")
        self.assertTrue(journal.save())
        self.assertEqual(journal.records()[-1]["copper"], 20304)
        self.app.new_profile()
        self.assertEqual(journal.gold.get(), "")
        self.app.profile = self.app.profiles[0]
        journal.refresh()
        self.assertEqual((journal.gold.get(), journal.silver.get(), journal.copper.get()), ("2", "3", "4"))


class WheelTests(unittest.TestCase):
    def test_nested_wheel_routes_page_then_focused_list_then_page_at_edge(self):
        root = tk.Tk()
        root.geometry("400x300")
        page = ScrollPage(root)
        page.pack(fill="both", expand=True)
        table = ttk.Treeview(page.inner, height=3)
        table.pack(fill="x")
        for i in range(40):
            table.insert("", "end", text=str(i))
        combo = ttk.Combobox(page.inner, values=("one", "two"), state="readonly")
        combo.current(0)
        combo.pack()
        ttk.Frame(page.inner, height=1200).pack()
        root.update()
        try:
            root.focus_force()
            table.event_generate("<MouseWheel>", delta=-120)
            root.update()
            self.assertGreater(page.canvas.yview()[0], 0)
            self.assertEqual(table.yview()[0], 0)
            page.canvas.yview_moveto(0)
            table.focus_force()
            root.update()
            table.event_generate("<MouseWheel>", delta=-120)
            self.assertGreater(table.yview()[0], 0)
            self.assertEqual(page.canvas.yview()[0], 0)
            table.yview_moveto(1)
            table.event_generate("<MouseWheel>", delta=-120)
            self.assertGreater(page.canvas.yview()[0], 0)
            page.canvas.yview_moveto(0)
            table.yview_moveto(0)
            table.event_generate("<MouseWheel>", delta=-120, state=4)
            self.assertGreater(page.canvas.yview()[0], 0)
            self.assertEqual(table.yview()[0], 0)
            combo.event_generate("<MouseWheel>", delta=-120)
            self.assertEqual(combo.get(), "one")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
