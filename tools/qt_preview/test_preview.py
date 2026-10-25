"""Qt-only UI regressions; no game or personal store is opened."""
import hashlib
from pathlib import Path
import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from app import QApplication, Preview, Title, THEMES, THEME_ART, FONT_CHOICES, ART_DIRECTORY, SOURCE


def state_fingerprint():
    return {str(path.relative_to(SOURCE)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (SOURCE / 'state').rglob('*') if path.is_file()}


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = state_fingerprint()
        cls.application = QApplication.instance() or QApplication([])
        cls.window = Preview()
        cls.window.show()
        cls.flush()

    @classmethod
    def flush(cls):
        cls.application.processEvents()
        cls.application.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.flush()
        assert state_fingerprint() == cls.before, 'Existing personal data changed'

    def setUp(self):
        self.window.defaults()
        self.window.save_session()
        self.window.resize(1200, 900)
        self.window.pages.setCurrentIndex(1)
        self.flush()

    def test_session_save_revert_does_not_save_simulation_edits(self):
        w = self.window
        w.hp.setValue(23)
        w.threshold.setValue(47)
        w.change('theme', 'Orgrimmar · Horde')
        w.change('panel_transparency', 45)
        w.save_session()
        w.change('text_size', 18)
        w.change('panel_transparency', 0)
        w.revert()
        self.assertEqual(w.settings['theme'], 'Orgrimmar · Horde')
        self.assertEqual(w.opacity.value(), 45)
        self.assertEqual(w.settings['text_size'], 12)
        self.assertEqual((w.hp.value(), w.threshold.value()), (23, 47))
        self.assertEqual(state_fingerprint(), self.before)

    def test_opacity_drag_is_paint_only_and_geometry_stays_still(self):
        w = self.window
        scroll = w.scrolls[1]
        scroll.ensureWidgetVisible(w.opacity)
        self.flush()
        geometry = w.opacity.geometry()
        styles, loads = w.style_updates, w.art_loads
        # The first dirty indicator must not make the row taller or move the thumb.
        for value in list(range(61)) + list(reversed(range(61))):
            w.opacity.setValue(value)
            self.flush()
            self.assertEqual(w.opacity.geometry(), geometry)
            self.assertEqual(w.percent.text(), f'{value}%')
        self.assertEqual((w.style_updates, w.art_loads), (styles, loads))
        self.assertNotEqual(w.settings, w.saved)

    def test_slider_keyboard_and_pointer(self):
        w = self.window
        w.scrolls[1].ensureWidgetVisible(w.opacity)
        self.flush()
        w.opacity.setFocus()
        QTest.keyClick(w.opacity, Qt.Key.Key_End)
        self.assertEqual(w.settings['panel_transparency'], 60)
        QTest.keyClick(w.opacity, Qt.Key.Key_Home)
        self.assertEqual(w.settings['panel_transparency'], 0)
        QTest.mousePress(w.opacity, Qt.MouseButton.LeftButton, pos=QPoint(7, 16))
        for x in range(7, 270, 5):
            QTest.mouseMove(w.opacity, QPoint(x, 16))
            self.flush()
        QTest.mouseRelease(w.opacity, Qt.MouseButton.LeftButton, pos=QPoint(269, 16))
        self.assertGreater(w.opacity.value(), 50)

    def test_theme_assets_and_skin_switches(self):
        w = self.window
        required = ('UI-DialogBox-Border.PNG', 'UI-DialogBox-Header.PNG', 'UI-Panel-Button-Up.PNG')
        self.assertEqual(w.textures.ready, all((ART_DIRECTORY/'wow_ui'/name).is_file() for name in required))
        for theme in THEMES:
            w.change('theme', theme)
            w.sync_controls()
            self.flush()
            self.assertEqual(w.theme.currentText(), theme)
            if theme in THEME_ART:
                self.assertEqual(not w.art.isNull(), (ART_DIRECTORY / THEME_ART[theme]).is_file(), theme)
        w.change('theme', 'Stormwind · Alliance')
        for skin in ('Standard', 'WoW'):
            w.change('ui_style', skin)
            self.flush()
            self.assertEqual(w.wow, skin == 'WoW' and w.textures.ready)

    def test_large_text_wrapping_and_reachable_bottom(self):
        w = self.window
        for family in FONT_CHOICES:
            w.change('font_family', family)
            w.change('text_size', 18)
            for width in (680, 1240, 1800):
                w.resize(width, 900)
                self.flush()
                self.assertEqual(w.theme.font().pointSize(), 18)
                self.assertEqual(w.percent.font().pointSize(), 18)
                self.assertEqual(w.opacity.width(), 280)
                for scroll in w.scrolls:
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                self.flush()
                for title in w.findChildren(Title):
                    if title.isVisible():
                        self.assertGreaterEqual(title.height(), title.fontMetrics().height() + 39)
                self.assertLessEqual(w.scrolls[1].horizontalScrollBar().maximum(), 0)
                mapped = w.session_status.mapTo(w.scrolls[1].viewport(), QPoint(0, 0))
                self.assertGreaterEqual(mapped.y(), 0)
                self.assertLess(mapped.y(), w.scrolls[1].viewport().height())

    def test_background_modes_and_reminders(self):
        w = self.window
        w.pages.setCurrentIndex(0)
        w.hp.setValue(20)
        self.assertIn('Your HP is low', w.reminder.text())
        w.hp.setValue(100)
        w.party.setValue(100)
        w.buff.setChecked(False)
        self.assertIn('buff is missing', w.reminder.text())
        w.missing_buff.setChecked(False)
        self.assertEqual(w.reminder.text(), 'No reminder right now.')
        w.cooldown.setValue(0)
        self.assertIn('castability unknown', w.cooldown_text.text())
        for mode in ('Header', 'Full background'):
            w.change('artwork_mode', mode)
            for show in (False, True):
                w.change('show_artwork', show)
                self.flush()
                self.assertFalse(w.grab().isNull())
        w.change('overview_visible', False)
        self.assertEqual(w.pages.currentIndex(), 1)
        w.change('overview_visible', True)
        self.assertTrue(w.overview_button.isVisible())

    def test_presented_pixels_match_fresh_render_during_motion(self):
        # Read only this test window's presented pixels BEFORE QWidget.grab(),
        # which renders afresh. This catches stale scroll strips that a normal
        # widget screenshot would silently repair. A real desktop is required.
        if self.application.platformName() in ('offscreen', 'minimal'):
            self.skipTest('Presented-pixel check requires a real desktop')
        w = self.window
        w.raise_()
        w.activateWindow()
        for points in (12, 18):
            w.change('text_size', points)
            self.flush()
            for index in range(16):
                w.resize(1000 + index * 12, 860 + index * 4)
                w.opacity.setValue(index * 4)
                bar = w.scrolls[1].verticalScrollBar()
                bar.setValue(round(bar.maximum() * index / 15))
                self.flush()
                QTest.qWait(25)
                presented = w.screen().grabWindow(w.winId()).toImage()
                self.assertFalse(presented.isNull())
                fresh = w.grab().toImage()
                self.assertEqual(presented.convertToFormat(fresh.format()), fresh,
                                 f'Stale pixels at {points}pt, step {index}')


if __name__ == '__main__':
    unittest.main()
