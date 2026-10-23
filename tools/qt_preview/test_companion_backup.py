from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest
import zipfile
from PySide6.QtWidgets import QApplication
from data import Data
from inventory import InventoryEntry,utc_now
from professions import CraftGoal,Ingredient
import companion_backup as backups
import test_saved_data_settings as fixtures
from backup_settings import RestorePreview


class BackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.state=self.root/'state';self.state.mkdir()
        data=Data(self.state);data.profile.name='Original character';data.save_profiles()
        self.archive=self.root/'backup.zip';backups.create(self.state,self.archive)

    def tearDown(self):self.temp.cleanup()

    def test_roundtrip_removes_new_supported_records_but_preserves_game_and_unknown_files(self):
        before=backups.snapshot(self.state)
        (self.state/'WFCore.lua').write_text('game save untouched')
        (self.state/'unrelated.json').write_text('unrelated')
        data=Data(self.state);data.profile.name='New name';data.save_profiles()
        (self.state/'updates.json').write_text('{"automatic":false}')
        current=backups.snapshot(self.state);review=backups.inspect(self.archive)
        recovery=backups.restore(self.state,self.archive,review['sha256'],current)
        self.assertEqual(backups.snapshot(self.state),before)
        self.assertEqual(backups.inspect(recovery)['files'],current)
        self.assertEqual((self.state/'WFCore.lua').read_text(),'game save untouched')
        self.assertEqual((self.state/'unrelated.json').read_text(),'unrelated')
        with zipfile.ZipFile(self.archive) as z:self.assertNotIn('WFCore.lua',z.namelist())

    def test_damaged_checksum_schema_and_traversal_are_rejected(self):
        baseline=backups.snapshot(self.state)
        bad=self.root/'bad.zip';bad.write_bytes(b'not a zip')
        with self.assertRaises(ValueError):backups.inspect(bad)
        for mode in ('checksum','schema','traversal','future','duplicate'):
            with zipfile.ZipFile(self.archive) as z:entries={n:z.read(n) for n in z.namelist()}
            if mode in ('checksum','schema'):
                entries['profiles.json']=b'{"version":999}'
                if mode=='schema':
                    m=json.loads(entries['manifest.json']);m['files']['profiles.json']=backups.digest(entries['profiles.json']);entries['manifest.json']=json.dumps(m).encode()
            elif mode=='traversal':entries['../outside.json']=b'{}'
            elif mode=='future':
                m=json.loads(entries['manifest.json']);m['version']=99;entries['manifest.json']=json.dumps(m).encode()
            with zipfile.ZipFile(bad,'w') as z:
                for name,raw in entries.items():z.writestr(name,raw)
                if mode=='duplicate':z.writestr('profiles.json',entries['profiles.json'])
            with self.assertRaises(ValueError,msg=mode):backups.inspect(bad)
            self.assertEqual(backups.snapshot(self.state),baseline)
        self.assertFalse((self.root/'outside.json').exists())

    def test_preview_changes_rejected_and_write_failure_rolls_back(self):
        current=backups.snapshot(self.state);review=backups.inspect(self.archive)
        (self.state/'updates.json').write_text('{"automatic":false}')
        with self.assertRaisesRegex(ValueError,'data changed'):backups.restore(self.state,self.archive,review['sha256'],current)
        current=backups.snapshot(self.state);real=backups.replace_files;calls=[]
        def fail_once(directory,files):
            calls.append(1)
            if len(calls)==1:
                (directory/'profiles.json').write_text('{}');raise OSError('Injected failure')
            real(directory,files)
        with patch.object(backups,'replace_files',side_effect=fail_once):
            with self.assertRaises(OSError):backups.restore(self.state,self.archive,review['sha256'],current)
        self.assertEqual(backups.snapshot(self.state),current)
        self.assertFalse((self.state/'restore-pending.json').exists())

    def test_interrupted_restore_recovers_before_data_load(self):
        before=backups.snapshot(self.state)
        recovery=self.state/'Backups/before-restore-test.zip';backups.create(self.state,recovery)
        (self.state/'restore-pending.json').write_text(json.dumps(dict(recovery=recovery.name)))
        (self.state/'profiles.json').write_text('{}')
        data=Data(self.state)
        self.assertEqual(data.profile.name,'Original character')
        self.assertEqual(backups.snapshot(self.state),before)

    def test_manual_records_restore_after_reopening(self):
        data=Data(self.state)
        data.inventory.entries.append(InventoryEntry('test-item','Linen Cloth',7,'Bank',utc_now()))
        data.plan.goals.append(CraftGoal('test-goal','Linen Bandage',3,[Ingredient('Linen Cloth',1)]))
        data.save_records('Inventory & Bank');data.save_records('Crafting')
        backups.create(self.state,self.archive);review=backups.inspect(self.archive)
        data.inventory.entries.clear();data.plan.goals.clear()
        data.save_records('Inventory & Bank');data.save_records('Crafting')
        backups.restore(self.state,self.archive,review['sha256'],backups.snapshot(self.state))
        reopened=Data(self.state)
        self.assertEqual(reopened.inventory.entries[0].quantity,7)
        self.assertEqual(reopened.plan.goals[0].quantity,3)

    def test_changed_archive_and_linked_recovery_folder_are_rejected(self):
        review=backups.inspect(self.archive);current=backups.snapshot(self.state)
        backups.create(self.state,self.archive)
        with self.assertRaisesRegex(ValueError,'Backup changed'):
            backups.restore(self.state,self.archive,review['sha256'],current)
        review=backups.inspect(self.archive)
        with patch.object(Path,'is_junction',side_effect=lambda:True):
            with self.assertRaises(ValueError):backups.recovery_path(self.state,'before-restore-test.zip')
        self.assertEqual(backups.snapshot(self.state),current)


class BackupUITests(unittest.TestCase):
    setUp=fixtures.SavedDataSettingsTests.setUp
    tearDown=fixtures.SavedDataSettingsTests.tearDown

    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_cancel_then_restore_preserves_game_save_and_closes(self):
        self.host.data.save_profiles()
        archive=self.root/'backup.zip';backups.create(self.host.data.directory,archive)
        before=backups.snapshot(self.host.data.directory)
        dialog=RestorePreview(self.host,archive);self.assertTrue(dialog.restore_button.isEnabled(),dialog.status.text())
        dialog.reject();self.assertEqual(backups.snapshot(self.host.data.directory),before)
        dialog=RestorePreview(self.host,archive)
        self.host.show();self.assertTrue(self.host.isVisible())
        dialog.restore();self.assertFalse(self.host.isVisible())
        self.assertEqual(backups.snapshot(self.host.data.directory),before)
        self.assertEqual(self.path.read_text(),fixtures.SAVE)

    def test_damaged_preview_disabled_and_unsaved_settings_block_restore(self):
        bad=self.root/'bad.zip';bad.write_bytes(b'broken')
        self.assertFalse(RestorePreview(self.host,bad).restore_button.isEnabled())
        archive=self.root/'backup.zip';backups.create(self.host.data.directory,archive)
        self.host.settings['text_size']+=1
        dialog=RestorePreview(self.host,archive)
        self.assertFalse(dialog.restore_button.isEnabled())
        self.assertIn('Save or revert',dialog.status.text())
