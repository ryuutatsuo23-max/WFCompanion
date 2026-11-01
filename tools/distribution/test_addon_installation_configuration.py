"""Configuration/service checks use synthetic clients and per-user roots only."""
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import install_addons as engine
from addon_installation_configuration import InstallationConfiguration as NativeConfiguration, ConfigurationError
from addon_installation_context import WindowsUserContext
from addon_installation_service import AddonInstallationService, ServiceResult
import test_addon_transactions as fixtures


def InstallationConfiguration(anchor=None):
    """Explicit synthetic OS identity; never resolve this machine's profile data."""
    location = Path(anchor if anchor is not None else os.environ['LOCALAPPDATA'])
    return NativeConfiguration(anchor, context_provider=lambda: WindowsUserContext(
        'S-1-5-21-1-2-3-1001', location, False, 1))


@unittest.skipUnless(os.name == 'nt', 'Windows publication and mutex requirements')
class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        fixtures.PreparationTests.setUp(self)
        self.anchor = self.root / 'local-app-data'
        self.anchor.mkdir()
        self.config = InstallationConfiguration(self.anchor)

    snapshot = fixtures.PreparationTests.snapshot

    def junction(self, alias, target):
        import _winapi
        _winapi.CreateJunction(str(target), str(alias))
        self.addCleanup(lambda: alias.rmdir() if alias.is_junction() else None)

    def all_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def selection(self):
        return self.config.provision(self.client)

    def service(self):
        return AddonInstallationService.configured(self.config)

    def test_first_use_lookup_is_read_only_and_provision_is_explicit_and_repeatable(self):
        before = self.all_bytes()
        selected = self.config.lookup(self.client)
        self.assertEqual((selected.status, selected.mode), ('unconfigured', 'default'))
        self.assertEqual(selected.state, self.config.standard)
        self.assertFalse(self.config.registry.exists())
        self.assertEqual(self.service().pending_summary(self.client).configuration,'unavailable')
        self.assertFalse(self.service().install(self.payload, self.client, ['WFCore']).ok)
        self.assertEqual(self.all_bytes(), before)
        ready = self.selection()
        self.assertEqual(ready.status, 'available')
        self.assertTrue((ready.state / 'AddonBackups').is_dir())
        before = self.all_bytes()
        self.assertEqual(self.selection(), ready)
        self.assertEqual(self.config.lookup(self.client), ready)
        with patch.dict(os.environ,LOCALAPPDATA=str(self.anchor)):
            self.assertEqual(InstallationConfiguration().lookup(self.client),ready)
        self.assertEqual(self.all_bytes(), before)
        self.assertEqual(self.snapshot(), self.before)

    def test_all_future_callers_and_restart_resolve_same_custom_selection(self):
        custom = self.root / 'custom-state'
        expected = self.config.provision(self.client, custom_state=custom)
        self.assertEqual(expected.mode, 'custom')
        for caller in ('GUI', 'CLI', 'setup'):
            with self.subTest(caller=caller):
                self.assertEqual(InstallationConfiguration(self.anchor).lookup(self.client), expected)
        code = '''
from test_addon_installation_configuration import InstallationConfiguration
import sys
c=InstallationConfiguration(sys.argv[1]); s=c.lookup(sys.argv[2])
assert s.mode=='custom' and str(s.state).lower()==sys.argv[3].lower()
'''
        child = subprocess.run([sys.executable, '-B', '-c', code, str(self.anchor), str(self.client), str(custom)],
                               cwd=Path(engine.__file__).parent, capture_output=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertFalse(self.config.standard.exists())
        with self.assertRaises(ConfigurationError):self.selection()  # No implicit migration to default.

    def test_existing_standard_or_custom_policy_requires_explicit_verified_adoption(self):
        for mode in ('default', 'custom'):
            with self.subTest(mode=mode):
                f=ConfigurationTests();f.setUp()
                try:
                    state=f.config.standard if mode=='default' else f.root/'old-custom'
                    users=state/'AddonBackups';users.mkdir(parents=True)
                    history=users/'old/WFCore/module.lua';history.parent.mkdir(parents=True);history.write_bytes(b'old backup')
                    legacy=AddonInstallationService(state)
                    self.assertTrue(legacy.install(f.payload,f.client,['WFCore']).ok)
                    before=f.all_bytes()
                    with self.assertRaises(ConfigurationError) as caught:f.config.lookup(f.client)
                    self.assertEqual(caught.exception.code,'choice_required')
                    self.assertEqual(f.all_bytes(),before)
                    selected=f.config.adopt(f.config.adoption_candidate(f.client,state),confirmed=True)
                    self.assertEqual(selected.mode,mode)
                    self.assertEqual(history.read_bytes(),b'old backup')
                    for name,raw in before.items():self.assertEqual((f.root/name).read_bytes(),raw)
                finally:f.doCleanups()

    def test_forever_and_beta_share_state_without_replacing_each_others_policy(self):
        beta=self.root/'_classic_beta_';beta.mkdir();(beta/'WowB.exe').touch()
        a=self.selection();before=self.all_bytes()
        b=self.config.provision(beta)
        self.assertEqual(a.state,b.state)
        self.assertNotEqual(self.config._paths(engine.client_identity(self.client)),self.config._paths(engine.client_identity(beta)))
        for name,raw in before.items():self.assertEqual((self.root/name).read_bytes(),raw)
        self.assertTrue(self.service().install(self.payload,beta,['WFStorage']).ok)
        self.assertEqual(self.config.lookup(self.client),a)

    def test_existing_policy_with_pending_transaction_can_be_explicitly_adopted_without_recovery(self):
        state=self.root/'existing-custom';(state/'AddonBackups').mkdir(parents=True)
        legacy=AddonInstallationService(state)
        with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('receipt')):
            self.assertEqual(legacy.install(self.payload,self.client,['WFCore']).category,'finalization_pending')
        before=self.all_bytes()
        with self.assertRaises(ConfigurationError):self.config.provision(self.client)
        self.assertEqual(self.all_bytes(),before)
        self.config.adopt(self.config.adoption_candidate(self.client,state),confirmed=True)
        for name,raw in before.items():self.assertEqual((self.root/name).read_bytes(),raw)
        self.assertTrue((self.client/engine.PENDING_NAME).exists())
        self.assertTrue(self.service().complete(self.client).ok)

    def test_registry_loss_requires_explicit_adoption_and_never_changes_existing_policy(self):
        selected=self.selection();self.config.registry.rename(self.config.registry.with_name('registry-held'))
        before=self.all_bytes()
        with self.assertRaises(ConfigurationError) as error:self.config.lookup(self.client)
        self.assertEqual(error.exception.code,'choice_required')
        self.assertEqual(self.all_bytes(),before)
        self.assertEqual(self.config.adopt(self.config.adoption_candidate(self.client,selected.state),confirmed=True),selected)
        for name,raw in before.items():self.assertEqual((self.root/name).read_bytes(),raw)

    def test_terminated_provisioning_is_rejected_by_fresh_process_without_cleanup(self):
        ready=self.root/'provision-ready'
        code='''
import sys,time
from pathlib import Path
import install_addons as e
from test_addon_installation_configuration import InstallationConfiguration
publish=e._publish_pending_file
def pause(stage,target,root):
    publish(stage,target,root)
    if stage.suffix=='.publish':
        Path(sys.argv[3]).write_bytes(b'ready');time.sleep(60)
e._publish_pending_file=pause
InstallationConfiguration(sys.argv[1]).provision(sys.argv[2])
'''
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(self.anchor),str(self.client),str(ready)],
                               cwd=Path(engine.__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+25
            while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(ready.exists())
        finally:
            if child.poll() is None:child.kill()
            child.communicate(timeout=10)
        before=self.all_bytes()
        retry='''
import sys
from test_addon_installation_configuration import InstallationConfiguration,ConfigurationError
c=InstallationConfiguration(sys.argv[1])
for operation in (c.lookup,c.provision):
    try:operation(sys.argv[2])
    except ConfigurationError as e:assert e.code=='interrupted'
    else:raise AssertionError('Interrupted publication accepted')
'''
        result=subprocess.run([sys.executable,'-B','-c',retry,str(self.anchor),str(self.client)],
                              cwd=Path(engine.__file__).parent,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.all_bytes(),before);self.assertEqual(self.snapshot(),self.before)

    def test_missing_or_replaced_established_directories_are_never_recreated(self):
        for which in ('state','users','registry','client'):
            with self.subTest(which=which):
                f=ConfigurationTests();f.setUp()
                try:
                    s=f.selection()
                    path={'state':s.state,'users':s.state/'AddonBackups','registry':f.config.registry,'client':f.client}[which]
                    moved=path.with_name(path.name+'-held');path.rename(moved)
                    before=f.all_bytes()
                    with self.assertRaises(ConfigurationError):f.config.lookup(f.client)
                    if which!='registry':
                        with self.assertRaises(ConfigurationError):f.selection()
                    self.assertEqual(f.all_bytes(),before)
                    path.mkdir()
                    if which=='client':(path/'Wow.exe').touch()
                    if which=='registry':
                        for p in moved.iterdir():
                            if p.is_file():(path/p.name).write_bytes(p.read_bytes())
                    before=f.all_bytes()
                    with self.assertRaises(ConfigurationError):f.config.lookup(f.client)
                    self.assertEqual(f.all_bytes(),before)
                finally:f.doCleanups()

    def test_malformed_records_conflicts_and_linked_records_fail_without_writes(self):
        for kind in ('truncated','schema','extra','changed','hardlink','denied'):
            with self.subTest(kind=kind):
                f=ConfigurationTests();f.setUp()
                try:
                    f.selection();target,_=f.config._paths(engine.client_identity(f.client))
                    raw=target.read_bytes();doc=json.loads(raw)
                    if kind=='truncated':target.write_bytes(b'{')
                    elif kind=='schema':doc['schema']=999;target.write_text(json.dumps(doc))
                    elif kind=='extra':doc['unexpected']=True;target.write_text(json.dumps(doc))
                    elif kind=='changed':doc['state']['inode']+=1;target.write_text(json.dumps(doc))
                    elif kind=='hardlink':os.link(target,f.root/'external-record')
                    before=f.all_bytes()
                    real=engine._read_preparation_file
                    def read(path,*args,**kwargs):
                        if kind=='denied' and path==target:raise PermissionError('private fixture path')
                        return real(path,*args,**kwargs)
                    with patch.object(engine,'_read_preparation_file',read):
                        with self.assertRaises(ConfigurationError):f.config.lookup(f.client)
                        with self.assertRaises(ConfigurationError):f.selection()
                        result=f.service().install(f.payload,f.client,['WFCore'])
                        self.assertEqual(result.category,'backup_unavailable')
                        self.assertFalse(result.ok)
                    self.assertEqual(f.all_bytes(),before)
                finally:f.doCleanups()

    def test_interrupted_provisioning_never_silently_retries_or_deletes_evidence(self):
        for boundary in ('intent_write','sync','record_write','publish','after_publish','intent_delete'):
            with self.subTest(boundary=boundary):
                f=ConfigurationTests();f.setUp()
                try:
                    write=engine._write_preparation_artifact;publish=engine._publish_pending_file;unlink=Path.unlink
                    def writing(path,*args,**kwargs):
                        if boundary=='record_write' and path.suffix=='.publish':raise OSError('write failure')
                        result=write(path,*args,**kwargs)
                        if boundary=='intent_write' and path.suffix=='.stage':raise RuntimeError('after intent')
                        return result
                    def publishing(stage,target,root):
                        is_record=stage.suffix=='.publish'
                        if is_record and boundary=='publish':raise OSError('publication failure')
                        result=publish(stage,target,root)
                        if is_record and boundary=='after_publish':raise RuntimeError('publication uncertain')
                        return result
                    def deleting(path,*args,**kwargs):
                        if boundary=='intent_delete' and path.suffix=='.stage':raise PermissionError('keep intent')
                        return unlink(path,*args,**kwargs)
                    with patch.object(engine,'_write_preparation_artifact',writing),patch.object(engine,'_publish_pending_file',publishing),\
                         patch.object(Path,'unlink',deleting):
                        if boundary=='sync':
                            with patch.object(engine.os,'fsync',side_effect=OSError('sync failure')):
                                with self.assertRaises(ConfigurationError):f.selection()
                        else:
                            with self.assertRaises(ConfigurationError):f.selection()
                    self.assertEqual(f.snapshot(),f.before)
                    before=f.all_bytes()
                    with self.assertRaises(ConfigurationError):f.config.lookup(f.client)
                    with self.assertRaises(ConfigurationError):f.selection()
                    self.assertEqual(f.all_bytes(),before)
                finally:f.doCleanups()

    def test_pending_blocks_provisioning_and_configured_completion_survives_restart(self):
        self.selection()
        with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('synthetic failure')):
            result=self.service().install(self.payload,self.client,['WFStorage'])
        self.assertEqual(result.category,'finalization_pending')
        summary=self.service().pending_summary(self.client)
        self.assertEqual(summary.pending,'valid');self.assertTrue(summary.may_complete);self.assertTrue(summary.may_rollback)
        before=self.all_bytes()
        self.assertEqual(self.service().pending_summary(self.client),summary)
        self.assertEqual(self.all_bytes(),before)
        restarted=AddonInstallationService.configured(InstallationConfiguration(self.anchor))
        self.assertTrue(restarted.complete(self.client).ok)
        self.assertEqual(restarted.pending_summary(self.client).pending,'none')
        self.assertTrue(any((self.config.standard/'AddonBackups').glob('transaction-*')))

    def test_recovery_and_invalid_evidence_advisory_is_read_only(self):
        self.selection();replace=engine.os.replace
        def fail(stage,target):
            if target.suffix=='.toc':raise OSError('replacement')
            return replace(stage,target)
        with patch.object(engine.os,'replace',fail),patch.object(engine,'_recover_pending_locked',side_effect=OSError('rollback')):
            result=self.service().install(self.payload,self.client,['WFStorage'])
        self.assertEqual(result.category,'recovery_pending')
        summary=self.service().pending_summary(self.client)
        self.assertTrue(summary.may_rollback);self.assertFalse(summary.may_complete)
        before=self.all_bytes()
        self.assertEqual(self.service().pending_summary(self.client),summary);self.assertEqual(self.all_bytes(),before)
        marker=self.client/engine.PENDING_NAME;raw=marker.read_bytes();marker.write_bytes(b'{')
        summary=self.service().pending_summary(self.client)
        self.assertEqual(summary.pending,'invalid');self.assertTrue(summary.manual_review)
        self.assertFalse(summary.may_rollback);self.assertFalse(summary.may_complete)
        marker.write_bytes(raw)
        target=self.client/'Interface/AddOns/WFCore/module.lua';installed=target.read_bytes()
        target.write_bytes(b'external change retained')
        before=self.all_bytes();summary=self.service().pending_summary(self.client)
        self.assertEqual(summary.pending,'ambiguous');self.assertTrue(summary.manual_review)
        self.assertFalse(summary.may_rollback);self.assertFalse(summary.may_complete)
        self.assertEqual(self.all_bytes(),before)
        target.write_bytes(installed)  # Explicit synthetic conflict resolution, never automatic recovery.
        self.assertEqual(self.service().rollback(self.client).category,'rollback_complete')
        self.assertEqual(self.snapshot(),self.before)

    def test_alias_and_directory_replacement_rejected_under_pinned_lock(self):
        alias=self.root/'alias';self.junction(alias,self.client)
        self.assertEqual(self.config.provision(alias),self.config.lookup(self.client))
        real=engine.installation_lock
        @contextmanager
        def replaced(client):
            with real(client) as identity:
                self.client.rename(self.root/'held-client');self.client.mkdir();(self.client/'Wow.exe').touch()
                yield identity
        with patch.object(engine,'installation_lock',replaced):
            with self.assertRaises(ConfigurationError):self.config.lookup(self.client)

    def test_unsafe_custom_junction_never_creates_backup_directories(self):
        external=self.root/'external';external.mkdir();alias=self.root/'linked-state'
        self.junction(alias,external)
        with self.assertRaises(ConfigurationError):self.config.provision(self.client,custom_state=alias)
        self.assertEqual(list(external.iterdir()),[])

    def test_configuration_symlink_rejected_when_supported(self):
        self.selection();target,_=self.config._paths(engine.client_identity(self.client))
        original=target.with_suffix('.held');target.rename(original)
        try:target.symlink_to(original)
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:self.skipTest('Symlinks unavailable: Windows error 1314')
            raise
        before=self.all_bytes()
        with self.assertRaises(ConfigurationError):self.config.lookup(self.client)
        self.assertEqual(self.all_bytes(),before)

    def test_policy_change_and_missing_backups_disable_advice_without_mutation(self):
        self.selection()
        with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('receipt')):
            self.service().install(self.payload,self.client,['WFCore'])
        policy=engine.production_recovery_root(self.client)/'user-backup-policy.json'
        raw=policy.read_bytes();policy.write_bytes(b'{')
        before=self.all_bytes();summary=self.service().pending_summary(self.client)
        self.assertEqual(summary.pending,'valid');self.assertEqual(summary.configuration,'unavailable')
        self.assertFalse(summary.may_complete);self.assertFalse(summary.may_rollback);self.assertTrue(summary.manual_review)
        self.assertEqual(self.all_bytes(),before)
        policy.write_bytes(raw)
        users=self.config.standard/'AddonBackups';users.rename(users.with_name('backups-held'))
        before=self.all_bytes();summary=self.service().pending_summary(self.client)
        self.assertEqual(summary.configuration,'unavailable');self.assertFalse(summary.may_rollback)
        self.assertFalse(self.service().complete(self.client).ok)
        self.assertEqual(self.all_bytes(),before)

    def test_ancestor_replacement_after_intent_blocks_directory_creation(self):
        custom=self.root/'custom-existing';custom.mkdir()
        write=engine._write_preparation_artifact
        def changed(path,*args,**kwargs):
            result=write(path,*args,**kwargs)
            if path.suffix=='.stage':
                custom.rename(self.root/'custom-held');custom.mkdir()
            return result
        with patch.object(engine,'_write_preparation_artifact',changed):
            with self.assertRaises(ConfigurationError):self.config.provision(self.client,custom_state=custom)
        self.assertEqual(list(custom.iterdir()),[])
        self.assertEqual(list((self.root/'custom-held').iterdir()),[])
        self.assertEqual(self.snapshot(),self.before)

    def test_real_completed_operations_with_late_errors_have_safe_summaries(self):
        for rollback in (False,True):
            with self.subTest(rollback=rollback):
                f=ConfigurationTests();f.setUp()
                try:
                    f.selection();lock=engine.installation_lock;replace=engine.os.replace;calls=0
                    @contextmanager
                    def late(client):
                        with lock(client) as identity:yield identity
                        raise RuntimeError('private diagnostic sentinel')
                    def apply(stage,target):
                        nonlocal calls
                        calls+=1
                        if rollback and calls==2:raise OSError('replacement')
                        return replace(stage,target)
                    with patch.object(engine,'installation_lock',late),patch.object(engine.os,'replace',apply):
                        result=f.service().install(f.payload,f.client,['WFStorage'])
                    self.assertFalse(result.ok)
                    self.assertEqual(result.summary.status,('rollback' if rollback else 'installation')+'_complete_with_error')
                    self.assertNotIn('private',json.dumps(asdict(result.summary)))
                    self.assertFalse((f.client/engine.PENDING_NAME).exists())
                    # Durable reporting uncertainty now survives a missing marker.
                    self.assertEqual(f.service().pending_summary(f.client).pending,'unresolved')
                    if rollback:self.assertEqual(f.snapshot(),f.before)
                finally:f.doCleanups()


class PublicSummaryTests(unittest.TestCase):
    def test_late_error_summaries_preserve_verified_outcome_without_private_diagnostics(self):
        for category,outcome in (('installation_complete','installation'),('rollback_complete','rollback')):
            prior=ServiceResult(category,_details={'private':'never render'})
            result=ServiceResult('finalization_pending','lock_or_postcheck',{'operation_result':prior,'late_error':OSError('private sentinel')})
            summary=result.summary
            self.assertEqual(summary.status,outcome+'_complete_with_error');self.assertEqual(summary.verified_outcome,outcome)
            self.assertFalse(summary.ok);self.assertTrue(summary.late_error);self.assertFalse(summary.automatic_reinstall)
            self.assertNotIn('private',json.dumps(asdict(summary)))

    def test_unresolved_and_configuration_categories_remain_distinct(self):
        for category in ('recovery_pending','recovery_incomplete','finalization_pending','backup_unavailable','busy','blocked','no_pending'):
            summary=ServiceResult(category,_details=OSError('private sentinel')).summary
            self.assertEqual(summary.status,category);self.assertFalse(summary.ok)
            self.assertIsNone(summary.verified_outcome);self.assertNotIn('private',json.dumps(asdict(summary)))
        self.assertEqual(ServiceResult('backup_unavailable','configuration_conflict').summary.status,'configuration_conflict')
        for diagnostic in ('pending_invalid','pending_ambiguous'):
            self.assertEqual(ServiceResult('recovery_incomplete',diagnostic).summary.status,diagnostic)
        self.assertTrue(ServiceResult('installation_complete').summary.ok)
        self.assertFalse(ServiceResult('rollback_complete').summary.ok)


if __name__ == '__main__':unittest.main()
