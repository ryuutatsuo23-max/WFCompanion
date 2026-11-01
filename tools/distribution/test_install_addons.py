from pathlib import Path
import tempfile
import unittest
import json
import hashlib
import os
from types import SimpleNamespace
from unittest.mock import patch
from install_addons import AddonInstallError, install, safe_target, _check_windows_link_support


class AddonTests(unittest.TestCase):
    def hard_link(self,source,target):
        try:os.link(source,target)
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Hard links unavailable: Windows error '+str(exc.winerror))
            raise

    def test_hard_link_rejected_before_any_target_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,originals,unrelated=self.rollback_fixture(root)
            sentinel=root/'external-sentinel.lua';self.hard_link(target/'d.lua',sentinel)
            self.assertEqual((target/'d.lua').stat().st_nlink,2)
            with self.assertRaisesRegex(ValueError,'Hard-linked.*WFCore/d.lua.*Preserve') as raised:
                install(payload,client,['WFCore'],root/'backups')
            self.assertNotIn(str(root),str(raised.exception))
            self.assertFalse((root/'backups').exists())
            self.assertEqual(sentinel.read_bytes(),originals['d.lua'])
            self.assertTrue(os.path.samefile(sentinel,target/'d.lua'))
            for name,raw in originals.items():
                self.assertEqual((target/name).read_bytes() if (target/name).exists() else None,raw)
            for path,raw in unrelated.items():self.assertEqual(path.read_bytes(),raw)

    def test_single_link_file_and_missing_destination_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,_,_=self.rollback_fixture(root)
            self.assertEqual((target/'a.lua').stat().st_nlink,1)
            self.assertEqual(safe_target(target/'a.lua',client,for_write=True),target/'a.lua')
            self.assertEqual(safe_target(target/'c.lua',client,for_write=True),target/'c.lua')
            install(payload,client,['WFCore'],root/'backups')
            for source in (payload/'WFCore').iterdir():self.assertEqual((target/source.name).read_bytes(),source.read_bytes())

    def test_unknown_link_count_and_stat_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();target=root/'module.lua';target.write_bytes(b'original');real_stat=Path.stat
            for links in (None,0,-1,True,'1'):
                with self.subTest(links=links):
                    def inspect(path,*args,**kwargs):
                        result=real_stat(path,*args,**kwargs)
                        if path==target and kwargs.get('follow_symlinks') is False:
                            return SimpleNamespace(st_mode=result.st_mode,st_nlink=links)
                        return result
                    with patch.object(Path,'stat',inspect):
                        with self.assertRaisesRegex(ValueError,'Cannot verify.*link count'):safe_target(target,root,for_write=True)
            def denied(path,*args,**kwargs):
                if path==target and kwargs.get('follow_symlinks') is False:raise PermissionError('Synthetic metadata access failure')
                return real_stat(path,*args,**kwargs)
            with patch.object(Path,'stat',denied):
                with self.assertRaises(PermissionError):safe_target(target,root,for_write=True)
            self.assertEqual(target.read_bytes(),b'original')

    @unittest.skipUnless(os.name=='nt','Windows filesystem capability API')
    def test_windows_filesystem_information_must_be_trustworthy(self):
        from unittest.mock import MagicMock
        import ctypes
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            for drive,filesystem,volume_ok,info_ok,allowed in (
                (3,'NTFS',True,True,True),(2,'exFAT',True,True,True),(3,'FAT32',True,True,True),
                (4,'NTFS',True,True,False),(0,'NTFS',True,True,False),(3,'ReFS',True,True,False),
                (3,'unknown',True,True,False),(3,'NTFS',False,True,False),(3,'NTFS',True,False,False)):
                with self.subTest(drive=drive,filesystem=filesystem,volume_ok=volume_ok,info_ok=info_ok):
                    kernel=MagicMock()
                    def volume(path,buffer,size):buffer.value=str(root.anchor);return volume_ok
                    def info(path,label,label_size,serial,maximum,flags,buffer,size):buffer.value=filesystem;return info_ok
                    kernel.GetVolumePathNameW.side_effect=volume;kernel.GetDriveTypeW.return_value=drive
                    kernel.GetVolumeInformationW.side_effect=info
                    with patch.object(ctypes,'WinDLL',return_value=kernel):
                        if allowed:_check_windows_link_support(root)
                        else:
                            with self.assertRaisesRegex(ValueError,'Choose a local'):_check_windows_link_support(root)

    def test_hard_link_added_after_preflight_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,originals,_=self.rollback_fixture(root)
            sentinel=root/'external-sentinel.lua';write_bytes=Path.write_bytes
            self.hard_link(target/'b.lua',sentinel);sentinel.unlink()  # Capability check outside install's exception handler.
            def write(path,raw):
                result=write_bytes(path,raw)
                if path==target/'a.lua' and raw.startswith(b'new '):self.hard_link(target/'b.lua',sentinel)
                return result
            with patch.object(Path,'write_bytes',write):
                with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFCore'],root/'backups')
            self.assertTrue(raised.exception.rollback_complete)
            self.assertIn('Hard-linked',str(raised.exception.__cause__))
            self.assertEqual(sentinel.read_bytes(),originals['b.lua'])
            self.assertEqual((target/'a.lua').read_bytes(),originals['a.lua'])
            self.assertTrue(os.path.samefile(sentinel,target/'b.lua'))

    def test_rollback_preserves_new_hard_link_and_recovers_independent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,originals,_=self.rollback_fixture(root)
            sentinel=root/'external-sentinel.lua';write_bytes=Path.write_bytes
            self.hard_link(target/'d.lua',sentinel);sentinel.unlink()
            def write(path,raw):
                result=write_bytes(path,raw)
                if path==target/'d.lua' and raw.startswith(b'new '):
                    self.hard_link(path,sentinel);raise OSError('Synthetic replacement failure')
                return result
            with patch.object(Path,'write_bytes',write):
                with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFCore'],root/'backups')
            error=raised.exception;self.assertFalse(error.rollback_complete)
            self.assertEqual([path for path,_ in error.rollback_failures],['WFCore/d.lua'])
            self.assertIn('Hard-linked',str(error.rollback_failures[0][1]))
            self.assertEqual(sentinel.read_bytes(),(payload/'WFCore/d.lua').read_bytes())
            self.assertTrue(os.path.samefile(sentinel,target/'d.lua'))
            self.assertEqual((error.backup/'WFCore/d.lua').read_bytes(),originals['d.lua'])
            for name in ('a.lua','b.lua'):self.assertEqual((target/name).read_bytes(),originals[name])
            self.assertFalse((target/'c.lua').exists())

    def test_symlinks_including_dangling_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();original=root/'original.lua';original.write_bytes(b'keep')
            for name,destination in (('linked.lua',original),('dangling.lua',root/'missing.lua')):
                link=root/name
                try:link.symlink_to(destination)
                except OSError as exc:
                    if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Symlinks unavailable: Windows error '+str(exc.winerror))
                    raise
                with self.assertRaisesRegex(ValueError,'Linked'):safe_target(link,root,for_write=True)
                self.assertTrue(link.is_symlink())
            self.assertEqual(original.read_bytes(),b'keep')

    @unittest.skipUnless(os.name=='nt','Windows junctions')
    def test_junctions_including_dangling_junctions_are_rejected(self):
        import _winapi
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();destination=root/'destination';destination.mkdir();link=root/'junction'
            try:_winapi.CreateJunction(str(destination),str(link))
            except OSError as exc:
                if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Junctions unavailable: Windows error '+str(exc.winerror))
                raise
            try:
                for dangling in (False,True):
                    if dangling:destination.rmdir()
                    with self.assertRaisesRegex(ValueError,'Linked'):safe_target(link/'module.lua',root,for_write=True)
                    self.assertTrue(link.is_junction())
            finally:link.rmdir()

    def test_directory_destination_and_containment_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,originals,_=self.rollback_fixture(root)
            (target/'d.lua').unlink();(target/'d.lua').mkdir()
            with self.assertRaisesRegex(ValueError,'regular file'):install(payload,client,['WFCore'],root/'backups')
            self.assertFalse((root/'backups').exists());self.assertEqual((target/'a.lua').read_bytes(),originals['a.lua'])
            with self.assertRaisesRegex(ValueError,'escapes'):safe_target(root/'outside.lua',client,for_write=True)

    def rollback_fixture(self,root):
        client=root/'_forever_';client.mkdir();(client/'Wow.exe').touch()
        payload=root/'payload';source=payload/'WFCore';source.mkdir(parents=True)
        target=client/'Interface/AddOns/WFCore';target.mkdir(parents=True)
        originals={'a.lua':b'old a\x00\xff','b.lua':b'old b','c.lua':None,'d.lua':b'old d','WFCore.toc':b'old toc'}
        for name,raw in originals.items():
            (source/name).write_bytes(b'new '+name.encode())
            if raw is not None:(target/name).write_bytes(raw)
        unrelated={client/'Interface/AddOns/OtherAddon/Keep.lua':b'unrelated addon',
                   target/'extra.lua':b'extra local file',client/'WTF/SavedVariables.lua':b'synthetic save'}
        for path,raw in unrelated.items():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        return client,payload,target,originals,unrelated

    def test_rollback_attempts_every_file_and_reports_all_failures(self):
        # d is first, b is in the middle, c is a newly created file to remove.
        for failed in ((),('d.lua',),('b.lua',),('d.lua','b.lua'),('c.lua',)):
            with self.subTest(failed=failed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();client,payload,target,originals,unrelated=self.rollback_fixture(root)
                write_bytes=Path.write_bytes;unlink=Path.unlink;attempts=[];recovery_errors={}
                original_error=RuntimeError('Synthetic replacement error at '+str(target))
                def recovery(path):
                    attempts.append(path.name)
                    if path.name in failed:
                        error=OSError('Synthetic recovery failure');recovery_errors[path.name]=error;raise error
                def write(path,raw):
                    if path.parent==target and raw==originals.get(path.name):recovery(path)
                    result=write_bytes(path,raw)
                    if path==target/'d.lua' and raw.startswith(b'new '):raise original_error
                    return result
                def remove(path,*args,**kwargs):
                    if path.parent==target:recovery(path)
                    return unlink(path,*args,**kwargs)
                with patch.object(Path,'write_bytes',write),patch.object(Path,'unlink',remove):
                    with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFCore'],root/'backups')
                error=raised.exception
                self.assertEqual(attempts,['d.lua','c.lua','b.lua','a.lua'])
                self.assertEqual(error.rollback_complete,not failed)
                self.assertIs(error.__cause__,original_error);self.assertIs(error.installation_error,original_error)
                self.assertEqual(error.rollback_failures,tuple(('WFCore/'+name,recovery_errors[name]) for name in attempts if name in failed))
                self.assertNotIn(str(root),str(error))
                self.assertIn('rollback was incomplete' if failed else 'original files were restored',str(error))
                for name,raw in originals.items():
                    expected=(payload/'WFCore'/name).read_bytes() if name in failed else raw
                    self.assertEqual((target/name).read_bytes() if (target/name).exists() else None,expected)
                    if raw is not None:self.assertEqual((error.backup/'WFCore'/name).read_bytes(),raw)
                for path,raw in unrelated.items():self.assertEqual(path.read_bytes(),raw)
                self.assertFalse((error.backup/'manifest.json').exists())

    def test_rollback_preserves_external_changes_and_ambiguous_partial_writes(self):
        for changed in ('a.lua','c.lua','d.lua'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();client,payload,target,originals,unrelated=self.rollback_fixture(root)
                write_bytes=Path.write_bytes
                unexpected=b'partial' if changed=='d.lua' else b'external edit'
                def write(path,raw):
                    result=write_bytes(path,raw)
                    if path==target/'d.lua' and raw.startswith(b'new '):
                        write_bytes(target/changed,unexpected)
                        raise OSError('Synthetic failure after change')
                    return result
                with patch.object(Path,'write_bytes',write):
                    with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFCore'],root/'backups')
                self.assertFalse(raised.exception.rollback_complete)
                self.assertEqual([path for path,_ in raised.exception.rollback_failures],['WFCore/'+changed])
                for name,raw in originals.items():
                    self.assertEqual((target/name).read_bytes() if (target/name).exists() else None,unexpected if name==changed else raw)
                for path,raw in unrelated.items():self.assertEqual(path.read_bytes(),raw)

    def test_rollback_verification_failure_does_not_stop_other_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,originals,_=self.rollback_fixture(root)
            write_bytes=Path.write_bytes
            def write(path,raw):
                if path==target/'b.lua' and raw==originals['b.lua']:return 0  # Silent failed recovery write.
                result=write_bytes(path,raw)
                if path==target/'d.lua' and raw.startswith(b'new '):raise RuntimeError('Synthetic failure')
                return result
            with patch.object(Path,'write_bytes',write):
                with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFCore'],root/'backups')
            self.assertFalse(raised.exception.rollback_complete)
            self.assertEqual([path for path,_ in raised.exception.rollback_failures],['WFCore/b.lua'])
            self.assertIn('verification failed',str(raised.exception.rollback_failures[0][1]))
            self.assertEqual((target/'a.lua').read_bytes(),originals['a.lua'])
            self.assertEqual((target/'d.lua').read_bytes(),originals['d.lua'])
            self.assertFalse((target/'c.lua').exists())

    def test_unsafe_rollback_target_does_not_stop_independent_recovery(self):
        from install_addons import safe_target
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();client,payload,target,originals,_=self.rollback_fixture(root)
            write_bytes=Path.write_bytes;rolling_back=[]
            def write(path,raw):
                result=write_bytes(path,raw)
                if path==target/'d.lua' and raw.startswith(b'new '):
                    rolling_back.append(True);raise RuntimeError('Synthetic failure')
                return result
            def check(path,base,**kwargs):
                if rolling_back and path==target/'d.lua':raise ValueError('Linked addon directories are not supported.')
                return safe_target(path,base,**kwargs)
            with patch.object(Path,'write_bytes',write),patch('install_addons.safe_target',check):
                with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFCore'],root/'backups')
            self.assertFalse(raised.exception.rollback_complete)
            self.assertEqual([path for path,_ in raised.exception.rollback_failures],['WFCore/d.lua'])
            for name in ('a.lua','b.lua'):self.assertEqual((target/name).read_bytes(),originals[name])
            self.assertFalse((target/'c.lua').exists())

    def test_core_compass_allowlist_and_malformed_icon_rejection(self):
        from install_addons import package_files
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();folder=root/'WFCore';branding=folder/'branding';branding.mkdir(parents=True)
            (folder/'WFCore.toc').write_text('## Version: 0.7.0\n')
            icon=branding/'wfcompanion-icon.tga'
            raw=bytes((0,0,2,0,0,0,0,0,0,0,0,0,128,0,128,0,32,8))+bytes(128*128*4)
            icon.write_bytes(raw)
            self.assertIn(icon,package_files(root,'WFCore'))
            for bad in (raw[:-1],b'bad',raw[:16]+b'\x18'+raw[17:]):
                icon.write_bytes(bad)
                with self.assertRaisesRegex(ValueError,'TGA'):package_files(root,'WFCore')
            icon.write_bytes(raw);icon.rename(branding/'other-icon.tga')
            with self.assertRaisesRegex(ValueError,'Unexpected'):package_files(root,'WFCore')

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
                with self.assertRaises(AddonInstallError) as raised:install(payload,client,['WFProfessions'],root/'backups')
            self.assertTrue(raised.exception.rollback_complete)
            self.assertIn('injected',str(raised.exception.__cause__))
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
