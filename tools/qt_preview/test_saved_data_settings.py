"""Preview must not write state, merge names, or connect a changed save."""
from pathlib import Path
import tempfile
import unittest
from PySide6.QtWidgets import QApplication
from companion import Companion
from saved_data_settings import ConnectionPreview, find_saves
from character_links import LinkStore

SAVE='''WFCoreDB={schema=1,producer="WFCore",characters={
["Player-1-ABC"]={identity={guid="Player-1-ABC",realm="Realm",firstName="Same",lastName="Name"},client={version="1.60.1",interface=16001},locations={}},
["Player-1-DEF"]={identity={guid="Player-1-DEF",realm="Realm",firstName="Same",lastName="Name"},client={version="1.60.1",interface=16001},locations={}}
}}'''


class SavedDataSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.path=self.root/'_classic_beta_/WTF/Account/Test/SavedVariables/WFCore.lua'
        self.path.parent.mkdir(parents=True);self.path.write_text(SAVE)
        self.host=Companion(self.root/'state');self.host.testing=True
        self.host.updates_panel.timer.stop()

    def tearDown(self):
        self.host.hide();self.host.deleteLater();self.app.processEvents();self.tmp.cleanup()

    def state(self):
        return {str(p.relative_to(self.root/'state')):p.read_bytes() for p in (self.root/'state').rglob('*') if p.is_file()}

    def test_preview_cancel_no_writes_then_connect_guid_isolation(self):
        before=self.state();raw=self.path.read_bytes()
        dialog=ConnectionPreview(self.host,self.path)
        self.assertEqual(dialog.characters.rowCount(),2)
        self.assertTrue(dialog.connect_button.isEnabled())
        dialog.reject();self.assertEqual(self.state(),before)
        dialog=ConnectionPreview(self.host,self.path);dialog.connect_saved()
        self.assertEqual(len(LinkStore(self.host.data.directory).records['links']),2)
        self.assertIn(str(self.path),self.host.saved_data_settings.current.text())
        self.assertEqual(self.path.read_bytes(),raw)
        self.assertFalse((self.host.data.directory/'addon_inventory.json').exists())
        count=len(self.host.data.profiles)
        dialog=ConnectionPreview(self.host,self.path);dialog.connect_saved()
        self.assertEqual(len(self.host.data.profiles),count)

    def test_changed_save_requires_new_preview(self):
        dialog=ConnectionPreview(self.host,self.path);before=self.state()
        self.path.write_text(SAVE+'\n')
        dialog.connect_saved()
        self.assertIn('changed since',dialog.status.text())
        self.assertFalse(dialog.connect_button.isEnabled());self.assertEqual(self.state(),before)

    def test_unavailable_malformed_empty_and_unsupported_saves(self):
        for value in ('bad lua','WFCoreDB={schema=1,producer="WFCore",characters={}}'):
            self.path.write_text(value);before=self.state()
            dialog=ConnectionPreview(self.host,self.path)
            self.assertFalse(dialog.connect_button.isEnabled());self.assertEqual(self.state(),before)
        self.path.unlink()
        self.assertFalse(ConnectionPreview(self.host,self.path).connect_button.isEnabled())
        other=self.root/'_forever_/WFCore.lua';other.parent.mkdir();other.write_text(SAVE)
        self.assertFalse(ConnectionPreview(self.host,other).connect_button.isEnabled())

    def test_discovery_is_scoped_to_selected_client_and_lists_accounts(self):
        client=self.root/'_classic_beta_'
        second=client/'WTF/Account/Other/SavedVariables/WFCore.lua'
        second.parent.mkdir(parents=True);second.write_text(SAVE)
        self.assertEqual(set(find_saves(client)),{self.path,second})
        self.assertEqual(find_saves(None),[])
        self.host.addons_page.client=client
        self.host.saved_data_settings.find()
        self.assertEqual(self.host.saved_data_settings.choices.count(),2)
        self.assertEqual(len(LinkStore(self.host.data.directory).records['links']),0)
