"""Guarded GUI operations use synthetic clients, packages and per-user roots."""
import json
from contextlib import contextmanager
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from companion import Companion
from addons_page import AddonsPage
from addon_installation_gui import GuiAddonTransactions
from test_addon_installation_configuration import InstallationConfiguration
from addon_installation_service import ServiceResult
import install_addons as engine
import test_addon_transactions as fixtures
import test_addons_page as gui_fixtures


@unittest.skipUnless(os.name == 'nt', 'Windows transaction publication and mutexes')
class TransactionPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        fixtures.PreparationTests.setUp(self)
        manifest=self.payload.parent/'addon_packages.json'
        metadata=json.loads(manifest.read_bytes())
        for package in metadata['packages'].values():package['version']='synthetic'
        manifest.write_text(json.dumps(metadata))
        gui_fixtures.AddonsPageTests.setUp(self)  # Patches discovery BEFORE host creation.
        self.anchor=self.root/'local-app-data';self.anchor.mkdir()
        self.installation_anchor=self.anchor  # Default factory uses the same synthetic native context.
        env=patch.dict(os.environ,LOCALAPPDATA=str(self.anchor),APPDATA=str(self.anchor))
        env.start();self.addCleanup(env.stop)
        self.config=InstallationConfiguration(self.anchor)
        self.controller=GuiAddonTransactions(self.config)
        self.host=Companion(self.root/'window-state');self.host.testing=True
        self.assertIsInstance(self.host.addons_page.transactions,GuiAddonTransactions)
        self.host.updates_panel.timer.stop();self.host.saved_character_connection.timer.stop()
        self.pages=[]
        self.addCleanup(self.close)
        self.page=self.make_page()

    snapshot=fixtures.PreparationTests.snapshot

    def close(self):
        self.host.close()
        for page in self.pages:page.deleteLater()
        self.app.processEvents()

    def make_page(self, controller=True):
        page=AddonsPage(self.host,payload=self.payload,clients=[self.client],
                        **({} if controller is True else {'transactions':controller}))
        if controller is True:
            self.assertIsInstance(page.transactions,GuiAddonTransactions)
            self.controller=page.transactions
        self.pages.append(page);self.host.addons_page=page
        return page

    def accept(self, addon='WFStorage'):
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.page.install_selected(addon)

    def all_bytes(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_default_path_uses_packaged_service_and_disabled_session_has_no_fallback(self):
        from audit_payload import allowed
        self.assertTrue(allowed('tools/distribution/addon_installation_gui.py'))
        self.assertIsInstance(self.host.addons_page.transactions,GuiAddonTransactions)
        before=self.all_bytes();page=self.make_page(None)
        with patch.object(engine,'install',side_effect=AssertionError('Legacy fallback')),patch.object(QMessageBox,'question') as question:
            page.install_selected('WFCore');question.assert_not_called()
        self.assertIn('disabled',page.notice.text());self.assertFalse(page.core_action.isEnabled())
        self.assertIsNone(page.transactions);self.assertFalse(self.config.registry.exists())
        self.assertEqual(before,self.all_bytes())

    def test_real_install_standard_configuration_and_retained_history(self):
        self.assertFalse(self.config.registry.exists())
        with patch.object(engine,'install',side_effect=AssertionError('Legacy fallback')):
            self.accept()
        self.assertIn('installation and retained backups verified',self.page.notice.text())
        selection=self.config.lookup(self.client)
        self.assertEqual(selection.state,self.config.standard)
        copies=list((selection.state/'AddonBackups').glob('transaction-*/WFCore/module.lua'))
        self.assertEqual(len(copies),1);self.assertEqual(copies[0].read_bytes(),self.before['Interface/AddOns/WFCore/module.lua'])
        self.assertFalse((self.client/engine.PENDING_NAME).exists())
        for name in ('WTF/synthetic.lua','Interface/AddOns/Other/keep.lua'):
            self.assertEqual((self.client/name).read_bytes(),self.before[name])
        self.assertFalse((self.host.data.directory/'AddonBackups').exists())

    def test_default_service_failure_blocks_every_action_without_legacy_fallback(self):
        before=self.all_bytes()
        with patch('addons_page.current_user_transactions',side_effect=RuntimeError('private sentinel')):
            page=AddonsPage(self.host,payload=self.payload,clients=[self.client])
        self.pages.append(page)
        with patch.object(engine,'install',side_effect=AssertionError('Legacy fallback')),patch.object(QMessageBox,'question') as question:
            for addon in ('WFCore','WFStorage','WFProfessions'):page.install_selected(addon)
            question.assert_not_called()
        for button in (page.core_action,page.action,page.professions_action):self.assertFalse(button.isEnabled())
        self.assertIsNone(page.transactions);self.assertIsNone(page.review_recovery())
        self.assertIn('unavailable',page.notice.text());self.assertNotIn('private sentinel',page.notice.text())
        self.assertEqual(before,self.all_bytes())

    def test_elevated_or_conflicting_account_context_cannot_enable_installation(self):
        from addon_installation_context import WindowsUserContext
        for elevated,anchor in ((True,self.anchor),(False,self.root)):
            with self.subTest(elevated=elevated,conflict=anchor!=self.anchor):
                before=self.all_bytes()
                with patch('addon_installation_configuration.current_windows_context',return_value=WindowsUserContext(
                        'S-1-5-21-1-2-3-1001',anchor,elevated,1)):
                    page=AddonsPage(self.host,payload=self.payload,clients=[self.client])
                self.pages.append(page)
                with patch.object(QMessageBox,'question') as question:page.install_selected();question.assert_not_called()
                self.assertIsNone(page.transactions);self.assertFalse(page.action.isEnabled())
                self.assertEqual(before,self.all_bytes())

    def test_legacy_backups_and_existing_character_preferences_are_not_migrated(self):
        history=self.host.data.directory/'AddonBackups/old/WFCore/module.lua'
        history.parent.mkdir(parents=True);history.write_bytes(b'legacy backup')
        preferences=self.host.data.directory/'saved_character_connection.json'
        preferences.write_bytes(b'{"version":1,"directory":"","automatic":false}')
        protected={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.host.data.directory.rglob('*') if p.is_file()}
        self.accept()
        self.assertIn('verified',self.page.notice.text())
        self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in protected},protected)
        self.assertEqual(self.config.lookup(self.client).state,self.config.standard)
        self.assertTrue(list((self.config.standard/'AddonBackups').glob('transaction-*/originals.json')))

    def test_new_bundled_revision_uses_transaction_and_keeps_both_backup_generations(self):
        self.accept('WFCore')
        previous=(self.payload/'WFCore/module.lua').read_bytes()
        (self.payload/'WFCore/module.lua').write_bytes(b'new synthetic revision')
        gui_fixtures.AddonsPageTests.authenticate_payload(self.payload)
        self.page.refresh();self.assertTrue(self.page.core_action.isEnabled())
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as question:
            self.page.install_selected('WFCore')
        confirmed_backup=next(line.removeprefix('Backups: ') for line in question.call_args.args[2].splitlines() if line.startswith('Backups: '))
        self.assertEqual(Path(confirmed_backup),self.config.standard/'AddonBackups')
        self.assertIn('Install into: '+str(self.client/'Interface/AddOns'),question.call_args.args[2])
        self.assertEqual((self.client/'Interface/AddOns/WFCore/module.lua').read_bytes(),b'new synthetic revision')
        copies=list((self.config.standard/'AddonBackups').glob('transaction-*/WFCore/module.lua'))
        self.assertEqual(len(copies),2)
        self.assertEqual({p.read_bytes() for p in copies},{previous,self.before['Interface/AddOns/WFCore/module.lua']})
        self.assertFalse(self.page.core_action.isEnabled())

    def test_custom_first_use_and_existing_custom_are_preserved(self):
        custom=self.root/'custom-state';history=custom/'AddonBackups/old/keep';history.parent.mkdir(parents=True);history.write_bytes(b'history')
        self.page=self.make_page(GuiAddonTransactions(self.config,custom_state=custom));self.accept()
        self.assertEqual(self.config.lookup(self.client).state,custom);self.assertEqual(history.read_bytes(),b'history')
        reopened=self.make_page(GuiAddonTransactions(InstallationConfiguration(self.anchor)))
        self.assertTrue(reopened.professions_action.isEnabled())
        self.page=reopened;self.accept('WFProfessions')
        self.assertIn('verified',self.page.notice.text());self.assertFalse(self.config.standard.exists())
        conflict=self.make_page(GuiAddonTransactions(self.config,custom_state=self.root/'other'))
        with patch.object(QMessageBox,'question') as question:conflict.install_selected('WFCore');question.assert_not_called()
        self.assertIn('conflicting',conflict.transaction_status.text());self.assertEqual(history.read_bytes(),b'history')

    def test_cancel_is_default_and_creates_no_configuration_or_backup(self):
        before=self.all_bytes()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
            self.page.install_selected()
        self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
        self.assertIn('may be newer or locally modified',question.call_args.args[2])
        self.assertIn(str(self.client),question.call_args.args[2])
        self.assertIn(str(self.config.standard),question.call_args.args[2])
        self.assertEqual(self.all_bytes(),before);self.assertFalse(self.config.registry.exists())

    def test_explicit_historical_adoption_uses_cancel_default_without_moving_backups(self):
        from addon_installation_service import AddonInstallationService
        custom=self.root/'old-custom';users=custom/'AddonBackups';users.mkdir(parents=True)
        history=users/'history';history.write_bytes(b'preserved history')
        legacy=AddonInstallationService(custom)
        with engine._transaction_client_lock(self.client) as (client,identity):
            root,_=engine._production_recovery_location(client,identity)
            legacy._policy(client,root,identity,create=True)
        self.page=self.make_page(GuiAddonTransactions(self.config,custom_state=custom))
        before=self.all_bytes()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
            self.page.install_selected('WFCore')
        self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
        self.assertIn('Use this existing addon backup location',question.call_args.args[2])
        self.assertEqual(self.all_bytes(),before)
        self.accept('WFCore')
        self.assertEqual(self.config.lookup(self.client).state,custom)
        self.assertEqual(history.read_bytes(),b'preserved history')
        self.assertFalse(self.config.standard.exists())

    def test_result_presentations_never_use_private_diagnostics_or_fallback(self):
        results=[ServiceResult(n,_details=OSError('private sentinel')) for n in
                 ('installation_complete','blocked','busy','recovery_pending','recovery_incomplete','rollback_complete',
                  'finalization_pending','backup_unavailable')]
        results += [ServiceResult('finalization_pending','lock_or_postcheck',
                    dict(operation_result=ServiceResult(n),late_error=OSError('private sentinel')))
                    for n in ('installation_complete','rollback_complete')]
        results += [ServiceResult('recovery_incomplete',n) for n in ('pending_invalid','pending_ambiguous')]
        for result in results:
            with self.subTest(status=result.summary.status):
                self.page._transaction_warnings.clear();self.page.refresh()
                with patch.object(self.controller,'execute',return_value=result) as execute,\
                     patch.object(engine,'install',side_effect=AssertionError('Legacy fallback')):
                    self.accept();execute.assert_called_once()
                self.assertEqual(self.page.notice.text(),result.summary.message)
                self.assertNotIn('private sentinel',self.page.notice.text())
                self.page.refresh()
                if result.summary.status in ('recovery_pending','recovery_incomplete','finalization_pending',
                                              'installation_complete_with_error','rollback_complete_with_error',
                                              'pending_invalid','pending_ambiguous'):
                    self.assertFalse(self.page.action.isEnabled());self.assertTrue(self.page.transaction_status.text())

    def test_duplicate_entry_target_controls_navigation_and_close_are_guarded(self):
        execute=self.controller.execute;calls=[]
        def guarded(request):
            calls.append(request)
            self.assertTrue(self.page.operation_active)
            for widget in (self.page.picker,self.page.refresh_action,self.page.action,self.host.page_picker,self.host.back_button):
                self.assertFalse(widget.isEnabled())
            self.page.install_selected();self.page.refresh()
            self.assertFalse(self.page.remember_client(None))
            event=QCloseEvent();self.host.closeEvent(event);self.assertFalse(event.isAccepted())
            with patch.object(QApplication,'processEvents',side_effect=AssertionError('Events pumped during mutation')):
                return execute(request)
        with patch.object(self.controller,'execute',guarded):self.accept()
        self.assertEqual(len(calls),1);self.assertFalse(self.page.operation_active)
        self.assertTrue(self.page.picker.isEnabled());self.assertTrue(self.host.page_picker.isEnabled())

    def test_preference_save_failure_does_not_misreport_verified_installation(self):
        with patch('addons_page.write_json',side_effect=OSError('private preference path')):self.accept()
        notice=self.page.notice.text()
        self.assertIn('verified',notice);self.assertIn('Folder preference could not be saved',notice)
        self.assertNotIn('private preference path',notice);self.assertFalse(self.page.action.isEnabled())
        self.assertFalse((self.client/engine.PENDING_NAME).exists())

    def test_real_pending_refresh_restart_and_client_switch_are_read_only(self):
        with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('synthetic receipt')):self.accept()
        self.assertIn('unresolved',self.page.notice.text());self.assertFalse(self.page.action.isEnabled())
        before=self.all_bytes();self.page.refresh();reopened=self.make_page()
        self.assertEqual(self.all_bytes(),before);self.assertIn('Recovery required',reopened.transaction_status.text())
        beta=self.root/'_classic_beta_';beta.mkdir();(beta/'Wow.exe').touch()
        self.page.remember_client(beta)
        self.assertTrue(self.page.action.isEnabled());self.assertNotIn('Recovery required',self.page.transaction_status.text())
        self.accept();self.assertTrue((beta/'Interface/AddOns/WFStorage/module.lua').exists())
        self.page.remember_client(self.client)
        self.assertFalse(self.page.action.isEnabled());self.assertTrue((self.client/engine.PENDING_NAME).exists())

    def test_selection_change_during_confirmation_does_not_install(self):
        def change(*args):
            self.page.client=None
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',change),patch.object(self.controller,'execute') as execute:
            self.page.install_selected();execute.assert_not_called()
        self.assertEqual(self.snapshot(),self.before);self.assertFalse(self.config.registry.exists())

    def test_changed_client_between_confirmation_and_lock_is_rejected(self):
        lock=engine.installation_lock;armed=False
        @contextmanager
        def changed(client):
            nonlocal armed
            if armed:
                armed=False;self.client.rename(self.root/'held-client');self.client.mkdir();(self.client/'Wow.exe').touch()
            with lock(client) as identity:yield identity
        def confirm(*args):
            nonlocal armed
            armed=True
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',confirm),patch.object(engine,'installation_lock',changed):
            self.page.install_selected()
        self.assertFalse((self.client/'Interface').exists());self.assertFalse(self.config.registry.exists())
        self.assertNotIn('installation and retained backups verified',self.page.notice.text())

    def test_service_rechecks_confirmed_identity_after_preflight(self):
        identity=engine.client_identity(self.client);identity['inode']+=1
        from addon_installation_configuration import ConfigurationError
        with self.assertRaises(ConfigurationError):
            self.config.provision(self.client,expected_client_identity=identity)
        self.assertFalse(self.config.registry.exists())
        self.config.provision(self.client)
        result=self.controller.service.install(self.payload,self.client,['WFCore'],expected_client_identity=identity)
        self.assertFalse(result.ok);self.assertEqual(self.snapshot(),self.before)
        selected=self.config.lookup(self.client)
        from dataclasses import replace
        result=self.controller.service.install(self.payload,self.client,['WFCore'],expected_selection=replace(selected,mode='custom'))
        self.assertFalse(result.ok);self.assertEqual(self.snapshot(),self.before)

    def test_busy_client_is_read_only_and_recovers_controls_after_release(self):
        before=self.all_bytes()
        with engine.installation_lock(self.client),patch.object(QMessageBox,'question') as question:
            self.page.refresh();self.page.install_selected();question.assert_not_called()
            self.assertIn('Another addon operation',self.page.transaction_status.text())
            self.assertFalse(self.page.action.isEnabled())
        self.assertEqual(self.all_bytes(),before)
        self.page.refresh();self.assertTrue(self.page.action.isEnabled())

    def test_real_failed_rollback_remains_blocked_without_automatic_recovery(self):
        replace=engine.os.replace;calls=0
        def fail(stage,target):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('synthetic replacement failure')
            return replace(stage,target)
        with patch.object(engine.os,'replace',fail),patch.object(engine,'_recover_pending_locked',side_effect=OSError('synthetic rollback')):
            self.accept()
        self.assertIn('explicit recovery',self.page.notice.text())
        before=self.all_bytes()
        with patch.object(engine,'_recover_pending_locked',side_effect=AssertionError('Automatic recovery')):
            self.page.refresh();reopened=self.make_page();reopened.refresh()
        self.assertEqual(self.all_bytes(),before);self.assertFalse(reopened.action.isEnabled())
        # Dialog-driven recovery is covered separately; inspection never restores files.
        self.assertEqual(self.controller.service.rollback(self.client).category,'rollback_complete')
        self.assertEqual(self.snapshot(),self.before)

    def test_unexpected_execution_exception_is_not_pre_mutation_success(self):
        with patch.object(self.controller,'execute',side_effect=RuntimeError('private sentinel')):self.accept()
        self.assertIn('uncertain',self.page.notice.text());self.assertNotIn('private sentinel',self.page.notice.text())
        self.page.refresh();self.assertFalse(self.page.action.isEnabled())


if __name__=='__main__':unittest.main()
