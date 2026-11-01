"""Synthetic-only transaction foundation and real cross-process lock checks."""
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

import install_addons as backend


def fingerprint(raw):
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.client=self.root/'_forever_';self.client.mkdir();(self.client/'Wow.exe').touch()
        self.recovery=self.root/'backup';self.recovery.mkdir()
        self.record=dict(schema=1,id=uuid.uuid4().hex,client=backend.client_identity(self.client),
                         destination='Interface/AddOns',selected=['WFStorage'],expanded=['WFCore','WFStorage'],
                         packages={name:dict(source_commit='a'*40,archive_sha256='b'*64) for name in ('WFCore','WFStorage')},
                         files=[],receipt=dict(path='manifest.json',**fingerprint(b'receipt')))
        for index,name in enumerate(('WFCore/Core.lua','WFStorage/Storage.lua','WFCore/WFCore.toc','WFStorage/WFStorage.toc')):
            old=b'original '+name.encode();new=b'replacement '+name.encode();existed=index!=1
            item=dict(path=name,existed=existed,original=fingerprint(old) if existed else None,
                      replacement=fingerprint(new),stage=name.rsplit('/',1)[0]+f'/.wf-{self.record["id"]}-{index}.stage',
                      backup=name if existed else None)
            self.record['files'].append(item)
            if existed:
                for path in (self.client/'Interface/AddOns'/name,self.recovery/name):
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(old)
        unrelated=self.client/'WTF/synthetic.lua';unrelated.parent.mkdir();unrelated.write_bytes(b'unchanged synthetic save')

    def snapshot(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def validate(self,record=None):
        return backend.validate_transaction(json.dumps(self.record if record is None else record).encode(),self.client,self.recovery)

    def rejected(self,record):
        before=self.snapshot()
        with self.assertRaises(ValueError):self.validate(record)
        self.assertEqual(self.snapshot(),before)

    def test_valid_record_and_bounded_reader_do_not_mutate(self):
        before=self.snapshot();self.assertEqual(self.validate(),self.record);self.assertEqual(self.snapshot(),before)
        (self.recovery/'transaction.json').write_bytes(json.dumps(self.record).encode())
        before=self.snapshot()
        self.assertEqual(backend.read_transaction(self.client,self.recovery),self.record)
        self.assertEqual(self.snapshot(),before)

    def test_schemas_ids_fields_and_dependencies(self):
        for schema in (None,0,2,True,'1'):
            record=copy.deepcopy(self.record);record['schema']=schema;self.rejected(record)
        for identifier in ('bad',uuid.uuid1().hex,'0'*32,self.record['id'].upper()):
            record=copy.deepcopy(self.record);record['id']=identifier;self.rejected(record)
        for field,value in (('extra',1),('selected',[]),('selected',['WFStorage','WFStorage']),
                            ('expanded',['WFStorage']),('expanded',['WFCore','WFStorage','WFProfessions']),
                            ('packages',{}),('files',[])):
            record=copy.deepcopy(self.record);record[field]=value;self.rejected(record)
        for section in ('client','receipt'):
            record=copy.deepcopy(self.record);record[section]['unexpected']=True;self.rejected(record)
        record=copy.deepcopy(self.record);record['files'][0]['unexpected']=True;self.rejected(record)
        record=copy.deepcopy(self.record);record['files'][0]['replacement']['unexpected']=True;self.rejected(record)

    def test_unsafe_and_equivalent_windows_paths(self):
        for name in ('../Core.lua','/WFCore/Core.lua','C:/Core.lua','WFCore\\Core.lua','WFCore/../Core.lua',
                     'WFCore//Core.lua','WFCore/./Core.lua','WFCore/Core.lua:stream','WFCore/CON.lua',
                     'WFCore/LPT1.lua','WFCore/Core.lua.','WFCore/Core.lua ','WFCore/CORE~1.LUA',
                     'OtherAddon/Core.lua','WFCore/state.json','WFCore/branding/unreviewed.png',
                     'WFCore/nested/Core.lua','WFCore/'+('a'*241)+'.lua'):
            record=copy.deepcopy(self.record);record['files'][0]['path']=name;self.rejected(record)
        for name in ('WFCore/Core.lua','WFCore/core.lua'):
            record=copy.deepcopy(self.record);item=copy.deepcopy(record['files'][0]);item['path']=name
            record['files'].insert(1,item);self.rejected(record)

    def test_hashes_sizes_presence_order_and_bounds(self):
        for value in (-1,True,1.5,'1',backend.MAX_TRANSACTION_FILE_BYTES+1):
            record=copy.deepcopy(self.record);record['files'][0]['original']['size']=value;self.rejected(record)
        for value in (None,'0'*63,'G'*64,'A'*64):
            record=copy.deepcopy(self.record);record['files'][0]['replacement']['sha256']=value;self.rejected(record)
        for field,value in (('existed',1),('original',None),('backup','../original'),('backup','WFCore/other.lua'),
                            ('stage','../stage'),('stage','WFCore/.wf-other-0.stage')):
            record=copy.deepcopy(self.record);record['files'][0][field]=value;self.rejected(record)
        record=copy.deepcopy(self.record);record['files'][1]['backup']='WFStorage/Storage.lua';self.rejected(record)
        record=copy.deepcopy(self.record);record['files'].reverse();self.rejected(record)
        record=copy.deepcopy(self.record);record['files'].pop();self.rejected(record)
        record=copy.deepcopy(self.record);record['receipt']['path']='../manifest.json';self.rejected(record)
        record=copy.deepcopy(self.record);record['files']*=backend.MAX_TRANSACTION_FILES;self.rejected(record)
        with patch.object(backend,'MAX_TRANSACTION_TOTAL_BYTES',1):self.rejected(self.record)

    def test_malformed_duplicate_deep_and_oversized_json(self):
        before=self.snapshot()
        for raw in (b'',b'not json',b'\xff',b'[]',b'{"schema":1,"schema":1}',b'{"x":NaN}',
                    b'['*3000+b'0'+b']'*3000,b' '* (backend.MAX_TRANSACTION_BYTES+1)):
            with self.subTest(length=len(raw)),self.assertRaises(ValueError):
                backend.validate_transaction(raw,self.client,self.recovery)
        self.assertEqual(self.snapshot(),before)
        (self.recovery/'transaction.json').write_bytes(b' '*(backend.MAX_TRANSACTION_BYTES+1))
        with self.assertRaisesRegex(ValueError,'oversized'):backend.read_transaction(self.client,self.recovery)

    def test_client_identity_and_recovery_scope(self):
        for key,value in (('path','C:\\wrong'),('inode',1),('device',True)):
            record=copy.deepcopy(self.record);record['client'][key]=value;self.rejected(record)
        record=copy.deepcopy(self.record);record['destination']='WTF';self.rejected(record)
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        with self.assertRaises(ValueError):backend.validate_transaction(json.dumps(self.record).encode(),other,self.recovery)
        with self.assertRaisesRegex(ValueError,'separate'):backend.validate_transaction(json.dumps(self.record).encode(),self.client,self.client)
        with self.assertRaisesRegex(ValueError,'separate'):backend.validate_transaction(json.dumps(self.record).encode(),self.client,self.root)
        with self.assertRaisesRegex(ValueError,'unavailable'):backend.validate_transaction(json.dumps(self.record).encode(),self.client,self.root/'missing')

    def test_hard_linked_targets_stages_backups_receipts_and_records_rejected(self):
        paths=(self.client/'Interface/AddOns/WFCore/Core.lua',self.client/'Interface/AddOns'/self.record['files'][0]['stage'],
               self.recovery/'WFCore/Core.lua',self.recovery/'manifest.json',self.recovery/'transaction.json')
        for path in paths:
            with self.subTest(name=path.name):
                existed=path.exists()
                if not existed:path.write_bytes(json.dumps(self.record).encode() if path.name=='transaction.json' else b'synthetic')
                sentinel=self.root/'sentinel'
                try:os.link(path,sentinel)
                except OSError as exc:
                    if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Hard links unavailable: '+str(exc.winerror))
                    raise
                try:
                    before=self.snapshot()
                    with self.assertRaisesRegex(ValueError,'Hard-linked'):
                        if path.name=='transaction.json':backend.read_transaction(self.client,self.recovery)
                        else:self.validate()
                    self.assertEqual(self.snapshot(),before)
                finally:
                    sentinel.unlink()
                    if not existed:path.unlink()

    def test_symlinked_recovery_reference_is_rejected(self):
        target=self.recovery/'manifest.json'
        try:target.symlink_to(self.recovery/'missing')
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Symlinks unavailable: '+str(exc.winerror))
            raise
        with self.assertRaisesRegex(ValueError,'Linked'):self.validate()

    @unittest.skipUnless(os.name=='nt','Windows junctions')
    def test_junction_recovery_directory_is_rejected(self):
        import _winapi
        alias=self.root/'recovery-alias'
        try:_winapi.CreateJunction(str(self.recovery),str(alias))
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Junctions unavailable: '+str(exc.winerror))
            raise
        try:
            with self.assertRaisesRegex(ValueError,'Linked'):
                backend.validate_transaction(json.dumps(self.record).encode(),self.client,alias)
        finally:alias.rmdir()


# Pause the actual backend after acquisition, before backups or target writes.
# The parent controls release/termination; all paths below are synthetic fixtures.
CHILD_INSTALLER='''
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
real=b.package_metadata
def paused(*args):
    Path(sys.argv[5]).write_text('locked')
    sys.stdin.readline()
    return real(*args)
b.package_metadata=paused
b.install(sys.argv[3],sys.argv[2],['WFCore'],sys.argv[4])
'''


class InstallationLockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.payload=self.root/'payload'
        source=self.payload/'WFCore';source.mkdir(parents=True);(source/'WFCore.toc').write_bytes(b'new toc')
        (source/'Core.lua').write_bytes(b'new module')
        self.client=self.make_client('_forever_')

    def make_client(self,name):
        client=self.root/name;client.mkdir();(client/'Wow.exe').touch()
        target=client/'Interface/AddOns/WFCore';target.mkdir(parents=True);(target/'Core.lua').write_bytes(b'old module')
        return client

    def install(self,client=None):
        return backend.install(self.payload,client or self.client,['WFCore'],self.root/'parent-backups')

    def start_child(self):
        ready=self.root/'ready'
        child=subprocess.Popen([sys.executable,'-B','-c',CHILD_INSTALLER,str(Path(backend.__file__).parent),
                                str(self.client),str(self.payload),str(self.root/'child-backups'),str(ready)],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                               creationflags=0x08000000 if os.name=='nt' else 0)
        def cleanup():
            if child.poll() is None:child.kill()
            child.communicate(timeout=10)
        self.addCleanup(cleanup)
        deadline=time.monotonic()+10
        while not ready.exists():
            if child.poll() is not None:self.fail('Child installer exited: '+child.communicate(timeout=1)[1])
            if time.monotonic()>deadline:self.fail('Child installer did not acquire lock within 10 seconds')
            time.sleep(.02)
        return child

    def test_same_client_competing_installer_rejected_without_changes(self):
        child=self.start_child()
        before={p.relative_to(self.client).as_posix():p.read_bytes() for p in self.client.rglob('*') if p.is_file()}
        variants=[self.client,self.client/'..'/self.client.name]
        if os.name=='nt':variants.append(Path(str(self.client).upper()))
        for variant in variants:
            with self.assertRaisesRegex(ValueError,'Another addon installation'):self.install(variant)
        self.assertEqual(before,{p.relative_to(self.client).as_posix():p.read_bytes() for p in self.client.rglob('*') if p.is_file()})
        self.assertFalse((self.root/'parent-backups').exists())
        _,error=child.communicate('continue\n',timeout=15);self.assertEqual(child.returncode,0,error)
        self.install()  # Normal release allows another installation.
        self.assertEqual((self.client/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'new module')
        self.assertFalse(any('transaction' in p.name or 'pending' in p.name or p.suffix=='.stage' for p in self.root.rglob('*')))

    def test_different_client_can_install_while_first_is_locked(self):
        child=self.start_child();other=self.make_client('_classic_beta_');self.install(other)
        self.assertEqual((self.client/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'old module')
        self.assertEqual((other/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'new module')
        _,error=child.communicate('continue\n',timeout=15);self.assertEqual(child.returncode,0,error)

    def test_terminated_installer_releases_lock(self):
        child=self.start_child();child.kill();child.communicate(timeout=10)
        self.assertNotEqual(child.returncode,0);self.assertFalse((self.root/'child-backups').exists())
        self.install()
        self.assertEqual((self.client/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'new module')

    def test_same_process_recursion_and_exception_release(self):
        with backend.installation_lock(self.client):
            with self.assertRaisesRegex(ValueError,'Another addon installation'):self.install()
        with self.assertRaises(ValueError):backend.install(self.payload,self.client,['invalid'],self.root/'backups')
        self.assertFalse((self.root/'backups').exists())
        self.install()

    def test_lock_covers_receipt_and_exception_rollback(self):
        target=self.client/'Interface/AddOns/WFCore/Core.lua'
        write_text=Path.write_text;write_bytes=Path.write_bytes;checked=[]
        def receipt(path,text,*args,**kwargs):
            if path.name=='manifest.json':
                with self.assertRaisesRegex(ValueError,'Another addon installation'):self.install()
                checked.append('receipt')
                raise OSError('Synthetic receipt publication failure')
            return write_text(path,text,*args,**kwargs)
        def rollback(path,raw):
            if path==target and raw==b'old module':
                with self.assertRaisesRegex(ValueError,'Another addon installation'):self.install()
                checked.append('rollback')
            return write_bytes(path,raw)
        with patch.object(Path,'write_text',receipt),patch.object(Path,'write_bytes',rollback):
            with self.assertRaises(backend.AddonInstallError) as raised:self.install()
        self.assertTrue(raised.exception.rollback_complete)
        self.assertEqual(checked,['receipt','rollback'])
        self.assertEqual(target.read_bytes(),b'old module')
        self.assertFalse((target.parent/'WFCore.toc').exists())
        self.install()

    def test_command_line_entry_uses_same_lock(self):
        import launcher
        bundle=self.root/'bundle';source=bundle/'payload/addons/WFCore';source.mkdir(parents=True)
        (source/'WFCore.toc').write_bytes(b'new toc')
        with patch.object(sys,'_MEIPASS',str(bundle),create=True),patch.object(sys,'path',list(sys.path)),\
             patch.object(sys,'argv',['companion','--install-addons',str(self.client),'--addons','WFCore']),\
             patch.dict(os.environ,{'LOCALAPPDATA':str(self.root/'appdata')}),backend.installation_lock(self.client):
            self.assertEqual(launcher.main(),1)
        state=self.root/'appdata/WoWForever/Companion'
        self.assertIn('Another addon installation',(state/'addon-install-error.txt').read_text())
        self.assertFalse((state/'AddonBackups').exists())
        self.assertEqual((self.client/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'old module')

    def test_unknown_client_identity_rejected_without_writes(self):
        from types import SimpleNamespace
        real=Path.stat
        def unknown(path,*args,**kwargs):
            info=real(path,*args,**kwargs)
            if path==self.client and not kwargs:
                return SimpleNamespace(st_dev=info.st_dev,st_ino=0,st_mode=info.st_mode)
            return info
        with patch.object(Path,'stat',unknown):
            with self.assertRaisesRegex(ValueError,'folder identity'):self.install()
        self.assertFalse((self.root/'parent-backups').exists())
        self.assertEqual((self.client/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'old module')

    @unittest.skipUnless(os.name=='nt','Windows mutex API')
    def test_mutex_acquisition_failures_and_abandoned_ownership(self):
        import ctypes
        for handle,result in ((None,0),(123,0xffffffff),(123,0x102),(123,0x80)):
            with self.subTest(handle=handle,result=result):
                kernel=MagicMock();kernel.CreateMutexW.return_value=handle
                kernel.WaitForSingleObject.return_value=result;kernel.ReleaseMutex.return_value=True
                with patch.object(ctypes,'WinDLL',return_value=kernel),patch.object(backend,'_check_windows_link_support'):
                    if result==0x80:
                        with backend.installation_lock(self.client):pass
                        kernel.ReleaseMutex.assert_called_once_with(handle)
                    else:
                        with self.assertRaises((OSError,ValueError)):self.install()
                        kernel.ReleaseMutex.assert_not_called()
                    if handle:kernel.CloseHandle.assert_called_once_with(handle)
                self.assertEqual((self.client/'Interface/AddOns/WFCore/Core.lua').read_bytes(),b'old module')
                self.assertFalse((self.root/'parent-backups').exists())


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.client=self.root/'_forever_';self.client.mkdir();(self.client/'Wow.exe').touch()
        self.backups=self.root/'backups';self.backups.mkdir()
        self.payload=self.root/'package/addons';packages={}
        for addon in ('WFCore','WFStorage','WFProfessions'):
            folder=self.payload/addon;folder.mkdir(parents=True)
            (folder/(addon+'.toc')).write_bytes(b'## Version: 0.7.0\nmodule.lua\n')
            (folder/'module.lua').write_bytes(b'replacement '+addon.encode())
            packages[addon]=dict(source_commit='a'*40,archive_sha256='b'*64,
                files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()})
        (self.payload.parent/'addon_packages.json').write_text(json.dumps(dict(schema=1,packages=packages)))
        self.original=self.client/'Interface/AddOns/WFCore/module.lua'
        self.original.parent.mkdir(parents=True);self.original.write_bytes(b'original\x00\xff exact bytes')
        unrelated=self.client/'Interface/AddOns/Other/keep.lua';unrelated.parent.mkdir();unrelated.write_bytes(b'untouched')
        save=self.client/'WTF/synthetic.lua';save.parent.mkdir();save.write_bytes(b'synthetic saved bytes')
        self.before=self.snapshot()

    def snapshot(self):
        return {p.relative_to(self.client).as_posix():p.read_bytes() for p in self.client.rglob('*') if p.is_file()}

    def prepare(self,selected=('WFStorage',)):
        return backend.prepare_transaction(self.payload,self.client,selected,self.backups)

    def assert_clean(self):
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(list(self.backups.iterdir()),[])

    def test_missing_member_after_verification_rejected_before_artifacts(self):
        real=backend.package_metadata
        for addon in ('WFStorage','WFCore'):
            with self.subTest(addon=addon):
                member=self.payload/addon/'module.lua';original=member.read_bytes()
                def changed(payload,selected):
                    metadata=real(payload,selected)
                    member.unlink()
                    return metadata
                try:
                    with patch.object(backend,'package_metadata',changed),\
                         patch.object(Path,'mkdir',side_effect=AssertionError('Artifact directory created before rejection')),\
                         patch.object(backend,'_write_preparation_artifact',wraps=backend._write_preparation_artifact) as write:
                        with self.assertRaisesRegex(ValueError,'package.*(incomplete|changed)') as raised:
                            with self.prepare():self.fail('Missing package member accepted')
                        write.assert_not_called()
                    self.assertNotIn(str(self.root),str(raised.exception))
                    self.assert_clean()
                finally:member.write_bytes(original)

    def test_unexpected_member_after_verification_rejected_before_artifacts(self):
        real=backend.package_metadata
        for addon in ('WFStorage','WFCore'):
            with self.subTest(addon=addon):
                member=self.payload/addon/'unlisted.lua'
                def changed(payload,selected):
                    metadata=real(payload,selected)
                    member.write_bytes(b'unlisted synthetic member')
                    return metadata
                try:
                    with patch.object(backend,'package_metadata',changed),\
                         patch.object(Path,'mkdir',side_effect=AssertionError('Artifact directory created before rejection')),\
                         patch.object(backend,'_write_preparation_artifact',wraps=backend._write_preparation_artifact) as write:
                        with self.assertRaisesRegex(ValueError,'package.*(incomplete|changed)') as raised:
                            with self.prepare():self.fail('Unexpected package member accepted')
                        write.assert_not_called()
                    self.assertNotIn(str(self.root),str(raised.exception))
                    self.assert_clean()
                finally:member.unlink(missing_ok=True)

    def test_verified_originals_stages_dependencies_receipt_and_scoped_cleanup(self):
        packages=json.loads((self.payload.parent/'addon_packages.json').read_text())['packages']
        with self.prepare(('WFStorage','WFProfessions')) as result:
            record=result['record'];recovery=result['recovery']
            self.assertEqual(record,backend.validate_transaction(result['record_bytes'],self.client,recovery))
            self.assertEqual(record['selected'],['WFProfessions','WFStorage'])
            self.assertEqual(record['expanded'],['WFCore','WFProfessions','WFStorage'])
            self.assertEqual(set(record['packages']),set(record['expanded']))
            for addon in record['expanded']:
                captured={item['path'].split('/',1)[1]:item['replacement']['sha256']
                          for item in record['files'] if item['path'].startswith(addon+'/')}
                self.assertEqual(captured,packages[addon]['files'])
            self.assertEqual([item['path'] for item in record['files']],
                ['WFCore/module.lua','WFProfessions/module.lua','WFStorage/module.lua',
                 'WFCore/WFCore.toc','WFProfessions/WFProfessions.toc','WFStorage/WFStorage.toc'])
            for item in record['files']:
                stage=self.client/'Interface/AddOns'/item['stage']
                self.assertEqual(stage.read_bytes(),(self.payload/item['path']).read_bytes())
                self.assertEqual(fingerprint(stage.read_bytes()),item['replacement'])
                self.assertEqual(stage.stat().st_dev,self.client.stat().st_dev)
                if item['existed']:
                    raw=(recovery/item['backup']).read_bytes()
                    self.assertEqual(raw,self.before['Interface/AddOns/'+item['path']])
                    self.assertEqual(fingerprint(raw),item['original'])
                else:
                    self.assertIsNone(item['original']);self.assertIsNone(item['backup'])
                    self.assertFalse((self.client/'Interface/AddOns'/item['path']).exists())
            self.assertEqual(fingerprint(result['receipt_bytes']),{k:record['receipt'][k] for k in ('size','sha256')})
            receipt=json.loads(result['receipt_bytes'])
            self.assertEqual(set(receipt),{'client','selected','packages','files'})
            self.assertEqual(receipt['selected'],record['expanded'])
            self.assertFalse((recovery/'manifest.json').exists())
            self.assertFalse((recovery/'transaction.json').exists())
            with self.assertRaisesRegex(ValueError,'Another addon installation'):
                backend.install(self.payload,self.client,['WFCore'],self.backups)
        self.assert_clean()
        # Same backend remains available and does not use the new helper.
        with patch.object(backend,'prepare_transaction',side_effect=AssertionError('inactive API')),\
             patch.object(backend,'inspect_pending_transaction',side_effect=AssertionError('inactive inspection')),\
             patch.object(backend,'recover_pending_transaction',side_effect=AssertionError('inactive recovery')),\
             patch.object(backend,'complete_pending_installation',side_effect=AssertionError('inactive completion')),\
             patch.object(backend,'complete_pending_rollback',side_effect=AssertionError('inactive retirement')),\
             patch.object(backend,'execute_transaction',side_effect=AssertionError('inactive executor')):
            backend.install(self.payload,self.client,['WFStorage'],self.backups)
        self.assertEqual(self.original.read_bytes(),(self.payload/'WFCore/module.lua').read_bytes())

    def test_originals_all_verified_before_first_stage(self):
        real=backend._write_preparation_artifact;observed=[]
        def write(path,root,raw,artifacts,directories):
            if path.suffix=='.stage':
                backups=list(self.backups.glob('prepare-*/WFCore/module.lua'))
                self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),self.original.read_bytes())
                observed.append(path)
            return real(path,root,raw,artifacts,directories)
        with patch.object(backend,'_write_preparation_artifact',write),self.prepare():pass
        self.assertTrue(observed);self.assert_clean()

    def test_empty_original_and_nested_asset_staging(self):
        self.original.write_bytes(b'')
        asset=self.payload/'WFStorage/branding/forever-storage-logo.png'
        asset.parent.mkdir();asset.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
        manifest=self.payload.parent/'addon_packages.json'
        document=json.loads(manifest.read_text())
        document['packages']['WFStorage']['files']['branding/'+asset.name]=hashlib.sha256(asset.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(document))
        before=self.snapshot()
        with self.prepare() as result:
            original=next(item for item in result['record']['files'] if item['path']=='WFCore/module.lua')
            self.assertTrue(original['existed']);self.assertEqual(original['original'],fingerprint(b''))
            self.assertEqual((result['recovery']/original['backup']).read_bytes(),b'')
            item=next(item for item in result['record']['files'] if item['path'].endswith('.png'))
            self.assertEqual((self.client/'Interface/AddOns'/item['stage']).read_bytes(),asset.read_bytes())
        self.assertEqual(self.snapshot(),before);self.assertEqual(list(self.backups.iterdir()),[])
        self.assertFalse((self.client/'Interface/AddOns/WFStorage').exists())

    def test_preparation_does_not_bypass_existing_lock(self):
        with backend.installation_lock(self.client),self.assertRaisesRegex(ValueError,'Another addon installation'):
            with self.prepare():pass
        self.assert_clean()

    def test_original_change_disappearance_or_new_destination_aborts(self):
        real=backend._write_preparation_artifact
        for mode in ('changed','removed','new'):
            with self.subTest(mode=mode):
                self.original.write_bytes(self.before['Interface/AddOns/WFCore/module.lua'])
                added=self.client/'Interface/AddOns/WFCore/WFCore.toc';added.unlink(missing_ok=True)
                changed=[]
                def write(*args):
                    real(*args)
                    if not changed:
                        changed.append(True)
                        if mode=='changed':self.original.write_bytes(b'external edit')
                        elif mode=='removed':self.original.unlink()
                        else:added.write_bytes(b'external new file')
                with patch.object(backend,'_write_preparation_artifact',write):
                    with self.assertRaisesRegex(ValueError,'changed during preparation'):
                        with self.prepare():self.fail('Must not yield stale originals')
                self.assertEqual(list(self.backups.iterdir()),[])
                self.assertFalse(list(self.client.rglob('*.stage')))
                if mode=='changed':self.assertEqual(self.original.read_bytes(),b'external edit')
                elif mode=='removed':self.assertFalse(self.original.exists())
                else:self.assertEqual(added.read_bytes(),b'external new file')

    def test_unreadable_original_and_changed_package_fail_without_artifacts(self):
        real=Path.open
        def unreadable(path,*args,**kwargs):
            if path==self.original:raise PermissionError('synthetic read denial')
            return real(path,*args,**kwargs)
        with patch.object(Path,'open',unreadable),self.assertRaises(PermissionError):
            with self.prepare():self.fail('Unreadable original accepted')
        self.assert_clean()
        source=self.payload/'WFStorage/module.lua';source.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'pinned manifest'):
            with self.prepare():self.fail('Changed package accepted')
        self.assert_clean()

    def test_hard_link_destination_rejected_without_modifying_sentinel(self):
        sentinel=self.root/'sentinel'
        try:os.link(self.original,sentinel)
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Hard links unavailable: '+str(exc.winerror))
            raise
        before=sentinel.read_bytes()
        with self.assertRaisesRegex(ValueError,'Hard-linked'):
            with self.prepare():self.fail('Hard link accepted')
        self.assertEqual(sentinel.read_bytes(),before);self.assert_clean()

    def test_unsafe_backup_roots_and_destination_types(self):
        with self.assertRaisesRegex(ValueError,'separate'):
            with backend.prepare_transaction(self.payload,self.client,['WFCore'],self.client):pass
        self.original.unlink();self.original.mkdir()
        with self.assertRaisesRegex(ValueError,'regular file'):
            with self.prepare():pass
        self.assertEqual(list(self.backups.iterdir()),[])

    @unittest.skipUnless(os.name=='nt','Windows junctions')
    def test_junction_backup_root_rejected(self):
        import _winapi
        alias=self.root/'alias'
        try:_winapi.CreateJunction(str(self.backups),str(alias))
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Junctions unavailable: '+str(exc.winerror))
            raise
        try:
            with self.assertRaisesRegex(ValueError,'Linked'):
                with backend.prepare_transaction(self.payload,self.client,['WFCore'],alias):pass
            self.assert_clean()
        finally:alias.rmdir()

    def test_symlink_destination_rejected(self):
        target=self.original.parent/'WFCore.toc'
        try:target.symlink_to(self.root/'missing')
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Symlinks unavailable: '+str(exc.winerror))
            raise
        with self.assertRaisesRegex(ValueError,'Linked'):
            with self.prepare():pass
        self.assertTrue(target.is_symlink());self.assertEqual(list(self.backups.iterdir()),[])

    def test_limits_rejected_before_artifact_creation(self):
        for limit in ('MAX_TRANSACTION_FILES','MAX_TRANSACTION_BYTES','MAX_TRANSACTION_FILE_BYTES','MAX_TRANSACTION_TOTAL_BYTES'):
            with self.subTest(limit=limit),patch.object(backend,limit,1),self.assertRaises(ValueError):
                with self.prepare():self.fail('Oversized preparation accepted')
            self.assert_clean()

    def test_creation_failure_and_collision_do_not_overwrite(self):
        real=Path.open
        def denied(path,mode='r',*args,**kwargs):
            if mode=='xb':raise PermissionError('synthetic create denial')
            return real(path,mode,*args,**kwargs)
        with patch.object(Path,'open',denied),self.assertRaises(PermissionError):
            with self.prepare():pass
        self.assert_clean()
        identifier=uuid.uuid4();collision=self.backups/('prepare-'+identifier.hex);collision.mkdir()
        (collision/'keep').write_bytes(b'other owner')
        with patch.object(backend.uuid,'uuid4',return_value=identifier),self.assertRaises(FileExistsError):
            with self.prepare():pass
        self.assertEqual((collision/'keep').read_bytes(),b'other owner')
        self.assertEqual(self.snapshot(),self.before)

    def test_partial_write_flush_sync_and_verification_failures(self):
        real_open=Path.open;real_read=backend._read_preparation_file
        for mode in ('short','flush','sync','verify'):
            with self.subTest(mode=mode):
                class Stream:
                    def __init__(self,stream):self.stream=stream
                    def __enter__(self):return self
                    def __exit__(self,*args):self.stream.close()
                    def fileno(self):return self.stream.fileno()
                    def write(self,raw):return self.stream.write(raw[:3] if mode=='short' else raw)
                    def flush(self):
                        if mode=='flush':raise OSError('synthetic flush failure')
                        self.stream.flush()
                def opened(path,open_mode='r',*args,**kwargs):
                    open_mode=kwargs.pop('mode',open_mode)
                    stream=real_open(path,open_mode,*args,**kwargs)
                    return Stream(stream) if open_mode=='xb' else stream
                injected=[]
                def read(path,root,**kwargs):
                    raw,stamp=real_read(path,root,**kwargs)
                    if mode=='verify' and path.is_relative_to(self.backups) and raw is not None and not injected:
                        injected.append(True);return b'wrong bytes',stamp
                    return raw,stamp
                sync=backend.os.fsync
                def fsync(fd):
                    if mode=='sync':raise OSError('synthetic sync failure')
                    return sync(fd)
                with patch.object(Path,'open',opened),patch.object(backend,'_read_preparation_file',read),patch.object(backend.os,'fsync',fsync):
                    with self.assertRaises((OSError,ValueError)):
                        with self.prepare():self.fail('Failed artifacts yielded')
                self.assert_clean()

    def test_exceptional_partial_write_is_preserved_and_reported(self):
        real=Path.open
        class Stream:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def fileno(self):return self.stream.fileno()
            def write(self,raw):
                self.stream.write(raw[:3]);raise OSError('unknown partial write')
        def opened(path,mode='r',*args,**kwargs):
            stream=real(path,mode,*args,**kwargs)
            return Stream(stream) if mode=='xb' else stream
        with patch.object(Path,'open',opened),self.assertRaises(backend.TransactionPreparationError) as raised:
            with self.prepare():pass
        self.assertTrue(raised.exception.cleanup_failures)
        self.assertIsInstance(raised.exception.preparation_error,OSError)
        leftovers=list(self.backups.glob('prepare-*/WFCore/module.lua'))
        self.assertEqual(len(leftovers),1);self.assertEqual(leftovers[0].read_bytes(),b'ori')
        self.assertEqual(self.snapshot(),self.before)

    def test_external_artifact_changes_preserved_other_artifacts_cleaned(self):
        with self.assertRaises(backend.TransactionPreparationError) as raised:
            with self.prepare() as result:
                stage=self.client/'Interface/AddOns'/result['record']['files'][0]['stage']
                stage.write_bytes(b'external edit')
                extra=result['recovery']/'external';extra.write_bytes(b'other owner')
        self.assertTrue(raised.exception.cleanup_failures)
        self.assertEqual(stage.read_bytes(),b'external edit');self.assertEqual(extra.read_bytes(),b'other owner')
        self.assertEqual(list(self.client.rglob('*.stage')),[stage])
        self.assertFalse((result['recovery']/'WFCore/module.lua').exists())
        for name,raw in self.before.items():self.assertEqual((self.client/name).read_bytes(),raw)

    def test_cleanup_failure_attempts_other_artifacts_and_releases_lock(self):
        real=Path.unlink;failed=[]
        def unlink(path,*args,**kwargs):
            if path.suffix=='.stage' and not failed:
                failed.append(path);raise PermissionError('synthetic cleanup denial')
            return real(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink),self.assertRaises(backend.TransactionPreparationError) as raised:
            with self.prepare():pass
        self.assertTrue(raised.exception.cleanup_failures)
        self.assertEqual(list(self.client.rglob('*.stage')),failed)
        self.assertEqual(list(self.backups.iterdir()),[])
        with backend.installation_lock(self.client):pass

    def test_caller_exception_cleans_artifacts_and_releases_lock(self):
        with self.assertRaisesRegex(RuntimeError,'synthetic caller'):
            with self.prepare():raise RuntimeError('synthetic caller failure')
        self.assert_clean()
        with backend.installation_lock(self.client):pass

    def test_stage_collision_is_preserved_and_backups_cleaned(self):
        identifier=uuid.uuid4()
        stage=self.original.parent/f'.wf-{identifier.hex}-0.stage';stage.write_bytes(b'not ours')
        before=self.snapshot()
        with patch.object(backend.uuid,'uuid4',return_value=identifier),self.assertRaises(FileExistsError):
            with self.prepare():pass
        self.assertEqual(self.snapshot(),before);self.assertEqual(list(self.backups.iterdir()),[])

    def test_stage_sync_failure_cleans_completed_backups_and_stages(self):
        real=backend._write_preparation_artifact
        def write(path,*args):
            if path.suffix=='.stage':
                with patch.object(backend.os,'fsync',side_effect=OSError('stage sync failed')):
                    return real(path,*args)
            return real(path,*args)
        with patch.object(backend,'_write_preparation_artifact',write),self.assertRaisesRegex(OSError,'stage sync'):
            with self.prepare():pass
        self.assert_clean()

    def test_late_artifact_corruption_fails_final_verification_and_preserves_it(self):
        real=backend._write_preparation_artifact;first=[]
        def write(path,*args):
            real(path,*args)
            if path.suffix=='.stage':
                if not first:first.append(path)
                else:first[0].write_bytes(b'external corruption')
        with patch.object(backend,'_write_preparation_artifact',write),self.assertRaises(backend.TransactionPreparationError) as raised:
            with self.prepare():self.fail('Corrupted stage accepted')
        self.assertIsInstance(raised.exception.preparation_error,ValueError)
        self.assertEqual(first[0].read_bytes(),b'external corruption')
        self.assertEqual(list(self.client.rglob('*.stage')),first)
        self.assertEqual(list(self.backups.iterdir()),[])

    def test_changed_artifact_metadata_is_preserved_even_if_bytes_match(self):
        with self.assertRaises(backend.TransactionPreparationError):
            with self.prepare() as result:
                stage=self.client/'Interface/AddOns'/result['record']['files'][0]['stage']
                info=stage.stat();raw=stage.read_bytes()
                os.utime(stage,ns=(info.st_atime_ns,info.st_mtime_ns+10_000_000_000))
        self.assertEqual(stage.read_bytes(),raw)
        self.assertEqual(list(self.client.rglob('*.stage')),[stage])

    def test_hard_link_added_to_stage_prevents_cleanup_of_external_sentinel(self):
        sentinel=self.root/'external-link'
        try:
            with self.assertRaises(backend.TransactionPreparationError):
                with self.prepare() as result:
                    stage=self.client/'Interface/AddOns'/result['record']['files'][0]['stage']
                    try:os.link(stage,sentinel)
                    except OSError as exc:
                        if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Hard links unavailable: '+str(exc.winerror))
                        raise
            self.assertEqual(sentinel.read_bytes(),stage.read_bytes())
            self.assertEqual(list(self.client.rglob('*.stage')),[stage])
        finally:sentinel.unlink(missing_ok=True)

    def test_original_change_during_open_read_is_detected(self):
        real=Path.open
        class Stream:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def fileno(self):return self.stream.fileno()
            def read(stream_self,*args):
                raw=stream_self.stream.read(*args)
                with real(self.original,'wb') as output:output.write(b'changed mid-read')
                return raw
        def opened(path,mode='r',*args,**kwargs):
            stream=real(path,mode,*args,**kwargs)
            return Stream(stream) if path==self.original and mode=='rb' else stream
        with patch.object(Path,'open',opened),self.assertRaisesRegex(ValueError,'changed during preparation'):
            with self.prepare():pass
        self.assertEqual(self.original.read_bytes(),b'changed mid-read')
        self.assertEqual(list(self.backups.iterdir()),[])


@unittest.skipUnless(os.name=='nt','Pending publication uses Windows non-replacing rename')
class ProductionGuardTests(unittest.TestCase):
    setUp=PreparationTests.setUp
    snapshot=PreparationTests.snapshot
    tree_bytes=staticmethod(lambda root:{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def install(self,client=None):
        return backend.install(self.payload,client or self.client,['WFStorage'],self.backups)

    def publish(self):
        root=backend.production_recovery_root(self.client);root.mkdir(parents=True)
        with backend.prepare_transaction(self.payload,self.client,['WFStorage'],root) as prepared:
            prepared.publish_pending()
        return root,prepared

    def assert_blocked(self,code):
        before=self.tree_bytes(self.root)
        with patch.object(backend,'_install_locked',side_effect=AssertionError('Legacy writer reached')):
            with self.assertRaises(backend.InstallationGuardError) as raised:self.install()
        self.assertEqual(raised.exception.code,code)
        self.assertNotIn(str(self.root),str(raised.exception))
        self.assertEqual(self.tree_bytes(self.root),before)

    def test_missing_root_inspection_creates_nothing_and_legacy_backups_unchanged(self):
        before=self.tree_bytes(self.root);root=backend.production_recovery_root(self.client)
        result=backend.inspect_production_pending(self.client)
        self.assertEqual((result['state'],result['root_state']),('none','absent_unproven'))
        self.assertEqual(self.tree_bytes(self.root),before);self.assertFalse(root.parent.exists())
        receipt=self.install()
        self.assertEqual(receipt['selected'],['WFCore','WFStorage'])
        self.assertEqual(self.original.read_bytes(),(self.payload/'WFCore/module.lua').read_bytes())
        backups=list(self.backups.glob('*/WFCore/module.lua'));self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(len(list(self.backups.glob('*/manifest.json'))),1)
        self.assertFalse(root.parent.exists());self.assertFalse((self.client/backend.PENDING_NAME).exists())

    def test_existing_empty_root_is_safe_and_retains_unrelated_residuals(self):
        root=backend.production_recovery_root(self.client);root.mkdir(parents=True)
        residual=root/'unrelated.txt';residual.write_bytes(b'preserve')
        result=backend.inspect_production_pending(self.client)
        self.assertEqual((result['state'],result['root_state']),('none','existing'))
        self.install();self.assertEqual(residual.read_bytes(),b'preserve')

    def test_valid_pending_blocks_even_with_different_legacy_backup_argument(self):
        self.publish()
        self.assertEqual(backend.inspect_production_pending(self.client)['state'],'valid')
        self.backups=self.root/'different-companion-state'
        self.assert_blocked('recovery_pending');self.assertFalse(self.backups.exists())

    def test_invalid_and_ambiguous_pending_block_without_mutation(self):
        marker=self.client/backend.PENDING_NAME;marker.write_bytes(b'{broken')
        self.assert_blocked('recovery_invalid');marker.unlink()
        (self.client/'.wf-addon-pending-synthetic.stage').write_bytes(b'partial')
        self.assert_blocked('recovery_ambiguous')

    def test_missing_or_replaced_root_with_marker_is_not_uninitialized(self):
        root,prepared=self.publish();parked=root.with_name('parked-evidence');root.rename(parked)
        result=backend.inspect_production_pending(self.client)
        self.assertEqual((result['state'],result['root_state']),('invalid','missing_with_pending_evidence'))
        self.assert_blocked('recovery_invalid')
        root.mkdir()  # Same path, different filesystem identity.
        self.assert_blocked('recovery_invalid')
        self.assertTrue((parked/prepared['recovery'].name/'transaction.json').is_file())

    def test_root_replaced_during_inspection_is_rejected(self):
        root=backend.production_recovery_root(self.client);root.mkdir(parents=True)
        real=backend._inspect_pending_locked
        def replace(*args,**kwargs):
            result=real(*args,**kwargs);root.rename(root.with_name('old-root'));root.mkdir();return result
        with patch.object(backend,'_inspect_pending_locked',replace):
            with self.assertRaises(backend.InstallationGuardError) as raised:self.install()
        self.assertEqual(raised.exception.code,'recovery_location_unavailable')
        self.assertEqual(self.snapshot(),self.before);self.assertEqual(list(self.backups.iterdir()),[])

    def test_permission_error_is_sanitized_and_has_no_fallback(self):
        root=backend.production_recovery_root(self.client);root.mkdir(parents=True)
        real=backend.os.scandir
        def denied(path):
            if Path(path)==root:raise PermissionError('private-path '+str(root))
            return real(path)
        before=self.snapshot()
        with patch.object(backend.os,'scandir',denied):
            with self.assertRaises(backend.InstallationGuardError) as raised:self.install()
        self.assertEqual(raised.exception.code,'recovery_location_unavailable')
        self.assertNotIn(str(root),str(raised.exception));self.assertIsInstance(raised.exception.__cause__,PermissionError)
        self.assertEqual(self.snapshot(),before);self.assertEqual(list(self.backups.iterdir()),[])

    def test_non_directory_or_hard_link_root_is_rejected(self):
        root=backend.production_recovery_root(self.client);root.parent.mkdir()
        sentinel=self.root/'sentinel';sentinel.write_bytes(b'external')
        os.link(sentinel,root)
        self.assert_blocked('recovery_location_unavailable');self.assertEqual(sentinel.read_bytes(),b'external')

    @unittest.skipUnless(os.name=='nt','Windows junction test')
    def test_linked_namespace_or_root_is_rejected(self):
        import _winapi
        root=backend.production_recovery_root(self.client);external=self.root/'external';external.mkdir()
        for target in (root.parent,root):
            if target==root:root.parent.mkdir()
            try:
                _winapi.CreateJunction(str(external),str(target))
                self.assert_blocked('recovery_location_unavailable')
            finally:
                if target.is_junction():target.rmdir()

    def test_same_client_busy_and_independent_beta_client(self):
        beta=self.root/'_classic_beta_';beta.mkdir();(beta/'WowB.exe').touch()
        self.assertNotEqual(backend.production_recovery_root(beta),backend.production_recovery_root(self.client))
        with backend.installation_lock(self.client):
            with self.assertRaisesRegex(ValueError,'Another addon installation'):self.install()
            self.install(beta)
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual((beta/'Interface/AddOns/WFCore/module.lua').read_bytes(),(self.payload/'WFCore/module.lua').read_bytes())

    def test_wrong_lock_identity_cannot_reach_inspection(self):
        real=backend.installation_lock
        @contextmanager
        def wrong(client):
            with real(client) as identity:yield dict(identity,inode=identity['inode']+1)
        with patch.object(backend,'installation_lock',wrong),patch.object(backend,'_inspect_pending_locked') as inspect:
            with self.assertRaisesRegex(ValueError,'changed while acquiring'):self.install()
            inspect.assert_not_called()
        self.assertEqual(self.snapshot(),self.before)

    @unittest.skipUnless(os.name=='nt','Windows junction test')
    def test_stable_alias_and_retargeting_before_or_after_lock(self):
        import _winapi
        alias=self.root/'alias'/'_forever_';alias.parent.mkdir()
        peer=self.root/'peer'/'_forever_';peer.mkdir(parents=True);(peer/'Wow.exe').touch()
        _winapi.CreateJunction(str(self.client),str(alias))
        real=backend.installation_lock
        try:
            self.assertEqual(backend.production_recovery_root(alias),backend.production_recovery_root(self.client))
            for timing in ('before','after'):
                @contextmanager
                def retarget(client):
                    self.assertEqual(client,self.client)
                    if timing=='before':alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
                    with real(client) as identity:
                        if timing=='after':alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
                        yield identity
                before=self.snapshot();peer_before=self.tree_bytes(peer)
                with real(peer),patch.object(backend,'installation_lock',retarget):
                    with self.assertRaisesRegex(ValueError,'changed while acquiring'):self.install(alias)
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.tree_bytes(peer),peer_before)
                alias.rmdir();_winapi.CreateJunction(str(self.client),str(alias))
            self.install(alias)  # Stable alias reaches only its canonical client.
            self.assertEqual(self.tree_bytes(peer),peer_before)
        finally:
            if alias.is_junction():alias.rmdir()

    def test_canonical_directory_replaced_during_preflight_is_rejected(self):
        real=backend._inspect_pending_locked;parked=self.root/'parked-client'
        def replaced(*args,**kwargs):
            result=real(*args,**kwargs)
            self.client.rename(parked);self.client.mkdir();(self.client/'Wow.exe').touch()
            return result
        with patch.object(backend,'_inspect_pending_locked',replaced):
            with self.assertRaises(backend.InstallationGuardError) as raised:self.install()
        self.assertEqual(raised.exception.code,'client_identity_changed')
        self.assertEqual(self.tree_bytes(parked),self.before)
        self.assertEqual(list(self.backups.iterdir()),[])
        self.assertEqual(self.snapshot(),{'Wow.exe':b''})


@unittest.skipUnless(os.name=='nt','Pending publication uses Windows non-replacing rename')
class PendingEvidenceTests(unittest.TestCase):
    setUp=PreparationTests.setUp
    snapshot=PreparationTests.snapshot
    prepare=PreparationTests.prepare
    assert_clean=PreparationTests.assert_clean

    def inspect(self):return backend.inspect_pending_transaction(self.client,self.backups)

    def assert_originals(self):
        for name,raw in self.before.items():self.assertEqual((self.client/name).read_bytes(),raw)
        self.assertFalse((self.original.parent/'WFCore.toc').exists())

    def assert_retained(self,result):
        self.assertTrue(result['recovery'].is_dir())
        self.assertEqual((result['recovery']/'WFCore/module.lua').read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        for item in result['record']['files']:
            self.assertTrue((self.client/'Interface/AddOns'/item['stage']).is_file())
        self.assert_originals()

    def test_published_evidence_survives_exit_and_binds_record(self):
        self.assertEqual(self.inspect(),dict(state='none'))
        with self.prepare() as result:
            self.assertEqual(result.ownership,'temporary')
            status=result.publish_pending()
            self.assertEqual(status['state'],'valid');self.assertEqual(result.ownership,'published')
            with self.assertRaisesRegex(ValueError,'Another addon installation'):self.inspect()
        self.assert_retained(result)
        marker=json.loads((self.client/backend.PENDING_NAME).read_bytes())
        self.assertEqual(marker['id'],result['record']['id'])
        self.assertEqual(marker['transaction'],fingerprint(result['record_bytes']))
        self.assertEqual(self.inspect()['record'],result['record'])
        self.assertFalse((result['recovery']/'manifest.json').exists())
        with self.assertRaisesRegex(ValueError,'Pending evidence'):
            with self.prepare():self.fail('Must not prepare over pending evidence')

    def test_publication_only_inside_owning_context_and_thread(self):
        import threading
        with self.prepare() as result:
            errors=[]
            def publish():
                try:result.publish_pending()
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=publish);thread.start();thread.join(timeout=5)
            self.assertFalse(thread.is_alive());self.assertIsInstance(errors[0],ValueError)
            self.assertEqual(result.ownership,'temporary')
        self.assert_clean()
        with self.assertRaisesRegex(ValueError,'active preparation'):result.publish_pending()

    def test_published_exit_never_calls_temporary_cleanup(self):
        with patch.object(backend,'_cleanup_preparation',side_effect=AssertionError('Published evidence cleanup')) as cleanup:
            with self.prepare() as result:result.publish_pending()
            cleanup.assert_not_called()
        self.assert_retained(result);self.assertEqual(self.inspect()['state'],'valid')

    def test_inspection_enumeration_failure_is_not_no_pending(self):
        with patch.object(backend.os,'scandir',side_effect=PermissionError('synthetic enumeration denial')):
            status=self.inspect()
            self.assertEqual(status['state'],'invalid');self.assertIsInstance(status['error'],PermissionError)
        self.assert_clean()

    def test_pending_symlink_rejected_without_reading_external_bytes(self):
        sentinel=self.root/'sentinel';sentinel.write_bytes(b'external unchanged')
        marker=self.client/backend.PENDING_NAME
        try:marker.symlink_to(sentinel)
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Symlinks unavailable: '+str(exc.winerror))
            raise
        self.assertEqual(self.inspect()['state'],'invalid')
        self.assertEqual(sentinel.read_bytes(),b'external unchanged');self.assertTrue(marker.is_symlink())

    def test_unpublished_cleanup_and_other_client_independence(self):
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        with self.prepare() as result:
            with backend.prepare_transaction(self.payload,other,['WFCore'],self.backups) as independent:
                independent.publish_pending()
            self.assertEqual(result.ownership,'temporary')
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(self.inspect()['state'],'none')
        self.assertEqual(backend.inspect_pending_transaction(other,self.backups)['state'],'valid')

    def test_creation_failure_before_marker_retains_originals(self):
        real=Path.open
        def denied(path,mode='r',*args,**kwargs):
            if mode=='xb' and path.name=='transaction.json':raise PermissionError('synthetic denial')
            return real(path,mode,*args,**kwargs)
        with self.assertRaises(PermissionError):
            with self.prepare() as result:
                with patch.object(Path,'open',denied):result.publish_pending()
        self.assertEqual(result.ownership,'ambiguous');self.assert_retained(result)
        self.assertEqual(self.inspect()['state'],'none')  # No client publication began; no destinations changed.

    def test_partial_marker_write_retains_all_evidence(self):
        real=Path.open
        class Stream:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def fileno(self):return self.stream.fileno()
            def write(self,raw):self.stream.write(raw[:9]);raise OSError('partial pending write')
        def opened(path,mode='r',*args,**kwargs):
            stream=real(path,mode,*args,**kwargs)
            return Stream(stream) if mode=='xb' and path.name.startswith('.wf-addon-pending-') else stream
        with self.assertRaisesRegex(OSError,'partial pending'):
            with self.prepare() as result:
                with patch.object(Path,'open',opened):result.publish_pending()
        self.assert_retained(result);self.assertEqual(result.ownership,'ambiguous')
        self.assertEqual(self.inspect()['state'],'ambiguous')
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Pending evidence'):
            with self.prepare():pass
        self.assertEqual(self.snapshot(),before)

    def test_marker_sync_failure_retains_evidence(self):
        real=backend._write_preparation_artifact
        def write(path,*args):
            if path.name.startswith('.wf-addon-pending-'):
                with patch.object(backend.os,'fsync',side_effect=OSError('pending sync failure')):return real(path,*args)
            return real(path,*args)
        with self.assertRaisesRegex(OSError,'pending sync'):
            with self.prepare() as result:
                with patch.object(backend,'_write_preparation_artifact',write):result.publish_pending()
        self.assert_retained(result);self.assertEqual(self.inspect()['state'],'ambiguous')

    def test_failure_after_publication_and_caller_notification_retains(self):
        real=backend._publish_pending_file
        def publish(*args):real(*args);raise RuntimeError('after rename')
        with self.assertRaisesRegex(RuntimeError,'after rename'):
            with self.prepare() as result:
                with patch.object(backend,'_publish_pending_file',publish):result.publish_pending()
        self.assertEqual(result.ownership,'ambiguous');self.assert_retained(result)
        self.assertEqual(self.inspect()['state'],'valid')
        # A separate client exercises the caller's notification exception after success.
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        with self.assertRaisesRegex(RuntimeError,'notification'):
            with backend.prepare_transaction(self.payload,other,['WFCore'],self.backups) as result2:
                result2.publish_pending();raise RuntimeError('notification failed')
        self.assertEqual(result2.ownership,'published')
        self.assertEqual(backend.inspect_pending_transaction(other,self.backups)['state'],'valid')

    def test_marker_verification_failure_and_baseexception_preserve(self):
        real=backend._publish_pending_file
        def corrupt(stage,marker,client):real(stage,marker,client);marker.write_bytes(b'corrupted marker')
        with self.assertRaisesRegex(ValueError,'could not be verified'):
            with self.prepare() as result:
                with patch.object(backend,'_publish_pending_file',corrupt):result.publish_pending()
        self.assert_retained(result);self.assertEqual(self.inspect()['state'],'invalid')
        # No broad BaseException catch: interruption propagates but retention still applies.
        (self.client/backend.PENDING_NAME).unlink()  # Synthetic fixture reset only.
        with self.assertRaises(KeyboardInterrupt):
            with self.prepare() as interrupted:
                with patch.object(backend,'_publish_pending_file',side_effect=KeyboardInterrupt):interrupted.publish_pending()
        self.assert_retained(interrupted);self.assertEqual(self.inspect()['state'],'ambiguous')

    def test_publication_still_requires_all_stages_after_rename(self):
        real=backend._publish_pending_file
        with self.assertRaisesRegex(ValueError,'could not be verified'):
            with self.prepare() as result:
                stage=self.client/'Interface/AddOns'/result['record']['files'][0]['stage']
                def missing(*args):real(*args);stage.unlink()
                with patch.object(backend,'_publish_pending_file',missing):result.publish_pending()
        self.assertEqual(result.ownership,'ambiguous');self.assert_originals()
        self.assertTrue((result['recovery']/'WFCore/module.lua').exists())
        # Recovery can reconcile these untouched originals despite the missing stage.
        self.assertEqual(self.inspect()['state'],'valid')

    def test_conflicting_marker_is_not_overwritten(self):
        real=backend._publish_pending_file
        def collision(stage,marker,client):marker.write_bytes(b'other transaction');real(stage,marker,client)
        with self.assertRaises(FileExistsError):
            with self.prepare() as result:
                with patch.object(backend,'_publish_pending_file',collision):result.publish_pending()
        self.assert_retained(result)
        self.assertEqual((self.client/backend.PENDING_NAME).read_bytes(),b'other transaction')
        self.assertEqual(self.inspect()['state'],'ambiguous')

    def test_invalid_markers_fail_closed_without_mutation(self):
        with self.prepare() as result:result.publish_pending()
        marker=self.client/backend.PENDING_NAME;original=marker.read_bytes();document=json.loads(original)
        cases=[b'bad',b'',b'[]',b'{"schema":1,"schema":1}',b' '* (backend.MAX_PENDING_BYTES+1),b'['*3000+b'0'+b']'*3000]
        for key,value in (('schema',True),('schema',2),('extra',1),('id','../escape'),('id',uuid.uuid4().hex),
                          ('transaction',fingerprint(b'wrong')),('backup_root',dict(document['backup_root'],inode=True)),
                          ('client',dict(document['client'],path='C:/untrusted'))):
            changed=copy.deepcopy(document);changed[key]=value;cases.append(json.dumps(changed).encode())
        for raw in cases:
            with self.subTest(length=len(raw)):
                marker.write_bytes(raw);before=self.snapshot()
                self.assertEqual(self.inspect()['state'],'invalid');self.assertEqual(self.snapshot(),before)
        marker.write_bytes(original)
        wrong_root=self.root/'wrong';wrong_root.mkdir()
        self.assertEqual(backend.inspect_pending_transaction(self.client,wrong_root)['state'],'invalid')
        self.assertEqual(self.inspect()['state'],'valid');self.assert_retained(result)

    def test_missing_or_changed_evidence_is_rejected_read_only(self):
        with self.prepare() as result:result.publish_pending()
        paths=[result['recovery']/'transaction.json',result['recovery']/'receipt.pending',
               result['recovery']/'WFCore/module.lua',self.client/'Interface/AddOns'/result['record']['files'][0]['stage']]
        for path in paths:
            original=path.read_bytes()
            for missing in (False,True):
                with self.subTest(name=path.name,missing=missing):
                    if missing:path.unlink()
                    else:path.write_bytes(b'changed')
                    before=self.snapshot()
                    expected='valid' if missing and path.suffix=='.stage' else 'invalid'
                    self.assertEqual(self.inspect()['state'],expected);self.assertEqual(self.snapshot(),before)
                    path.write_bytes(original)
        self.assertEqual(self.inspect()['state'],'valid');self.assert_retained(result)

    def test_mutable_result_does_not_control_publication_or_cleanup(self):
        with self.prepare() as result:
            expected=json.loads(result['record_bytes'])
            result['record']['id']='bad';result['record_bytes']=b'bad';result['recovery']=self.root
            self.assertEqual(result.publish_pending()['record'],expected)
        self.assertEqual(self.inspect()['record'],expected)
        self.assert_originals()

    def test_changed_artifact_before_publish_rejected_and_preserved(self):
        with self.assertRaises(backend.TransactionPreparationError):
            with self.prepare() as result:
                stage=self.client/'Interface/AddOns'/result['record']['files'][0]['stage']
                stage.write_bytes(b'external bytes')
                result.publish_pending()
        self.assertEqual(stage.read_bytes(),b'external bytes');self.assert_originals()
        self.assertFalse((self.client/backend.PENDING_NAME).exists())

    def test_pending_and_evidence_hard_links_and_junction_rejected(self):
        import _winapi
        with self.prepare() as result:result.publish_pending()
        marker=self.client/backend.PENDING_NAME;sentinel=self.root/'sentinel';os.link(marker,sentinel)
        raw=sentinel.read_bytes();self.assertEqual(self.inspect()['state'],'invalid')
        self.assertEqual(sentinel.read_bytes(),raw);sentinel.unlink()
        backup=result['recovery']/'WFCore/module.lua';os.link(backup,sentinel)
        self.assertEqual(self.inspect()['state'],'invalid');sentinel.unlink()
        alias=self.root/'alias';_winapi.CreateJunction(str(self.backups),str(alias))
        try:self.assertEqual(backend.inspect_pending_transaction(self.client,alias)['state'],'invalid')
        finally:alias.rmdir()
        self.assertEqual(self.inspect()['state'],'valid');self.assert_retained(result)

    def test_termination_after_publication_and_new_process_inspection(self):
        ready=self.root/'ready'
        code="""
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
with b.prepare_transaction(Path(sys.argv[2]),Path(sys.argv[3]),['WFStorage'],Path(sys.argv[4])) as prepared:
    prepared.publish_pending()
    Path(sys.argv[5]).write_text('ready')
    time.sleep(30)
"""
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(backend.__file__).parent),str(self.payload),str(self.client),str(self.backups),str(ready)],
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=0x08000000)
        try:
            deadline=time.monotonic()+10
            while not ready.exists():
                if child.poll() is not None:self.fail(child.communicate(timeout=1)[1])
                if time.monotonic()>deadline:self.fail('Publication timed out')
                time.sleep(.02)
            with self.assertRaisesRegex(ValueError,'Another addon installation'):self.inspect()
            other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
            self.assertEqual(backend.inspect_pending_transaction(other,self.backups)['state'],'none')
            child.kill();child.communicate(timeout=10)
        finally:
            if child.poll() is None:child.kill();child.communicate(timeout=10)
        inspect_code="""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
assert b.inspect_pending_transaction(Path(sys.argv[2]),Path(sys.argv[3]))['state']=='valid'
"""
        checked=subprocess.run([sys.executable,'-B','-c',inspect_code,str(Path(backend.__file__).parent),str(self.client),str(self.backups)],
                               capture_output=True,text=True,timeout=15,creationflags=0x08000000)
        self.assertEqual(checked.returncode,0,checked.stderr);self.assert_originals()
        self.assertEqual(self.inspect()['state'],'valid')


@unittest.skipUnless(os.name=='nt','Recovery fixtures publish with Windows non-replacing rename')
class RecoveryTests(unittest.TestCase):
    setUp=PreparationTests.setUp
    snapshot=PreparationTests.snapshot
    prepare=PreparationTests.prepare

    def published(self,*,all_existing=True):
        if all_existing:
            for source in self.payload.rglob('*'):
                if source.is_file():
                    target=self.client/'Interface/AddOns'/source.relative_to(self.payload)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    prefix=b'## Version: 0.7.0\n# original ' if target.suffix=='.toc' else b'old\x00\xff '
                    target.write_bytes(prefix+source.relative_to(self.payload).as_posix().encode())
        self.before=self.snapshot()
        with self.prepare(('WFStorage','WFProfessions')) as prepared:prepared.publish_pending()
        self.prepared=prepared;self.items=prepared['record']['files']
        self.evidence={p:p.read_bytes() for p in prepared['recovery'].rglob('*') if p.is_file()}
        marker=self.client/backend.PENDING_NAME;self.evidence[marker]=marker.read_bytes()
        return prepared

    def replace_items(self,items=None,*,consume=True):
        for item in self.items if items is None else items:
            target=self.client/'Interface/AddOns'/item['path'];stage=self.client/'Interface/AddOns'/item['stage']
            if consume and stage.exists():os.replace(stage,target)
            else:target.write_bytes((self.payload/item['path']).read_bytes())

    def recover(self):return backend.recover_pending_transaction(self.client,self.backups)

    def assert_evidence(self):
        for path,raw in self.evidence.items():self.assertEqual(path.read_bytes(),raw)

    def assert_originals(self):
        for name,raw in self.before.items():self.assertEqual((self.client/name).read_bytes(),raw)
        for item in self.items:
            if not item['existed']:self.assertFalse((self.client/'Interface/AddOns'/item['path']).exists())
        self.assert_evidence()

    def test_none_and_untouched_transaction_are_read_only(self):
        self.assertEqual(self.recover()['state'],'none')
        self.assertEqual(self.snapshot(),self.before)
        self.published(all_existing=False);before=self.snapshot()
        with patch.object(backend,'_write_preparation_artifact',side_effect=AssertionError('Unnecessary write')):
            self.assertEqual(self.recover()['state'],'rollback_complete')
            self.assertEqual(self.recover()['state'],'rollback_complete')
        self.assertEqual(self.snapshot(),before);self.assert_originals()

    def test_one_several_and_all_replacements_with_consumed_stages(self):
        self.published()
        for count in (1,3,len(self.items)):
            with self.subTest(count=count):
                self.replace_items(self.items[:count])
                inspected=backend.inspect_pending_transaction(self.client,self.backups)
                self.assertEqual(inspected['state'],'valid')
                self.assertEqual(sum(x['state']=='replacement' for x in inspected['destinations']),count)
                self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()
                self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()

    def test_previously_absent_files_removed_only_if_created(self):
        self.published(all_existing=False)
        self.replace_items(self.items[:-1],consume=False)
        self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()
        for item in self.items:self.assertTrue((self.client/'Interface/AddOns'/item['stage']).exists())

    def test_empty_original_and_identical_original_replacement_are_preserved(self):
        self.original.write_bytes(b'')
        identical=self.client/'Interface/AddOns/WFStorage/module.lua';identical.parent.mkdir()
        identical.write_bytes((self.payload/'WFStorage/module.lua').read_bytes())
        self.published(all_existing=False);self.replace_items();stamp=backend._file_stamp(identical.stat())
        self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()
        self.assertEqual(self.original.read_bytes(),b'');self.assertEqual(backend._file_stamp(identical.stat()),stamp)

    def test_reverse_mutation_order_including_tocs(self):
        self.published();self.replace_items();order=[];real=backend.os.replace
        def replace(source,target):order.append(target.relative_to(self.client/'Interface/AddOns').as_posix());return real(source,target)
        with patch.object(backend.os,'replace',replace):self.assertEqual(self.recover()['state'],'rollback_complete')
        self.assertEqual(order,[x['path'] for x in reversed(self.items)])
        self.assertTrue(order[0].endswith('.toc'));self.assert_originals()

    def test_first_middle_and_multiple_failures_continue_independent_recovery(self):
        self.published();real=backend.os.replace
        for failed_indexes in ((0,),(2,),(0,2)):
            with self.subTest(failed_indexes=failed_indexes):
                self.replace_items();attempted=[];failed={self.items[-1-i]['path'] for i in failed_indexes}
                def replace(source,target):
                    name=target.relative_to(self.client/'Interface/AddOns').as_posix();attempted.append(name)
                    if name in failed:raise RuntimeError('synthetic private diagnostic')
                    return real(source,target)
                with patch.object(backend.os,'replace',replace):result=self.recover()
                self.assertEqual(result['state'],'incomplete');self.assertEqual(len(attempted),len(self.items))
                self.assertEqual({f['path'] for f in result['failures'] if f['path']},failed)
                self.assertIsInstance(result['failures'][0]['error'],RuntimeError)
                self.assertNotIn('private diagnostic',result['reason'])
                for item in self.items:
                    raw=(self.client/'Interface/AddOns'/item['path']).read_bytes()
                    expected=(self.payload/item['path']).read_bytes() if item['path'] in failed else self.before['Interface/AddOns/'+item['path']]
                    self.assertEqual(raw,expected)
                self.assert_evidence()
                self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()

    def test_new_file_removal_failure_retains_evidence_and_retries(self):
        self.published(all_existing=False);self.replace_items();real=Path.unlink
        target=self.client/'Interface/AddOns'/self.items[-1]['path']
        def unlink(path,*args,**kwargs):
            if path==target:raise PermissionError('synthetic sharing violation')
            return real(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):result=self.recover()
        self.assertEqual(result['state'],'incomplete');self.assertTrue(target.exists());self.assert_evidence()
        self.assertEqual(self.original.read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()

    def test_preflight_external_change_blocks_every_mutation(self):
        self.published();self.replace_items()
        target=self.client/'Interface/AddOns'/self.items[0]['path'];target.write_bytes(b'external change')
        before=self.snapshot()
        with patch.object(backend,'_write_preparation_artifact',side_effect=AssertionError('Preflight must block writes')):
            result=self.recover()
        self.assertEqual(result['state'],'blocked')
        self.assertEqual(result['inspection']['affected'],[self.items[0]['path']])
        self.assertEqual(self.snapshot(),before);self.assert_evidence()

    def test_existing_original_missing_is_not_inferred_from_missing_stage(self):
        self.published();self.replace_items();self.original.unlink();before=self.snapshot()
        self.assertEqual(self.recover()['state'],'blocked');self.assertEqual(self.snapshot(),before);self.assert_evidence()

    def test_external_change_after_temp_verification_is_preserved(self):
        self.published();self.replace_items();real=backend._write_preparation_artifact;changed=[]
        target=self.client/'Interface/AddOns'/self.items[-1]['path']
        def write(*args):
            real(*args)
            if not changed:changed.append(True);target.write_bytes(b'external edit before replacement')
        with patch.object(backend,'_write_preparation_artifact',write):result=self.recover()
        self.assertEqual(result['state'],'incomplete');self.assertEqual(target.read_bytes(),b'external edit before replacement')
        for item in self.items[:-1]:self.assertEqual((self.client/'Interface/AddOns'/item['path']).read_bytes(),self.before['Interface/AddOns/'+item['path']])
        self.assert_evidence()

    def test_new_file_external_edit_after_preflight_is_not_removed(self):
        self.published(all_existing=False);self.replace_items();real=backend._inspect_pending_locked;changed=[]
        target=self.client/'Interface/AddOns'/self.items[-1]['path']
        def inspect(*args,**kwargs):
            status=real(*args,**kwargs)
            if not changed:changed.append(True);target.write_bytes(b'external new-file edit')
            return status
        with patch.object(backend,'_inspect_pending_locked',inspect):result=self.recover()
        self.assertEqual(result['state'],'incomplete');self.assertEqual(target.read_bytes(),b'external new-file edit');self.assert_evidence()

    def test_same_bytes_new_identity_after_preflight_is_rejected(self):
        self.published();self.replace_items();real=backend._write_preparation_artifact;changed=[]
        target=self.client/'Interface/AddOns'/self.items[-1]['path']
        def write(*args):
            real(*args)
            if not changed:
                changed.append(True);external=self.root/'external';external.write_bytes(target.read_bytes());os.replace(external,target)
        with patch.object(backend,'_write_preparation_artifact',write):result=self.recover()
        self.assertEqual(result['state'],'incomplete');self.assertEqual(target.read_bytes(),(self.payload/self.items[-1]['path']).read_bytes());self.assert_evidence()

    def test_marker_change_after_preflight_blocks_remaining_writes(self):
        self.published();self.replace_items();real=backend._write_preparation_artifact
        marker=self.client/backend.PENDING_NAME;before={x['path']:(self.client/'Interface/AddOns'/x['path']).read_bytes() for x in self.items}
        def write(*args):real(*args);marker.write_bytes(b'external marker change')
        with patch.object(backend,'_write_preparation_artifact',write):result=self.recover()
        self.assertEqual(result['state'],'incomplete')
        for name,raw in before.items():self.assertEqual((self.client/'Interface/AddOns'/name).read_bytes(),raw)
        self.assertEqual(marker.read_bytes(),b'external marker change')

    def test_restoration_artifact_create_write_flush_sync_and_verify_failures(self):
        self.published();real_open=Path.open;real_read=backend._read_preparation_file;real_sync=backend.os.fsync
        for mode in ('create','short','write','flush','sync','verify'):
            with self.subTest(mode=mode):
                self.replace_items();before={x['path']:(self.client/'Interface/AddOns'/x['path']).read_bytes() for x in self.items}
                class Stream:
                    def __init__(self,stream):self.stream=stream
                    def __enter__(self):return self
                    def __exit__(self,*args):self.stream.close()
                    def fileno(self):return self.stream.fileno()
                    def write(self,raw):
                        if mode=='write':self.stream.write(raw[:2]);raise OSError('uncertain partial write')
                        return self.stream.write(raw[:2] if mode=='short' else raw)
                    def flush(self):
                        if mode=='flush':raise OSError('flush failure')
                        self.stream.flush()
                def opened(path,open_mode='r',*args,**kwargs):
                    if open_mode=='xb' and mode=='create':raise PermissionError('create denied')
                    stream=real_open(path,open_mode,*args,**kwargs)
                    return Stream(stream) if open_mode=='xb' else stream
                def read(path,*args,**kwargs):
                    raw,stamp=real_read(path,*args,**kwargs)
                    if mode=='verify' and path.name.startswith('.wf-restore-') and raw is not None:return b'wrong bytes',stamp
                    return raw,stamp
                def sync(fd):
                    if mode=='sync':raise OSError('sync failure')
                    return real_sync(fd)
                with patch.object(Path,'open',opened),patch.object(backend,'_read_preparation_file',read),patch.object(backend.os,'fsync',sync):result=self.recover()
                self.assertEqual(result['state'],'incomplete');self.assertTrue(result['failures']);self.assert_evidence()
                for name,raw in before.items():self.assertEqual((self.client/'Interface/AddOns'/name).read_bytes(),raw)
                self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()

    def test_changed_restoration_copy_preserved_and_cleanup_reported(self):
        self.published();self.replace_items();real=backend._write_preparation_artifact;changed=[]
        def write(path,*args):
            real(path,*args)
            if not changed:changed.append(path);path.write_bytes(b'external temporary contents')
        with patch.object(backend,'_write_preparation_artifact',write):result=self.recover()
        self.assertEqual(result['state'],'incomplete');self.assertEqual(changed[0].read_bytes(),b'external temporary contents')
        self.assertTrue(any('cleanup' in f['reason'] for f in result['failures']));self.assert_evidence()
        self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()
        self.assertEqual(changed[0].read_bytes(),b'external temporary contents')

    def test_missing_or_corrupted_backup_stage_and_metadata_block_writes(self):
        self.published();self.replace_items(consume=False)
        paths=[self.prepared['recovery']/'WFCore/module.lua',self.prepared['recovery']/'transaction.json',
               self.prepared['recovery']/'receipt.pending',self.client/backend.PENDING_NAME]
        for path in paths:
            original=path.read_bytes()
            for missing in (False,True):
                with self.subTest(name=path.name,missing=missing):
                    if missing:path.unlink()
                    else:path.write_bytes(b'bad')
                    before=self.snapshot()
                    result=self.recover()
                    self.assertEqual(result['state'],'none' if missing and path.name==backend.PENDING_NAME else 'blocked')
                    self.assertEqual(self.snapshot(),before);path.write_bytes(original)
        stage=self.client/'Interface/AddOns'/self.items[0]['stage'];stage.write_bytes(b'changed stage')
        before=self.snapshot();self.assertEqual(self.recover()['state'],'blocked');self.assertEqual(self.snapshot(),before)

    def test_unsafe_destination_and_backup_links_block_preflight(self):
        self.published();self.replace_items();sentinel=self.root/'sentinel'
        for path in (self.original,self.prepared['recovery']/'WFCore/module.lua'):
            os.link(path,sentinel);raw=sentinel.read_bytes();before=self.snapshot()
            try:
                self.assertEqual(self.recover()['state'],'blocked');self.assertEqual(self.snapshot(),before)
                self.assertEqual(sentinel.read_bytes(),raw)
            finally:sentinel.unlink()
        self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()

    def test_junction_destination_blocks_without_touching_external_files(self):
        import _winapi
        self.published();self.replace_items()
        folder=self.original.parent;external=self.root/'external-addon';folder.rename(external)
        _winapi.CreateJunction(str(external),str(folder))
        try:
            raw=(external/'module.lua').read_bytes();self.assertEqual(self.recover()['state'],'blocked')
            self.assertEqual((external/'module.lua').read_bytes(),raw);self.assert_evidence()
        finally:folder.rmdir();external.rename(folder)

    def test_symlink_destination_blocks_without_following_target(self):
        self.published();self.replace_items();sentinel=self.root/'sentinel';sentinel.write_bytes(b'external')
        self.original.unlink()
        try:self.original.symlink_to(sentinel)
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Symlinks unavailable: '+str(exc.winerror))
            raise
        self.assertEqual(self.recover()['state'],'blocked');self.assertEqual(sentinel.read_bytes(),b'external');self.assert_evidence()

    def test_path_alias_in_consistently_rehashed_metadata_is_rejected(self):
        self.published();self.replace_items()
        record=copy.deepcopy(self.prepared['record']);record['files'][0]['path']='WFCore/MODULE.LUA.'
        raw=json.dumps(record).encode();(self.prepared['recovery']/'transaction.json').write_bytes(raw)
        marker=self.client/backend.PENDING_NAME;document=json.loads(marker.read_bytes());document['transaction']=fingerprint(raw);marker.write_text(json.dumps(document))
        before=self.snapshot();self.assertEqual(self.recover()['state'],'blocked');self.assertEqual(self.snapshot(),before)

    def test_baseexception_propagates_and_retry_completes(self):
        self.published();self.replace_items();real=backend.os.replace;calls=[]
        def replace(*args):
            real(*args);calls.append(True);raise KeyboardInterrupt()
        with patch.object(backend.os,'replace',replace),self.assertRaises(KeyboardInterrupt):self.recover()
        self.assertEqual(len(calls),1);self.assert_evidence()
        self.assertEqual(self.recover()['state'],'rollback_complete');self.assert_originals()

    def test_lock_contention_and_other_client_independence(self):
        self.published();self.replace_items();before=self.snapshot()
        with backend.installation_lock(self.client):
            with self.assertRaisesRegex(ValueError,'Another addon installation'):self.recover()
            other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
            self.assertEqual(backend.recover_pending_transaction(other,self.backups)['state'],'none')
        self.assertEqual(self.snapshot(),before);self.assert_evidence()

    def junction_clients(self):
        import _winapi
        self.published();self.replace_items()
        peer=self.root/'peer'/'_forever_';peer.mkdir(parents=True);(peer/'Wow.exe').touch()
        original=peer/'Interface/AddOns/WFCore/module.lua'
        original.parent.mkdir(parents=True);original.write_bytes(b'peer original')
        unrelated=peer/'WTF/sentinel.lua';unrelated.parent.mkdir();unrelated.write_bytes(b'peer unrelated')
        with backend.prepare_transaction(self.payload,peer,['WFStorage'],self.backups) as prepared:prepared.publish_pending()
        for item in prepared['record']['files']:
            os.replace(peer/'Interface/AddOns'/item['stage'],peer/'Interface/AddOns'/item['path'])
        alias=self.root/'alias'/'_forever_';alias.parent.mkdir()
        try:_winapi.CreateJunction(str(self.client),str(alias))
        except OSError as exc:
            if getattr(exc,'winerror',None) in (1,5,50,1314):self.skipTest('Junctions unavailable: '+str(exc.winerror))
            raise
        self.addCleanup(lambda:alias.rmdir() if alias.is_junction() else None)
        return alias,peer

    @staticmethod
    def tree_bytes(root):
        return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_retargeted_alias_after_lock_rejects_both_recovery_and_inspection(self):
        import _winapi
        alias,peer=self.junction_clients();lock=backend.installation_lock
        a=self.snapshot();b=self.tree_bytes(peer);evidence=self.tree_bytes(self.backups)
        for operation in (backend.recover_pending_transaction,backend.inspect_pending_transaction):
            with self.subTest(operation=operation.__name__):
                alias.rmdir();_winapi.CreateJunction(str(self.client),str(alias))
                @contextmanager
                def retarget(client):
                    with lock(client) as identity:
                        alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
                        yield identity
                with lock(peer):
                    with patch.object(backend,'installation_lock',retarget):
                        with self.assertRaisesRegex(ValueError,'changed while acquiring transaction lock'):
                            operation(alias,self.backups)
                    with self.assertRaisesRegex(ValueError,'Another addon installation'):
                        with lock(peer):self.fail('Peer lock was released')
                self.assertEqual(self.snapshot(),a);self.assertEqual(self.tree_bytes(peer),b)
                self.assertEqual(self.tree_bytes(self.backups),evidence)
                with lock(self.client):pass

    def test_alias_change_before_lock_acquisition_fails_without_writes(self):
        import _winapi
        alias,peer=self.junction_clients();lock=backend.installation_lock
        a=self.snapshot();b=self.tree_bytes(peer);evidence=self.tree_bytes(self.backups)
        @contextmanager
        def retarget(client):
            self.assertEqual(client,self.client)  # Lock the retained location, never the alias.
            alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
            with lock(client) as identity:yield identity
        with lock(peer),patch.object(backend,'installation_lock',retarget):
            with self.assertRaisesRegex(ValueError,'changed while acquiring transaction lock'):
                backend.recover_pending_transaction(alias,self.backups)
        self.assertEqual(self.snapshot(),a);self.assertEqual(self.tree_bytes(peer),b)
        self.assertEqual(self.tree_bytes(self.backups),evidence)

    def test_stable_alias_recovers_only_its_canonical_client(self):
        alias,peer=self.junction_clients();b=self.tree_bytes(peer);evidence=self.tree_bytes(self.backups)
        with backend.installation_lock(peer):
            self.assertEqual(backend.inspect_pending_transaction(alias,self.backups)['state'],'valid')
            self.assertEqual(backend.recover_pending_transaction(alias,self.backups)['state'],'rollback_complete')
            self.assertEqual(self.recover()['state'],'rollback_complete')
        self.assert_originals();self.assertEqual(self.tree_bytes(peer),b)
        self.assertEqual(self.tree_bytes(self.backups),evidence)

    def test_yielded_lock_identity_mismatch_rejected_before_inspection(self):
        self.published();self.replace_items();before=self.snapshot();evidence=self.tree_bytes(self.backups)
        lock=backend.installation_lock
        @contextmanager
        def wrong_identity(client):
            with lock(client) as identity:yield dict(identity,inode=identity['inode']+1)
        with patch.object(backend,'installation_lock',wrong_identity),\
             patch.object(backend,'_inspect_pending_locked',side_effect=AssertionError('Must not inspect wrong identity')):
            with self.assertRaisesRegex(ValueError,'changed while acquiring transaction lock'):self.recover()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.tree_bytes(self.backups),evidence)
        with lock(self.client):pass

    def test_late_alias_retarget_does_not_select_new_destination(self):
        import _winapi
        alias,peer=self.junction_clients();b=self.tree_bytes(peer);evidence=self.tree_bytes(self.backups)
        inspect=backend._inspect_pending_locked;changed=[]
        def retarget(client,*args,**kwargs):
            self.assertEqual(client,self.client)
            if not changed:
                changed.append(True);alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
            return inspect(client,*args,**kwargs)
        with backend.installation_lock(peer),patch.object(backend,'_inspect_pending_locked',retarget):
            result=backend.recover_pending_transaction(alias,self.backups)
        self.assertEqual(result['state'],'rollback_complete');self.assert_originals()
        self.assertEqual(self.tree_bytes(peer),b);self.assertEqual(self.tree_bytes(self.backups),evidence)

    def test_canonical_location_changed_after_guard_cannot_rebind_pending_evidence(self):
        import _winapi
        alias,peer=self.junction_clients();a=self.snapshot();b=self.tree_bytes(peer);evidence=self.tree_bytes(self.backups)
        inspect=backend._inspect_pending_locked;parked=self.root/'parked';changed=[]
        def retarget(client,*args,**kwargs):
            if not changed:
                changed.append(True);self.client.rename(parked);_winapi.CreateJunction(str(peer),str(self.client))
            return inspect(client,*args,**kwargs)
        try:
            with backend.installation_lock(peer),patch.object(backend,'_inspect_pending_locked',retarget):
                result=backend.recover_pending_transaction(alias,self.backups)
            self.assertEqual(result['state'],'blocked')
            self.assertEqual(self.tree_bytes(parked),a);self.assertEqual(self.tree_bytes(peer),b)
            self.assertEqual(self.tree_bytes(self.backups),evidence)
        finally:
            if self.client.is_junction():self.client.rmdir()
            if parked.exists():parked.rename(self.client)

    def test_repeated_process_termination_between_real_restorations(self):
        self.published();self.replace_items()
        code="""
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
real=b.os.replace
def interrupted(source,target):
    real(source,target)
    Path(sys.argv[4]).write_text('restored')
    time.sleep(30)
b.os.replace=interrupted
b.recover_pending_transaction(Path(sys.argv[2]),Path(sys.argv[3]))
"""
        for attempt in range(2):
            ready=self.root/f'ready-{attempt}'
            child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(backend.__file__).parent),str(self.client),str(self.backups),str(ready)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=0x08000000)
            try:
                deadline=time.monotonic()+10
                while not ready.exists():
                    if child.poll() is not None:self.fail(child.communicate(timeout=1)[1])
                    if time.monotonic()>deadline:self.fail('Recovery subprocess timed out')
                    time.sleep(.02)
                with self.assertRaisesRegex(ValueError,'Another addon installation'):self.recover()
                child.kill();child.communicate(timeout=10)
            finally:
                if child.poll() is None:child.kill();child.communicate(timeout=10)
            self.assert_evidence()
            status=backend.inspect_pending_transaction(self.client,self.backups)
            self.assertEqual(status['state'],'valid')
            self.assertEqual(sum(x['state']=='original' for x in status['destinations']),attempt+1)
        finish="""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
assert b.recover_pending_transaction(Path(sys.argv[2]),Path(sys.argv[3]))['state']=='rollback_complete'
"""
        done=subprocess.run([sys.executable,'-B','-c',finish,str(Path(backend.__file__).parent),str(self.client),str(self.backups)],
                            capture_output=True,text=True,timeout=15,creationflags=0x08000000)
        self.assertEqual(done.returncode,0,done.stderr);self.assert_originals()


@unittest.skipUnless(os.name=='nt','Completion uses Windows non-overwriting publication')
class CompletionTests(unittest.TestCase):
    setUp=PreparationTests.setUp
    snapshot=PreparationTests.snapshot
    prepare=PreparationTests.prepare
    published=RecoveryTests.published
    replace_items=RecoveryTests.replace_items
    assert_evidence=RecoveryTests.assert_evidence

    def complete(self,outcome='installation'):
        operation=backend.complete_pending_installation if outcome=='installation' else backend.complete_pending_rollback
        return operation(self.client,self.backups)

    def assert_destinations(self,outcome):
        for item in self.items:
            target=self.client/'Interface/AddOns'/item['path']
            if outcome=='rollback' and not item['existed']:self.assertFalse(target.exists())
            else:
                expected=(self.payload/item['path']).read_bytes() if outcome=='installation' else self.before['Interface/AddOns/'+item['path']]
                self.assertEqual(target.read_bytes(),expected)
        for name,raw in self.before.items():
            if not name.startswith(('Interface/AddOns/WFCore/','Interface/AddOns/WFStorage/','Interface/AddOns/WFProfessions/')):
                self.assertEqual((self.client/name).read_bytes(),raw)

    def test_install_complete_receipt_cleanup_and_idempotent_no_pending(self):
        self.published(all_existing=False);self.replace_items(consume=False)
        result=self.complete();self.assertEqual(result['state'],'installation_complete');self.assertFalse(result['failures'])
        self.assert_destinations('installation');self.assertFalse((self.client/backend.PENDING_NAME).exists())
        self.assertEqual((self.prepared['recovery']/'manifest.json').read_bytes(),self.prepared['receipt_bytes'])
        self.assertEqual([p.name for p in self.prepared['recovery'].iterdir()],['manifest.json'])
        self.assertFalse(list(self.client.rglob('*.stage')))
        before=self.snapshot();self.assertEqual(self.complete()['state'],'no_pending');self.assertEqual(self.snapshot(),before)

    def test_rollback_complete_after_recovery_and_idempotent_no_pending(self):
        self.published(all_existing=False);self.replace_items()
        self.assertEqual(backend.recover_pending_transaction(self.client,self.backups)['state'],'rollback_complete')
        result=self.complete('rollback');self.assertEqual(result['state'],'rollback_complete');self.assertFalse(result['failures'])
        self.assert_destinations('rollback');self.assertFalse(self.prepared['recovery'].exists())
        self.assertEqual(self.complete('rollback')['state'],'no_pending')

    def test_partial_install_and_partial_rollback_rejected(self):
        self.published();self.replace_items(self.items[:2]);before=self.snapshot()
        for outcome in ('installation','rollback'):
            result=self.complete(outcome);self.assertEqual(result['state'],'incomplete');self.assertFalse(result['retired'])
            self.assertEqual(self.snapshot(),before);self.assert_evidence()
        self.assertFalse((self.prepared['recovery']/'manifest.json').exists())

    def test_untouched_rollback_and_missing_original_backups(self):
        self.published(all_existing=False);backup=self.prepared['recovery']/'WFCore/module.lua';raw=backup.read_bytes()
        for missing in (False,True):
            if missing:backup.unlink()
            else:backup.write_bytes(b'corrupt')
            before=self.snapshot();self.assertEqual(self.complete('rollback')['state'],'blocked');self.assertEqual(self.snapshot(),before)
            backup.write_bytes(raw)
        self.assertEqual(self.complete('rollback')['state'],'rollback_complete');self.assert_destinations('rollback')

    def test_identical_bytes_keep_explicit_outcomes(self):
        for outcome in ('installation','rollback'):
            with self.subTest(outcome=outcome):
                # Separate fresh transactions with identical original/replacement bytes.
                for source in self.payload.rglob('*'):
                    if source.is_file():
                        target=self.client/'Interface/AddOns'/source.relative_to(self.payload)
                        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
                self.published(all_existing=False)
                result=self.complete(outcome);self.assertEqual(result['state'],outcome+'_complete')
                self.assert_destinations(outcome)
                self.assertEqual((self.prepared['recovery']/'manifest.json').exists(),outcome=='installation')

    def test_external_changes_and_corrupt_metadata_block_before_retirement(self):
        self.published();self.replace_items()
        for path in (self.original,self.client/backend.PENDING_NAME,self.prepared['recovery']/'transaction.json'):
            raw=path.read_bytes();path.write_bytes(b'external');before=self.snapshot()
            self.assertEqual(self.complete()['state'],'blocked');self.assertEqual(self.snapshot(),before)
            self.assertEqual(path.read_bytes(),b'external');path.write_bytes(raw)
        self.assert_evidence()

    def test_matching_receipt_accepted_conflicting_receipt_preserved(self):
        self.published();self.replace_items();receipt=self.prepared['recovery']/'manifest.json'
        receipt.write_bytes(b'unrelated receipt');before=self.snapshot()
        self.assertEqual(self.complete()['state'],'incomplete');self.assertEqual(self.snapshot(),before)
        self.assertEqual(receipt.read_bytes(),b'unrelated receipt');self.assert_evidence()
        receipt.write_bytes(self.prepared['receipt_bytes'])
        with patch.object(backend,'_publish_pending_file',side_effect=AssertionError('Must not overwrite matching receipt')):
            self.assertEqual(self.complete()['state'],'installation_complete')
        self.assert_destinations('installation')

    def test_receipt_creation_partial_write_flush_sync_and_publication_failures(self):
        self.published();self.replace_items();real_open=Path.open
        stage=self.prepared['recovery']/f'.wf-receipt-{self.prepared["record"]["id"]}.stage'
        for mode in ('create','short','write','flush','sync','publish'):
            with self.subTest(mode=mode):
                class Stream:
                    def __init__(self,stream):self.stream=stream
                    def __enter__(self):return self
                    def __exit__(self,*args):self.stream.close()
                    def fileno(self):return self.stream.fileno()
                    def write(self,raw):
                        if mode=='write':self.stream.write(raw[:2]);raise OSError('partial write')
                        return self.stream.write(raw[:2] if mode=='short' else raw)
                    def flush(self):
                        if mode=='flush':raise OSError('flush failed')
                        self.stream.flush()
                def opened(path,open_mode='r',*args,**kwargs):
                    if path==stage and open_mode=='xb':
                        if mode=='create':raise PermissionError('creation denied')
                        return Stream(real_open(path,open_mode,*args,**kwargs))
                    return real_open(path,open_mode,*args,**kwargs)
                real_sync=backend.os.fsync;real_publish=backend._publish_pending_file
                def sync(fd):
                    if mode=='sync':raise OSError('sync failed')
                    return real_sync(fd)
                def publish(*args):
                    if mode=='publish':raise OSError('publication failed')
                    return real_publish(*args)
                with patch.object(Path,'open',opened),patch.object(backend.os,'fsync',sync),patch.object(backend,'_publish_pending_file',publish):
                    result=self.complete()
                self.assertEqual(result['state'],'incomplete');self.assertFalse(result['retired'])
                self.assert_evidence();self.assert_destinations('installation')
                if stage.exists():
                    # Partial stages are deliberately not repaired by the API.
                    if mode in ('short','write'):self.assertEqual(self.complete()['state'],'incomplete')
                    stage.unlink()  # Reset only this synthetic injected artifact.
        self.assertEqual(self.complete()['state'],'installation_complete')

    def test_receipt_exception_after_publication_and_verification_retry(self):
        self.published();self.replace_items();real=backend._publish_pending_file
        def published(*args):real(*args);raise RuntimeError('private diagnostic')
        with patch.object(backend,'_publish_pending_file',published):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertNotIn('private diagnostic',result['reason'])
        self.assertIsInstance(result['failures'][0][1],RuntimeError);self.assert_evidence()
        self.assertEqual((self.prepared['recovery']/'manifest.json').read_bytes(),self.prepared['receipt_bytes'])
        self.assertEqual(self.complete()['state'],'installation_complete');self.assert_destinations('installation')

    def test_receipt_publication_collision_does_not_overwrite(self):
        self.published();self.replace_items();real=backend._publish_pending_file
        receipt=self.prepared['recovery']/'manifest.json'
        def collision(stage,target,root):receipt.write_bytes(b'external collision');return real(stage,target,root)
        with patch.object(backend,'_publish_pending_file',collision):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertIsInstance(result['failures'][0][1],FileExistsError)
        self.assertEqual(receipt.read_bytes(),b'external collision');self.assert_evidence();self.assert_destinations('installation')
        self.assertEqual(self.complete()['state'],'incomplete')

    def test_receipt_verification_failure_preserves_evidence(self):
        self.published();self.replace_items();real=backend._read_preparation_file
        receipt=self.prepared['recovery']/'manifest.json'
        def read(path,*args,**kwargs):
            result=real(path,*args,**kwargs)
            if path==receipt and result[0] is not None:raise OSError('receipt verification failed')
            return result
        with patch.object(backend,'_read_preparation_file',read):self.assertEqual(self.complete()['state'],'incomplete')
        self.assert_evidence();self.assert_destinations('installation')
        self.assertEqual(self.complete()['state'],'installation_complete')

    def test_destination_changed_after_receipt_publication_blocks_retirement(self):
        self.published();self.replace_items();real=backend._publish_completion_receipt
        def publish(*args):
            receipt=real(*args);self.original.write_bytes(b'late external');return receipt
        with patch.object(backend,'_publish_completion_receipt',publish):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertEqual(self.original.read_bytes(),b'late external');self.assert_evidence()

    def assert_plan_change_preserves_evidence_and_retry(self,outcome):
        self.published(all_existing=False)
        if outcome=='installation':self.replace_items()
        real=backend._retirement_artifacts
        for existed in (True,False):
            with self.subTest(originally_existed=existed):
                item=next(item for item in self.items if item['existed']==existed)
                target=self.client/'Interface/AddOns'/item['path']
                expected=target.read_bytes() if target.exists() else None
                def changed(*args):
                    verify.assert_called_once()  # Earlier terminal check really succeeded.
                    before=self.snapshot();evidence={p:p.read_bytes() for p in self.evidence}
                    plan=real(*args)
                    self.assertEqual(self.snapshot(),before)
                    self.assertEqual({p:p.read_bytes() for p in self.evidence},evidence)
                    target.write_bytes(b'external change during cleanup planning')
                    return plan
                with patch.object(backend,'_verify_terminal_destinations',wraps=backend._verify_terminal_destinations) as verify,\
                     patch.object(backend,'_retirement_artifacts',changed),\
                     patch.object(backend,'_retire_verified_artifacts',side_effect=AssertionError('Premature cleanup')) as cleanup:
                    result=self.complete(outcome)
                self.assertEqual(result['state'],'incomplete');self.assertFalse(result['retired'])
                cleanup.assert_not_called();self.assert_evidence()
                self.assertEqual(backend.inspect_pending_transaction(self.client,self.backups)['state'],'ambiguous')
                self.assertEqual(backend.recover_pending_transaction(self.client,self.backups)['state'],'blocked')
                self.assertEqual(self.complete(outcome)['state'],'blocked');self.assert_evidence()
                self.assertEqual(target.read_bytes(),b'external change during cleanup planning')
                # Explicit synthetic conflict resolution, never automatic overwrite by recovery.
                if expected is None:target.unlink()
                else:target.write_bytes(expected)
                self.assertEqual(backend.inspect_pending_transaction(self.client,self.backups)['state'],'valid')
        if outcome=='rollback':
            self.assertEqual(backend.recover_pending_transaction(self.client,self.backups)['state'],'rollback_complete')
        with patch.object(backend,'_publish_pending_file',side_effect=AssertionError('Receipt must not be republished')):
            result=self.complete(outcome)
        self.assertEqual(result['state'],outcome+'_complete');self.assertTrue(result['retired']);self.assertFalse(result['failures'])
        self.assert_destinations(outcome);self.assertFalse((self.client/backend.PENDING_NAME).exists())
        if outcome=='installation':
            self.assertEqual((self.prepared['recovery']/'manifest.json').read_bytes(),self.prepared['receipt_bytes'])
            self.assertEqual([p.name for p in self.prepared['recovery'].iterdir()],['manifest.json'])
        else:self.assertFalse(self.prepared['recovery'].exists())
        self.assertFalse(list(self.client.rglob('*.stage')))

    def test_install_plan_change_preserves_evidence_and_allows_explicit_retry(self):
        self.assert_plan_change_preserves_evidence_and_retry('installation')

    def test_rollback_plan_change_preserves_evidence_and_allows_explicit_retry(self):
        self.assert_plan_change_preserves_evidence_and_retry('rollback')

    def test_marker_deletion_failure_and_exception_after_deletion(self):
        self.published();self.replace_items();real=Path.unlink;marker=self.client/backend.PENDING_NAME
        def denied(path,*args,**kwargs):
            if path==marker:raise PermissionError('marker sharing violation')
            return real(path,*args,**kwargs)
        with patch.object(Path,'unlink',denied):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertFalse(result['retired']);self.assert_evidence()
        originals={p:raw for p,raw in self.evidence.items() if p!=marker}
        def uncertain(path,*args,**kwargs):
            result=real(path,*args,**kwargs)
            if path==marker:raise RuntimeError('after marker removal')
            return result
        with patch.object(Path,'unlink',uncertain):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertFalse(result['retired'])
        self.assertFalse(marker.exists())
        for path,raw in originals.items():self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(self.complete()['state'],'no_pending');self.assert_destinations('installation')
        for path,raw in originals.items():self.assertEqual(path.read_bytes(),raw)

    def test_marker_absence_verification_failure_never_cleans_backups(self):
        self.published();self.replace_items()
        with patch.object(backend,'_retirement_guard',side_effect=OSError('cannot verify marker absence')):
            result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertFalse(result['retired'])
        self.assertFalse((self.client/backend.PENDING_NAME).exists())
        for path,raw in self.evidence.items():
            if path.name!=backend.PENDING_NAME:self.assertEqual(path.read_bytes(),raw)

    def test_independent_cleanup_failures_preserve_changed_artifacts_and_metadata(self):
        self.published();self.replace_items(consume=False);real=backend._retire_verified_artifacts
        changed=self.prepared['recovery']/'WFCore/module.lua'
        failed=self.client/'Interface/AddOns'/self.items[-1]['stage'];unlink=Path.unlink;attempts=[]
        def retire(*args):changed.write_bytes(b'external backup');return real(*args)
        def denied(path,*args,**kwargs):
            attempts.append(path)
            if path==failed:raise OSError('stage sharing violation')
            return unlink(path,*args,**kwargs)
        with patch.object(backend,'_retire_verified_artifacts',retire),patch.object(Path,'unlink',denied):result=self.complete()
        self.assertEqual(result['state'],'installation_complete');self.assertTrue(result['retired']);self.assertEqual(len(result['failures']),2)
        self.assertEqual(changed.read_bytes(),b'external backup');self.assertTrue(failed.exists())
        self.assertTrue((self.prepared['recovery']/'transaction.json').exists())
        self.assertFalse((self.prepared['recovery']/'WFStorage/module.lua').exists())
        self.assertGreater(len(attempts),2);self.assert_destinations('installation')

    def test_unrelated_files_and_directories_are_not_cleanup_targets(self):
        self.published();recovery=self.prepared['recovery']
        extra=recovery/'unrelated';extra.mkdir();sentinel=extra/'keep';sentinel.write_bytes(b'unrelated')
        result=self.complete('rollback')
        self.assertEqual(result['state'],'rollback_complete');self.assertTrue(result['failures'])
        self.assertEqual(sentinel.read_bytes(),b'unrelated');self.assertTrue(extra.is_dir());self.assert_destinations('rollback')

    def test_wrong_lock_identity_fails_before_completion_mutation(self):
        self.published();self.replace_items();before=self.snapshot();real=backend.installation_lock
        @contextmanager
        def wrong(client):
            with real(client) as identity:yield dict(identity,inode=identity['inode']+1)
        with patch.object(backend,'installation_lock',wrong),self.assertRaises(ValueError):self.complete()
        self.assertEqual(self.snapshot(),before);self.assert_evidence()

    def test_receipt_hard_link_and_rollback_receipt_conflict_fail_closed(self):
        self.published();receipt=self.prepared['recovery']/'manifest.json';receipt.write_bytes(b'conflict')
        self.assertEqual(self.complete('rollback')['state'],'incomplete');self.assert_evidence();self.assert_destinations('rollback')
        receipt.write_bytes(self.prepared['receipt_bytes']);sentinel=self.root/'external-receipt';os.link(receipt,sentinel)
        try:
            self.assertEqual(self.complete('rollback')['state'],'blocked');self.assert_evidence()
            self.assertEqual(sentinel.read_bytes(),self.prepared['receipt_bytes'])
        finally:sentinel.unlink()
        result=self.complete('rollback');self.assertEqual(result['state'],'rollback_complete')
        self.assertEqual(receipt.read_bytes(),self.prepared['receipt_bytes']);self.assert_destinations('rollback')

    def test_consistently_rehashed_wrong_receipt_is_not_published(self):
        self.published();self.replace_items();record=copy.deepcopy(self.prepared['record'])
        receipt=json.loads(self.prepared['receipt_bytes']);receipt['files']=[]
        receipt_raw=json.dumps(receipt).encode();(self.prepared['recovery']/'receipt.pending').write_bytes(receipt_raw)
        record['receipt'].update(fingerprint(receipt_raw));record_raw=json.dumps(record).encode()
        (self.prepared['recovery']/'transaction.json').write_bytes(record_raw)
        marker=self.client/backend.PENDING_NAME;pending=json.loads(marker.read_bytes());pending['transaction']=fingerprint(record_raw)
        marker.write_bytes(json.dumps(pending).encode());before=self.snapshot()
        self.assertEqual(self.complete()['state'],'incomplete');self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.prepared['recovery']/'manifest.json').exists());self.assert_destinations('installation')

    def test_new_pending_marker_after_retirement_blocks_artifact_cleanup(self):
        self.published();self.replace_items();real=backend._retire_verified_artifacts;marker=self.client/backend.PENDING_NAME
        def changed(*args):marker.write_bytes(b'new external marker');return real(*args)
        with patch.object(backend,'_retire_verified_artifacts',changed):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertTrue(result['failures'])
        self.assertEqual(marker.read_bytes(),b'new external marker')
        for path,raw in self.evidence.items():
            if path!=marker:self.assertEqual(path.read_bytes(),raw)
        self.assert_destinations('installation')

    def test_late_destination_change_cannot_report_terminal_success(self):
        self.published();self.replace_items();real=backend._retire_verified_artifacts
        def changed(*args):
            failures=real(*args);self.original.write_bytes(b'external after retirement');return failures
        with patch.object(backend,'_retire_verified_artifacts',changed):result=self.complete()
        self.assertEqual(result['state'],'incomplete');self.assertTrue(result['retired'])
        self.assertEqual(self.original.read_bytes(),b'external after retirement')
        self.assertFalse((self.client/backend.PENDING_NAME).exists())

    def test_fresh_process_retry_at_completion_interruption_boundaries(self):
        code="""
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
client,root,ready=map(Path,sys.argv[2:5]);boundary=sys.argv[5]
def stop():
    ready.write_text('boundary reached')
    time.sleep(60)
opened=Path.open
class PartialWriter:
    def __init__(self,stream):self.stream=stream
    def __enter__(self):return self
    def __exit__(self,*args):self.stream.close()
    def fileno(self):return self.stream.fileno()
    def write(self,raw):self.stream.write(raw[:2]);self.stream.flush();stop()
def partial(path,mode='r',*args,**kwargs):
    stream=opened(path,mode,*args,**kwargs)
    return PartialWriter(stream) if boundary=='receipt-partial' and mode=='xb' else stream
Path.open=partial
write=b._write_preparation_artifact
def staged(path,*args):
    write(path,*args)
    if boundary=='receipt-stage' and path.name.startswith('.wf-receipt-'):stop()
b._write_preparation_artifact=staged
sync=b.os.fsync
def synced(fd):
    sync(fd)
    if boundary=='receipt-sync':stop()
b.os.fsync=synced
publish=b._publish_pending_file
def published(*args):
    publish(*args)
    if boundary=='receipt-published':stop()
b._publish_pending_file=published
receipt=b._publish_completion_receipt
def verified(*args):
    result=receipt(*args)
    if boundary=='receipt-verified':stop()
    return result
b._publish_completion_receipt=verified
terminal=b._verify_terminal_destinations
def verified_terminal(*args):
    terminal(*args)
    if boundary=='terminal-verified':stop()
b._verify_terminal_destinations=verified_terminal
unlink=Path.unlink
def removed(path,*args,**kwargs):
    result=unlink(path,*args,**kwargs)
    if ((boundary=='marker-removed' and path.name==b.PENDING_NAME)
        or (boundary=='stage-removed' and path.suffix=='.stage')
        or (boundary=='backup-removed' and path.suffix=='.lua' and path.is_relative_to(root))):stop()
    return result
Path.unlink=removed
guard=b._retirement_guard
def checked(*args):
    guard(*args)
    if boundary=='marker-verified':stop()
b._retirement_guard=checked
rmdir=Path.rmdir
def directory_removed(path,*args,**kwargs):
    result=rmdir(path,*args,**kwargs)
    if boundary=='directory-removed' and path.name.startswith('prepare-'):stop()
    return result
Path.rmdir=directory_removed
op=b.complete_pending_rollback if boundary=='directory-removed' else b.complete_pending_installation
op(client,root)
"""
        boundaries=('receipt-partial','receipt-sync','receipt-stage','receipt-published','receipt-verified','terminal-verified',
                    'marker-removed','marker-verified','backup-removed','stage-removed','directory-removed')
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                fixture=CompletionTests();fixture.setUp()
                try:
                    fixture.published(all_existing=False)
                    outcome='rollback' if boundary=='directory-removed' else 'installation'
                    if outcome=='installation':fixture.replace_items(consume=False)
                    ready=fixture.root/'ready'
                    child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(backend.__file__).parent),
                        str(fixture.client),str(fixture.backups),str(ready),boundary],
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=0x08000000)
                    try:
                        deadline=time.monotonic()+15
                        while not ready.exists():
                            if child.poll() is not None:self.fail(child.communicate(timeout=1)[1] or 'Boundary not reached')
                            if time.monotonic()>deadline:self.fail('Completion subprocess timed out')
                            time.sleep(.02)
                        with self.assertRaisesRegex(ValueError,'Another addon installation'):fixture.complete(outcome)
                        child.kill();child.communicate(timeout=10)
                    finally:
                        if child.poll() is None:child.kill();child.communicate(timeout=10)
                    fixture.assert_destinations(outcome)
                    pending=(fixture.client/backend.PENDING_NAME).exists()
                    if pending:fixture.assert_evidence()
                    residual={p:p.read_bytes() for p in fixture.backups.rglob('*') if p.is_file()}
                    retry="""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
op=b.complete_pending_installation if sys.argv[4]=='installation' else b.complete_pending_rollback
result=op(Path(sys.argv[2]),Path(sys.argv[3]))
assert result['state']==sys.argv[5], result['state']
assert bool(result['failures'])==(sys.argv[5]=='incomplete'), result['failures']
"""
                    expected='incomplete' if boundary=='receipt-partial' else outcome+'_complete' if pending else 'no_pending'
                    done=subprocess.run([sys.executable,'-B','-c',retry,str(Path(backend.__file__).parent),
                        str(fixture.client),str(fixture.backups),outcome,expected],capture_output=True,text=True,timeout=15,creationflags=0x08000000)
                    self.assertEqual(done.returncode,0,done.stderr);fixture.assert_destinations(outcome)
                    if not pending or boundary=='receipt-partial':
                        for path,raw in residual.items():self.assertEqual(path.read_bytes(),raw)
                finally:fixture.doCleanups()


@unittest.skipUnless(os.name=='nt','Retained backups use Windows non-overwriting publication')
class RetainedBackupTests(unittest.TestCase):
    snapshot=PreparationTests.snapshot

    def setUp(self):
        PreparationTests.setUp(self)
        self.users=self.root/'user-backups';self.users.mkdir()
        old=self.users/'20260101-000000-000000/WFCore/module.lua'
        old.parent.mkdir(parents=True);old.write_bytes(b'prior legacy original')
        (old.parent.parent/'manifest.json').write_bytes(b'prior receipt unchanged')
        self.history={p.relative_to(self.users):p.read_bytes() for p in self.users.rglob('*') if p.is_file()}

    def execute(self):
        return backend.execute_transaction(self.payload,self.client,['WFStorage','WFProfessions'],self.backups,
                                           retained_backup_root=self.users)

    def assert_history(self):
        for path,raw in self.history.items():self.assertEqual((self.users/path).read_bytes(),raw)
        for name in ('WTF/synthetic.lua','Interface/AddOns/Other/keep.lua','Wow.exe'):
            self.assertEqual((self.client/name).read_bytes(),self.before[name])

    def test_success_keeps_all_originals_including_unchanged_and_absent(self):
        for mode in ('different','matching','fresh'):
            with self.subTest(mode=mode):
                fixture=RetainedBackupTests();fixture.setUp()
                try:
                    if mode=='fresh':fixture.original.unlink()
                    elif mode=='matching':fixture.original.write_bytes((fixture.payload/'WFCore/module.lua').read_bytes())
                    original=fixture.original.read_bytes() if fixture.original.exists() else None
                    result=fixture.execute();self.assertEqual(result['state'],'installation_complete',result)
                    saved=result['retained_backup'];index=json.loads((saved/'originals.json').read_bytes())
                    expected=[] if original is None else [dict(path='WFCore/module.lua',**fingerprint(original))]
                    self.assertEqual(index['files'],expected)
                    self.assertEqual((saved/'WFCore/module.lua').read_bytes() if original is not None else None,original)
                    receipt=json.loads((saved/'manifest.json').read_bytes())
                    self.assertEqual(set(receipt),{'client','selected','packages','files'})
                    self.assertEqual(receipt['selected'],['WFCore','WFProfessions','WFStorage'])
                    self.assertEqual(len(receipt['files']),6)
                    for addon in receipt['selected']:
                        for source in (fixture.payload/addon).iterdir():
                            self.assertEqual((fixture.client/'Interface/AddOns'/addon/source.name).read_bytes(),source.read_bytes())
                    self.assertFalse((fixture.client/backend.PENDING_NAME).exists())
                    self.assertEqual([p.name for p in fixture.backups.glob('prepare-*/*')],['manifest.json'])
                    fixture.assert_history()
                finally:fixture.doCleanups()

    def test_preparation_failures_leave_destinations_and_history_untouched(self):
        real=backend._write_preparation_artifact
        for kind in ('create','partial','write','flush','sync','verify','publish'):
            with self.subTest(kind=kind):
                fixture=RetainedBackupTests();fixture.setUp()
                def failed(path,root,raw,*args):
                    if Path(root)==fixture.users and Path(path).name=='module.lua':
                        if kind=='create':raise PermissionError('synthetic private path')
                        if kind in ('partial','write','flush'):
                            opening=Path.open
                            class FaultyStream:
                                def __init__(self,stream):self.stream=stream
                                def __enter__(self):return self
                                def __exit__(self,*args):return self.stream.__exit__(*args)
                                def fileno(self):return self.stream.fileno()
                                def write(self,data):
                                    count=self.stream.write(data[:2] if kind in ('partial','write') else data)
                                    if kind=='write':raise OSError('write failed after partial write')
                                    return count
                                def flush(self):
                                    if kind=='flush':raise OSError('flush')
                                    return self.stream.flush()
                            def opened(target,*a,**kw):
                                stream=opening(target,*a,**kw)
                                return FaultyStream(stream) if Path(target)==Path(path) and a[0]=='xb' else stream
                            with patch.object(Path,'open',opened):return real(path,root,raw,*args)
                        if kind=='sync':
                            with patch.object(backend.os,'fsync',side_effect=OSError('sync')):return real(path,root,raw,*args)
                        result=real(path,root,raw,*args)
                        if kind=='verify':Path(path).write_bytes(b'external change')
                        return result
                    return real(path,root,raw,*args)
                publish=backend._publish_pending_file
                def publication(stage,target,root):
                    if kind=='publish' and Path(target).name=='originals.json':raise OSError('publication')
                    return publish(stage,target,root)
                try:
                    with patch.object(backend,'_write_preparation_artifact',failed),patch.object(backend,'_publish_pending_file',publication):
                        result=fixture.execute()
                    self.assertEqual((result['state'],result['phase']),('blocked','retained_backup'),result)
                    self.assertEqual(fixture.snapshot(),fixture.before)
                    self.assertEqual(list(fixture.backups.iterdir()),[])
                    self.assertFalse(list(fixture.users.glob('transaction-*/originals.json')))
                    self.assertFalse(list(fixture.users.glob('transaction-*/manifest.json')))
                    fixture.assert_history()
                finally:fixture.doCleanups()

    def test_name_collision_is_not_reused(self):
        real=backend._prepare_retained_backup
        def collide(prepared,root):
            path=Path(root)/('transaction-'+prepared['record']['id']);path.mkdir()
            (path/'sentinel').write_bytes(b'keep collision')
            return real(prepared,root)
        with patch.object(backend,'_prepare_retained_backup',collide):result=self.execute()
        self.assertEqual(result['state'],'blocked');self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(next(self.users.glob('transaction-*/sentinel')).read_bytes(),b'keep collision')
        self.assert_history()

    def test_unsafe_roots_and_linked_copy_targets_block_before_publication(self):
        for root in (self.client,self.backups,self.root,self.payload,self.users/'missing'):
            result=backend.execute_transaction(self.payload,self.client,['WFStorage'],self.backups,retained_backup_root=root)
            self.assertEqual(result['state'],'blocked',result);self.assertEqual(self.snapshot(),self.before)
        import _winapi
        alias=self.root/'linked-users';_winapi.CreateJunction(str(self.users),str(alias))
        try:
            result=backend.execute_transaction(self.payload,self.client,['WFStorage'],self.backups,retained_backup_root=alias)
            self.assertEqual(result['state'],'blocked');self.assertEqual(self.snapshot(),self.before)
        finally:alias.rmdir()
        real=backend._write_preparation_artifact;sentinel=self.root/'external';sentinel.write_bytes(b'external')
        def linked(path,root,raw,*args):
            if Path(root)==self.users and Path(path).name=='module.lua':
                Path(path).parent.mkdir(parents=True);os.link(sentinel,path)
            return real(path,root,raw,*args)
        with patch.object(backend,'_write_preparation_artifact',linked):result=self.execute()
        self.assertEqual(result['state'],'blocked');self.assertEqual(sentinel.read_bytes(),b'external')
        self.assertEqual(self.snapshot(),self.before);self.assert_history()

    def test_failed_replacement_rolls_back_but_keeps_retained_set(self):
        replace=backend.os.replace;count=0
        def fail(stage,target):
            nonlocal count
            count+=1
            if count==2:raise OSError('replacement failure')
            return replace(stage,target)
        with patch.object(backend.os,'replace',fail):result=self.execute()
        self.assertEqual(result['state'],'rollback_complete',result)
        self.assertEqual(self.snapshot(),self.before)
        self.assertEqual((result['retained_backup']/'WFCore/module.lua').read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertTrue((result['retained_backup']/'originals.json').exists())
        self.assertFalse((result['retained_backup']/'manifest.json').exists())
        self.assert_history()

    def test_retained_damage_during_finalization_preserves_recovery(self):
        plan=backend._retirement_artifacts
        def changed(*args):
            result=plan(*args)
            next(self.users.glob('transaction-*/WFCore/module.lua')).write_bytes(b'external')
            return result
        with patch.object(backend,'_retirement_artifacts',changed):result=self.execute()
        self.assertEqual(result['state'],'finalization_pending',result)
        self.assertFalse(result['completion']['retired'])
        status=backend.inspect_pending_transaction(self.client,self.backups)
        self.assertEqual(status['state'],'valid')
        original=self.before['Interface/AddOns/WFCore/module.lua']
        self.assertEqual((status['recovery']/'WFCore/module.lua').read_bytes(),original)
        self.assertEqual(backend.complete_pending_installation(self.client,self.backups,retained_backup_root=self.users)['state'],'incomplete')
        # Explicit test-only conflict resolution; no helper overwrites external bytes.
        (result['retained_backup']/'WFCore/module.lua').write_bytes(original)
        retry=backend.complete_pending_installation(self.client,self.backups,retained_backup_root=self.users)
        self.assertEqual(retry['state'],'installation_complete',retry);self.assert_history()

    def test_retained_receipt_failure_and_matching_or_conflicting_retry(self):
        publish=backend._publish_pending_file
        def fail(stage,target,root):
            if Path(root)==self.users and Path(target).name=='manifest.json':raise OSError('receipt publication')
            return publish(stage,target,root)
        with patch.object(backend,'_publish_pending_file',fail):result=self.execute()
        self.assertEqual(result['state'],'finalization_pending')
        saved=result['retained_backup'];self.assertTrue((self.client/backend.PENDING_NAME).exists())
        (saved/'manifest.json').write_bytes(b'conflicting receipt')
        retry=backend.complete_pending_installation(self.client,self.backups,retained_backup_root=self.users)
        self.assertEqual(retry['state'],'incomplete');self.assertFalse(retry['retired'])
        self.assertEqual((saved/'manifest.json').read_bytes(),b'conflicting receipt')
        (saved/'manifest.json').unlink()  # Explicit fixture resolution.
        expected=(saved/'.manifest.stage').read_bytes()
        (saved/'manifest.json').write_bytes(expected)  # Already-published receipt retry.
        retry=backend.complete_pending_installation(self.client,self.backups,retained_backup_root=self.users)
        self.assertEqual(retry['state'],'installation_complete',retry)
        self.assertEqual((saved/'manifest.json').read_bytes(),expected);self.assert_history()

    def test_destination_change_during_final_backup_check_keeps_recovery_evidence(self):
        verify=backend.RetainedUserBackup.verify;plan=backend._retirement_artifacts;planned=False
        def planned_cleanup(*args):
            nonlocal planned
            result=plan(*args);planned=True;return result
        def changed(saved,**kwargs):
            result=verify(saved,**kwargs)
            if planned:self.original.write_bytes(b'external after backup verification')
            return result
        with patch.object(backend,'_retirement_artifacts',planned_cleanup),patch.object(backend.RetainedUserBackup,'verify',changed):
            result=self.execute()
        self.assertEqual(result['state'],'finalization_pending');self.assertFalse(result['completion']['retired'])
        self.assertTrue((self.client/backend.PENDING_NAME).exists())
        self.assertEqual(next(self.backups.glob('prepare-*/WFCore/module.lua')).read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(self.original.read_bytes(),b'external after backup verification')
        self.assert_history()

    def test_separate_clients_share_history_without_sharing_recovery(self):
        first=self.execute();self.assertEqual(first['state'],'installation_complete')
        peer=self.root/'_classic_beta_';peer.mkdir();(peer/'WowB.exe').touch()
        recovery=self.root/'peer-recovery';recovery.mkdir()
        result=backend.execute_transaction(self.payload,peer,['WFStorage'],recovery,retained_backup_root=self.users)
        self.assertEqual(result['state'],'installation_complete',result)
        self.assertNotEqual(first['retained_backup'],result['retained_backup'])
        self.assertEqual(json.loads((result['retained_backup']/'originals.json').read_bytes())['files'],[])
        self.assert_history()

    def test_terminated_executor_keeps_user_and_recovery_originals_for_retries(self):
        ready=self.root/'ready'
        code=r'''
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
payload,client,recovery,users,ready=map(Path,sys.argv[2:])
replace=b.os.replace
def pause(stage,target):
    replace(stage,target);ready.write_text('replaced');time.sleep(60)
b.os.replace=pause
b.execute_transaction(payload,client,['WFStorage','WFProfessions'],recovery,retained_backup_root=users)
'''
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(backend.__file__).parent),
                                str(self.payload),str(self.client),str(self.backups),str(self.users),str(ready)],
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+20
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(ready.exists(),'child did not reach replacement')
        finally:
            if child.poll() is None:child.kill()
            child.communicate(timeout=10)
        saved=next(self.users.glob('transaction-*'));original=self.before['Interface/AddOns/WFCore/module.lua']
        self.assertEqual((saved/'WFCore/module.lua').read_bytes(),original)
        for _ in range(2):
            result=backend.recover_pending_transaction(self.client,self.backups)
            self.assertEqual(result['state'],'rollback_complete',result)
            self.assertEqual((saved/'WFCore/module.lua').read_bytes(),original)
        self.assertEqual(backend.complete_pending_rollback(self.client,self.backups)['state'],'rollback_complete')
        self.assertEqual(self.snapshot(),self.before);self.assert_history()


@unittest.skipUnless(os.name=='nt','Executor uses Windows non-overwriting publication')
class ExecutorTests(unittest.TestCase):
    setUp=PreparationTests.setUp
    snapshot=PreparationTests.snapshot
    prepare=PreparationTests.prepare

    def execute(self,client=None):
        return backend.execute_transaction(self.payload,client or self.client,['WFStorage','WFProfessions'],self.backups)

    def assert_installed(self):
        for source in self.payload.rglob('*'):
            if source.is_file():
                self.assertEqual((self.client/'Interface/AddOns'/source.relative_to(self.payload)).read_bytes(),source.read_bytes())
        self.assert_unrelated()

    def assert_unrelated(self):
        for name in ('WTF/synthetic.lua','Interface/AddOns/Other/keep.lua','Wow.exe'):
            self.assertEqual((self.client/name).read_bytes(),self.before[name])

    def assert_pending_original(self):
        marker=json.loads((self.client/backend.PENDING_NAME).read_bytes())
        recovery=self.backups/('prepare-'+marker['id'])
        self.assertEqual((recovery/'WFCore/module.lua').read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertTrue((recovery/'transaction.json').exists())
        self.assert_unrelated()

    def test_fresh_update_and_already_matching_files_complete(self):
        for mode in ('fresh','different','matching'):
            with self.subTest(mode=mode):
                fixture=ExecutorTests();fixture.setUp()
                try:
                    if mode=='fresh':fixture.original.unlink()
                    else:
                        for source in fixture.payload.rglob('*'):
                            if source.is_file():
                                target=fixture.client/'Interface/AddOns'/source.relative_to(fixture.payload)
                                target.parent.mkdir(parents=True,exist_ok=True)
                                target.write_bytes(source.read_bytes() if mode=='matching' else
                                    (b'## Version: 0.7.0\n# old toc' if target.suffix=='.toc' else b'old\x00\xff '+source.name.encode()))
                    order=[];real=backend.os.replace
                    def replaced(stage,target):
                        order.append(Path(target).relative_to(fixture.client/'Interface/AddOns').as_posix())
                        return real(stage,target)
                    with patch.object(backend.os,'replace',replaced):result=fixture.execute()
                    self.assertEqual(result['state'],'installation_complete',result);fixture.assert_installed()
                    self.assertEqual(order,['WFCore/module.lua','WFProfessions/module.lua','WFStorage/module.lua',
                        'WFCore/WFCore.toc','WFProfessions/WFProfessions.toc','WFStorage/WFStorage.toc'])
                    self.assertFalse((fixture.client/backend.PENDING_NAME).exists())
                    receipts=list(fixture.backups.glob('prepare-*/manifest.json'));self.assertEqual(len(receipts),1)
                    self.assertEqual(json.loads(receipts[0].read_bytes())['selected'],['WFCore','WFProfessions','WFStorage'])
                    self.assertFalse(list(fixture.client.rglob('*.stage')))
                finally:fixture.doCleanups()

    def test_preexisting_pending_valid_invalid_and_ambiguous_block_without_writes(self):
        with self.prepare() as prepared:prepared.publish_pending()
        marker=self.client/backend.PENDING_NAME;raw=marker.read_bytes()
        for state in ('valid','invalid','ambiguous'):
            with self.subTest(state=state):
                marker.write_bytes(b'bad' if state=='invalid' else raw)
                if state=='ambiguous':self.original.write_bytes(b'external')
                before=self.snapshot();evidence={p:p.read_bytes() for p in self.backups.rglob('*') if p.is_file()}
                with patch.object(backend,'_prepare_transaction_locked',side_effect=AssertionError('Must not prepare')):
                    result=self.execute()
                self.assertEqual(result['state'],'blocked');self.assertEqual(result['inspection']['state'],state)
                self.assertEqual(self.snapshot(),before)
                for p,content in evidence.items():self.assertEqual(p.read_bytes(),content)

    def test_prepublication_failure_cleans_only_temporary_artifacts(self):
        real=backend._write_preparation_artifact
        def fail(path,*args):
            if Path(path).suffix=='.stage':raise RuntimeError('private diagnostic')
            return real(path,*args)
        with patch.object(backend,'_write_preparation_artifact',fail):result=self.execute()
        self.assertEqual(result['state'],'blocked');self.assertNotIn('private diagnostic',result['reason'])
        self.assertEqual(self.snapshot(),self.before);self.assertEqual(list(self.backups.iterdir()),[])

    def test_uncertain_publication_never_mutates_destinations_or_cleans_backups(self):
        real=backend._publish_pending_file
        def fail(*args):real(*args);raise RuntimeError('after publication')
        with patch.object(backend,'_publish_pending_file',fail):result=self.execute()
        self.assertEqual(result['state'],'recovery_pending');self.assert_pending_original()
        self.assertEqual(self.original.read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(backend.inspect_pending_transaction(self.client,self.backups)['state'],'valid')

    def test_replacement_failure_restores_exact_originals_and_retires(self):
        real=backend.os.replace;calls=[]
        def fail(stage,target):
            calls.append(Path(target).name)
            if len(calls)==3:raise RuntimeError('synthetic replacement failure')
            return real(stage,target)
        with patch.object(backend.os,'replace',fail):result=self.execute()
        self.assertEqual(result['state'],'rollback_complete',result)
        self.assertIsInstance(result['error'],RuntimeError)
        self.assertEqual(self.snapshot(),self.before);self.assertEqual(list(self.backups.iterdir()),[])

    def test_failed_rollback_retains_evidence_and_later_retry_restores_exactly(self):
        real=backend.os.replace;count=0
        def fail(stage,target):
            nonlocal count
            count+=1
            if count>=3:raise OSError('synthetic write failure')
            return real(stage,target)
        with patch.object(backend.os,'replace',fail):result=self.execute()
        self.assertEqual(result['state'],'recovery_pending');self.assert_pending_original()
        self.assertFalse((self.client/'Interface/AddOns/WFProfessions/module.lua').exists())
        self.assertEqual(backend.recover_pending_transaction(self.client,self.backups)['state'],'rollback_complete')
        self.assertEqual(backend.complete_pending_rollback(self.client,self.backups)['state'],'rollback_complete')
        self.assertEqual(self.snapshot(),self.before)

    def test_external_change_before_replacement_is_preserved_and_recovery_blocked(self):
        real=backend._check_recovery_inputs;changed=False
        def change(status,item,*args):
            nonlocal changed
            if not changed and item['path']=='WFProfessions/module.lua':
                changed=True;(self.client/'Interface/AddOns'/item['path']).write_bytes(b'external')
            return real(status,item,*args)
        with patch.object(backend,'_check_recovery_inputs',change):result=self.execute()
        self.assertEqual(result['state'],'recovery_pending');self.assert_pending_original()
        self.assertEqual((self.client/'Interface/AddOns/WFProfessions/module.lua').read_bytes(),b'external')
        self.assertEqual(backend.inspect_pending_transaction(self.client,self.backups)['state'],'ambiguous')

    def test_missing_or_changed_stage_cannot_be_used(self):
        for missing in (False,True):
            with self.subTest(missing=missing):
                fixture=ExecutorTests();fixture.setUp();real=backend._apply_transaction_files
                def changed(status,*args):
                    path=status['destinations'][0]['stage'][0]
                    if missing:path.unlink()
                    else:path.write_bytes(b'external stage')
                    return real(status,*args)
                try:
                    with patch.object(backend,'_apply_transaction_files',changed):result=fixture.execute()
                    self.assertEqual(result['state'],'rollback_complete' if missing else 'recovery_pending',result)
                    self.assertEqual(fixture.original.read_bytes(),fixture.before['Interface/AddOns/WFCore/module.lua'])
                    if not missing:fixture.assert_pending_original()
                finally:fixture.doCleanups()

    def test_complete_bytes_after_replace_exception_are_not_rolled_back(self):
        real=backend.os.replace
        def fail(stage,target):
            real(stage,target)
            if Path(target).name=='WFStorage.toc':raise RuntimeError('after final replacement')
        with patch.object(backend.os,'replace',fail),patch.object(backend,'_recover_pending_locked',side_effect=AssertionError('No rollback')):
            result=self.execute()
        self.assertEqual(result['state'],'finalization_pending');self.assert_installed();self.assert_pending_original()
        self.assertEqual(backend.complete_pending_installation(self.client,self.backups)['state'],'installation_complete')

    def test_receipt_and_retirement_failures_never_trigger_rollback(self):
        for fault in ('collision','publication','after-publication','marker','cleanup'):
            with self.subTest(fault=fault):
                fixture=ExecutorTests();fixture.setUp()
                publish=backend._publish_completion_receipt;rename=backend.os.rename;unlink=Path.unlink
                def receipt(status,*args):
                    if fault=='collision':(status['recovery']/'manifest.json').write_bytes(b'conflict')
                    return publish(status,*args)
                def fail_rename(stage,target):
                    if Path(target).name=='manifest.json':
                        if fault=='publication':raise OSError('receipt publication')
                        if fault=='after-publication':rename(stage,target);raise RuntimeError('after receipt')
                    return rename(stage,target)
                def fail_unlink(path,*args,**kwargs):
                    if fault=='marker' and path.name==backend.PENDING_NAME:raise OSError('marker removal')
                    if fault=='cleanup' and path==next(fixture.backups.glob('prepare-*'))/'WFCore/module.lua':raise OSError('cleanup')
                    return unlink(path,*args,**kwargs)
                try:
                    with patch.object(backend,'_publish_completion_receipt',receipt),patch.object(backend.os,'rename',fail_rename),\
                         patch.object(Path,'unlink',fail_unlink),patch.object(backend,'_recover_pending_locked',side_effect=AssertionError('No rollback')):
                        result=fixture.execute()
                    self.assertEqual(result['state'],'finalization_pending',result);fixture.assert_installed()
                    if fault!='cleanup':fixture.assert_pending_original()
                    else:
                        self.assertTrue(result['completion']['retired']);self.assertTrue(result['completion']['failures'])
                        self.assertFalse((fixture.client/backend.PENDING_NAME).exists())
                    if fault in ('publication','after-publication','marker'):
                        self.assertEqual(backend.complete_pending_installation(fixture.client,fixture.backups)['state'],'installation_complete')
                finally:fixture.doCleanups()

    def test_one_lock_covers_publication_replacements_completion_and_cleanup(self):
        acquire=backend.installation_lock;seen=[];real=backend._read_preparation_file
        @contextmanager
        def counted(client):
            seen.append(backend.client_identity(client))
            with acquire(client) as identity:yield identity
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        def read(path,*args,**kwargs):
            with self.assertRaisesRegex(ValueError,'Another addon installation'):
                with acquire(self.client):pass
            with acquire(other):pass
            return real(path,*args,**kwargs)
        with patch.object(backend,'installation_lock',counted),patch.object(backend,'_read_preparation_file',read):result=self.execute()
        self.assertEqual(result['state'],'installation_complete');self.assertEqual(len(seen),1)
        with acquire(self.client):pass

    def test_wrong_lock_identity_and_alias_retarget_before_acquisition_fail_closed(self):
        import _winapi
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        alias=self.root/'alias';_winapi.CreateJunction(str(self.client),str(alias));self.addCleanup(alias.rmdir)
        acquire=backend.installation_lock
        @contextmanager
        def wrong(client):
            with acquire(client):yield backend.client_identity(other)
        with patch.object(backend,'installation_lock',wrong):result=self.execute()
        self.assertEqual(result['state'],'blocked');self.assertEqual(self.snapshot(),self.before)
        @contextmanager
        def retarget(client):
            alias.rmdir();_winapi.CreateJunction(str(other),str(alias))
            with acquire(client) as identity:yield identity
        with acquire(other),patch.object(backend,'installation_lock',retarget):result=self.execute(alias)
        self.assertEqual(result['state'],'blocked');self.assertEqual(self.snapshot(),self.before)
        self.assertEqual(list(other.iterdir()),[other/'WowB.exe']);self.assertEqual(list(self.backups.iterdir()),[])

    def test_alias_retarget_after_pinning_never_redirects_writes(self):
        import _winapi
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        alias=self.root/'alias';_winapi.CreateJunction(str(self.client),str(alias));self.addCleanup(alias.rmdir)
        real=backend._prepare_transaction_locked
        @contextmanager
        def retarget(*args):
            alias.rmdir();_winapi.CreateJunction(str(other),str(alias))
            with real(*args) as prepared:yield prepared
        with backend.installation_lock(other),patch.object(backend,'_prepare_transaction_locked',retarget):result=self.execute(alias)
        self.assertEqual(result['state'],'installation_complete');self.assert_installed()
        self.assertEqual(list(other.iterdir()),[other/'WowB.exe'])

    def test_hard_link_added_before_forward_write_is_rejected(self):
        real=backend._apply_transaction_files;sentinel=self.root/'sentinel'
        def linked(*args):
            os.link(self.original,sentinel)
            return real(*args)
        with patch.object(backend,'_apply_transaction_files',linked):result=self.execute()
        self.assertEqual(result['state'],'recovery_pending');self.assert_pending_original()
        self.assertEqual(sentinel.read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(self.original.read_bytes(),sentinel.read_bytes())

    def test_busy_client_is_blocked_while_other_client_executor_completes(self):
        other=self.root/'_classic_beta_';other.mkdir();(other/'WowB.exe').touch()
        with backend.installation_lock(self.client):
            self.assertEqual(self.execute()['state'],'blocked')
            self.assertEqual(self.snapshot(),self.before)
            self.assertEqual(self.execute(other)['state'],'installation_complete')
        for source in self.payload.rglob('*'):
            if source.is_file():
                self.assertEqual((other/'Interface/AddOns'/source.relative_to(self.payload)).read_bytes(),source.read_bytes())
        self.assertEqual(self.snapshot(),self.before)

    def test_process_interruption_exception_is_not_suppressed(self):
        real=backend.os.replace
        def interrupted(stage,target):real(stage,target);raise KeyboardInterrupt()
        with patch.object(backend.os,'replace',interrupted):
            with self.assertRaises(KeyboardInterrupt):self.execute()
        self.assert_pending_original()
        self.assertEqual(backend.recover_pending_transaction(self.client,self.backups)['state'],'rollback_complete')
        self.assertEqual(backend.complete_pending_rollback(self.client,self.backups)['state'],'rollback_complete')
        self.assertEqual(self.snapshot(),self.before)

    def test_last_stage_identity_check_rejects_change_after_content_check(self):
        real=backend._check_recovery_inputs;changed=False
        def altered(status,item,observed,*args):
            nonlocal changed
            result=real(status,item,observed,*args)
            if not changed:
                changed=True;observed['stage'][0].write_bytes(b'external stage')
            return result
        with patch.object(backend,'_check_recovery_inputs',altered):result=self.execute()
        self.assertEqual(result['state'],'recovery_pending');self.assert_pending_original()
        self.assertEqual(self.original.read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])

    def test_forced_termination_and_fresh_process_recovery_or_completion(self):
        # Actual Windows mutexes, rename/replace/unlink and TerminateProcess.
        # Hooks pause immediately at production helper/syscall boundaries only.
        boundaries=('prepared','published','before-first','after-1','after-2','after-3',
                    'before-toc','after-4','after-6','receipt-before','receipt-written',
                    'receipt-synced','receipt-published','marker-before','marker-after','cleanup')
        child_code=r'''
import sys,time,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
payload,client,root,ready=map(Path,sys.argv[2:6]);boundary=sys.argv[6]
def pause(name):
    if boundary==name:
        ready.write_text(name)
        time.sleep(60)
publish=b.PreparedTransaction.publish_pending
def pending(self):
    pause('prepared')
    result=publish(self);pause('published');return result
b.PreparedTransaction.publish_pending=pending
replace=b.os.replace;count=0
def forward(stage,target):
    global count
    if count==0:pause('before-first')
    if Path(target).suffix=='.toc':pause('before-toc')
    replace(stage,target);count+=1;pause('after-'+str(count))
b.os.replace=forward
receipt=b._publish_completion_receipt
def completion(*args):pause('receipt-before');return receipt(*args)
b._publish_completion_receipt=completion
rename=b.os.rename
def renamed(stage,target):
    rename(stage,target)
    if Path(target).name=='manifest.json':pause('receipt-published')
b.os.rename=renamed
write=b._write_preparation_artifact
def artifact(path,*args):
    result=write(path,*args)
    if Path(path).name.startswith('.wf-receipt-'):pause('receipt-written')
    return result
b._write_preparation_artifact=artifact
sync=b.os.fsync
def synced(fd):
    sync(fd)
    if list(root.glob('prepare-*/.wf-receipt-*.stage')):pause('receipt-synced')
b.os.fsync=synced
unlink=Path.unlink
def removed(path,*args,**kwargs):
    if path.name==b.PENDING_NAME:pause('marker-before')
    result=unlink(path,*args,**kwargs)
    if path.name==b.PENDING_NAME:pause('marker-after')
    if path.is_relative_to(root) and path.name=='module.lua':pause('cleanup')
    return result
Path.unlink=removed
result=b.execute_transaction(payload,client,['WFStorage','WFProfessions'],root)
raise AssertionError('Boundary not reached: '+str(result))
'''
        retry_code=r'''
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
client,root=map(Path,sys.argv[2:4]);expected=sys.argv[4]
status=b.inspect_pending_transaction(client,root)
assert status['state']==expected,status
if expected=='valid':
    try:b._verify_terminal_destinations(status,'installation')
    except ValueError:
        assert b.recover_pending_transaction(client,root)['state']=='rollback_complete'
        result=b.complete_pending_rollback(client,root)
    else:result=b.complete_pending_installation(client,root)
    assert result['state'] in ('installation_complete','rollback_complete'),result
    assert not result['failures'],result
    print(result['state'])
else:
    assert b.complete_pending_installation(client,root)['state']=='no_pending'
    print('no_pending')
'''
        recovery_code=r'''
import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import install_addons as b
client,root,ready=map(Path,sys.argv[2:5])
unlink=Path.unlink
def removed(path,*args,**kwargs):
    result=unlink(path,*args,**kwargs)
    if path.is_relative_to(client/'Interface/AddOns') and path.name=='module.lua':
        ready.write_text('recovery');time.sleep(60)
    return result
Path.unlink=removed
b.recover_pending_transaction(client,root)
raise AssertionError('Recovery boundary not reached')
'''
        def kill_at_ready(code,args,ready,client):
            child=subprocess.Popen([sys.executable,'-B','-c',code,str(Path(backend.__file__).parent),*map(str,args)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=0x08000000)
            try:
                deadline=time.monotonic()+15
                while not ready.exists():
                    if child.poll() is not None:self.fail(child.communicate(timeout=1)[1])
                    if time.monotonic()>deadline:self.fail('Executor interruption boundary timed out')
                    time.sleep(.02)
                with self.assertRaisesRegex(ValueError,'Another addon installation'):
                    with backend.installation_lock(client):pass
                child.kill();child.communicate(timeout=10)
            finally:
                if child.poll() is None:child.kill();child.communicate(timeout=10)
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                fixture=ExecutorTests();fixture.setUp();ready=fixture.root/'ready'
                try:
                    kill_at_ready(child_code,[fixture.payload,fixture.client,fixture.backups,ready,boundary],ready,fixture.client)
                    expected='none' if boundary in ('prepared','marker-after','cleanup') else 'valid'
                    status=backend.inspect_pending_transaction(fixture.client,fixture.backups)
                    self.assertEqual(status['state'],expected,status)
                    if expected=='valid':
                        fixture.assert_pending_original()
                        # Before a new process resolves it, a second executor
                        # must refuse even ordinary (not abandoned) lock acquisition.
                        before=fixture.snapshot();self.assertEqual(fixture.execute()['state'],'blocked')
                        self.assertEqual(fixture.snapshot(),before)
                    if boundary=='after-3':
                        # Two further terminations while removing independently
                        # recoverable originally absent files, then a fresh retry.
                        for attempt in range(2):
                            recovery_ready=fixture.root/('recovery-ready-'+str(attempt))
                            kill_at_ready(recovery_code,[fixture.client,fixture.backups,recovery_ready],recovery_ready,fixture.client)
                            fixture.assert_pending_original()
                    residual={p:p.read_bytes() for p in fixture.backups.rglob('*') if p.is_file()}
                    done=subprocess.run([sys.executable,'-B','-c',retry_code,str(Path(backend.__file__).parent),
                        str(fixture.client),str(fixture.backups),expected],capture_output=True,text=True,timeout=15,creationflags=0x08000000)
                    self.assertEqual(done.returncode,0,done.stderr)
                    installed=boundary in ('after-6','receipt-before','receipt-written','receipt-synced','receipt-published','marker-before','marker-after','cleanup')
                    if installed:fixture.assert_installed()
                    else:
                        for name,content in fixture.before.items():self.assertEqual((fixture.client/name).read_bytes(),content)
                        for source in fixture.payload.rglob('*'):
                            if source.is_file():
                                name='Interface/AddOns/'+source.relative_to(fixture.payload).as_posix()
                                if name not in fixture.before:self.assertFalse((fixture.client/name).exists())
                    if expected=='none':
                        for p,content in residual.items():self.assertEqual(p.read_bytes(),content)
                    self.assertFalse((fixture.client/backend.PENDING_NAME).exists());fixture.assert_unrelated()
                finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()


if __name__=='__main__':unittest.main()
