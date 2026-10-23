import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from PySide6.QtWidgets import QApplication, QMessageBox
from companion import Companion
import release_updates as releases
from test_release_updates import release
import update_restart


class UpdateFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_download_reports_bytes_and_verifies(self):
        content=b'abc';events=[]
        checksum=(hashlib.sha256(content).hexdigest()+'  '+releases.ASSET+'\n').encode()
        with tempfile.TemporaryDirectory() as tmp, patch.object(releases,'request',side_effect=[io.BytesIO(checksum),io.BytesIO(content)]):
            releases.download(releases.candidate(release()),tmp,lambda a,b:events.append((a,b)))
        self.assertEqual(events,[(0,3),(3,3)])

    def test_notification_cancel_progress_and_restart_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            panel=host.updates_panel
            host.show();self.app.processEvents()
            try:
                panel.checked(releases.candidate(release()),'');self.app.processEvents()
                prompt=panel.prompt;self.assertTrue(prompt.isVisible());prompt.reject()
                panel.checked(releases.candidate(release()),'');self.assertIs(panel.prompt,prompt)
                panel.show_progress(50,100);self.assertEqual(panel.progress.value(),50)
                installer=Path(tmp)/'update.exe';installer.write_bytes(b'fixture')
                panel.downloaded(installer,'')
                with patch.object(update_restart,'start_update') as start, patch.object(panel,'confirm_restart',return_value=(False,True)):
                    panel.install();start.assert_not_called()
                host.settings['text_size']+=1
                with patch.object(update_restart,'start_update') as start, patch.object(panel,'confirm_restart',return_value=(True,False)):
                    panel.install();start.assert_not_called();self.assertIn('Save or discard',panel.notice.text())
                host.settings['text_size']-=1
                helper=Mock()
                with patch.object(update_restart,'start_update',return_value=helper) as start, patch.object(host,'close',return_value=False), patch.object(panel,'confirm_restart',return_value=(True,True)):
                    panel.install();start.assert_called_once();helper.terminate.assert_called_once()
                installer.write_bytes(b'tampered')
                with patch.object(update_restart,'start_update') as start:
                    panel.install();start.assert_not_called();self.assertIsNone(panel.installer)
            finally:host.close();self.app.processEvents()

    def test_periodic_checks_and_persistent_toast(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True
            panel=host.updates_panel
            host.show();self.app.processEvents()
            try:
                with patch.object(panel,'check') as check:
                    panel.toggle(True)
                    self.assertEqual(panel.timer.interval(),300000)
                    panel.timer.timeout.emit()
                    self.assertEqual(check.call_count,2)
                    panel.toggle(False);panel.timer.timeout.emit()
                    self.assertEqual(check.call_count,2)
                panel.checked(releases.candidate(release()),'');self.app.processEvents()
                toast=panel.prompt
                self.assertEqual(toast.windowTitle(),'WF Companion update available')
                self.assertFalse(toast.isModal())
                area=host.contentsRect()
                self.assertFalse(toast.isWindow())
                self.assertIs(toast.parentWidget(),host)
                self.assertTrue(area.contains(toast.geometry()))
                self.assertEqual(toast.width(),area.width()-32)
                self.assertLess(toast.geometry().bottom(),host.navigation.y())
                self.assertLessEqual(abs(toast.geometry().right()-(area.right()-16)),2)
                self.assertTrue(toast.isVisible())
                host.resize(900,700);self.app.processEvents()
                self.assertTrue(host.contentsRect().contains(toast.geometry()))
                self.assertLess(toast.geometry().bottom(),host.navigation.y())
                self.assertEqual(toast.x()+toast.width(),host.contentsRect().right()-15)
                host.settings['text_size']=16;host.apply_appearance();self.app.processEvents()
                toast.reposition();self.app.processEvents()
                self.assertLess(toast.geometry().bottom(),host.navigation.y())
                self.assertTrue(toast.rect().contains(toast.update_button.geometry()))
                self.assertTrue(toast.rect().contains(toast.cancel_button.geometry()))
                host.hide();self.app.processEvents();self.assertFalse(toast.isVisible())
                host.show();self.app.processEvents();self.assertTrue(toast.isVisible())
                with patch.object(panel,'download') as download:
                    toast.update_button.click();download.assert_called_once_with(True)
                self.assertFalse(toast.isVisible())
            finally:host.close();self.app.processEvents()

    def test_restart_saves_settings_only_and_stops_on_save_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            panel=host.updates_panel
            installer=Path(tmp)/'update.exe';installer.write_bytes(b'fixture');panel.downloaded(installer,'')
            try:
                host.settings['text_size']+=1
                host.inventory_page.form.load({'name':'Unfinished item','quantity':'???'})
                draft=host.inventory_page.form.values()
                with patch.object(panel,'confirm_restart',return_value=(False,True)),patch.object(host,'save_session') as save,patch.object(update_restart,'start_update') as start:
                    panel.install();save.assert_not_called();start.assert_not_called()
                with patch.object(panel,'confirm_restart',return_value=(True,True)),patch.object(host,'save_session',return_value=False),patch.object(update_restart,'start_update') as start:
                    panel.install();start.assert_not_called();self.assertIn('could not be saved',panel.notice.text())
                helper=Mock()
                with patch.object(panel,'confirm_restart',return_value=(True,True)),patch.object(update_restart,'start_update',return_value=helper) as start,patch.object(host.close_behavior,'quit',return_value=False):
                    panel.install();start.assert_called_once();helper.terminate.assert_called_once()
                self.assertEqual(host.settings,host.saved)
                self.assertEqual(host.data.display.data['text_size'],host.settings['text_size'])
                self.assertEqual(host.inventory_page.form.values(),draft)
                host.data.dirty.add('Inventory')
                with patch.object(panel,'confirm_restart') as confirm,patch.object(update_restart,'start_update') as start:
                    panel.install();confirm.assert_not_called();start.assert_not_called()
                host.data.dirty.clear()
            finally:host.close();self.app.processEvents()

    def test_restart_checkbox_defaults_to_save_and_cancel_stays_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            try:
                def inspect(box):
                    self.assertTrue(box.checkBox().isChecked())
                    self.assertEqual(box.standardButton(box.defaultButton()),QMessageBox.StandardButton.Cancel)
                    self.assertIn('Settings only',box.text())
                    return QMessageBox.StandardButton.Cancel
                with patch.object(QMessageBox,'exec',inspect):
                    self.assertEqual(host.updates_panel.confirm_restart(),(False,True))
            finally:host.close();self.app.processEvents()

    def test_windows_dialog_background_matches_theme(self):
        previous=self.app.style().objectName();self.app.setStyle('Windows')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
                try:
                    for theme in ('Classic Fantasy','Parchment','Midnight'):
                        host.settings['theme']=theme;host.apply_appearance()
                        box=QMessageBox(host);box.setText('Update and restart?');box.show();self.app.processEvents()
                        image=box.grab().toImage()
                        self.assertEqual(image.pixelColor(2,2).name(),host.colors[1].lower())
                        box.close()
                finally:host.close()
        finally:self.app.setStyle(previous)

    def test_development_checkout_cannot_replace_itself(self):
        with self.assertRaisesRegex(ValueError,'installed companion'):
            update_restart.start_update(Path('missing.exe'),'invalid',Path('unused'))


if __name__=='__main__':unittest.main()
