from pathlib import Path
import tempfile
import unittest
from install_addons import install


class AddonTests(unittest.TestCase):
    def test_selection_dependency_backup_and_saved_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_forever_';client.mkdir();(client/'Wow.exe').write_bytes(b'fixture')
            payload=root/'payload';payload.mkdir()
            for addon in ('WFCore','WFStorage','WFStressProbe'):
                folder=payload/addon;folder.mkdir();(folder/(addon+'.toc')).write_text('new '+addon)
            old=client/'Interface/AddOns/WFCore/WFCore.toc';old.parent.mkdir(parents=True);old.write_text('old')
            saved=client/'WTF/save.lua';saved.parent.mkdir();saved.write_text('personal')
            manifest=install(payload,client,['WFStorage'],root/'backups',check_game=False)
            self.assertEqual(manifest['selected'],['WFCore','WFStorage'])
            self.assertEqual(saved.read_text(),'personal');self.assertEqual(old.read_text(),'new WFCore')
            self.assertFalse((client/'Interface/AddOns/WFStressProbe').exists())
            self.assertEqual(next((root/'backups').glob('*/WFCore/WFCore.toc')).read_text(),'old')
            with self.assertRaises(ValueError):install(payload,root,['WFCore'],root/'backups',check_game=False)
            with self.assertRaises(ValueError):install(payload,client,['OtherAddon'],root/'backups',check_game=False)
