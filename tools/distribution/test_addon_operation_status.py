"""Durable outcome tests: synthetic clients only, including fresh-process exits."""
from contextlib import contextmanager
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import addon_operation_status as durable
import addon_installation_service as service
import install_addons as engine
import test_addon_installation_service as fixtures


@unittest.skipUnless(os.name == 'nt', 'Windows publication and client mutexes')
class DurableStatusTests(unittest.TestCase):
    setUp = fixtures.ServiceTests.setUp
    snapshot = fixtures.ServiceTests.snapshot
    install = fixtures.ServiceTests.install
    assert_preserved = fixtures.ServiceTests.assert_preserved
    pending_installed = fixtures.ServiceTests.pending_installed

    def record(self):return json.loads((self.recovery / durable.NAME).read_bytes())

    def fingerprint(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def restart(self):return service.AddonInstallationService(self.state)

    def test_reporting_handoff_preserves_newer_attempt_after_termination_or_late_error(self):
        for mode in ('early_terminate', 'terminate', 'late'):
            with self.subTest(mode=mode):
                f=DurableStatusTests();f.setUp();child=None;started=False
                unlink=Path.unlink
                try:
                    def handoff(path,*args,**kwargs):
                        nonlocal child,started
                        if path.name.startswith('.operation-reporting-') and not started:
                            started=True
                            signal=f.root/'retry-holds-lock'
                            child=subprocess.Popen([sys.executable,'-B','-c',HANDOFF,
                                str(f.state),str(f.client),str(signal),mode],
                                cwd=Path(engine.__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                            if mode.endswith('terminate'):
                                deadline=time.monotonic()+30
                                while not signal.exists():
                                    if child.poll() is not None:raise AssertionError(child.communicate())
                                    if time.monotonic()>deadline:raise TimeoutError('Synthetic retry boundary')
                                    time.sleep(.01)
                                with self.assertRaisesRegex(ValueError,'Another addon installation'):
                                    with engine.installation_lock(f.client):pass
                            else:
                                output,error=child.communicate(timeout=30)
                                self.assertEqual(child.returncode,0,error)
                                self.assertEqual(json.loads(output),['finalization_pending',False])
                        return unlink(path,*args,**kwargs)
                    with patch.object(Path,'unlink',handoff):result=f.install()
                    if child is not None and child.poll() is None:
                        child.terminate();child.communicate(timeout=10)
                    self.assertTrue(started)
                    self.assertFalse(result.ok,'Old reporter must not report clean success after a newer retry')
                    self.assertTrue(list(f.recovery.glob('.operation-reporting-*')))
                    inspected=subprocess.run([sys.executable,'-B','-c',INSPECT,str(f.state),str(f.client)],
                        cwd=Path(engine.__file__).parent,capture_output=True,text=True,timeout=30)
                    self.assertEqual(inspected.returncode,0,inspected.stderr)
                    self.assertNotIn('"ready"',inspected.stdout)
                    self.assertFalse(f.install().ok)
                    self.assertTrue(f.restart().complete(f.client).ok)
                    self.assertFalse(list(f.recovery.glob('.operation-reporting-*')))
                    f.assert_preserved()
                finally:
                    if child is not None and child.poll() is None:child.terminate();child.communicate(timeout=10)
                    f.doCleanups()

    def test_orphan_reporting_marker_blocks_without_status_or_witness(self):
        lock=engine.installation_lock
        @contextmanager
        def late(client):
            with lock(client) as identity:yield identity
            raise OSError('synthetic late failure')
        with patch.object(engine,'installation_lock',late):self.assertFalse(self.install().ok)
        (self.recovery/durable.NAME).unlink();(self.recovery/durable.KNOWN).unlink()
        before=self.fingerprint()
        self.assertNotEqual(self.restart().inspect(self.client).category,'ready')
        self.assertFalse(self.install().ok)
        self.assertEqual(before,self.fingerprint())
        self.assertTrue(list(self.recovery.glob('.operation-reporting-*')))
        self.assert_preserved()

    def leave_reporting_pending(self, operation=None):
        lock=engine.installation_lock
        @contextmanager
        def late(client):
            with lock(client) as identity:yield identity
            raise OSError('synthetic release error')
        with patch.object(engine,'installation_lock',late):
            result=(operation or self.install)()
        self.assertEqual(result.category,'finalization_pending');self.assertFalse(result.ok)
        return next(self.recovery.glob('.operation-reporting-*'))

    def test_confirmed_reporting_retry_resolves_both_outcomes_without_rewriting_addons(self):
        for rollback in (False, True):
            with self.subTest(rollback=rollback):
                f=DurableStatusTests();f.setUp()
                try:
                    if rollback:f.pending_installed()
                    f.leave_reporting_pending((lambda:f.restart().rollback(f.client)) if rollback else None)
                    before=f.fingerprint()
                    advice=f.restart().pending_summary(f.client)
                    self.assertEqual(before,f.fingerprint())
                    self.assertTrue(advice.may_report);self.assertFalse(advice.manual_review)
                    self.assertFalse(advice.may_complete);self.assertFalse(advice.may_rollback)
                    client_before=f.snapshot()
                    with patch.object(engine,'_execute_transaction_locked',side_effect=AssertionError('Reinstall')),\
                         patch.object(engine,'_recover_pending_locked',side_effect=AssertionError('Restore')):
                        result=f.restart().finish_reporting(f.client,expected_reporting=advice.reporting_key)
                    self.assertEqual(result.category,('rollback' if rollback else 'installation')+'_complete')
                    self.assertFalse(result.summary.late_error);self.assertEqual(f.snapshot(),client_before)
                    self.assertFalse(f.restart().pending_summary(f.client).may_report)
                    self.assertFalse(list(f.recovery.glob('.operation-reporting-*')))
                    before=f.fingerprint()
                    self.assertFalse(f.restart().finish_reporting(f.client,expected_reporting=advice.reporting_key).ok)
                    self.assertEqual(before,f.fingerprint());f.assert_preserved()
                finally:f.doCleanups()

    def test_reporting_requires_exact_confirmation_and_never_resolves_new_attempt(self):
        self.leave_reporting_pending()
        advice=self.restart().pending_summary(self.client)
        for key in (None,(),('different',)):
            before=self.fingerprint()
            self.assertFalse(self.restart().finish_reporting(self.client,expected_reporting=key).ok)
            self.assertEqual(before,self.fingerprint())
        # A newer reporting attempt for the SAME transaction also needs new consent.
        self.leave_reporting_pending(lambda:self.restart().complete(self.client))
        self.assertNotEqual(advice.reporting_key,self.restart().pending_summary(self.client).reporting_key)
        before=self.fingerprint()
        self.assertFalse(self.restart().finish_reporting(self.client,expected_reporting=advice.reporting_key).ok)
        self.assertEqual(before,self.fingerprint())

    def test_reporting_never_substitutes_for_pending_recovery(self):
        self.pending_installed();before=self.fingerprint()
        advice=self.restart().pending_summary(self.client)
        self.assertFalse(advice.may_report);self.assertIsNone(advice.reporting_key)
        self.assertFalse(self.restart().finish_reporting(self.client,expected_reporting=advice.transaction_key).ok)
        self.assertEqual(before,self.fingerprint())

    def test_reporting_rechecks_changed_bytes_and_residual_cleanup_before_writing(self):
        self.leave_reporting_pending();advice=self.restart().pending_summary(self.client)
        confirmed=advice.reporting_key
        original=self.original.read_bytes();self.original.write_bytes(b'changed synthetic addon')
        before=self.fingerprint()
        self.assertFalse(self.restart().pending_summary(self.client).may_report)
        self.assertFalse(self.restart().finish_reporting(self.client,expected_reporting=advice.reporting_key).ok)
        self.assertEqual(before,self.fingerprint())
        self.original.write_bytes(original)
        directory=self.recovery/('prepare-'+self.record()['transaction']['id'])
        (directory/'unresolved-evidence').write_bytes(b'preserve')
        before=self.fingerprint();advice=self.restart().pending_summary(self.client)
        self.assertEqual(advice.pending,'unresolved');self.assertTrue(advice.manual_review)
        self.assertFalse(advice.may_report);self.assertIsNone(advice.reporting_key)
        self.assertFalse(self.restart().finish_reporting(self.client,expected_reporting=confirmed).ok)
        self.assertEqual(before,self.fingerprint())

    def test_reporting_advice_rejects_failed_lock_release(self):
        self.leave_reporting_pending();real_lock=engine.installation_lock
        @contextmanager
        def late(client):
            with real_lock(client) as identity:yield identity
            raise OSError('synthetic release failure')
        before=self.fingerprint()
        with patch.object(engine,'installation_lock',late):advice=self.restart().pending_summary(self.client)
        self.assertFalse(advice.may_report);self.assertIsNone(advice.reporting_key)
        self.assertEqual(advice.inspection,'unavailable');self.assertEqual(before,self.fingerprint())

    def test_reporting_preparation_and_publication_changes_preserve_evidence_then_retry(self):
        for boundary in ('attempt', 'publication'):
            for changed in ('installed', 'restored', 'backup_index'):
                with self.subTest(boundary=boundary,changed=changed):
                    f=DurableStatusTests();f.setUp()
                    try:
                        rollback=changed=='restored'
                        if rollback:
                            f.pending_installed()
                            old=f.leave_reporting_pending(lambda:f.restart().rollback(f.client))
                        else:old=f.leave_reporting_pending()
                        target=next(f.users.glob('transaction-*/originals.json')) if changed=='backup_index' else f.original
                        expected=target.read_bytes();old_bytes=old.read_bytes();injected=False
                        writer=engine._write_preparation_artifact;replace=engine.os.replace
                        def change():
                            nonlocal injected
                            injected=True;target.write_bytes(b'external synthetic conflict')
                        def writing(path,*args):
                            result=writer(path,*args)
                            if boundary=='attempt' and path.name.startswith(durable.REPORT_PREFIX):change()
                            return result
                        def publishing(stage,path):
                            result=replace(stage,path)
                            if boundary=='publication' and Path(path).name==durable.NAME:change()
                            return result
                        operation=lambda:(f.restart().rollback if rollback else f.restart().complete)(f.client)
                        with patch.object(engine,'_write_preparation_artifact',writing),patch.object(engine.os,'replace',publishing):
                            result=operation()
                        self.assertTrue(injected)
                        self.assertFalse(result.ok)
                        self.assertNotIn(result.category,('installation_complete','rollback_complete'))
                        self.assertEqual(old.read_bytes(),old_bytes)
                        self.assertGreaterEqual(len(list(f.recovery.glob('.operation-reporting-*'))),2)
                        self.assertEqual(target.read_bytes(),b'external synthetic conflict')
                        self.assertEqual(f.record()['phase'],'finalized')
                        before=f.fingerprint()
                        self.assertNotEqual(f.restart().inspect(f.client).category,'ready')
                        self.assertFalse(f.install().ok);self.assertEqual(before,f.fingerprint())
                        # Only the synthetic external actor resolves its own conflict.
                        target.write_bytes(expected)
                        result=operation()
                        self.assertEqual(result.category,'rollback_complete' if rollback else 'installation_complete')
                        self.assertEqual(result.ok,not rollback)
                        self.assertFalse(list(f.recovery.glob('.operation-reporting-*')))
                        if rollback:self.assertEqual(f.snapshot(),f.before)
                        f.assert_preserved()
                    finally:f.doCleanups()

    def test_repeated_attempts_have_distinct_ownership_and_preserve_backup_history(self):
        seen=set();current=self.leave_reporting_pending()
        retained={p.relative_to(self.users):p.read_bytes() for p in self.users.rglob('*') if p.is_file()}
        for _ in range(3):
            value=json.loads(current.read_bytes())
            self.assertEqual(value['schema'],2);self.assertNotIn(value['attempt'],seen)
            seen.add(value['attempt'])
            self.assertEqual(self.restart().inspect(self.client).category,'finalization_pending')
            previous=current
            current=self.leave_reporting_pending(lambda:self.restart().complete(self.client))
            self.assertNotEqual(current,previous);self.assertFalse(previous.exists())
            self.assertEqual(len(list(self.recovery.glob('.operation-reporting-*'))),1)
        self.assertTrue(self.restart().complete(self.client).ok)
        self.assertFalse(list(self.recovery.glob('.operation-reporting-*')))
        self.assertEqual(retained,{p.relative_to(self.users):p.read_bytes() for p in self.users.rglob('*') if p.is_file()})
        self.assert_preserved()

    def test_reporting_retry_failures_preserve_discoverable_evidence(self):
        for point in ('marker_write','marker_sync','status_publish','terminal_verify','older_cleanup','own_cleanup'):
            with self.subTest(point=point):
                f=DurableStatusTests();f.setUp();injected=False
                try:
                    old=f.leave_reporting_pending();old_bytes=old.read_bytes();installed=f.original.read_bytes()
                    writer=engine._write_preparation_artifact;replace=engine.os.replace
                    verify=durable.OperationStatus.verify_terminal;unlink=Path.unlink
                    def writing(path,*args):
                        nonlocal injected
                        if path.name.startswith(durable.REPORT_PREFIX):
                            if point=='marker_write':
                                injected=True;path.write_bytes(b'{partial');raise OSError('synthetic write failure')
                            if point=='marker_sync':
                                injected=True
                                with patch.object(engine.os,'fsync',side_effect=OSError('synthetic sync failure')):
                                    return writer(path,*args)
                        return writer(path,*args)
                    def publishing(stage,path):
                        nonlocal injected
                        if point=='status_publish' and Path(path).name==durable.NAME:
                            injected=True;raise OSError('synthetic publication failure')
                        return replace(stage,path)
                    def verifying(record,users):
                        nonlocal injected
                        verify(record,users)
                        if point=='terminal_verify' and record.attempt is not None and record.document['phase']=='finalized':
                            injected=True;raise OSError('synthetic content read failure')
                    def removing(path,*args,**kwargs):
                        nonlocal injected
                        if (point=='older_cleanup' and path==old or point=='own_cleanup'
                                and path!=old and path.name.startswith(durable.REPORT_PREFIX)):
                            injected=True;raise OSError('synthetic cleanup failure')
                        return unlink(path,*args,**kwargs)
                    with patch.object(engine,'_write_preparation_artifact',writing),\
                         patch.object(engine.os,'replace',publishing),\
                         patch.object(durable.OperationStatus,'verify_terminal',verifying),patch.object(Path,'unlink',removing):
                        result=f.restart().complete(f.client)
                    self.assertTrue(injected);self.assertFalse(result.ok)
                    self.assertNotEqual(result.category,'installation_complete')
                    if point!='own_cleanup':self.assertEqual(old.read_bytes(),old_bytes)
                    self.assertTrue(list(f.recovery.glob('.operation-reporting-*')))
                    self.assertEqual(f.original.read_bytes(),installed)
                    before=f.fingerprint()
                    self.assertNotEqual(f.restart().inspect(f.client).category,'ready')
                    self.assertFalse(f.install().ok);self.assertEqual(before,f.fingerprint())
                    f.assert_preserved()
                finally:f.doCleanups()

    def test_reporting_rechecks_policy_after_publication_without_retiring_markers(self):
        old=self.leave_reporting_pending();old_bytes=old.read_bytes()
        policy=next(self.recovery.glob('*policy*.json'));expected=policy.read_bytes()
        replace=engine.os.replace;injected=False
        def publishing(stage,path):
            nonlocal injected
            result=replace(stage,path)
            if Path(path).name==durable.NAME:
                injected=True;policy.write_bytes(b'changed policy')
            return result
        with patch.object(engine.os,'replace',publishing):result=self.restart().complete(self.client)
        self.assertTrue(injected);self.assertFalse(result.ok)
        self.assertEqual(old.read_bytes(),old_bytes)
        self.assertEqual(len(list(self.recovery.glob('.operation-reporting-*'))),2)
        self.assertEqual(policy.read_bytes(),b'changed policy')
        policy.write_bytes(expected)  # Explicit synthetic conflict resolution.
        self.assertTrue(self.restart().complete(self.client).ok)
        self.assert_preserved()

    def test_reporting_rechecks_required_absence_and_contents_after_lock_exit(self):
        for absent in (True,False):
            with self.subTest(absent=absent):
                f=DurableStatusTests();f.setUp()
                try:
                    if absent:
                        f.pending_installed()
                        old=f.leave_reporting_pending(lambda:f.restart().rollback(f.client))
                        item=next(item for item in f.record()['transaction']['files'] if item['original'] is None)
                        target=f.client/'Interface/AddOns'/item['path'];expected=None
                    else:
                        old=f.leave_reporting_pending();target=f.original;expected=target.read_bytes()
                    replace=engine.os.replace;lock=engine.installation_lock
                    def publishing(stage,path):
                        result=replace(stage,path)
                        if absent and Path(path).name==durable.NAME:target.write_bytes(b'external conflict')
                        return result
                    @contextmanager
                    def releasing(client):
                        with lock(client) as identity:yield identity
                        if not absent:target.write_bytes(b'external conflict')
                    operation=lambda:(f.restart().rollback if absent else f.restart().complete)(f.client)
                    with patch.object(engine.os,'replace',publishing),patch.object(engine,'installation_lock',releasing):
                        result=operation()
                    self.assertFalse(result.ok)
                    self.assertNotIn(result.category,('installation_complete','rollback_complete'))
                    self.assertEqual(target.read_bytes(),b'external conflict')
                    self.assertTrue(list(f.recovery.glob('.operation-reporting-*')))
                    if absent:self.assertTrue(old.exists());target.unlink()
                    else:target.write_bytes(expected)
                    result=operation()
                    self.assertEqual(result.category,'rollback_complete' if absent else 'installation_complete')
                    self.assertFalse(list(f.recovery.glob('.operation-reporting-*')))
                    f.assert_preserved()
                finally:f.doCleanups()

    def test_legacy_reporting_marker_is_detected_and_only_explicitly_resolved(self):
        current=self.leave_reporting_pending();record=self.record()
        old=self.recovery/('.operation-reporting-'+record['transaction']['id']+'.json')
        old.write_bytes(durable.encode(dict(client=record['client'],policy=record['policy'],transaction=record['transaction_digest'])))
        current.unlink()
        before=self.fingerprint()
        self.assertEqual(self.restart().inspect(self.client).category,'finalization_pending')
        self.assertFalse(self.install().ok);self.assertEqual(before,self.fingerprint())
        # Even the previous transaction-only format is detectable without status.
        status=(self.recovery/durable.NAME).read_bytes();known=(self.recovery/durable.KNOWN).read_bytes()
        (self.recovery/durable.NAME).unlink();(self.recovery/durable.KNOWN).unlink()
        before=self.fingerprint()
        self.assertNotEqual(self.restart().inspect(self.client).category,'ready')
        self.assertFalse(self.install().ok);self.assertEqual(before,self.fingerprint())
        (self.recovery/durable.NAME).write_bytes(status);(self.recovery/durable.KNOWN).write_bytes(known)
        self.assertTrue(self.restart().complete(self.client).ok)
        self.assertFalse(old.exists());self.assert_preserved()

    def test_invalid_reporting_entries_are_preserved_and_block_read_only(self):
        for mode in ('malformed','schema','extra','attempt','transaction','name','case','hardlink','directory','junction'):
            with self.subTest(mode=mode):
                f=DurableStatusTests();f.setUp();marker=None
                try:
                    marker=f.leave_reporting_pending();value=json.loads(marker.read_bytes())
                    if mode=='malformed':marker.write_bytes(b'{')
                    elif mode in ('schema','extra','attempt','transaction'):
                        if mode=='schema':value['schema']=99
                        elif mode=='extra':value['unexpected']=True
                        elif mode=='attempt':value['attempt']='0'*32
                        else:value['transaction']['sha256']='0'*64
                        marker.write_bytes(durable.encode(value))
                    elif mode in ('name','case'):
                        name='.operation-reporting-unexpected.json' if mode=='name' else marker.name.upper()
                        renamed=marker.with_name(name);marker.rename(renamed);marker=renamed
                    elif mode=='hardlink':os.link(marker,f.root/'external-sentinel')
                    else:
                        marker.unlink()
                        if mode=='directory':marker.mkdir()
                        else:
                            target=f.root/'external';target.mkdir();(target/'sentinel').write_bytes(b'unchanged')
                            process=subprocess.run(['cmd','/c','mklink','/J',str(marker),str(target)],capture_output=True)
                            self.assertEqual(process.returncode,0)
                    before=f.fingerprint()
                    self.assertNotEqual(f.restart().inspect(f.client).category,'ready')
                    self.assertFalse(f.install().ok)
                    self.assertEqual(before,f.fingerprint());f.assert_preserved()
                finally:
                    if marker is not None and marker.is_junction():marker.rmdir()
                    f.doCleanups()

    def test_reporting_enumeration_is_bounded_and_errors_do_not_authorize_install(self):
        self.leave_reporting_pending();before=self.fingerprint()
        for limit in ('MAX_ROOT_ENTRIES','MAX_REPORTS','REPORT_LIMIT'):
            with self.subTest(limit=limit),patch.object(durable,limit,0):
                self.assertNotEqual(self.restart().inspect(self.client).category,'ready')
                self.assertFalse(self.install().ok)
        self.assertEqual(before,self.fingerprint())

    def test_symlinked_reporting_marker_is_rejected_when_supported(self):
        marker=self.leave_reporting_pending();external=self.root/'external-marker'
        external.write_bytes(marker.read_bytes());marker.unlink()
        try:marker.symlink_to(external)
        except OSError as exc:self.skipTest(f'Symlinks unavailable: Windows error {exc.winerror}')
        before=self.fingerprint()
        self.assertNotEqual(self.restart().inspect(self.client).category,'ready')
        self.assertFalse(self.install().ok);self.assertEqual(before,self.fingerprint())

    def test_changed_own_marker_during_reporting_is_not_deleted(self):
        read=durable.OperationStatus.read;report=durable.OperationStatus.reported;reporting=False
        def start(record):
            nonlocal reporting
            reporting=True
            return report(record)
        def change(record,name):
            result=read(record,name)
            if reporting and name==durable.STAGE:record.fence_path().write_bytes(b'external marker')
            return result
        with patch.object(durable.OperationStatus,'reported',start),patch.object(durable.OperationStatus,'read',change):
            result=self.install()
        self.assertFalse(result.ok)
        marker=next(self.recovery.glob('.operation-reporting-*'))
        self.assertEqual(marker.read_bytes(),b'external marker')
        before=self.fingerprint()
        self.assertNotEqual(self.restart().inspect(self.client).category,'ready')
        self.assertEqual(before,self.fingerprint())

    def test_unresolved_forever_does_not_block_independent_beta(self):
        beta=self.root/'_classic_beta_';shutil.copytree(self.client,beta)
        marker=self.leave_reporting_pending();before=marker.read_bytes()
        result=self.service.install(self.payload,beta,['WFStorage','WFProfessions'])
        self.assertTrue(result.ok)
        self.assertEqual(marker.read_bytes(),before)
        self.assertEqual(self.service.inspect(self.client).category,'finalization_pending')
        self.assertEqual(self.service.inspect(beta).category,'ready')
        self.assertTrue(self.service.complete(self.client).ok)
        self.assertEqual(self.service.inspect(beta).category,'ready');self.assert_preserved()

    def test_success_retains_bounded_record_and_readonly_inspection(self):
        self.assertTrue(self.install().ok)
        self.assertEqual(self.record()['phase'], 'finalized')
        self.assertEqual(self.record()['outcome'], 'installation')
        self.assertFalse(bool(list(self.recovery.glob('.operation-reporting-*'))))
        before = self.fingerprint()
        self.assertEqual(self.restart().inspect(self.client).category, 'ready')
        advice = self.restart().pending_summary(self.client)
        self.assertEqual(advice.verified_outcome, 'installation')
        self.assertEqual(before, self.fingerprint())
        first = self.record()['transaction']['id']
        self.assertTrue(self.install().ok)
        self.assertNotEqual(self.record()['transaction']['id'], first)
        self.assertEqual(len(list(self.recovery.glob('*operation*'))), 2)
        self.assert_preserved()

    def test_late_release_preserves_terminal_outcome_and_explicit_retry(self):
        for rollback in (False, True):
            with self.subTest(rollback=rollback):
                f=DurableStatusTests();f.setUp()
                real_lock=engine.installation_lock;replace=engine.os.replace;count=0
                @contextmanager
                def late(client):
                    with real_lock(client) as identity:yield identity
                    raise OSError('private diagnostic sentinel')
                def fail(stage,target):
                    nonlocal count
                    if Path(stage).suffix=='.stage' and '.wf-' in Path(stage).name:
                        count+=1
                        if rollback and count==2:raise OSError('replacement')
                    return replace(stage,target)
                try:
                    with patch.object(engine,'installation_lock',late),patch.object(engine.os,'replace',fail):
                        result=f.install()
                    self.assertFalse(result.ok)
                    outcome='rollback' if rollback else 'installation'
                    self.assertEqual(result.summary.verified_outcome,outcome)
                    self.assertEqual(f.record()['outcome'],outcome)
                    self.assertTrue(bool(list(f.recovery.glob('.operation-reporting-*'))))
                    self.assertFalse((f.client/engine.PENDING_NAME).exists())
                    before=f.fingerprint()
                    result=f.restart().inspect(f.client)
                    self.assertEqual(result.category,'finalization_pending')
                    self.assertEqual(result.summary.verified_outcome,outcome)
                    self.assertEqual(before,f.fingerprint())
                    self.assertFalse(f.install().ok)
                    result=(f.restart().rollback if rollback else f.restart().complete)(f.client)
                    self.assertEqual(result.category,outcome+'_complete')
                    if rollback:self.assertEqual(f.snapshot(),f.before)
                    self.assertFalse(bool(list(f.recovery.glob('.operation-reporting-*'))));f.assert_preserved()
                finally:f.doCleanups()

    def test_postcheck_after_verified_cleanup_can_be_explicitly_completed(self):
        outcome=self.service._outcome;location=engine._production_recovery_location;returned=False
        def capture(raw):
            nonlocal returned
            result=outcome(raw);returned=True;return result
        def postcheck(*args):
            if returned:raise RuntimeError('private postcheck diagnostic')
            return location(*args)
        with patch.object(self.service,'_outcome',capture),patch.object(engine,'_production_recovery_location',postcheck):
            result=self.install()
        self.assertFalse(result.ok)
        self.assertEqual(result.summary.verified_outcome,'installation')
        self.assertEqual(self.record()['phase'],'terminal')
        self.assertFalse((self.client/engine.PENDING_NAME).exists())
        before=self.fingerprint()
        self.assertEqual(self.restart().inspect(self.client).category,'finalization_pending')
        self.assertEqual(before,self.fingerprint())
        advice=self.restart().pending_summary(self.client)
        self.assertTrue(advice.may_report);self.assertEqual(advice.finalization,'terminal')
        self.assertTrue(self.restart().finish_reporting(self.client,expected_reporting=advice.reporting_key).ok)
        self.assertEqual(self.record()['phase'],'finalized');self.assert_preserved()

    def test_publication_faults_never_replace_destinations(self):
        for point in ('write','sync','publish','collision','verify'):
            with self.subTest(point=point):
                f=DurableStatusTests();f.setUp();writer=engine._write_preparation_artifact
                publisher=engine._publish_pending_file
                def write(path,*args):
                    if path.name==durable.STAGE:
                        if point=='write':
                            path.write_bytes(b'{partial');raise OSError('write')
                        if point=='sync':
                            with patch.object(engine.os,'fsync',side_effect=OSError('sync')):return writer(path,*args)
                        if point=='collision':path.write_bytes(b'external')
                    result=writer(path,*args)
                    if point=='verify' and path.name==durable.STAGE:path.write_bytes(b'external')
                    return result
                def publish(stage,target,root):
                    if point=='publish' and target.name==durable.NAME:raise OSError('publication')
                    return publisher(stage,target,root)
                try:
                    with patch.object(engine,'_write_preparation_artifact',write),patch.object(engine,'_publish_pending_file',publish):
                        self.assertFalse(f.install().ok)
                    # Stages/marker may exist, but no managed destination changed.
                    for path,raw in f.before.items():self.assertEqual((f.client/path).read_bytes(),raw)
                    self.assertTrue((f.client/engine.PENDING_NAME).exists())
                    self.assertEqual(next(f.recovery.glob('prepare-*/WFCore/module.lua')).read_bytes(),
                                     f.before['Interface/AddOns/WFCore/module.lua'])
                    before=f.fingerprint();self.assertFalse(f.install().ok)
                    self.assertEqual(before,f.fingerprint());f.assert_preserved()
                finally:f.doCleanups()

    def test_missing_corrupt_or_conflicting_records_fail_closed(self):
        for point in ('missing_status','bad_status','schema','id','policy','missing_marker','bad_marker','changed_original'):
            with self.subTest(point=point):
                f=DurableStatusTests();f.setUp()
                try:
                    f.pending_installed();path=f.recovery/durable.NAME
                    if point=='missing_status':path.unlink()
                    elif point=='bad_status':path.write_bytes(b'{')
                    elif point in ('schema','id','policy'):
                        value=f.record()
                        if point=='schema':value['schema']=99
                        elif point=='id':value['transaction']['id']='a'*32
                        else:value['policy']['sha256']='a'*64
                        path.write_bytes(durable.encode(value))
                    elif point=='missing_marker':(f.client/engine.PENDING_NAME).unlink()
                    elif point=='bad_marker':(f.client/engine.PENDING_NAME).write_bytes(b'{')
                    else:f.original.write_bytes(b'external')
                    before=f.fingerprint()
                    self.assertFalse(f.restart().inspect(f.client).ok)
                    self.assertFalse(f.restart().complete(f.client).ok)
                    self.assertFalse(f.install().ok)
                    self.assertEqual(before,f.fingerprint());f.assert_preserved()
                finally:f.doCleanups()

    def test_external_modification_during_terminal_status_write_preserved(self):
        writer=engine._write_preparation_artifact
        def changed(path,*args):
            result=writer(path,*args)
            if path.name==durable.STAGE and b'"phase":"terminal"' in args[1]:
                (self.recovery/durable.NAME).write_bytes(b'external status')
            return result
        with patch.object(engine,'_write_preparation_artifact',changed):result=self.install()
        self.assertFalse(result.ok)
        self.assertEqual((self.recovery/durable.NAME).read_bytes(),b'external status')
        self.assertTrue((self.client/engine.PENDING_NAME).exists())
        self.assertTrue(list(self.recovery.glob('prepare-*/WFCore/module.lua')))

    def test_pre_status_pending_can_be_explicitly_adopted(self):
        # Simulate a transaction produced by the older service under its policy.
        with patch.object(durable.OperationStatus,'begin'),patch.object(durable.OperationStatus,'terminal'),\
             patch.object(engine,'_publish_completion_receipt',side_effect=OSError('receipt')):
            self.assertFalse(self.install().ok)
        self.assertFalse((self.recovery/durable.NAME).exists())
        self.assertTrue(self.restart().complete(self.client).ok)
        self.assertEqual(self.record()['phase'],'finalized')

    def test_next_pending_publication_crash_preserves_previous_verified_status(self):
        self.assertTrue(self.install().ok)
        previous=self.snapshot();old=self.record()['transaction']['id']
        publish=engine.PreparedTransaction.publish_pending
        def interrupted(prepared):
            publish(prepared);raise KeyboardInterrupt()
        with patch.object(engine.PreparedTransaction,'publish_pending',interrupted):
            with self.assertRaises(KeyboardInterrupt):self.install()
        self.assertEqual(self.record()['transaction']['id'],old)
        self.assertEqual(self.restart().inspect(self.client).category,'recovery_pending')
        self.assertEqual(self.restart().rollback(self.client).category,'rollback_complete')
        self.assertNotEqual(self.record()['transaction']['id'],old)
        self.assertEqual(self.snapshot(),previous)

    def test_repeated_recovery_interruptions_keep_original_copies(self):
        self.pending_installed()
        replace=engine.os.replace;unlink=Path.unlink
        def interrupted_replace(stage,target):
            result=replace(stage,target)
            if Path(stage).name.startswith('.wf-restore-'):raise KeyboardInterrupt()
            return result
        with patch.object(engine.os,'replace',interrupted_replace):
            with self.assertRaises(KeyboardInterrupt):self.service.rollback(self.client)
        def interrupted_remove(path,*args,**kwargs):
            result=unlink(path,*args,**kwargs)
            if path.suffix=='.toc':raise KeyboardInterrupt()
            return result
        # The first reverse-order rollback may already have removed all TOCs;
        # use a fresh installed pending transaction for the deletion boundary.
        self.assertEqual(self.restart().rollback(self.client).category,'rollback_complete')
        self.assertEqual(self.snapshot(),self.before)
        self.pending_installed()
        with patch.object(Path,'unlink',interrupted_remove):
            with self.assertRaises(KeyboardInterrupt):self.service.rollback(self.client)
        self.assertTrue((self.client/engine.PENDING_NAME).exists())
        self.assertEqual(self.restart().rollback(self.client).category,'rollback_complete')
        self.assertEqual(self.snapshot(),self.before);self.assert_preserved()

    def test_retirement_cleanup_failure_keeps_durable_warning_without_marker(self):
        with patch.object(engine,'_retire_verified_artifacts',return_value=[(None,OSError('cleanup'))]):
            result=self.install()
        self.assertFalse(result.ok)
        self.assertEqual(self.record()['phase'],'terminal')
        self.assertFalse((self.client/engine.PENDING_NAME).exists())
        before=self.fingerprint()
        inspected=self.restart().inspect(self.client)
        self.assertEqual(inspected.category,'finalization_pending')
        self.assertEqual(inspected.summary.verified_outcome,'installation')
        self.assertFalse(self.restart().complete(self.client).ok)
        self.assertFalse(self.install().ok)
        self.assertEqual(self.fingerprint(),before)
        self.assertTrue(list(self.recovery.glob('prepare-*/WFCore/module.lua')))

    def test_missing_known_status_and_linked_record_preserve_external_files(self):
        for mode in ('known','hardlink'):
            with self.subTest(mode=mode):
                f=DurableStatusTests();f.setUp()
                try:
                    self.assertTrue(f.install().ok)
                    if mode=='known':(f.recovery/durable.NAME).unlink()
                    else:os.link(f.recovery/durable.NAME,f.root/'sentinel')
                    before=f.fingerprint()
                    self.assertEqual(f.restart().inspect(f.client).category,'recovery_incomplete')
                    self.assertFalse(f.install().ok)
                    self.assertEqual(before,f.fingerprint())
                finally:f.doCleanups()

    def test_process_exit_boundaries_and_fresh_inspection(self):
        for point in ('pending','known','fence','status_stage','active','replacement','receipt','terminal',
                      'marker','cleanup','backup_cleanup','finalized','released'):
            with self.subTest(point=point):
                f=DurableStatusTests();f.setUp()
                try:
                    args=[sys.executable,'-B','-c',CHILD,str(f.state),str(f.client),str(f.payload),point]
                    child=subprocess.run(args,cwd=Path(engine.__file__).parent,capture_output=True,text=True,timeout=45)
                    self.assertEqual(child.returncode,73,child.stderr)
                    check=subprocess.run([sys.executable,'-B','-c',INSPECT,str(f.state),str(f.client)],
                                         cwd=Path(engine.__file__).parent,capture_output=True,text=True,timeout=45)
                    self.assertEqual(check.returncode,0,check.stderr)
                    self.assertNotIn('"ready"',check.stdout)
                    self.assertFalse(f.install().ok);f.assert_preserved()
                    if point in ('pending','known','fence','status_stage','active'):
                        for path,raw in f.before.items():self.assertEqual((f.client/path).read_bytes(),raw)
                        self.assertFalse((f.client/'Interface/AddOns/WFStorage/module.lua').exists())
                    if point in ('pending','fence','active','replacement','receipt','terminal'):
                        self.assertEqual(f.restart().rollback(f.client).category,'rollback_complete')
                        self.assertEqual(f.snapshot(),f.before)
                    if point in ('finalized','released'):
                        self.assertTrue(f.restart().complete(f.client).ok)
                finally:f.doCleanups()


INSPECT = '''
import json,sys
from addon_installation_service import AddonInstallationService
s=AddonInstallationService(sys.argv[1]);r=s.inspect(sys.argv[2])
print(json.dumps([r.category,r.summary.verified_outcome]))
assert not r.ok
'''

HANDOFF = '''
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import json,sys,time
import install_addons as e
import addon_operation_status as d
from addon_installation_service import AddonInstallationService
lock=e.installation_lock
ensure=d.OperationStatus._ensure_fence
def paused():
    Path(sys.argv[3]).write_bytes(b'held')
    while True:time.sleep(.01)
def attempt(record):
    ensure(record)
    if sys.argv[4]=='early_terminate':paused()
@contextmanager
def retry(client):
    with lock(client) as identity:
        yield identity
        if sys.argv[4]=='terminate':paused()
    raise OSError('synthetic late release failure')
with patch.object(e,'installation_lock',retry),patch.object(d.OperationStatus,'_ensure_fence',attempt):
    result=AddonInstallationService(sys.argv[1]).complete(sys.argv[2])
print(json.dumps([result.category,result.ok]))
'''

CHILD = '''
import os,sys
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import install_addons as e
import addon_operation_status as d
from addon_installation_service import AddonInstallationService
point=sys.argv[4]
def stop():os._exit(73)
write=e._write_preparation_artifact;pub=e._publish_pending_file;replace=e.os.replace
unlink=Path.unlink;cleanup=e._retire_verified_artifacts;lock=e.installation_lock
def writing(path,*args):
    result=write(path,*args)
    if point=='known' and path.name==d.KNOWN:stop()
    if point=='fence' and path.name.startswith('.operation-reporting-'):stop()
    if point=='status_stage' and path.name==d.STAGE:stop()
    return result
def published(stage,target,root):
    result=pub(stage,target,root)
    if point=='pending' and target.name==e.PENDING_NAME:stop()
    if point=='active' and target.name==d.NAME:stop()
    if point=='receipt' and target.name=='manifest.json':stop()
    return result
def replaced(stage,target):
    result=replace(stage,target)
    if point=='replacement' and '.wf-' in Path(stage).name:stop()
    if Path(target).name==d.NAME:
        raw=Path(target).read_bytes()
        if point=='terminal' and b'"phase":"terminal"' in raw:stop()
        if point=='finalized' and b'"phase":"finalized"' in raw:stop()
    return result
def removed(path,*args,**kw):
    result=unlink(path,*args,**kw)
    if point=='marker' and path.name==e.PENDING_NAME:stop()
    if point=='backup_cleanup' and path.name=='module.lua' and any(p.name.startswith('prepare-') for p in path.parents):stop()
    return result
def cleaned(*args):
    if point=='cleanup':stop()
    return cleanup(*args)
@contextmanager
def released(client):
    with lock(client) as identity:yield identity
    if point=='released':stop()
with patch.object(e,'_write_preparation_artifact',writing),patch.object(e,'_publish_pending_file',published),patch.object(e.os,'replace',replaced),patch.object(Path,'unlink',removed),patch.object(e,'_retire_verified_artifacts',cleaned),patch.object(e,'installation_lock',released):
    result=AddonInstallationService(sys.argv[1]).install(sys.argv[3],sys.argv[2],['WFStorage','WFProfessions'])
raise AssertionError(result)
'''
