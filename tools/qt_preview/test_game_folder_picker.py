"""Folder discovery, choice and setup persistence use synthetic clients only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from companion import Companion
from addons_page import AddonsPage
from game_folder_picker import GameFolderPicker, find_clients
from first_run import SetupGuide


class GameFolderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def client(self,root,name):
        client=root/name;client.mkdir(parents=True);(client/'Wow.exe').touch();return client.resolve()

    def test_bounded_discovery_deduplicates_and_excludes_unrelated_clients(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();a=self.client(root,'_forever_');b=self.client(root,'_classic_beta_')
            self.client(root,'_retail_');self.client(root/'nested','_forever_')
            self.assertEqual(set(find_clients([root,a,a])),{a,b})
            (a/'Wow.exe').unlink();(a/'WowB.exe').touch()
            self.assertIn(a,find_clients([root]))

    def test_browse_parent_cancel_invalid_and_explicit_selection(self):
        with tempfile.TemporaryDirectory() as tmp,patch('game_folder_picker.standard_roots',return_value=[]):
            root=Path(tmp).resolve();a=self.client(root/'custom','_forever_');b=self.client(root/'custom','_classic_beta_')
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                page=host.addons_page
                with patch('game_folder_picker.QFileDialog.getExistingDirectory',return_value=str(a.parent)):page.choose()
                self.assertIsNone(page.client);self.assertIn('Multiple clients',page.picker.notice.text())
                page.picker.choices.setCurrentIndex(page.picker.choices.findData(str(b)))
                self.assertEqual(page.client,b);self.assertIn(str(b/'Interface/AddOns'),page.folder.text())
                before=page.path.read_bytes()
                for response in ('',str(root/'invalid')):
                    with patch('game_folder_picker.QFileDialog.getExistingDirectory',return_value=response):page.choose()
                    self.assertEqual(page.client,b);self.assertEqual(page.path.read_bytes(),before)
                reopened=AddonsPage(host,clients=[a]);self.assertEqual(reopened.client,b)
                (b/'Wow.exe').unlink()
                missing=AddonsPage(host,clients=[a]);self.assertIsNone(missing.client)
                self.assertIn('unavailable',missing.picker.notice.text());self.assertEqual(page.path.read_bytes(),before)
                self.assertFalse((a/'Interface').exists());self.assertFalse((b/'Interface').exists())
            finally:host.close();self.app.processEvents()

    def test_setup_cancel_finish_and_offline_choice(self):
        with tempfile.TemporaryDirectory() as tmp,patch('game_folder_picker.standard_roots',return_value=[]),patch('windows_startup.set_enabled'):
            root=Path(tmp).resolve();client=self.client(root,'_forever_')
            host=Companion(root/'state');host.testing=True;host.updates_panel.timer.stop()
            try:
                for finish in (False,True):
                    guide=SetupGuide(host)
                    with patch('game_folder_picker.QFileDialog.getExistingDirectory',return_value=str(client)):guide.game_folder.choose()
                    if finish:guide.accept()
                    else:
                        guide.reject();self.assertFalse(host.addons_page.path.exists());self.assertIsNone(host.addons_page.client)
                self.assertEqual(host.addons_page.client,client)
                self.assertEqual(host.addons_page.picker.choices.currentData(),str(client))
                self.assertEqual(json.loads(host.addons_page.path.read_text())['client'],str(client))
                self.assertFalse((client/'Interface').exists());self.assertFalse((client/'WTF').exists())
                host.addons_page.picker.choices.setCurrentIndex(0)
                reopened=AddonsPage(host,clients=[client]);self.assertIsNone(reopened.client)
            finally:host.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
