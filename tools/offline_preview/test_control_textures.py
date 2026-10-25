"""Texture geometry and reversible input-control layouts."""
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, font
import unittest
from unittest.mock import patch
from app import PreviewApp

class ControlTextureTests(unittest.TestCase):
    def test_large_titles_native_behaviour_and_standard_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk(); app = PreviewApp(root, Path(folder))
            try:
                p = app.preferences
                p.theme.set('Stormwind · Alliance');p.size.set('18');p.panel_transparency.set('60');p.preview()
                root.geometry('1240x1000');app.tabs.select(p.page);root.update()
                root.after(350,root.quit);root.mainloop()
                controls = getattr(app.style, '_control_textures', None)
                if controls is None or not controls.layouts:
                    self.skipTest('Optional local control artwork unavailable')
                # The text fits inside the header atlas caps, not over its border.
                height = font.Font(root=root,font=app.style.lookup('FantasyTitle.TLabel','font')).metrics('linespace')
                self.assertGreaterEqual(p.heading.winfo_reqheight(), height + 39)
                for name in ('TCombobox','TSpinbox','Vertical.TScrollbar','Horizontal.TScale','TCheckbutton'):
                    self.assertIn('WoW.',str(app.style.layout(name)))
                self.assertLess(p.scroll.scrollbar.winfo_reqheight(), 100)
                combo = app.profile_selector
                combo.tk.call('ttk::combobox::Post', str(combo))
                popup_font = combo.tk.call(f'{combo}.popdown.f.l', 'cget', '-font')
                self.assertEqual(font.Font(root=root, font=popup_font).actual('size'), 18)
                combo.tk.call('ttk::combobox::Unpost', str(combo))
                slider=p.transparency_slider
                p.scroll.canvas.yview_moveto(.6);root.update()
                root.after(250,root.quit);root.mainloop()
                # Hit testing keeps Tk's standard slider part name for native dragging.
                parts={slider.identify(x,slider.winfo_height()//2) for x in range(slider.winfo_width())}
                self.assertTrue(any(part.endswith('slider') for part in parts),parts)
                # Scrolling and opacity must not rebuild label layouts every frame.
                art=p.panel_artwork
                with patch.object(art,'configure_text_layout',wraps=art.configure_text_layout) as layout:
                    p.panel_transparency.set('40');p.preview();art.render()
                    self.assertEqual(layout.call_count,0)
                p.ui_style.set('Standard');p.preview();root.update()
                for name in controls.names:
                    self.assertEqual(app.style.layout(name),controls.original[name])
                p.ui_style.set('WoW');p.preview();root.update()
                self.assertIn('WoW.Combobox.downarrow',str(app.style.layout('TCombobox')))
                self.assertFalse(p.store.path.exists())
            finally:
                app.close()

if __name__ == '__main__':
    unittest.main()
