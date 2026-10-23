from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import test_saved_data_settings as fixtures
SAVE=fixtures.SAVE
from saved_data_settings import ConnectionPreview
from saved_data_reconnect import preview_reconnect, reconnect
from character_links import LinkStore


class ReconnectTests(unittest.TestCase):
    setUp=fixtures.SavedDataSettingsTests.setUp
    tearDown=fixtures.SavedDataSettingsTests.tearDown

    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def move(self):
        self.service=self.host.saved_character_connection
        self.service.connect(self.path.parent)
        self.oldlinks=(self.host.data.directory/'character_links.json').read_bytes()
        self.profiles=self.host.data.profile_store.path.read_bytes()
        self.pref=self.service.store.path.read_bytes()
        self.manual=self.host.data.directory/'planning.json'
        self.manual.write_text('{"reconnect-test":"keep exact bytes"}')
        self.target=self.root/'moved/_classic_beta_/WTF/Account/Test/SavedVariables/WFCore.lua'
        self.target.parent.mkdir(parents=True)
        self.path.rename(self.target)

    def assert_kept(self):
        self.assertEqual(self.host.data.profile_store.path.read_bytes(),self.profiles)
        self.assertEqual(self.manual.read_text(),'{"reconnect-test":"keep exact bytes"}')

    def test_missing_cancel_and_reconnect_keep_profile_ids_and_plans(self):
        self.move();self.host.saved_data_settings.refresh()
        self.assertIn('Characters and manual plans are kept',self.host.saved_data_settings.current.text())
        before=LinkStore(self.host.data.directory).records
        dialog=ConnectionPreview(self.host,self.target,reconnecting=True)
        self.assertTrue(dialog.connect_button.isEnabled());dialog.reject()
        self.assertEqual(self.service.store.path.read_bytes(),self.pref)
        self.assertEqual((self.host.data.directory/'character_links.json').read_bytes(),self.oldlinks)
        dialog=ConnectionPreview(self.host,self.target,reconnecting=True);dialog.connect_saved()
        self.assertEqual(dialog.result(),1,dialog.status.text())
        after=LinkStore(self.host.data.directory).records
        self.assertEqual([x['profile'] for x in before['links']],[x['profile'] for x in after['links']])
        self.assertEqual(self.service.source(),str(self.target.parent))
        self.assert_kept()
        self.assertEqual(self.target.read_text(),SAVE)

    def test_different_guid_realm_or_partial_save_rejected_without_writes(self):
        self.move()
        for raw in (SAVE.replace('Player-1-ABC','Player-1-XYZ'),SAVE.replace('realm="Realm"','realm="Other"'),'\n'.join(line for line in SAVE.splitlines() if 'Player-1-DEF' not in line)):
            self.target.write_text(raw)
            dialog=ConnectionPreview(self.host,self.target,reconnecting=True)
            self.assertFalse(dialog.connect_button.isEnabled())
            self.assertEqual(self.service.store.path.read_bytes(),self.pref)
            self.assertEqual((self.host.data.directory/'character_links.json').read_bytes(),self.oldlinks)
            self.assert_kept()

    def test_changed_replacement_and_returned_original_reject_old_preview(self):
        self.move();token,*_=preview_reconnect(self.service,self.target.parent)
        self.target.write_text(SAVE+'\n')
        with self.assertRaisesRegex(ValueError,'changed since'):reconnect(self.service,self.target.parent,token)
        token,*_=preview_reconnect(self.service,self.target.parent)
        shutil.copy2(self.target,self.path)
        with self.assertRaisesRegex(ValueError,'original save is available'):reconnect(self.service,self.target.parent,token)
        self.assertEqual((self.host.data.directory/'character_links.json').read_bytes(),self.oldlinks)
        self.assert_kept()

    def test_connection_write_failure_restores_exact_links(self):
        self.move();token,*_=preview_reconnect(self.service,self.target.parent)
        with patch.object(self.service.store,'save',side_effect=OSError('test failure')):
            with self.assertRaises(OSError):reconnect(self.service,self.target.parent,token)
        self.assertEqual((self.host.data.directory/'character_links.json').read_bytes(),self.oldlinks)
        self.assertEqual(self.service.store.path.read_bytes(),self.pref)
        self.assert_kept()

    def test_links_changed_since_preview_are_preserved(self):
        self.move();token,*_=preview_reconnect(self.service,self.target.parent)
        path=self.host.data.directory/'character_links.json'
        external=self.oldlinks+b'\n';path.write_bytes(external)
        with self.assertRaisesRegex(ValueError,'changed since'):reconnect(self.service,self.target.parent,token)
        self.assertEqual(path.read_bytes(),external)
        self.assertEqual(self.service.store.path.read_bytes(),self.pref)
        self.assert_kept()
