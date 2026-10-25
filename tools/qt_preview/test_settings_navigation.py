"""Settings collapse geometry and user navigation, with disposable records."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QTimer, QThreadPool
from PySide6.QtWidgets import QMessageBox
from companion import Companion, QApplication
from test_copy_and_alts import seed, files


class SettingsNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);seed(self.root)
        self.w=Companion(self.root);self.w.testing=True
        for timer in (self.w.timer,self.w.updates_panel.timer,self.w.saved_character_connection.timer,self.w.probe_page.timer):timer.stop()
        self.w.character_overview.game_data_monitor.set_enabled(False)
        self.w.resize(1200,950);self.w.show_page('Settings');self.w.show();self.flush()
        self.assertTrue(self.w.save_session())
        self.w.queue.form.load({'name':'Unfinished craft'})

    def flush(self):
        for _ in range(8):self.app.processEvents()

    def tearDown(self):
        self.w.close();QThreadPool.globalInstance().waitForDone(3000)
        self.w.deleteLater();self.flush();self.tmp.cleanup()

    def answer(self,caption):
        def click():
            dialog=self.app.activeModalWidget()
            self.assertIsInstance(dialog,QMessageBox)
            if caption is None:dialog.close()
            else:
                button=next(b for b in dialog.buttons() if b.text()==caption)
                button.click()
        QTimer.singleShot(0,click)

    def dirty(self):self.w.change('volume',self.w.settings['volume']+1)

    def assert_compact(self):
        layout=self.w.scrollers['Settings'].widget().layout()
        widgets=[layout.itemAt(i).widget() for i in range(layout.count())]
        visible=[widget for widget in widgets if widget is not None and widget.isVisible()]
        self.assertEqual(visible[0].y(),0)
        for first,second in zip(visible,visible[1:]):
            gap=second.y()-first.geometry().bottom()-1
            self.assertLessEqual(gap,layout.spacing()+1,(gap,first.geometry(),second.geometry()))
            self.assertGreaterEqual(gap,0)

    def test_collapsed_and_mixed_sections_pack_at_top_at_multiple_widths(self):
        w=self.w
        for width in (1200,900,1400):
            w.resize(width,950)
            w.qt_settings['collapsed_settings']=list(w.settings_sections);w.sync_settings_sections()
            for category,panels in w.settings_groups.items():
                w.select_settings_category(category);self.flush();self.assert_compact()
                key=panels[0].box.itemAt(0).widget().text
                w.toggle_settings_section(key);self.flush();self.assert_compact()
                w.toggle_settings_section(key);self.flush();self.assert_compact()
        self.assertTrue(w.save_session());w.close()
        self.w=Companion(self.root);self.w.testing=True;self.w.show_page('Settings');self.w.show();self.flush()
        self.assert_compact()

    def test_continue_preserves_temporary_preferences_and_drafts_without_writes(self):
        before=files(self.root);self.dirty();self.answer('Continue without saving')
        self.w.page_picker.setCurrentText('Storage')
        self.assertEqual(self.w.page_picker.currentText(),'Storage')
        self.assertTrue(self.w.has_unsaved_settings());self.assertEqual(files(self.root),before)
        self.assertEqual(self.w.queue.form.values()['name'],'Unfinished craft')

    def test_save_then_leave_and_reopen(self):
        self.dirty();volume=self.w.settings['volume'];self.answer('Save settings')
        self.assertTrue(self.w.navigate_page('Storage'));self.assertFalse(self.w.has_unsaved_settings())
        self.assertEqual(self.w.queue.form.values()['name'],'Unfinished craft')
        reopened=Companion(self.root);reopened.testing=True
        self.assertEqual(reopened.settings['volume'],volume);reopened.close();reopened.deleteLater()

    def test_stay_and_close_prompt_keep_page_picker_and_history(self):
        self.dirty();history=list(self.w.page_history);before=files(self.root)
        for choice in ('Stay in Settings',None):
            self.answer(choice);self.w.page_picker.setCurrentText('Storage')
            self.assertEqual(self.w.page_picker.currentText(),'Settings')
            self.assertEqual(self.w.pages.currentWidget(),self.w.scrollers['Settings'])
            self.assertEqual(self.w.page_history,history);self.assertEqual(files(self.root),before)

    def test_back_cancel_preserves_history_then_continue_consumes_it(self):
        self.w.show_page('Storage');self.w.show_page('Settings');self.dirty()
        history=list(self.w.page_history)
        self.answer('Stay in Settings');self.w.go_back();self.assertEqual(self.w.page_history,history)
        self.answer('Continue without saving');self.w.go_back()
        self.assertEqual(self.w.page_history,history[:-1]);self.assertEqual(self.w.page_picker.currentText(),'Storage')

    def test_save_failure_stays_and_preserves_draft(self):
        self.dirty();before=files(self.root);self.answer('Save settings')
        with patch.object(self.w.data.display,'save',side_effect=OSError('Temporary test failure')),patch.object(QMessageBox,'warning') as warning:
            self.assertFalse(self.w.navigate_page('Storage'));warning.assert_called_once()
        self.assertEqual(self.w.page_picker.currentText(),'Settings');self.assertTrue(self.w.has_unsaved_settings())
        self.assertEqual(files(self.root),before);self.assertEqual(self.w.queue.form.values()['name'],'Unfinished craft')

    def test_clean_leave_and_category_switch_do_not_prompt(self):
        with patch.object(self.w,'confirm_settings_exit',side_effect=AssertionError('Unexpected prompt')):
            self.assertTrue(self.w.navigate_page('Storage'));self.w.navigate_page('Settings');self.dirty()
            self.w.select_settings_category('Appearance');self.flush()

    def test_second_settings_file_failure_does_not_mark_changes_saved(self):
        self.dirty();self.answer('Save settings')
        with patch.object(self.w.data.qt,'save',side_effect=OSError('Temporary test failure')),patch.object(QMessageBox,'warning'):
            self.assertFalse(self.w.navigate_page('Storage'))
        self.assertTrue(self.w.has_unsaved_settings())
        self.answer('Save settings');self.assertTrue(self.w.navigate_page('Storage'))
        self.assertFalse(self.w.has_unsaved_settings())


if __name__=='__main__':unittest.main()
