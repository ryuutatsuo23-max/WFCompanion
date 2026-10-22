"""Public themes must work without game textures and survive preference saves."""
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication
from companion import Companion
from first_run import SetupGuide
from display_settings import validate_preferences


class PublicAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_bundled_fonts_preview_cancel_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            self.assertEqual(host.windowTitle(),'WFCompanion')
            self.assertEqual(host.settings['theme'],'Classic Fantasy')
            self.assertFalse(hasattr(host,'skin'))
            self.assertIn('Cinzel',host.fonts.available)
            self.assertIn('Lora',host.fonts.available)
            original=host.settings['theme']
            guide=SetupGuide(host)
            for name in ('Classic Fantasy','Parchment','Midnight'):
                index=next(i for i in range(guide.theme.count()) if guide.theme.item(i).text()==name)
                guide.theme.setCurrentRow(index);self.app.processEvents()
                self.assertTrue(host.original_theme)
                self.assertFalse(host.wow)
                self.assertIn('qlineargradient',host.styleSheet())
                validate_preferences({k:host.settings[k] for k in __import__('display_settings').DEFAULT})
            guide.reject();self.assertEqual(host.settings['theme'],original)
            host.settings.update(theme='Parchment',font_family='Lora')
            host.apply_appearance();self.assertEqual(host.appearance_font_family,'Lora')
            self.assertTrue(host.save_session());host.close()
            restored=Companion(Path(tmp));restored.testing=True;restored.updates_panel.timer.stop()
            self.assertEqual(restored.settings['theme'],'Parchment')
            self.assertEqual(restored.settings['font_family'],'Lora');restored.close()

    def test_existing_palette_is_preserved_in_short_menu(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            host.change('theme','Class · Shaman');host.sync_controls()
            self.assertEqual(host.theme.currentText(),'Class · Shaman')
            self.assertEqual(host.theme.count(),6)
            guide=SetupGuide(host)
            self.assertEqual(guide.theme.currentItem().text(),'Class · Shaman')
            guide.reject();self.assertTrue(host.save_session());host.close()


if __name__=='__main__':unittest.main()
