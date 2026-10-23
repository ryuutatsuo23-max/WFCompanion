from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from companion import Companion
from addons_page import AddonsPage


class AddonsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_install_backup_repair_and_remembered_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').write_bytes(b'fixture')
            payload=root/'package'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('fixture '+name)
            save=client/'WTF/saved.lua';save.parent.mkdir();save.write_bytes(b'personal')
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                host.show_page('Addons');self.assertEqual(host.page_picker.currentText(),'Addons')
                page=AddonsPage(host,payload=payload,clients=[client])
                with patch('install_addons.game_running',return_value=True) as running:
                    page.install_selected();running.assert_not_called()
                self.assertEqual(page.status.text(),'Installed · matches bundled package')
                self.assertFalse(page.action.isEnabled());self.assertEqual(save.read_bytes(),b'personal')
                target=client/'Interface/AddOns/WFStorage/WFStorage.toc';target.write_text('local modification')
                page.refresh()
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):page.install_selected()
                self.assertEqual(target.read_text(),'local modification')
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.install_selected()
                backups=list((root/'state/AddonBackups').glob('*/WFStorage/WFStorage.toc'))
                self.assertTrue(any(p.read_text()=='local modification' for p in backups))
                reopened=AddonsPage(host,payload=payload,clients=[])
                self.assertEqual(reopened.client.resolve(),client.resolve())
                self.assertEqual(save.read_bytes(),b'personal')
                self.assertIsNone(host.addons_page.payload)
                self.assertFalse(host.addons_page.action.isEnabled())
            finally:host.close();self.app.processEvents()

    def test_ambiguous_clients_require_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);clients=[root/'_forever_',root/'_classic_beta_']
            for client in clients:client.mkdir();(client/'Wow.exe').touch()
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                page=AddonsPage(host,clients=clients)
                self.assertIsNone(page.client);self.assertIn('Multiple clients',page.notice.text())
            finally:host.close();self.app.processEvents()

    def test_core_installs_independently_and_storage_keeps_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'package'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('fixture '+name)
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                page=AddonsPage(host,payload=payload,clients=[client])
                page.core_action.click()
                self.assertTrue((client/'Interface/AddOns/WFCore/WFCore.toc').is_file())
                self.assertFalse((client/'Interface/AddOns/WFStorage').exists())
                self.assertFalse(page.core_action.isEnabled());self.assertTrue(page.action.isEnabled())
                self.assertEqual(page.status.text(),'Ready to install missing files')
                self.assertEqual(page.action.text(),'Install Forever Storage')
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
                    page.action.click()
                    question.assert_not_called()
                self.assertTrue((client/'Interface/AddOns/WFStorage/WFStorage.toc').is_file())
                self.assertFalse(page.action.isEnabled())
                self.assertFalse(page.core_action.isEnabled())
                # A missing Storage file must not hide a real Core conflict.
                (client/'Interface/AddOns/WFStorage/WFStorage.toc').unlink()
                core=client/'Interface/AddOns/WFCore/WFCore.toc'
                core.write_text('locally modified Core')
                page.refresh()
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
                    page.action.click()
                    question.assert_called_once()
                self.assertEqual(core.read_text(),'locally modified Core')
                self.assertFalse((client/'Interface/AddOns/WFStorage/WFStorage.toc').exists())
            finally:host.close();self.app.processEvents()
