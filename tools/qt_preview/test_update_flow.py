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
            try:
                panel.checked(releases.candidate(release()),'');self.app.processEvents()
                prompt=panel.prompt;self.assertTrue(prompt.isVisible());prompt.reject()
                panel.checked(releases.candidate(release()),'');self.assertIs(panel.prompt,prompt)
                panel.show_progress(50,100);self.assertEqual(panel.progress.value(),50)
                installer=Path(tmp)/'update.exe';installer.write_bytes(b'fixture')
                panel.downloaded(installer,'')
                with patch.object(update_restart,'start_update') as start, patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):
                    panel.install();start.assert_not_called()
                host.settings['text_size']+=1
                with patch.object(update_restart,'start_update') as start:
                    panel.install();start.assert_not_called();self.assertIn('Save or discard',panel.notice.text())
                host.settings['text_size']-=1
                helper=Mock()
                with patch.object(update_restart,'start_update',return_value=helper) as start, patch.object(host,'close',return_value=False), patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
                    panel.install();start.assert_called_once();helper.terminate.assert_called_once()
                installer.write_bytes(b'tampered')
                with patch.object(update_restart,'start_update') as start:
                    panel.install();start.assert_not_called();self.assertIsNone(panel.installer)
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
