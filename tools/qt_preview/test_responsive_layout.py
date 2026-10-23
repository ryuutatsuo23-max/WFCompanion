"""Public UI regressions for wrapped card names and themed search surfaces."""
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QScrollArea
from companion import Companion
from character_overview import CardHandle
from catalogue_dialog import ItemPicker


class ResponsiveLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.host = Companion(Path(self.directory.name))
        self.host.testing = True
        self.host.updates_panel.timer.stop()

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        QThreadPool.globalInstance().waitForDone()
        self.app.processEvents()
        self.directory.cleanup()

    def test_long_character_card_name_wraps_at_large_text(self):
        host = self.host
        name = 'A long profile name for our travelling gathering and crafting adventurer'
        host.data.profile.name = name
        host.profiles_changed()
        host.settings['text_size'] = 18
        host.apply_appearance()
        host.resize(680, 900)
        host.show_page('Overview')
        host.show()
        for _ in range(3): self.app.processEvents()
        handle = host.character_overview.cards.findChild(CardHandle)
        self.assertTrue(handle.wordWrap())
        self.assertEqual(handle.text(), name)
        self.assertEqual(handle.accessibleName(), 'Move ' + name)
        self.assertGreaterEqual(handle.height(), handle.heightForWidth(handle.width()))
        self.assertEqual(host.scrollers['Overview'].horizontalScrollBar().maximum(), 0)

    def test_search_dialog_panel_matches_scroll_body_in_public_themes(self):
        for theme in ('Classic Fantasy', 'Parchment', 'Midnight'):
            with self.subTest(theme=theme):
                self.host.change('theme', theme)
                dialog = ItemPicker(self.host, 'All', lambda _: None)
                try:
                    dialog.show()
                    self.app.processEvents()
                    expected = QColor(self.host.colors[1])
                    scroll = dialog.findChild(QScrollArea)
                    for surface in (dialog, scroll.widget()):
                        self.assertEqual(surface.palette().color(QPalette.ColorRole.Window), expected)
                    # The host stylesheet makes the viewport transparent; its
                    # unused Window brush is black. Verify composited pixels,
                    # not that brush, so this checks the visible background.
                    self.assertFalse(scroll.viewport().autoFillBackground())
                    self.assertEqual(dialog.grab().toImage().pixelColor(2, 2), expected)
                    self.assertEqual(dialog.grab().toImage().pixelColor(15, 15), expected)
                finally:
                    dialog.close()
                    dialog.deleteLater()
                    self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
