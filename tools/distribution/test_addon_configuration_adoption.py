"""Stage D-2: native token query only; all filesystem/account scenarios synthetic.

Account, elevation and ACL failures are injected. Junctions, hard links, shared
mutexes and configuration publication use actual Windows operations on fixtures.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import install_addons as engine
from addon_installation_configuration import InstallationConfiguration, ConfigurationError
from addon_installation_context import WindowsUserContext, current_windows_context
from addon_installation_gui import GuiAddonTransactions
from addon_installation_service import AddonInstallationService
import test_addon_transactions as fixtures


@unittest.skipUnless(os.name == 'nt', 'Windows identity, publication and mutex contract')
class AdoptionTests(unittest.TestCase):
    def setUp(self):
        fixtures.PreparationTests.setUp(self)
        self.anchor = self.root / 'synthetic-profile'
        self.anchor.mkdir()
        self.context = WindowsUserContext('S-1-5-21-1-2-3-1001', self.anchor, False, 1)
        self.provider = lambda: self.context
        self.config = InstallationConfiguration(self.anchor, context_provider=self.provider)
        self.state = self.root / 'historical-custom'

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.is_dir(), p.stat().st_mtime_ns,
                None if p.is_dir() else p.read_bytes()) for p in self.root.rglob('*')}

    def policy(self, client=None, state=None):
        client, state = client or self.client, state or self.state
        users = state / 'AddonBackups'
        users.mkdir(parents=True, exist_ok=True)
        history = users / 'legacy-history'
        if not history.exists():
            history.write_bytes(b'old backups stay byte-for-byte')
        service = AddonInstallationService(state)
        with engine._transaction_client_lock(client) as (canonical, identity):
            root, _ = engine._production_recovery_location(canonical, identity)
            service._policy(canonical, root, identity, create=True)
        return service

    def candidate(self):
        return self.config.adoption_candidate(self.client, self.state)

    def test_native_query_reads_account_metadata_without_opening_profile_contents(self):
        native = current_windows_context()
        self.assertRegex(native.sid, r'^S-1-')
        self.assertTrue(native.local_app_data.is_absolute())
        self.assertIs(type(native.elevated), bool)
        self.assertIsInstance(native.session_id, int)

    def test_new_default_custom_and_equivalent_caller_contexts(self):
        before = self.snapshot()
        self.assertEqual(self.config.inspect(self.client).status, 'provision_available')
        self.assertEqual(self.snapshot(), before)
        selected = self.config.provision(self.client)
        for caller in ('GUI', 'CLI', 'setup-in-original-user-process'):
            with self.subTest(caller=caller):
                restarted = InstallationConfiguration(self.anchor, context_provider=lambda: replace(self.context, session_id=2),
                                                      intended_sid=self.context.sid)
                self.assertEqual(restarted.lookup(self.client), selected)
                self.assertEqual(restarted.inspect(self.client).status, 'matching')
        beta = self.root / '_classic_beta_'
        beta.mkdir(); (beta / 'WowB.exe').touch()
        custom = self.config.provision(beta, custom_state=self.state)
        self.assertEqual(custom.state, self.state)
        self.assertEqual(self.config.lookup(self.client), selected)
        self.assertNotEqual(self.config._paths(engine.client_identity(beta)),
                            self.config._paths(engine.client_identity(self.client)))

    def test_environment_spelling_cannot_select_another_profile(self):
        with patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'wrong-profile')):
            with self.assertRaises(ConfigurationError) as error:
                InstallationConfiguration(context_provider=self.provider)
            self.assertEqual(error.exception.code, 'user_conflict')
        with self.assertRaises(ConfigurationError):
            InstallationConfiguration(self.root / 'other', context_provider=self.provider)
        with patch.dict(os.environ, LOCALAPPDATA=str(self.anchor)):
            default = InstallationConfiguration(context_provider=self.provider)
            self.assertEqual(default.lookup(self.client).state, self.config.standard)
            with patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'changed')):
                self.assertEqual(default.inspect(self.client).status, 'user_conflict')

    def test_different_unknown_elevated_service_and_setup_contexts_fail_closed(self):
        before = self.snapshot()
        for args in ({'intended_sid': 'S-1-5-21-9-8-7-1002'}, {'launch_context': 'setup'},
                     {'launch_context': 'unknown'}):
            with self.subTest(args=args), self.assertRaises(ConfigurationError):
                InstallationConfiguration(self.anchor, context_provider=self.provider, **args)
        for context in (replace(self.context, elevated=True), replace(self.context, session_id=0),
                        replace(self.context, sid='S-1-5-18'), None):
            with self.subTest(context=context), self.assertRaises(ConfigurationError):
                InstallationConfiguration(self.anchor, context_provider=lambda: context)
        with self.assertRaises(ConfigurationError):
            InstallationConfiguration(self.anchor, context_provider=lambda: (_ for _ in ()).throw(OSError('private path')))
        self.assertEqual(self.snapshot(), before)

    def test_changed_context_blocks_service_and_public_messages_are_sanitized(self):
        self.config.provision(self.client)
        self.context = replace(self.context, sid='S-1-5-21-9-8-7-1002')
        before = self.snapshot()
        result = AddonInstallationService.configured(self.config).install(self.payload, self.client, ['WFCore'])
        self.assertFalse(result.ok)
        self.assertEqual(result.summary.status, 'configuration_user_conflict')
        self.assertNotIn(str(self.root), result.summary.message)
        self.assertEqual(self.snapshot(), before)
        # A fresh object cannot reuse a schema-2 record under another SID either.
        restarted = InstallationConfiguration(self.anchor, context_provider=self.provider)
        self.assertEqual(restarted.inspect(self.client).status, 'user_conflict')

    def test_context_change_during_intent_preserves_witness_and_no_state_is_created(self):
        write = engine._write_preparation_artifact
        def changed(path, *args, **kwargs):
            result = write(path, *args, **kwargs)
            if path.suffix == '.stage':
                self.context = replace(self.context, sid='S-1-5-21-9-8-7-1002')
            return result
        with patch.object(engine, '_write_preparation_artifact', changed):
            with self.assertRaises(ConfigurationError):
                self.config.provision(self.client)
        self.assertFalse(self.config.standard.exists())
        self.assertTrue(self.config._paths(engine.client_identity(self.client))[1].exists())

    def test_explicit_adoption_cancel_repeat_and_policy_bytes_unchanged(self):
        self.policy()
        before = self.snapshot()
        self.assertEqual(self.config.inspect(self.client).status, 'choice_required')
        candidate = self.candidate()
        with self.assertRaises(ConfigurationError):
            self.config.adopt(candidate)  # Cancel/no affirmative consent.
        with self.assertRaises(ConfigurationError):
            self.config.provision(self.client, custom_state=self.state)
        self.assertEqual(self.snapshot(), before)
        selected = self.config.adopt(candidate, confirmed=True)
        self.assertEqual(selected.state, self.state)
        self.assertEqual(self.config.adopt(candidate, confirmed=True), selected)
        self.assertFalse(self.config.standard.exists())
        for name, (_, _, content) in before.items():
            if content is not None:
                self.assertEqual((self.root / name).read_bytes(), content)

    def test_missing_replaced_conflicting_or_linked_established_targets(self):
        for kind in ('missing_state', 'missing_users', 'replaced_state', 'replaced_users',
                     'changed_policy', 'hardlink_policy', 'wrong_path'):
            with self.subTest(kind=kind):
                f = AdoptionTests(); f.setUp()
                try:
                    f.policy(); candidate = f.candidate()
                    if kind in ('missing_state', 'replaced_state', 'missing_users', 'replaced_users'):
                        target = f.state if kind.endswith('state') else f.state / 'AddonBackups'
                        target.rename(target.with_name(target.name + '-held'))
                        if kind.startswith('replaced'):
                            target.mkdir()
                    else:
                        root = engine.production_recovery_root(f.client)
                        policy = root / 'user-backup-policy.json'
                        if kind == 'changed_policy': policy.write_bytes(b'{')
                        if kind == 'hardlink_policy': os.link(policy, f.root / 'linked-policy')
                        if kind == 'wrong_path': candidate = replace(candidate, state=f.root / 'untrusted')
                    before = f.snapshot()
                    with self.assertRaises(ConfigurationError): f.config.adopt(candidate, confirmed=True)
                    self.assertEqual(f.snapshot(), before)
                    self.assertFalse(f.config.registry.exists())
                finally:
                    f.doCleanups()

    def test_registered_location_cannot_be_reselected_or_migrated(self):
        self.config.provision(self.client)
        self.state.mkdir(); (self.state / 'AddonBackups').mkdir()
        before = self.snapshot()
        with self.assertRaises(ConfigurationError):
            self.config.adoption_candidate(self.client, self.state)
        with self.assertRaises(ConfigurationError):
            self.config.provision(self.client, custom_state=self.state)
        self.assertEqual(self.snapshot(), before)

    def test_adoption_preserves_pending_and_durable_status_and_does_not_authorize_install(self):
        legacy = self.policy()
        with patch.object(engine, '_publish_completion_receipt', side_effect=OSError('receipt')):
            self.assertEqual(legacy.install(self.payload, self.client, ['WFStorage']).category, 'finalization_pending')
        before = self.snapshot()
        candidate = self.candidate()
        self.assertTrue(candidate.unresolved)
        self.assertEqual(self.snapshot(), before)
        self.config.adopt(candidate, confirmed=True)
        service = AddonInstallationService.configured(self.config)
        self.assertEqual(self.config.inspect(self.client).status, 'pending')
        self.assertFalse(service.install(self.payload, self.client, ['WFCore']).ok)
        for name, (_, _, content) in before.items():
            if content is not None:
                self.assertEqual((self.root / name).read_bytes(), content)
        self.assertTrue(service.complete(self.client).ok)  # Explicit, existing verified completion.

    def test_orphaned_status_without_policy_is_not_first_use(self):
        root = engine.production_recovery_root(self.client)
        root.mkdir(parents=True)
        for name in ('operation-status-known.json', 'operation-status.json', '.operation-status.stage',
                     '.operation-reporting-unrecognized.json'):
            with self.subTest(name=name):
                marker = root / name
                marker.write_bytes(b'orphaned synthetic witness')
                before = self.snapshot()
                self.assertEqual(self.config.inspect(self.client).status, 'pending')
                with self.assertRaises(ConfigurationError): self.config.provision(self.client)
                self.assertEqual(self.snapshot(), before)
                marker.unlink()  # Fixture reset only, never done by the implementation.

    def test_policy_and_status_change_after_confirmation_reject_adoption(self):
        legacy = self.policy(); candidate = self.candidate()
        with patch.object(engine, '_publish_completion_receipt', side_effect=OSError('receipt')):
            legacy.install(self.payload, self.client, ['WFCore'])
        before = self.snapshot()
        with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
        self.assertEqual(self.snapshot(), before)

    def test_durable_reporting_without_pending_marker_survives_adoption(self):
        legacy = self.policy(); lock = engine.installation_lock
        @contextmanager
        def late(client):
            with lock(client) as identity:
                yield identity
            raise OSError('synthetic release failure')
        with patch.object(engine, 'installation_lock', late):
            result = legacy.install(self.payload, self.client, ['WFCore'])
        self.assertFalse(result.ok)
        self.assertFalse((self.client / engine.PENDING_NAME).exists())
        before = self.snapshot()
        candidate = self.candidate()
        self.assertTrue(candidate.unresolved)
        self.config.adopt(candidate, confirmed=True)
        for name, (_, _, content) in before.items():
            if content is not None: self.assertEqual((self.root / name).read_bytes(), content)
        service = AddonInstallationService.configured(self.config)
        self.assertEqual(self.config.inspect(self.client).status, 'pending')
        self.assertFalse(service.install(self.payload, self.client, ['WFCore']).ok)
        self.assertTrue(service.complete(self.client).ok)

    def test_junction_retarget_replaced_client_and_unsafe_state_fail_closed(self):
        import _winapi
        self.policy()
        alias = self.root / 'client-alias'
        _winapi.CreateJunction(str(self.client), str(alias))
        self.addCleanup(lambda: alias.rmdir() if alias.is_junction() else None)
        candidate = self.config.adoption_candidate(alias, self.state)
        self.assertEqual(candidate.bindings, self.candidate().bindings)
        beta = self.root / '_classic_beta_'; beta.mkdir(); (beta / 'WowB.exe').touch()
        alias.rmdir(); _winapi.CreateJunction(str(beta), str(alias))
        with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
        candidate = self.candidate()
        self.client.rename(self.root / 'old-client'); self.client.mkdir(); (self.client / 'Wow.exe').touch()
        with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
        state_alias = self.root / 'state-alias'; _winapi.CreateJunction(str(self.state), str(state_alias))
        self.addCleanup(lambda: state_alias.rmdir() if state_alias.is_junction() else None)
        with self.assertRaises(ConfigurationError): self.config.adoption_candidate(beta, state_alias)
        self.assertFalse(self.config.registry.exists())

    def test_permission_denial_and_publication_failure_never_repair_history(self):
        self.policy(); candidate = self.candidate()
        before = self.snapshot()
        with patch.object(engine, '_transaction_directory', side_effect=PermissionError('private path')):
            with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
        self.assertEqual(self.snapshot(), before)
        publish = engine._publish_pending_file
        def uncertain(stage, target, root):
            publish(stage, target, root)
            if stage.suffix == '.publish': raise RuntimeError('after publication')
        with patch.object(engine, '_publish_pending_file', uncertain):
            with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
        self.assertEqual(self.config.inspect(self.client).status, 'interrupted')
        for name, (_, _, content) in before.items():
            if content is not None: self.assertEqual((self.root / name).read_bytes(), content)

    def test_retarget_during_adoption_intent_prevents_configuration_publication(self):
        import _winapi
        self.policy()
        alias = self.root / 'alias'; _winapi.CreateJunction(str(self.client), str(alias))
        self.addCleanup(lambda: alias.rmdir() if alias.is_junction() else None)
        beta = self.root / '_classic_beta_'; beta.mkdir(); (beta / 'WowB.exe').touch()
        candidate = self.config.adoption_candidate(alias, self.state)
        write = engine._write_preparation_artifact
        def changed(path, *args, **kwargs):
            result = write(path, *args, **kwargs)
            if path.suffix == '.stage':
                alias.rmdir(); _winapi.CreateJunction(str(beta), str(alias))
            return result
        with patch.object(engine, '_write_preparation_artifact', changed):
            with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
        target, intent = self.config._paths(engine.client_identity(self.client))
        self.assertFalse(target.exists()); self.assertTrue(intent.exists())
        self.assertEqual((self.state / 'AddonBackups/legacy-history').read_bytes(), b'old backups stay byte-for-byte')
        self.assertFalse((beta / 'Interface').exists())

    def baseline_selection(self):
        # Generate a genuine pre-D-2 record; never remove/alter fields to simulate it.
        import types
        name = '_baseline_addon_configuration'
        module = types.ModuleType(name)
        import hashlib
        source = (Path(__file__).with_name('fixtures') / 'addon_configuration_schema1.py').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),
            '7425e444bd8d54e96498e4336b96fae5510e12959bcc4a4d7e51e831e01ac84d')
        with patch.dict(sys.modules, {name: module}):
            exec(compile(source, name, 'exec'), module.__dict__)
            return module.InstallationConfiguration(self.anchor).provision(self.client)

    def test_genuine_schema1_is_readable_but_blocks_all_configured_mutations(self):
        initial_adapter = GuiAddonTransactions(self.config)
        initial_request = initial_adapter.capture(self.client, self.payload, 'WFCore')
        selected = self.baseline_selection()
        path, _ = self.config._paths(engine.client_identity(self.client))
        record = json.loads(path.read_bytes())
        self.assertEqual(record['schema'], 1)
        self.assertNotIn('user_sid', record)
        history = selected.state / 'AddonBackups' / 'history'
        history.write_bytes(b'preserved legacy backup')
        # No pending evidence can mask the original authorization defect here.
        other_context = replace(self.context, sid='S-1-5-21-9-8-7-1002')
        other = InstallationConfiguration(self.anchor, context_provider=lambda: other_context)
        before = self.snapshot()
        result = AddonInstallationService.configured(other).install(self.payload, self.client, ['WFCore'])
        self.assertEqual(result.summary.status, 'configuration_identity_unverified')
        self.assertFalse(result.ok)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(initial_adapter.execute(initial_request).summary.status, 'configuration_identity_unverified')
        self.assertEqual(self.snapshot(), before)
        # Include real pending and durable evidence, which must also remain intact.
        with patch.object(engine, '_publish_completion_receipt', side_effect=OSError('receipt')):
            result = AddonInstallationService(selected.state).install(self.payload, self.client, ['WFCore'])
        self.assertEqual(result.category, 'finalization_pending')
        for sid in (self.context.sid, 'S-1-5-21-9-8-7-1002'):
            context = replace(self.context, sid=sid)
            config = InstallationConfiguration(self.anchor, context_provider=lambda: context)
            service = AddonInstallationService.configured(config)
            adapter = GuiAddonTransactions(config)
            before = self.snapshot()
            with self.assertRaises(ConfigurationError) as error: config.lookup(self.client)
            self.assertEqual(error.exception.code, 'identity_unverified')
            self.assertEqual(config.inspect(self.client).status, 'identity_unverified')
            self.assertIn('historical account binding', adapter.inspect(self.client).message)
            target = adapter.capture_recovery(self.client)
            for action in ('complete', 'rollback'):
                result = adapter.resolve_recovery(target, action, ('untrusted-advice',))
                self.assertEqual(result.summary.status, 'configuration_identity_unverified')
                self.assertFalse(result.ok)
            for operation in (service.inspect, service.complete, service.rollback,
                              lambda client: service.install(self.payload, client, ['WFCore'])):
                result = operation(self.client)
                self.assertFalse(result.ok)
                self.assertEqual(result.summary.status, 'configuration_identity_unverified')
                self.assertNotIn(sid, result.summary.message)
                self.assertNotIn(str(self.root), result.summary.message)
            for operation in (lambda: config.provision(self.client),
                              lambda: config.adoption_candidate(self.client, selected.state),
                              lambda: adapter.capture(self.client, self.payload, 'WFCore')):
                with self.assertRaises(ConfigurationError) as error: operation()
                self.assertEqual(error.exception.code, 'identity_unverified')
            # Even an explicitly captured policy snapshot cannot rebind a registry.
            with engine._transaction_client_lock(self.client) as (client, identity):
                candidate = config._adoption_locked(client, identity, selected.state)
            with self.assertRaises(ConfigurationError) as error: config.adopt(candidate, confirmed=True)
            self.assertEqual(error.exception.code, 'identity_unverified')
            self.assertEqual(self.snapshot(), before)  # bytes, existence and mtimes

    def test_cross_account_adoption_and_install_requests_require_fresh_consent(self):
        for mode in ('adoption', 'first_use', 'registered'):
            with self.subTest(mode=mode):
                f = AdoptionTests(); f.setUp()
                try:
                    if mode == 'adoption': f.policy()
                    if mode == 'registered': f.config.provision(f.client, custom_state=f.state)
                    adapter = GuiAddonTransactions(f.config, custom_state=f.state)
                    request = adapter.capture(f.client, f.payload, 'WFStorage')
                    other_context = replace(f.context, sid='S-1-5-21-9-8-7-1002')
                    other = InstallationConfiguration(f.anchor, context_provider=lambda: other_context)
                    before = f.snapshot()
                    result = GuiAddonTransactions(other, custom_state=f.state).execute(request)
                    self.assertFalse(result.ok)
                    self.assertEqual(result.summary.status, 'configuration_user_conflict')
                    if request.adoption is not None:
                        with self.assertRaises(ConfigurationError) as error:
                            other.adopt(request.adoption, confirmed=True)
                        self.assertEqual(error.exception.code, 'user_conflict')
                        for invalid in (None, (), 'untrusted'):
                            with self.assertRaises(ConfigurationError) as error:
                                f.config.adopt(replace(request.adoption, authority=invalid), confirmed=True)
                            self.assertEqual(error.exception.code, 'user_unverified')
                    self.assertEqual(f.snapshot(), before)
                    # Independent same-account caller can execute newly captured consent.
                    same = InstallationConfiguration(f.anchor, context_provider=f.provider)
                    legitimate = GuiAddonTransactions(same, custom_state=f.state)
                    fresh = legitimate.capture(f.client, f.payload, 'WFStorage')
                    self.assertTrue(legitimate.execute(fresh).ok)
                finally: f.doCleanups()

    def test_changed_context_gui_diagnostic_and_missing_authority_are_sanitized(self):
        self.config.provision(self.client)
        adapter = GuiAddonTransactions(self.config)
        request = adapter.capture(self.client, self.payload, 'WFCore')
        before = self.snapshot()
        for invalid in (None, (), 'untrusted'):
            result = adapter.execute(replace(request, authority=invalid))
            self.assertEqual(result.summary.status, 'configuration_user_unverified')
            self.assertFalse(result.ok)
        self.context = replace(self.context, sid='S-1-5-21-9-8-7-1002')
        result = adapter.execute(request)
        self.assertEqual(result.summary.status, 'configuration_user_conflict')
        self.assertIn('Windows user context', adapter.inspect(self.client).message)
        self.assertNotIn(self.context.sid, result.summary.message)
        self.assertNotIn(str(self.root), result.summary.message)
        self.assertEqual(self.snapshot(), before)

    def test_authority_is_checked_under_provision_and_service_lock(self):
        authority = self.config.capture_authority()
        other_context = replace(self.context, sid='S-1-5-21-9-8-7-1002')
        other = InstallationConfiguration(self.anchor, context_provider=lambda: other_context)
        before = self.snapshot()
        with self.assertRaises(ConfigurationError) as error:
            other.provision(self.client, expected_authority=authority)
        self.assertEqual(error.exception.code, 'user_conflict')
        result = AddonInstallationService.configured(other).install(self.payload, self.client, ['WFCore'],
                                                                   expected_authority=authority)
        self.assertEqual(result.summary.status, 'configuration_user_conflict')
        self.assertEqual(self.snapshot(), before)

    def test_recovery_consent_cannot_transfer_account_but_same_account_can_complete(self):
        self.config.provision(self.client)
        adapter = GuiAddonTransactions(self.config)
        with patch.object(engine, '_publish_completion_receipt', side_effect=OSError('receipt')):
            result = adapter.execute(adapter.capture(self.client, self.payload, 'WFCore'))
        self.assertEqual(result.category, 'finalization_pending')
        target = adapter.capture_recovery(self.client)
        key = adapter.recovery_summary(target).transaction_key
        self.assertIsNotNone(key)
        other_context = replace(self.context, sid='S-1-5-21-9-8-7-1002')
        other = GuiAddonTransactions(InstallationConfiguration(self.anchor, context_provider=lambda: other_context))
        before = self.snapshot()
        for action in ('complete', 'rollback'):
            result = other.resolve_recovery(target, action, key)
            self.assertEqual(result.summary.status, 'configuration_user_conflict')
            self.assertFalse(result.ok)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(adapter.resolve_recovery(target, 'complete', key).ok)

    def test_guarded_adapter_captures_adoption_before_user_confirmation(self):
        self.policy()
        adapter = GuiAddonTransactions(self.config, custom_state=self.state)
        before = self.snapshot()
        request = adapter.capture(self.client, self.payload, 'WFStorage')
        self.assertIsNotNone(request.adoption)
        self.assertEqual(self.snapshot(), before)
        # The real Qt confirmation owns the decision to call execute(). No UI or
        # public switch is added by the adapter; this is an explicit fixture call.
        result = adapter.execute(request)
        self.assertTrue(result.ok)
        self.assertEqual((self.state / 'AddonBackups/legacy-history').read_bytes(), b'old backups stay byte-for-byte')

    def test_real_mutex_blocks_same_client_while_other_client_adoption_remains_independent(self):
        self.policy(); candidate = self.candidate()
        beta = self.root / '_classic_beta_'; beta.mkdir(); (beta / 'WowB.exe').touch()
        self.policy(beta)
        other = self.config.adoption_candidate(beta, self.state)
        ready = self.root / 'lock-ready'
        code = '''
import sys,time
from pathlib import Path
import install_addons as e
with e.installation_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_bytes(b'locked')
    time.sleep(60)
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.client), str(ready)],
                                 cwd=Path(engine.__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 20
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(ready.exists())
            before = self.snapshot()
            with self.assertRaises(ConfigurationError): self.config.adopt(candidate, confirmed=True)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.config.adopt(other, confirmed=True).state, self.state)
        finally:
            if child.poll() is None: child.kill()
            child.communicate(timeout=10)
        self.assertEqual(self.config.adopt(candidate, confirmed=True).state, self.state)
        self.assertEqual(self.config.lookup(beta).state, self.state)


if __name__ == '__main__':
    unittest.main()
