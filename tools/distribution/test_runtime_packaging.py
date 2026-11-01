"""Static/source-fixture packaging checks; never invoke PyInstaller or ISCC."""
import ast
import builtins
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import ExitStack, redirect_stdout, redirect_stderr

import audit_payload as audit
import build_installer as build


ROOT=Path(__file__).resolve().parents[2]
EXPECTED={
    'install_addons','addon_installation_service','addon_installation_configuration',
    'addon_installation_context','addon_installation_gui','addon_operation_status',
}


class RuntimePackagingTests(unittest.TestCase):
    def fixture(self, root):
        """Exercise the actual audited mapping with only known source files."""
        source=root/'source';payload=root/'payload';source.mkdir();payload.mkdir()
        names=list(audit.ADDON_RUNTIME_SOURCES)
        for name in names:
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/name).read_bytes())
        # These are names only; private/test inputs do not exist or get opened.
        excluded=['User files/secret.lua','tools/distribution/test_addon_setup_handoff.py',
                  'tools/distribution/launcher.py','tools/distribution/private.py']
        with patch.object(audit.subprocess,'check_output',return_value=('\0'.join(names+excluded)+'\0').encode()):
            report=audit.audit(source)
        self.assertEqual({r['path'] for r in report['files']},set(names))
        for row in report['files']:
            destination,raw,_=audit.read_payload_source(source,row['path'],
                expected_identity=row['identity'],expected_sha256=row['sha256'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])
            target=payload/destination
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        return payload

    def test_exact_runtime_inventory_and_restrictive_allowlist(self):
        self.assertEqual(set(audit.DISTRIBUTION_RUNTIME),EXPECTED)
        self.assertEqual(len(audit.ADDON_RUNTIME_SOURCES),7)
        for name in audit.ADDON_RUNTIME_SOURCES:self.assertTrue(audit.allowed(name))
        for name in ('tools/distribution/private.py','tools/distribution/addon_new_unreviewed.py',
                     'tools/distribution/fixtures/addon_configuration_schema1.py','tools/distribution/fixtures/README.md',
                     'tools/distribution/test_addon_installation_cli.py','tools/distribution/build_installer.py',
                     'tools/distribution/addon_installation_cli.py.bak','tools/distribution/../distribution/addon_installation_cli.py',
                     'User files/private.py','tools/qt_preview/state/config.json',
                     'tools/qt_preview/test_addon_recovery_dialog.py','tools/distribution/subdir/addon_installation_cli.py'):
            self.assertFalse(audit.allowed(name),name)
            with self.assertRaises(ValueError):audit.payload_relative_path(name)
        targets=[audit.payload_relative_path(n) for n in audit.ADDON_RUNTIME_SOURCES]
        self.assertEqual(len(targets),len(set(targets)))
        self.assertIn('install_addons.py',targets)  # Preserve legacy frozen import location.
        self.assertIn('tools/qt_preview/addon_recovery_dialog.py',targets)

    def test_audited_source_mapping_and_hidden_imports_both_editions(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload=self.fixture(Path(tmp))
            for public in (False,True):
                names=build.collect_imports(payload,public=public)
                self.assertTrue(EXPECTED <= names)
                self.assertTrue({'PySide6.QtCore','PySide6.QtGui','PySide6.QtWidgets','ctypes','uuid'} <= names)
                self.assertEqual('PySide6.QtMultimedia' in names,not public)
                self.assertFalse(any(n.startswith('test_') for n in names))
            for name in audit.ADDON_RUNTIME_SOURCES:
                target=payload/audit.payload_relative_path(name);raw=target.read_bytes();target.unlink()
                with self.assertRaises(ValueError):build.collect_imports(payload,public=True)
                target.write_bytes(raw)

    def test_transitive_local_imports_are_in_inventory(self):
        # Inspect all lexical imports, including deliberately lazy function imports.
        for source in audit.ADDON_RUNTIME_SOURCES:
            for node in ast.walk(ast.parse((ROOT/source).read_text(encoding='utf-8'))):
                imports=([a.name for a in node.names] if isinstance(node,ast.Import) else
                         [node.module] if isinstance(node,ast.ImportFrom) and node.module else [])
                for name in imports:
                    head=name.split('.')[0]
                    for directory in ('tools/distribution','tools/qt_preview','tools/offline_preview'):
                        candidate=ROOT/directory/(head+'.py')
                        if candidate.is_file():
                            self.assertIn(candidate.relative_to(ROOT).as_posix(),audit.ADDON_RUNTIME_SOURCES,(source,name))

    def test_inactive_staged_sources_import_without_initialization_or_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload=self.fixture(Path(tmp))
            code=r'''
import sys,os,ctypes,importlib
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
os.environ['LOCALAPPDATA']=str(root/'uninitialized-profile')
os.environ['APPDATA']=str(root/'uninitialized-roaming')
def forbidden(*a,**k):raise AssertionError('Unexpected native context initialization')
ctypes.WinDLL=forbidden
def audit(event,args):
    if event in ('os.mkdir','os.remove','os.rmdir','os.rename','os.link','os.symlink','subprocess.Popen','os.system'):
        raise AssertionError('Unexpected import mutation')
    if event=='open' and isinstance(args[2],int) and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
        raise AssertionError('Unexpected write')
sys.addaudithook(audit)
for name in sys.argv[2:]:
    module=importlib.import_module(name)
    assert Path(module.__file__).resolve()==(root/(name+'.py')).resolve()
assert not (root/'uninitialized-profile').exists()
'''
            for first in sorted(EXPECTED):
                names=[first]+sorted(EXPECTED-{first})
                result=subprocess.run([sys.executable,'-I','-B','-c',code,str(payload),*names],
                                      cwd=payload,capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_build_uses_manifest_mapping_and_static_collection(self):
        tree=ast.parse((ROOT/'tools/distribution/build_installer.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        calls=[n for n in ast.walk(main) if isinstance(n,ast.Call)]
        self.assertTrue(any(isinstance(n.func,ast.Name) and n.func.id=='read_payload_source' for n in calls))
        self.assertTrue(any(isinstance(n.func,ast.Name) and n.func.id=='collect_imports' for n in calls))
        self.assertIn("for name in sorted(imports):command+=['--hidden-import',name]",ast.get_source_segment((ROOT/'tools/distribution/build_installer.py').read_text(),main))
        read=next(n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='read_payload_source')
        self.assertEqual({n.arg for n in read.keywords},{'expected_identity','expected_sha256'})

    def source_fixture(self, root, name='tools/distribution/addon_installation_service.py'):
        source=root/'source';source.mkdir();path=source/name
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'value=1\n')
        return source,name,path

    def assert_source_rejected(self, source, name):
        with patch.object(audit.subprocess,'check_output',return_value=(name+'\0').encode()):
            with self.assertRaises(ValueError) as caught:audit.audit(source)
        self.assertIn(name,str(caught.exception));self.assertNotIn(str(source),str(caught.exception))
        with self.assertRaises(ValueError):audit.read_payload_source(source,name)

    @unittest.skipUnless(os.name=='nt','Real Windows hard-link ownership')
    def test_outside_and_inside_hardlinks_rejected_by_audit_and_mapping(self):
        for name in ('tools/distribution/addon_installation_service.py','tools/qt_preview/companion.py','addons/WFCore/Core.lua'):
            for inside in (False,True):
                with self.subTest(name=name,inside=inside),tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);source,name,path=self.source_fixture(root,name)
                    peer=(source if inside else root)/'sentinel.py';peer.write_bytes(path.read_bytes())
                    path.unlink();os.link(peer,path)
                    self.assertEqual(path.stat().st_nlink,2)
                    before=(peer.read_bytes(),peer.stat().st_mtime_ns)
                    self.assert_source_rejected(source,name)
                    self.assertEqual((peer.read_bytes(),peer.stat().st_mtime_ns),before)

    @unittest.skipUnless(os.name=='nt','Real Windows hard-link ownership')
    def test_collector_rejects_required_and_other_python_hardlinks(self):
        for relative in ('addon_installation_service.py','tools/qt_preview/companion.py'):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);payload=self.fixture(root);sentinel=root/'sentinel.py';sentinel.write_bytes(b'value=1\n')
                path=payload/relative;path.parent.mkdir(parents=True,exist_ok=True)
                if path.exists():path.unlink()
                os.link(sentinel,path)
                with self.assertRaises(ValueError) as caught:build.collect_imports(payload)
                self.assertIn(relative,str(caught.exception))
                self.assertEqual(sentinel.read_bytes(),b'value=1\n')

    def test_single_link_read_and_full_synthetic_enumeration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,name,path=self.source_fixture(root)
            destination,raw,identity=audit.read_payload_source(source,name)
            self.assertEqual(destination,'addon_installation_service.py');self.assertEqual(raw,b'value=1\n')
            self.assertEqual(identity['file'][-1],1)
            self.assertEqual(audit.read_source(source,name,expected_identity=identity)[0],raw)
            # Full inventory, not the real checkout or any user directory.
            names=list(audit.ADDON_RUNTIME_SOURCES)+['addons/WFCore/Core.lua','tools/offline_preview/model.py']
            for item in names:
                p=source/item;p.parent.mkdir(parents=True,exist_ok=True)
                if not p.exists():p.write_bytes(b'value=1\n')
            with patch.object(audit.subprocess,'check_output',return_value=('\0'.join(names)+'\0').encode()):
                self.assertEqual({r['path'] for r in audit.audit(source)['files']},set(names))

    def test_missing_source_and_traversal_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp));path.unlink()
            with self.assertRaises(FileNotFoundError):audit.read_payload_source(source,name)
            for invalid in ('../sentinel.py','/sentinel.py','C:/sentinel.py','tools/../sentinel.py','tools\\sentinel.py'):
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):audit.read_source(source,invalid)

    @unittest.skipUnless(os.name=='nt','Real Windows junctions')
    def test_junction_ancestors_and_root_are_rejected(self):
        import _winapi
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();outside=root/'outside';outside.mkdir()
            (outside/'addon_installation_service.py').write_bytes(b'value=1\n')
            (source/'tools').mkdir();link=source/'tools/distribution'
            _winapi.CreateJunction(str(outside),str(link))
            try:self.assert_source_rejected(source,'tools/distribution/addon_installation_service.py')
            finally:link.rmdir()
            alias=root/'alias';_winapi.CreateJunction(str(outside),str(alias))
            try:
                with self.assertRaises(ValueError):audit.read_source(alias,'addon_installation_service.py')
            finally:alias.rmdir()

    def test_symlink_source_is_rejected_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,name,path=self.source_fixture(root);outside=root/'sentinel.py';outside.write_bytes(b'value=1\n')
            path.unlink()
            try:path.symlink_to(outside)
            except OSError as exc:
                if os.name=='nt' and exc.winerror==1314:self.skipTest('Symlinks unavailable: Windows error 1314')
                raise
            self.assert_source_rejected(source,name)

    def test_failed_or_unavailable_handle_identity_and_link_queries_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp));real=os.fstat
            fields=('st_mode','st_dev','st_ino','st_nlink','st_size','st_mtime_ns','st_ctime_ns','st_birthtime_ns','st_file_attributes')
            for field,value in (('st_nlink',None),('st_nlink',0),('st_nlink',2),('st_ino',0),('st_dev',None)):
                def query(fd,field=field,value=value):
                    info=real(fd);data={key:getattr(info,key,None) for key in fields};data[field]=value
                    return SimpleNamespace(**data)
                with self.subTest(field=field,value=value),patch.object(audit.os,'fstat',query):
                    self.assert_source_rejected(source,name)
            with patch.object(audit.os,'fstat',side_effect=OSError('private sentinel')):
                self.assert_source_rejected(source,name)
            with patch.object(Path,'lstat',side_effect=PermissionError('private sentinel')):
                with self.assertRaisesRegex(ValueError,'Unsafe or changed package input'):audit.read_source(source,name)

    @unittest.skipUnless(os.name=='nt','Windows filesystem support gate')
    def test_unverified_windows_filesystem_query_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp))
            with patch.object(audit,'_check_source_filesystem',side_effect=OSError('private sentinel')):
                self.assert_source_rejected(source,name)

    def test_validation_never_imports_the_runtime_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp),'tools/distribution/install_addons.py')
            path.write_bytes(b'raise AssertionError("Do not execute collected source")\n')
            original=builtins.__import__
            def importing(name,*args,**kwargs):
                if name.split('.')[0] in EXPECTED:raise AssertionError('Runtime input imported')
                return original(name,*args,**kwargs)
            with patch.object(builtins,'__import__',importing),patch.object(audit.subprocess,'check_output',return_value=(name+'\0').encode()):
                self.assertEqual(len(audit.audit(source)['files']),1)

    def test_changed_identity_or_contents_between_audit_and_consumption_reject(self):
        for replace in (False,True):
            with self.subTest(replace=replace),tempfile.TemporaryDirectory() as tmp:
                source,name,path=self.source_fixture(Path(tmp))
                with patch.object(audit.subprocess,'check_output',return_value=(name+'\0').encode()):row=audit.audit(source)['files'][0]
                if replace:
                    path.rename(path.with_suffix('.held'));path.write_bytes(b'value=1\n')
                else:path.write_bytes(b'value=changed\n')
                with self.assertRaises(ValueError):audit.read_payload_source(source,name,expected_identity=row['identity'],expected_sha256=row['sha256'])

    @unittest.skipUnless(os.name=='nt','Real Windows hard-link transition')
    def test_link_added_after_audit_or_during_read_rejects(self):
        for during_read in (False,True):
            with self.subTest(during_read=during_read),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source,name,path=self.source_fixture(root);peer=root/'peer.py'
                with patch.object(audit.subprocess,'check_output',return_value=(name+'\0').encode()):row=audit.audit(source)['files'][0]
                real=os.fstat;calls=0
                def query(fd):
                    nonlocal calls
                    calls+=1
                    if calls==2:os.link(path,peer)
                    return real(fd)
                if not during_read:os.link(path,peer)
                with patch.object(audit.os,'fstat',query if during_read else real):
                    with self.assertRaises(ValueError):audit.read_payload_source(source,name,expected_identity=row['identity'],expected_sha256=row['sha256'])
                self.assertEqual(path.stat().st_nlink,2);self.assertEqual(peer.read_bytes(),b'value=1\n')

    def test_source_replaced_between_snapshot_and_open_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp));real=Path.open;armed=True
            def open_source(candidate,*args,**kwargs):
                nonlocal armed
                if candidate==path and armed:
                    armed=False;candidate.rename(candidate.with_suffix('.held'))
                    with real(candidate,'wb') as stream:stream.write(b'value=1\n')
                return real(candidate,*args,**kwargs)
            with patch.object(Path,'open',open_source):
                with self.assertRaises(ValueError):audit.read_payload_source(source,name)

    def test_growing_source_read_is_bounded_to_initial_size_plus_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp));real=Path.open;reads=[];handles=[]
            class GrowingReader:
                def __init__(self,stream):self.stream=stream;handles.append(stream)
                def __enter__(self):return self
                def __exit__(self,*args):self.stream.close()
                def fileno(self):return self.stream.fileno()
                def read(self,size=-1):
                    with real(path,'ab',buffering=0) as writer:writer.write(b'x'*32768)
                    raw=self.stream.read(size);reads.append((size,len(raw)))
                    return raw
            def opening(candidate,*args,**kwargs):
                stream=real(candidate,*args,**kwargs)
                if candidate==path and args==('rb',):
                    self.assertEqual(kwargs.get('buffering'),0)
                    return GrowingReader(stream)
                return stream
            with patch.object(Path,'open',opening):
                with self.assertRaises(ValueError):audit.read_payload_source(source,name)
            self.assertEqual(reads,[(9,9)])
            self.assertTrue(all(stream.closed for stream in handles))
            self.assertEqual(path.stat().st_size,32776)  # Growth is preserved, never staged.

    def test_short_read_and_unexpected_eof_fail_closed(self):
        for returned in (b'',b'value=1'):
            with self.subTest(returned=returned),tempfile.TemporaryDirectory() as tmp:
                source,name,path=self.source_fixture(Path(tmp));real=Path.open
                class ShortReader:
                    def __init__(self,stream):self.stream=stream
                    def __enter__(self):return self
                    def __exit__(self,*args):self.stream.close()
                    def fileno(self):return self.stream.fileno()
                    def read(self,size):return returned
                def opening(candidate,*args,**kwargs):
                    stream=real(candidate,*args,**kwargs)
                    return ShortReader(stream) if candidate==path and args==('rb',) else stream
                with patch.object(Path,'open',opening):
                    with self.assertRaises(ValueError):audit.read_payload_source(source,name)
                self.assertEqual(path.read_bytes(),b'value=1\n')

    def test_same_size_changed_content_rejected_by_audited_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp))
            raw,identity=audit.read_source(source,name);stamp=path.stat()
            path.write_bytes(b'value=2\n');os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            with self.assertRaises(ValueError):
                audit.read_payload_source(source,name,expected_identity=identity,
                                          expected_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(path.read_bytes(),b'value=2\n')

    def test_oversized_source_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,name,path=self.source_fixture(Path(tmp));snapshot=audit._source_snapshot(source,path)
            snapshot['file'][2]=audit.MAX_SOURCE_BYTES+1
            with patch.object(audit,'_source_snapshot',return_value=snapshot),patch.object(Path,'open') as opening:
                with self.assertRaises(ValueError):audit.read_payload_source(source,name)
                opening.assert_not_called()


    def test_required_source_changed_between_collection_checks_rejects(self):
        for change in ('replace','contents','remove'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                payload=self.fixture(Path(tmp));target=payload/'addon_installation_service.py';real=Path.rglob
                def enumerate_sources(root,pattern):
                    if root==payload:
                        if change=='replace':
                            raw=target.read_bytes();target.rename(target.with_suffix('.held'));target.write_bytes(raw)
                        elif change=='contents':target.write_bytes(b'changed=True\n')
                        else:target.unlink()
                    return real(root,pattern)
                with patch.object(Path,'rglob',enumerate_sources):
                    with self.assertRaises(ValueError):build.collect_imports(payload)

    def test_only_addons_page_enables_transaction_route(self):
        launcher=(ROOT/'tools/distribution/launcher.py').read_text()
        self.assertIn('from install_addons import install',launcher)
        self.assertIn("state/'AddonBackups'",launcher)
        installer=(ROOT/'tools/distribution/installer.iss').read_text()
        self.assertIn('PrivilegesRequired=lowest',installer)
        self.assertIn('--install-addons',installer)
        for path in ('tools/distribution/launcher.py','tools/distribution/installer.iss',
                     'tools/qt_preview/companion.py'):
            source=(ROOT/path).read_text(encoding='utf-8')
            for name in ('addon_installation_gui','addon_installation_cli','addon_setup_handoff'):
                self.assertNotIn(name,source)
        source=(ROOT/'tools/qt_preview/addons_page.py').read_text()
        self.assertIn('from addon_installation_gui import GuiAddonTransactions',source)
        self.assertIn('from addon_installation_configuration import InstallationConfiguration',source)
        for name in ('addon_installation_cli','addon_setup_handoff'):
            self.assertNotIn(name,source)
        page=ast.parse(source)
        # No normal Addons action may retain the old install() fallback.
        for node in ast.walk(page):
            if isinstance(node,ast.ImportFrom) and node.module=='install_addons':
                self.assertNotIn('install',[name.name for name in node.names])
        cls=next(n for n in page.body if isinstance(n,ast.ClassDef) and n.name=='AddonsPage')
        init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
        defaults=dict(zip((n.arg for n in init.args.kwonlyargs),init.args.kw_defaults))
        self.assertIsInstance(defaults['transactions'],ast.Name)
        self.assertEqual(defaults['transactions'].id,'_DEFAULT_TRANSACTIONS')


class PublicLayoutTests(unittest.TestCase):
    def test_root_compatibility_import_shares_the_canonical_engine_and_lock_registry(self):
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import install_addons as compatibility
from tools.distribution import install_addons as canonical
from unittest.mock import patch
assert compatibility._install_locks is canonical._install_locks
assert Path(canonical.__file__).resolve() == Path(sys.argv[1], 'tools/distribution/install_addons.py').resolve()
assert compatibility.execute_transaction is canonical.execute_transaction
with patch.object(canonical, 'install', return_value='sentinel') as install:
    assert compatibility.install('payload', 'client', ['WFCore'], 'backup') == 'sentinel'
    assert install.call_args.kwargs == {'check_game': True}
    compatibility.install('payload', 'client', ['WFCore'], 'backup', check_game=False)
    assert install.call_args.kwargs == {'check_game': False}
"""
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(ROOT)],
                                    cwd=tmp, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_current_public_package_members_still_match_the_unchanged_pins(self):
        import install_addons as engine
        pins = (ROOT/'tools/distribution/addon_packages.json').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'addon_packages.json').write_bytes(pins)
            for addon, package in json.loads(pins)['packages'].items():
                for name in package['files']:
                    target = root/'addons'/addon/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT/'addons'/addon/name).read_bytes())
            records = engine.package_metadata(root/'addons', engine.PINNED_ADDONS)
        self.assertEqual(set(records), engine.PINNED_ADDONS)


if __name__ == '__main__':
    unittest.main()
