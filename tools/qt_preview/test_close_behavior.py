import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox
from companion import Companion


class CloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def test_tray_preserves_session_and_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            try:
                host.show();self.app.processEvents()
                self.assertTrue(host.close_behavior.save('Minimize to tray'))
                with patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=True):
                    self.assertFalse(host.close_behavior.allow_close())
                self.assertFalse(host.isVisible());self.assertTrue(host.timer.isActive())
                host.close_behavior.restore();self.assertTrue(host.isVisible())
                self.assertFalse(host.close_behavior.tray.isVisible())
                with patch.object(host,'close',return_value=False) as close:
                    self.assertFalse(host.close_behavior.quit());close.assert_called_once()
                self.assertFalse(host.close_behavior.force_quit)
            finally:host.close()

    def test_preference_survives_reopen_and_can_be_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for initial,chosen in [('Ask every time','Minimize to tray'),('Minimize to tray','Quit'),('Quit','Ask every time')]:
                host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
                try:
                    self.assertEqual(host.close_choice.currentText(),initial)
                    self.assertTrue(host.close_behavior.save(chosen))
                finally:host.close()

    def test_dialog_remembers_only_chosen_action_and_handles_no_tray(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            selected=[]
            def respond(box):
                box.checkBox().setChecked(True)
                selected.append(next(b for b in box.buttons() if b.text()==answer[0]))
                return 0
            try:
                answer=['Cancel']
                with patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=True), patch.object(QMessageBox,'exec',respond), patch.object(QMessageBox,'clickedButton',lambda box:selected[-1]):
                    self.assertFalse(host.close_behavior.allow_close())
                    self.assertEqual(host.close_behavior.store.data['action'],'ask')
                    answer[0]='Quit'
                    self.assertTrue(host.close_behavior.allow_close())
                    self.assertEqual(host.close_behavior.store.data['action'],'quit')
                host.close_behavior.save('Minimize to tray');answer[0]='Cancel'
                with patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=False), patch.object(QMessageBox,'exec',respond), patch.object(QMessageBox,'clickedButton',lambda box:selected[-1]):
                    self.assertFalse(host.close_behavior.allow_close())
                self.assertFalse(host.close_behavior.tray.isVisible())
            finally:host.close()


if __name__=='__main__':unittest.main()
