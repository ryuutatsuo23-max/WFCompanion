"""Shared service fixtures never discover clients or read actual Companion state."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import install_addons as engine
import addon_installation_service as service
import test_addon_transactions as fixtures


@unittest.skipUnless(os.name=='nt','Service publication uses Windows rename and mutexes')
class ServiceTests(unittest.TestCase):
    snapshot=fixtures.PreparationTests.snapshot

    def setUp(self):
        fixtures.PreparationTests.setUp(self)
        self.state=self.root/'state';self.users=self.state/'AddonBackups';self.users.mkdir(parents=True)
        self.legacy=self.users/'20260101-000000-000000/WFCore/module.lua'
        self.legacy.parent.mkdir(parents=True);self.legacy.write_bytes(b'legacy history')
        self.service=service.AddonInstallationService(self.state)
        self.recovery=engine.production_recovery_root(self.client)

    def install(self):return self.service.install(self.payload,self.client,['WFStorage','WFProfessions'])

    def assert_preserved(self):
        self.assertEqual(self.legacy.read_bytes(),b'legacy history')
        for name in ('Wow.exe','WTF/synthetic.lua','Interface/AddOns/Other/keep.lua'):
            self.assertEqual((self.client/name).read_bytes(),self.before[name])

    def pending_installed(self):
        with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('private synthetic failure')):
            result=self.install()
        self.assertEqual(result.category,'finalization_pending',result)
        self.assertTrue((self.client/engine.PENDING_NAME).exists())
        return result

    def test_common_default_and_explicit_state_across_callers(self):
        with patch.dict(os.environ,LOCALAPPDATA=str(self.root)):
            expected=self.root/'WoWForever/Companion'
            for _caller in ('GUI','CLI','setup'):
                self.assertEqual(service.AddonInstallationService.standard().state,expected)
            self.assertFalse(expected.exists())
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(service.BackupConfigurationError):service.AddonInstallationService.standard()
        for _caller in ('GUI','CLI','setup'):
            self.assertEqual(service.AddonInstallationService(self.state).state,self.state)

    def test_inspection_read_only_then_new_install_no_legacy_fallback(self):
        self.assertEqual(self.service.inspect(self.client).category,'ready')
        self.assertFalse(self.recovery.parent.exists());self.assertEqual(self.snapshot(),self.before)
        with patch.object(engine,'install',side_effect=AssertionError('legacy bypass')),\
             patch.object(engine,'_install_locked',side_effect=AssertionError('legacy bypass')):
            result=self.install()
        self.assertEqual(result.category,'installation_complete',result);self.assertTrue(result.ok)
        with self.assertRaises(TypeError):bool(result)
        saved=next(self.users.glob('transaction-*'))
        self.assertEqual((saved/'WFCore/module.lua').read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(json.loads((saved/'manifest.json').read_bytes())['selected'],['WFCore','WFProfessions','WFStorage'])
        self.assertFalse((self.client/engine.PENDING_NAME).exists())
        self.assertEqual(self.service.inspect(self.client).category,'ready')
        self.assert_preserved()

    def test_restart_completion_and_no_pending_are_explicit(self):
        self.pending_installed()
        code="""
import sys
from addon_installation_service import AddonInstallationService
r=AddonInstallationService(sys.argv[1]).complete(sys.argv[2])
assert r.category=='installation_complete',r
print(r.category)
"""
        child=subprocess.run([sys.executable,'-B','-c',code,str(self.state),str(self.client)],
                             cwd=Path(engine.__file__).parent,capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,0,child.stderr);self.assertIn('installation_complete',child.stdout)
        self.assertEqual(self.service.complete(self.client).category,'no_pending')
        self.assert_preserved()

    def test_missing_changed_unsafe_and_inaccessible_configuration(self):
        for mode in ('missing','changed','denied','malformed','hardlink','junction','stage'):
            with self.subTest(mode=mode):
                fixture=ServiceTests();fixture.setUp()
                try:
                    fixture.pending_installed();before=fixture.snapshot()
                    policy=fixture.recovery/service.POLICY_NAME
                    context=patch.object(service,'POLICY_LIMIT',service.POLICY_LIMIT)
                    selected=fixture.service
                    if mode=='missing':fixture.users.rename(fixture.state/'preserved')
                    elif mode=='changed':
                        other=fixture.root/'other-state';(other/'AddonBackups').mkdir(parents=True)
                        selected=service.AddonInstallationService(other)
                    elif mode=='denied':
                        reader=engine._transaction_directory
                        def denied(path):
                            if Path(path)==fixture.users:raise PermissionError('private account path')
                            return reader(path)
                        context=patch.object(engine,'_transaction_directory',denied)
                    elif mode=='malformed':policy.write_bytes(b'{invalid')
                    elif mode=='hardlink':os.link(policy,fixture.root/'sentinel')
                    elif mode=='junction':
                        import _winapi
                        fixture.users.rename(fixture.state/'preserved')
                        _winapi.CreateJunction(str(fixture.state/'preserved'),str(fixture.users))
                    else:(fixture.recovery/service.POLICY_STAGE).write_bytes(b'partial')
                    with context:result=selected.complete(fixture.client)
                    self.assertEqual(result.category,'backup_unavailable',result)
                    self.assertNotIn(str(fixture.root),result.message+repr(result))
                    self.assertEqual(fixture.snapshot(),before)
                    self.assertTrue((fixture.client/engine.PENDING_NAME).exists())
                    self.assertEqual(next(fixture.recovery.glob('prepare-*/WFCore/module.lua')).read_bytes(),
                                     fixture.before['Interface/AddOns/WFCore/module.lua'])
                finally:
                    if fixture.users.is_junction():fixture.users.rmdir()
                    fixture.doCleanups()

    def test_missing_configuration_never_creates_root_or_installs(self):
        self.users.rename(self.state/'preserved')
        result=self.install()
        self.assertEqual(result.category,'backup_unavailable');self.assertEqual(self.snapshot(),self.before)
        self.assertFalse(self.recovery.exists())

    def test_policy_publication_failures_preserve_state_and_fail_closed(self):
        for point in ('write','publish','after_publish'):
            with self.subTest(point=point):
                fixture=ServiceTests();fixture.setUp()
                writer=engine._write_preparation_artifact;publisher=engine._publish_pending_file
                def write(path,*args):
                    if point=='write' and path.name==service.POLICY_STAGE:raise OSError('write')
                    return writer(path,*args)
                def publish(stage,target,root):
                    if target.name==service.POLICY_NAME:
                        if point=='publish':raise OSError('publication')
                        publisher(stage,target,root);raise OSError('notification')
                    return publisher(stage,target,root)
                try:
                    with patch.object(engine,'_write_preparation_artifact',write),patch.object(engine,'_publish_pending_file',publish):
                        result=fixture.install()
                    self.assertEqual(result.category,'backup_unavailable');self.assertEqual(fixture.snapshot(),fixture.before)
                    self.assertFalse((fixture.client/engine.PENDING_NAME).exists())
                    if point=='publish':self.assertEqual(fixture.install().category,'backup_unavailable')
                    if point=='after_publish':self.assertEqual(fixture.install().category,'installation_complete')
                finally:fixture.doCleanups()

    def test_pending_valid_invalid_and_ambiguous_never_start_install(self):
        for mode in ('valid','invalid','ambiguous'):
            with self.subTest(mode=mode):
                fixture=ServiceTests();fixture.setUp()
                try:
                    fixture.pending_installed()
                    if mode=='invalid':(fixture.client/engine.PENDING_NAME).write_bytes(b'broken')
                    if mode=='ambiguous':fixture.original.write_bytes(b'external')
                    before=fixture.snapshot()
                    with patch.object(engine,'_execute_transaction_locked',side_effect=AssertionError('must block')):
                        for result in (fixture.install(),fixture.service.inspect(fixture.client)):
                            self.assertEqual(result.category,'recovery_pending' if mode=='valid' else 'recovery_incomplete')
                    self.assertEqual(fixture.snapshot(),before)
                finally:fixture.doCleanups()

    def test_recovery_retains_history_and_retry_is_idempotent(self):
        def interrupt(status,client,recovery,identity):
            item=status['record']['files'][0]
            os.replace(client/'Interface/AddOns'/item['stage'],client/'Interface/AddOns'/item['path'])
            raise KeyboardInterrupt()
        with patch.object(engine,'_apply_transaction_files',interrupt):
            with self.assertRaises(KeyboardInterrupt):self.install()
        self.assertEqual(self.service.inspect(self.client).category,'recovery_pending')
        result=service.AddonInstallationService(self.state).rollback(self.client)
        self.assertEqual(result.category,'rollback_complete',result)
        self.assertEqual(self.snapshot(),self.before);self.assert_preserved()
        self.assertEqual(self.service.rollback(self.client).category,'no_pending')

    def test_retained_damage_blocks_completion_and_never_falls_back(self):
        self.pending_installed();saved=next(self.users.glob('transaction-*'))
        (saved/'originals.json').write_bytes(b'changed')
        with patch.object(engine,'install',side_effect=AssertionError('fallback')):
            result=self.service.complete(self.client)
        self.assertEqual(result.category,'finalization_pending');self.assertTrue((self.client/engine.PENDING_NAME).exists())

    def test_executor_results_are_mapped_without_truthy_failures(self):
        for source,expected in (('blocked','blocked'),('rollback_complete','rollback_complete'),
                                ('recovery_pending','recovery_pending'),('finalization_pending','finalization_pending')):
            # Mapping is separate from durable terminal verification; a mocked
            # executor result alone must not establish a completed operation.
            result=self.service._outcome(dict(state=source))
            self.assertEqual(result.category,expected)
            self.assertFalse(result.ok)
        with patch.object(engine,'_execute_transaction_locked',return_value=dict(state='blocked',phase='retained_backup')):
            self.assertEqual(self.install().category,'backup_unavailable')

    def test_same_client_lock_exclusion_and_independent_beta(self):
        peer=self.root/'_classic_beta_';peer.mkdir();(peer/'WowB.exe').touch()
        with engine.installation_lock(self.client):
            self.assertEqual(self.install().category,'busy');self.assertEqual(self.snapshot(),self.before)
            self.assertEqual(self.service.install(self.payload,peer,['WFStorage']).category,'installation_complete')
        self.assertEqual(self.install().category,'installation_complete')
        self.assertNotEqual(engine.production_recovery_root(peer),self.recovery)
        self.assert_preserved()

    def test_stable_alias_and_retargeted_alias_lock_binding(self):
        import _winapi
        alias=self.root/'alias';_winapi.CreateJunction(str(self.client),str(alias))
        try:
            self.assertEqual(self.service.inspect(alias).category,'ready')
            peer=self.root/'_classic_beta_';peer.mkdir();(peer/'WowB.exe').touch()
            lock=engine.installation_lock
            @contextmanager
            def retarget(client):
                with lock(client) as identity:
                    alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
                    yield identity
            with patch.object(engine,'installation_lock',retarget):
                result=self.service.install(self.payload,alias,['WFCore'])
            self.assertEqual(result.category,'blocked');self.assertEqual(self.snapshot(),self.before)
            self.assertFalse((peer/'Interface').exists());self.assertFalse(self.recovery.exists())
        finally:alias.rmdir()

    def test_wrong_lock_identity_and_single_lock_through_executor(self):
        lock=engine.installation_lock
        @contextmanager
        def wrong(client):
            with lock(client) as identity:yield dict(identity,inode=identity['inode']+1)
        with patch.object(engine,'installation_lock',wrong):self.assertEqual(self.install().category,'blocked')
        self.assertEqual(self.snapshot(),self.before)
        apply=engine._apply_transaction_files
        def checked(*args):
            self.assertEqual(self.service.inspect(self.client).category,'busy')
            return apply(*args)
        with patch.object(engine,'_apply_transaction_files',checked):
            self.assertEqual(self.install().category,'installation_complete')

    def test_replaced_backup_directory_and_missing_policy_reject_retry(self):
        self.pending_installed();before=self.snapshot()
        previous=self.state/'preserved';self.users.rename(previous);self.users.mkdir()
        # Copying bytes into another directory does not reestablish its identity.
        import shutil
        for path in previous.iterdir():shutil.copytree(path,self.users/path.name)
        self.assertEqual(self.service.complete(self.client).category,'backup_unavailable')
        self.assertEqual(self.snapshot(),before)
        (self.recovery/service.POLICY_NAME).unlink()  # Synthetic policy loss.
        self.assertEqual(self.service.complete(self.client).category,'backup_unavailable')
        self.assertTrue((self.client/engine.PENDING_NAME).exists())

    def test_actual_replacement_failure_classification_and_recovery_retry(self):
        replace=engine.os.replace;calls=0
        def fail(stage,target):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('replacement')
            return replace(stage,target)
        with patch.object(engine.os,'replace',fail),\
             patch.object(engine,'_recover_pending_locked',side_effect=OSError('recovery')):
            result=self.install()
        self.assertEqual(result.category,'recovery_pending');self.assertFalse(result.ok)
        self.assertTrue((self.client/engine.PENDING_NAME).exists())
        result=self.service.rollback(self.client)
        self.assertEqual(result.category,'rollback_complete');self.assertFalse(result.ok)
        self.assertEqual(self.snapshot(),self.before);self.assert_preserved()

    @contextmanager
    def late_failure(self,mode,observed):
        """Inject only after an actual executor outcome, retaining pre-error bytes."""
        lock=engine.installation_lock;location=engine._production_recovery_location
        outcome=self.service._outcome
        error=OSError('synthetic private path '+str(self.root))
        def capture(raw):
            result=outcome(raw)
            observed.update(result=result,error=error,files=self.all_fixture_bytes())
            return result
        @contextmanager
        def release(client):
            with lock(client) as identity:yield identity
            if mode=='release':raise error
        def postcheck(*args):
            if mode=='postcheck' and 'result' in observed:raise error
            return location(*args)
        with patch.object(self.service,'_outcome',capture),patch.object(engine,'installation_lock',release),\
             patch.object(engine,'_production_recovery_location',postcheck):
            yield

    def all_fixture_bytes(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_recovery_pending_survives_late_exception_and_exact_retry(self):
        for mode in ('release','postcheck'):
            with self.subTest(mode=mode):
                f=ServiceTests();f.setUp()
                try:
                    replace=engine.os.replace;calls=0;observed={}
                    def fail(stage,target):
                        nonlocal calls
                        calls+=1
                        if calls==2:raise OSError('synthetic replacement failure')
                        return replace(stage,target)
                    with f.late_failure(mode,observed),patch.object(engine.os,'replace',fail),\
                         patch.object(engine,'_recover_pending_locked',side_effect=OSError('synthetic rollback failure')):
                        result=f.install()
                    self.assertEqual(result.category,'recovery_pending')
                    self.assertFalse(result.ok)
                    self.assertNotIn('before replacement',result.message)
                    self.assertNotIn(str(f.root),result.message+repr(result))
                    self.assertIs(result._details['operation_result'],observed['result'])
                    self.assertIs(result._details['late_error'],observed['error'])
                    self.assertIn('recovery_error',observed['result']._details)
                    self.assertEqual(f.all_fixture_bytes(),observed['files'])
                    self.assertNotEqual(f.snapshot(),f.before)
                    self.assertEqual(f.service.inspect(f.client).category,'recovery_pending')
                    self.assertEqual(f.service.rollback(f.client).category,'rollback_complete')
                    self.assertEqual(f.snapshot(),f.before);f.assert_preserved()
                    self.assertFalse((f.client/engine.PENDING_NAME).exists())
                finally:f.doCleanups()

    def test_finalization_pending_survives_late_exception_and_completion_retry(self):
        for mode in ('release','postcheck'):
            with self.subTest(mode=mode):
                f=ServiceTests();f.setUp()
                try:
                    observed={}
                    with f.late_failure(mode,observed),\
                         patch.object(engine,'_publish_completion_receipt',side_effect=OSError('synthetic receipt failure')):
                        result=f.install()
                    self.assertEqual(result.category,'finalization_pending');self.assertFalse(result.ok)
                    self.assertIs(result._details['operation_result'],observed['result'])
                    self.assertIs(result._details['late_error'],observed['error'])
                    self.assertEqual(f.all_fixture_bytes(),observed['files'])
                    self.assertTrue((f.client/engine.PENDING_NAME).exists())
                    for path in f.payload.rglob('*'):
                        if path.is_file():
                            self.assertEqual((f.client/'Interface/AddOns'/path.relative_to(f.payload)).read_bytes(),path.read_bytes())
                    self.assertEqual(f.service.complete(f.client).category,'installation_complete')
                    self.assertFalse((f.client/engine.PENDING_NAME).exists());f.assert_preserved()
                finally:f.doCleanups()

    def test_pre_dispatch_exception_and_verified_block_remain_blocked(self):
        with patch.object(engine,'_production_recovery_location',side_effect=RuntimeError('preflight')),\
             patch.object(engine,'_execute_transaction_locked') as execute:
            result=self.install()
            execute.assert_not_called()
        self.assertEqual(result.category,'blocked');self.assertFalse(result.ok)
        self.assertEqual(self.snapshot(),self.before)
        result=self.service.install(self.payload,self.client,['invalid'])
        self.assertEqual(result.category,'blocked');self.assertFalse(result.ok)
        self.assertEqual(self.snapshot(),self.before)

    def test_unreturned_executor_outcome_is_uncertain_even_for_configuration_exception(self):
        for error_type in (RuntimeError,service.BackupConfigurationError):
            with self.subTest(error_type=error_type):
                f=ServiceTests();f.setUp()
                try:
                    execute=engine._execute_transaction_locked
                    def unreturned(*args,**kwargs):
                        # Real installation leaves verified files and pending evidence,
                        # but the caller never receives its authoritative result.
                        with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('receipt')):
                            raw=execute(*args,**kwargs)
                        self.assertEqual(raw['state'],'finalization_pending')
                        raise error_type('synthetic private path '+str(f.root))
                    with patch.object(engine,'_execute_transaction_locked',unreturned):result=f.install()
                    self.assertEqual(result.category,'recovery_incomplete');self.assertFalse(result.ok)
                    self.assertNotIn('before replacement',result.message)
                    self.assertNotIn(str(f.root),result.message+repr(result))
                    self.assertTrue((f.client/engine.PENDING_NAME).exists())
                    self.assertEqual(f.service.complete(f.client).category,'installation_complete')
                    f.assert_preserved()
                finally:f.doCleanups()

    def test_completed_outcomes_with_late_errors_never_report_installation_success(self):
        for rollback in (False,True):
            with self.subTest(rollback=rollback):
                f=ServiceTests();f.setUp()
                try:
                    observed={};replace=engine.os.replace;calls=0
                    def apply(stage,target):
                        nonlocal calls
                        calls+=1
                        if rollback and calls==2:raise OSError('replacement')
                        return replace(stage,target)
                    with f.late_failure('release',observed),patch.object(engine.os,'replace',apply):result=f.install()
                    self.assertEqual(result.category,'finalization_pending');self.assertFalse(result.ok)
                    self.assertEqual(result._details['operation_result'].category,
                                     'rollback_complete' if rollback else 'installation_complete')
                    from addon_operation_status import NAME
                    unchanged=lambda files:{p:raw for p,raw in files.items() if Path(p).name!=NAME}
                    self.assertEqual(unchanged(f.all_fixture_bytes()),unchanged(observed['files']))
                    self.assertEqual(json.loads((f.recovery/NAME).read_bytes())['phase'],'finalized')
                    self.assertTrue(bool(list(f.recovery.glob('.operation-reporting-*'))))
                    self.assertFalse((f.client/engine.PENDING_NAME).exists())
                    if rollback:self.assertEqual(f.snapshot(),f.before)
                    f.assert_preserved()
                finally:f.doCleanups()

    def test_unsafe_policy_symlink_rejected(self):
        self.pending_installed();policy=self.recovery/service.POLICY_NAME
        original=policy.read_bytes();external=self.root/'policy-original';external.write_bytes(original)
        policy.unlink()
        try:policy.symlink_to(external)
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:self.skipTest('Symlinks unavailable: Windows error 1314')
            raise
        self.assertEqual(self.service.complete(self.client).category,'backup_unavailable')
        self.assertEqual(external.read_bytes(),original)
        self.assertTrue((self.client/engine.PENDING_NAME).exists())

    def test_marker_retirement_failure_keeps_evidence_and_explicit_retry(self):
        unlink=Path.unlink
        def fail(path,*args,**kwargs):
            if path.name==engine.PENDING_NAME:raise PermissionError('marker busy')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):result=self.install()
        self.assertEqual(result.category,'finalization_pending');self.assertFalse(result.ok)
        self.assertEqual(next(self.recovery.glob('prepare-*/WFCore/module.lua')).read_bytes(),
                         self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertEqual(self.service.complete(self.client).category,'installation_complete')

    def test_canonical_client_replacement_during_lock_acquisition_is_rejected(self):
        lock=engine.installation_lock
        @contextmanager
        def replace(client):
            with lock(client) as identity:
                client.rename(self.root/'preserved-client');client.mkdir();(client/'Wow.exe').touch()
                yield identity
        with patch.object(engine,'installation_lock',replace):result=self.install()
        self.assertEqual(result.category,'blocked');self.assertFalse(self.recovery.exists())
        self.assertFalse((self.client/'Interface').exists())
        self.assertEqual((self.root/'preserved-client/Interface/AddOns/WFCore/module.lua').read_bytes(),
                         self.before['Interface/AddOns/WFCore/module.lua'])

    def test_terminated_service_fresh_process_rollback(self):
        ready=self.root/'ready'
        code=r'''
import sys,time
from pathlib import Path
import install_addons as b
from addon_installation_service import AddonInstallationService
state,payload,client,ready=map(Path,sys.argv[1:])
replace=b.os.replace
def pause(stage,target):
    replace(stage,target);ready.write_text('ready');time.sleep(60)
b.os.replace=pause
AddonInstallationService(state).install(payload,client,['WFStorage'])
'''
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(self.state),str(self.payload),str(self.client),str(ready)],
                               cwd=Path(engine.__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+25
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(ready.exists())
        finally:
            if child.poll() is None:child.kill()
            child.communicate(timeout=10)
        retry="""
import sys
from addon_installation_service import AddonInstallationService
s=AddonInstallationService(sys.argv[1])
assert s.inspect(sys.argv[2]).category=='recovery_pending'
r=s.rollback(sys.argv[2]);assert r.category=='rollback_complete',r
"""
        fresh=subprocess.run([sys.executable,'-B','-c',retry,str(self.state),str(self.client)],
                             cwd=Path(engine.__file__).parent,capture_output=True,text=True,timeout=30)
        self.assertEqual(fresh.returncode,0,fresh.stderr)
        self.assertEqual(self.snapshot(),self.before);self.assert_preserved()


if __name__=='__main__':unittest.main()
