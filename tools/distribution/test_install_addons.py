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
            root=Path(tmp).resolve();client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
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
            root=Path(tmp).resolve();client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
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

    def test_exact_tga_asset_and_invalid_image_rejection(self):
        from install_addons import package_files
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();folder=root/'WFStorage';(folder/'branding').mkdir(parents=True)
            (folder/'WFStorage.toc').write_text('toc')
            icon=folder/'branding/forever-storage-icon.tga'
            raw=bytes((0,0,2,0,0,0,0,0,0,0,0,0,128,0,128,0,32,8))+bytes(128*128*4)
            for value in (raw,raw+bytes(8)+b'TRUEVISION-XFILE.\0'):
                icon.write_bytes(value);self.assertIn(icon,package_files(root,'WFStorage'))
            for value in (b'bad',raw[:-1],raw+bytes(26)):
                icon.write_bytes(value)
                with self.assertRaisesRegex(ValueError,'TGA'):package_files(root,'WFStorage')
            icon.write_bytes(raw);icon.rename(icon.with_name('other-icon.tga'))
            with self.assertRaisesRegex(ValueError,'Unexpected'):package_files(root,'WFStorage')

    def test_professions_pin_dependency_assets_and_rollback(self):
        from install_addons import package_metadata
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'package/addons';packages={}
            for name in ('WFCore','WFProfessions'):
                folder=payload/name;folder.mkdir(parents=True)
                (folder/(name+'.toc')).write_text('## Version: 0.1.4\n')
            folder=payload/'WFProfessions';(folder/'branding').mkdir()
            (folder/'branding/README.md').write_text('Original artwork')
            (folder/'branding/forever-professions-logo.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            (folder/'branding/forever-professions-icon.tga').write_bytes(bytes((0,0,2,0,0,0,0,0,0,0,0,0,64,0,64,0,32,8))+bytes(64*64*4))
            (folder/'PACKAGE_SHA256.json').write_text(json.dumps(dict(addon='WFProfessions',files={})))
            with self.assertRaisesRegex(ValueError,'manifest is missing'):install(payload,client,['WFProfessions'],root/'backups')
            for name in ('WFCore','WFProfessions'):
                packages[name]=dict(source_commit='a'*40,archive_sha256='b'*64,files={p.relative_to(payload/name).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (payload/name).rglob('*') if p.is_file()})
            (payload.parent/'addon_packages.json').write_text(json.dumps(dict(schema=1,packages=packages)))
            original=Path.write_bytes;failed=[]
            def write(path,raw):
                if path==client/'Interface/AddOns/WFProfessions/WFProfessions.toc' and not failed:
                    failed.append(True);raise OSError('injected Professions failure')
                return original(path,raw)
            with patch.object(Path,'write_bytes',write):
                with self.assertRaisesRegex(OSError,'injected'):install(payload,client,['WFProfessions'],root/'backups')
            self.assertFalse(any(p.is_file() for p in (client/'Interface').rglob('*')))
            receipt=install(payload,client,['WFProfessions'],root/'backups')
            self.assertEqual(receipt['selected'],['WFCore','WFProfessions'])
            self.assertEqual(set(receipt['packages']),{'WFCore','WFProfessions'})
            self.assertFalse((client/'Interface/AddOns/WFStorage').exists())
            (folder/'PACKAGE_SHA256.json').write_text(json.dumps(dict(addon='WFProfessions',files={'tampered':'value'})))
            with self.assertRaisesRegex(ValueError,'pinned manifest'):package_metadata(payload,['WFProfessions'])

    def test_write_failure_restores_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client=root/'_classic_beta_';client.mkdir();(client/'WowB.exe').touch()
            payload=root/'payload'
            for name in ('WFCore','WFStorage'):
                folder=payload/name;folder.mkdir(parents=True);(folder/(name+'.toc')).write_text('new')
                target=client/'Interface/AddOns'/name/(name+'.toc');target.parent.mkdir(parents=True);target.write_text('old')
            original=Path.write_bytes
            failed=[]
            def write(path,raw):
                if path.resolve()==(client/'Interface/AddOns/WFStorage/WFStorage.toc').resolve() and not failed:
                    failed.append(True);raise OSError('simulated write failure')
                return original(path,raw)
            with patch.object(Path,'write_bytes',write):
                with self.assertRaises(OSError):install(payload,client,['WFStorage'],root/'backups')
            for name in ('WFCore','WFStorage'):
                self.assertEqual((client/'Interface/AddOns'/name/(name+'.toc')).read_text(),'old')

    def test_selection_dependency_backup_and_saved_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client=root/'_forever_';client.mkdir();(client/'Wow.exe').write_bytes(b'fixture')
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
