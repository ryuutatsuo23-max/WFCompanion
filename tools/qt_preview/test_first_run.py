import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QColor
from companion import Companion
from first_run import SetupGuide, show_if_needed


class FirstRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_then_confirm_only_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Companion(Path(tmp)); host.testing = True
            host.updates_panel.timer.stop()
            self.app.processEvents()
            before = {p.name:p.read_bytes() for p in Path(tmp).glob('*.json')}
            original = deepcopy(host.settings)
            host.inventory_page.form.load({'name':'Keep this unfinished item'})
            guide = SetupGuide(host); guide.mode.setCurrentText('Advanced')
            guide.theme.setCurrentRow(2); guide.tab_checks['Crafting'].setChecked(False)
            self.assertEqual(host.settings['theme'],'Midnight')
            self.assertIn('Crafting',host.settings['hidden'])
            self.assertEqual([guide.theme.item(i).text() for i in range(guide.theme.count())],['Classic Fantasy','Parchment','Midnight','Dark','Normal'])
            self.assertFalse(hasattr(guide,'skin'))
            guide.reject()
            self.assertEqual(host.settings,original)
            self.assertEqual(host.inventory_page.form.values()['name'],'Keep this unfinished item')
            self.assertFalse(host.settings['setup'])
            self.assertEqual(before,{p.name:p.read_bytes() for p in Path(tmp).glob('*.json')})
            guide = SetupGuide(host); guide.mode.setCurrentText('Advanced'); guide.size.setCurrentText('16'); guide.accept()
            self.assertTrue(host.settings['setup'])
            self.assertEqual(host.settings['text_size'],16)
            self.assertEqual(host.qt_settings['experience_mode'],'Advanced')
            self.assertEqual(host.inventory_page.form.values()['name'],'Keep this unfinished item')
            for name,raw in before.items():
                if name not in ('display.json','display_settings.json','qt_settings.json','qt_appearance.json'):
                    self.assertEqual((Path(tmp)/name).read_bytes(),raw,name)
            host.testing = False; show_if_needed(host)
            self.assertFalse(hasattr(host,'setup_guide'))
            host.testing = True; host.close()

    def test_scroll_surfaces_use_theme_in_windows_style(self):
        previous = self.app.style().objectName()
        self.app.setStyle('Windows')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                host = Companion(Path(tmp)); host.testing = True
                guide = SetupGuide(host); guide.show(); guide.next()
                for theme in ('Dark', 'Normal', 'Classic Fantasy'):
                    guide.theme.setCurrentRow(next(i for i in range(guide.theme.count()) if guide.theme.item(i).text() == theme))
                    self.app.processEvents()
                    for surface in guide.findChildren(QWidget, 'guideSurface'):
                        # Bottom-right padding is outside form controls and labels.
                        pixel = surface.grab().toImage().pixelColor(surface.width()-2, surface.height()-2)
                        self.assertEqual(pixel.name(), QColor(host.colors[1]).name())
                guide.reject(); host.close()
        finally:
            self.app.setStyle(previous)


if __name__ == '__main__': unittest.main()
