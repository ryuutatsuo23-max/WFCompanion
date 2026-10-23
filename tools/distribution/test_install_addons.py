from pathlib import Path
import tempfile
import unittest
import json
import hashlib
from unittest.mock import patch
from install_addons import install


class AddonTests(unittest.TestCase):
    def test_pins_receipts_tampering_and_legacy_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'addons';packages={}
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);toc=folder/(name+'.toc');toc.write_text('## Version: 0.7.0\n')
                packages[name]=dict(version='0.7.0',source_commit='a'*40,archive_sha256='b'*64,files={toc.name:hashlib.sha256(toc.read_bytes()).hexdigest()})
            (root/'addon_packages.json').write_text(json.dumps(dict(schema=1,packages=packages)))
            receipt=install(payload,client,['WFStorage'],root/'backups')
            self.assertEqual(receipt['packages'],packages)
            old=client/'Interface/AddOns/WFCore/WFCore.toc';old.write_text('## Version: 0.6.0\nBags.lua\n')
            with self.assertRaisesRegex(ValueError,'combined Core'):install(payload,client,['WFStorage'],root/'backups')
            self.assertIn('0.6.0',old.read_text());old.write_text('## Version: 0.7.0\n')
            (payload/'WFStorage/WFStorage.toc').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'pinned manifest'):install(payload,client,['WFStorage'],root/'backups')

    def test_nested_branding_licence_backup_and_toc_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'payload'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('toc')
                (folder/'LICENSE').write_text('licence')
            logo=payload/'WFStorage/branding/forever-storage-logo.png';logo.parent.mkdir();logo.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            old=client/'Interface/AddOns/WFStorage/branding/forever-storage-logo.png';old.parent.mkdir(parents=True);old.write_bytes(b'old logo')
            receipt=install(payload,client,['WFStorage'],root/'backups')
            self.assertEqual(old.read_bytes(),logo.read_bytes())
            self.assertEqual(next((root/'backups').glob('*/WFStorage/branding/*.png')).read_bytes(),b'old logo')
            self.assertTrue(all(row['path'].endswith('.toc') for row in receipt['files'][-2:]))
            (payload/'WFStorage/branding/unreviewed.png').write_bytes(b'anything')
            with self.assertRaises(ValueError):install(payload,client,['WFStorage'],root/'backups')

    def test_write_failure_restores_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'payload'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('new')
                target=client/'Interface/AddOns'/name/(name+'.toc');target.parent.mkdir(parents=True);target.write_text('old')
            original=Path.write_bytes
            failed=[]
            def write(path,raw):
                if path==client/'Interface/AddOns/WFStorage/WFStorage.toc' and not failed:
                    failed.append(True);raise OSError('simulated write failure')
                return original(path,raw)
            with patch.object(Path,'write_bytes',write):
                with self.assertRaises(OSError):install(payload,client,['WFStorage'],root/'backups')
            for name in ('WFCore','WFStorage'):
                self.assertEqual((client/'Interface/AddOns'/name/(name+'.toc')).read_text(),'old')

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
