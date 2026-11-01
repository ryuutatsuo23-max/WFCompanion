"""Explicit recovery UI: synthetic clients/configuration before host construction."""
from contextlib import contextmanager
import os
import unittest
from unittest.mock import patch

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
# The shared GUI fixture establishes the source-layout distribution imports.
import test_addon_transactions_page as fixtures
import install_addons as engine
from addon_operation_status import OperationStatus
from addon_installation_service import ServiceResult
from addon_installation_gui import GuiAddonTransactions


@unittest.skipUnless(os.name=='nt','Windows transaction publication and locks')
class RecoveryDialogTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.TransactionPageTests.setUpClass.__func__)
    setUp=fixtures.TransactionPageTests.setUp
    close=fixtures.TransactionPageTests.close
    make_page=fixtures.TransactionPageTests.make_page
    accept=fixtures.TransactionPageTests.accept
    all_bytes=fixtures.TransactionPageTests.all_bytes
    snapshot=fixtures.TransactionPageTests.snapshot

    def pending(self,partial=False):
        if not partial:
            with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('synthetic receipt')):self.accept()
        else:
            real=engine.os.replace;calls=0
            def fail(stage,target):
                nonlocal calls
                calls+=1
                if calls==2:raise OSError('synthetic replacement')
                return real(stage,target)
            with patch.object(engine.os,'replace',fail),patch.object(engine,'_recover_pending_locked',side_effect=OSError('synthetic rollback')):
                self.accept()
        self.assertTrue((self.client/engine.PENDING_NAME).exists())
        self.assertTrue(self.page._transaction_warnings)

    def dialog(self):
        value=self.page.review_recovery()
        self.assertIsNotNone(value)
        return value

    def yes(self,dialog,action):
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.resolve(action)

    def reporting_pending(self, action='complete'):
        self.pending()
        with patch.object(OperationStatus,'reported',side_effect=OSError('private reporting failure')):
            result=getattr(self.controller.service,action)(self.client)
        self.assertTrue(result.summary.late_error)
        self.assertFalse((self.client/engine.PENDING_NAME).exists())
        self.assertTrue(list(engine.production_recovery_root(self.client).glob('.operation-reporting-*')))

    def test_finish_reporting_installation_after_reopen_preserves_files_and_backups(self):
        self.reporting_pending();self.page=self.make_page();before=self.all_bytes()
        stamps={p:p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        dialog=self.dialog();dialog.check_again()
        self.assertEqual(self.all_bytes(),before)
        self.assertEqual({p:p.stat().st_mtime_ns for p in stamps},stamps)
        self.assertTrue(dialog.report_action.isEnabled())
        self.assertFalse(dialog.finish_action.isEnabled());self.assertFalse(dialog.restore_action.isEnabled())
        self.assertIn('Installed addon files are verified',dialog.state.text())
        client_before=self.snapshot()
        backups={p:p.read_bytes() for p in self.config.standard.rglob('*') if p.is_file()}
        with patch.object(engine,'_execute_transaction_locked',side_effect=AssertionError('Reinstall')),\
             patch.object(engine,'_recover_pending_locked',side_effect=AssertionError('Restore')):
            self.yes(dialog,'report')
        self.assertEqual(self.snapshot(),client_before)
        self.assertEqual({p:p.read_bytes() for p in backups},backups)
        self.assertFalse(self.page._transaction_warnings);self.assertIn('verified',dialog.notice.text())
        self.assertFalse(dialog.report_action.isEnabled())

    def test_finish_reporting_rollback_does_not_claim_installation_success(self):
        self.reporting_pending('rollback');dialog=self.dialog()
        self.assertTrue(dialog.report_action.isEnabled());self.assertIn('restored and verified',dialog.state.text())
        self.yes(dialog,'report')
        self.assertEqual(self.snapshot(),self.before)
        self.assertIn('restored and rollback finalized',dialog.notice.text())
        self.assertFalse(self.page._transaction_warnings);self.assertTrue(self.page.action.isEnabled())

    def test_reporting_cancel_and_changed_attempt_preserve_evidence(self):
        self.reporting_pending();dialog=self.dialog();before=self.all_bytes()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
            dialog.resolve('report')
        self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
        self.assertIn('will not be installed or restored again',question.call_args.args[2])
        self.assertEqual(before,self.all_bytes())
        after=[]
        def confirm(*args):
            with patch.object(OperationStatus,'reported',side_effect=OSError('new synthetic attempt')):
                self.controller.service.complete(self.client)
            after.append(self.all_bytes());return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',confirm):dialog.resolve('report')
        self.assertEqual(after[0],self.all_bytes());self.assertTrue(self.page._transaction_warnings)
        self.assertEqual(dialog.notice.text(),ServiceResult('recovery_incomplete').summary.message)

    def test_reporting_missing_configuration_and_residual_evidence_stay_blocked(self):
        self.reporting_pending();dialog=self.dialog()
        state=self.config.standard;parked=state.with_name('held-state');state.rename(parked)
        before=self.all_bytes();dialog.check_again()
        self.assertFalse(dialog.report_action.isEnabled());self.assertEqual(before,self.all_bytes())
        parked.rename(state)
        root=engine.production_recovery_root(self.client)
        receipt=next(root.glob('prepare-*/manifest.json'))
        (receipt.parent/'unresolved-evidence').write_bytes(b'keep synthetic evidence')
        before=self.all_bytes();dialog.check_again()
        self.assertFalse(dialog.report_action.isEnabled());self.assertIn('manual review',dialog.state.text())
        self.yes(dialog,'report');self.assertEqual(before,self.all_bytes())

    def test_reporting_late_error_retains_warning_and_allows_fresh_confirmed_retry(self):
        self.reporting_pending();dialog=self.dialog()
        with patch.object(OperationStatus,'reported',side_effect=OSError('private failure')):
            self.yes(dialog,'report')
        self.assertTrue(self.page._transaction_warnings);self.assertFalse(self.page.action.isEnabled())
        self.assertNotIn('private failure',dialog.notice.text())
        self.assertIn('later operation check failed',dialog.notice.text())
        self.assertTrue(dialog.report_action.isEnabled())
        self.yes(dialog,'report');self.assertFalse(self.page._transaction_warnings)

    def test_reporting_keeps_mutation_navigation_and_close_guards(self):
        self.reporting_pending();dialog=self.dialog();real=self.controller.resolve_recovery;calls=[]
        def guarded(*args):
            calls.append(args)
            self.assertTrue(dialog.busy);self.assertTrue(self.page.operation_active)
            self.assertFalse(dialog.report_action.isEnabled());self.assertFalse(self.page.picker.isEnabled())
            dialog.resolve('report');dialog.reject();self.page.install_selected()
            event=QCloseEvent();self.host.closeEvent(event);self.assertFalse(event.isAccepted())
            with patch.object(QApplication,'processEvents',side_effect=AssertionError('Event pump')):return real(*args)
        with patch.object(self.controller,'resolve_recovery',guarded):self.yes(dialog,'report')
        self.assertEqual(len(calls),1);self.assertFalse(dialog.busy);self.assertTrue(dialog.close_action.isEnabled())

    def test_reporting_client_selection_change_cannot_affect_another_client(self):
        self.reporting_pending();dialog=self.dialog()
        peer=self.root/'_classic_beta_';peer.mkdir();(peer/'Wow.exe').touch()
        self.page.remember_client(peer);before=self.all_bytes()
        self.yes(dialog,'report')
        self.assertEqual(before,self.all_bytes());self.assertFalse(dialog.report_action.isEnabled())
        self.assertFalse((peer/'Interface').exists())

    def test_reporting_configuration_change_during_confirmation_rejects_without_writes(self):
        self.reporting_pending();dialog=self.dialog();after=[]
        path,_=self.config._paths(engine.client_identity(self.client))
        def confirm(*args):
            path.write_bytes(b'{}');after.append(self.all_bytes())
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',confirm):dialog.resolve('report')
        self.assertEqual(after[0],self.all_bytes());self.assertTrue(self.page._transaction_warnings)
        self.assertFalse(dialog.report_action.isEnabled())

    def test_disabled_default_no_pending_check_close_and_timestamps_are_read_only(self):
        legacy=self.make_page(None)
        self.assertIsNone(legacy.recovery_action);self.assertIsNone(legacy.review_recovery())
        self.host.addons_page=self.page
        before=self.all_bytes()
        stamps={p:p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        dialog=self.dialog();dialog.check_again();dialog.reject()
        self.assertEqual(self.all_bytes(),before)
        self.assertEqual({p:p.stat().st_mtime_ns for p in stamps},stamps)
        self.assertFalse(dialog.finish_action.isEnabled());self.assertFalse(dialog.restore_action.isEnabled())
        self.assertIn('No pending',dialog.state.text());self.assertFalse(self.config.registry.exists())

    def test_finish_installation_verifies_receipt_and_resolves_warning(self):
        self.pending();installed=self.snapshot();dialog=self.dialog()
        self.assertTrue(dialog.finish_action.isEnabled());self.assertTrue(dialog.restore_action.isEnabled())
        self.assertIn('Forever Core',dialog.addons.text());self.assertIn('Forever Storage',dialog.addons.text())
        retained=self.config.lookup(self.client).state/'AddonBackups'
        copies={p:p.read_bytes() for p in retained.glob('transaction-*/WFCore/module.lua')}
        with patch.object(engine,'_execute_transaction_locked',side_effect=AssertionError('New installation')):
            self.yes(dialog,'complete')
        self.assertFalse((self.client/engine.PENDING_NAME).exists())
        for path,raw in copies.items():self.assertEqual(path.read_bytes(),raw)
        self.assertTrue(list(retained.glob('transaction-*/originals.json')))
        for name,raw in installed.items():
            if not name.startswith('.wf-addon') and '/.wf-' not in name:self.assertEqual((self.client/name).read_bytes(),raw)
        self.assertIn('verified',dialog.notice.text());self.assertFalse(self.page._transaction_warnings)
        self.assertFalse(dialog.finish_action.isEnabled());self.assertFalse(dialog.restore_action.isEnabled())
        self.assertEqual(self.controller.service.inspect(self.client).category,'ready')

    def test_partial_installation_rolls_back_and_finalizes_exact_originals(self):
        self.pending(partial=True);dialog=self.dialog()
        self.assertFalse(dialog.finish_action.isEnabled());self.assertTrue(dialog.restore_action.isEnabled())
        self.yes(dialog,'rollback')
        self.assertEqual(self.snapshot(),self.before);self.assertFalse(self.page._transaction_warnings)
        self.assertIn('restored and rollback finalized',dialog.notice.text())
        self.assertTrue(self.page.action.isEnabled())
        self.assertTrue(list((self.config.standard/'AddonBackups').glob('transaction-*/originals.json')))

    def test_both_confirmations_default_to_cancel_and_preserve_every_byte(self):
        self.pending();dialog=self.dialog();before=self.all_bytes()
        for action in ('complete','rollback'):
            with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as question:
                dialog.resolve(action)
            self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
            self.assertEqual(self.all_bytes(),before);self.assertFalse(dialog.busy);self.assertFalse(self.page.operation_active)
            self.assertTrue(dialog.close_action.isEnabled());self.assertTrue(self.page.picker.isEnabled())
        dialog.reject();self.assertEqual(self.all_bytes(),before);self.assertTrue(self.page._transaction_warnings)

    def test_reopened_page_observed_pending_warning_survives_missing_marker(self):
        self.pending();self.page=self.make_page()
        self.assertTrue(self.page._transaction_warnings)
        dialog=self.dialog();marker=self.client/engine.PENDING_NAME;raw=marker.read_bytes()
        marker.unlink()  # Synthetic external disappearance is NOT verified completion.
        before=self.all_bytes();dialog.check_again();self.page.refresh();dialog.reject()
        self.assertEqual(self.all_bytes(),before);self.assertTrue(self.page._transaction_warnings)
        self.assertFalse(self.page.action.isEnabled());self.assertIn('Recovery required',self.page.transaction_status.text())
        marker.write_bytes(raw);dialog=self.dialog();self.yes(dialog,'rollback')
        self.assertEqual(self.snapshot(),self.before);self.assertFalse(self.page._transaction_warnings)

    def test_incomplete_recovery_then_retry_keeps_evidence_and_restores_bytes(self):
        self.pending(partial=True);dialog=self.dialog()
        with patch.object(engine.os,'replace',side_effect=OSError('private synthetic failure')):self.yes(dialog,'rollback')
        self.assertTrue((self.client/engine.PENDING_NAME).exists());self.assertTrue(self.page._transaction_warnings)
        self.assertNotIn('private synthetic',dialog.notice.text());self.assertFalse(self.page.action.isEnabled())
        dialog.check_again();self.yes(dialog,'rollback')
        self.assertEqual(self.snapshot(),self.before);self.assertFalse(self.page._transaction_warnings)

    def test_already_recovered_originals_still_require_terminal_completion(self):
        self.pending(partial=True)
        root=engine.production_recovery_root(self.client)
        result=engine.recover_pending_transaction(self.client,root)
        self.assertEqual(result['state'],'rollback_complete');self.assertTrue((self.client/engine.PENDING_NAME).exists())
        dialog=self.dialog();self.assertFalse(dialog.finish_action.isEnabled());self.yes(dialog,'rollback')
        self.assertEqual(self.snapshot(),self.before);self.assertFalse(self.page._transaction_warnings)

    def test_invalid_ambiguous_and_changed_destinations_disable_mutation(self):
        self.pending();dialog=self.dialog();marker=self.client/engine.PENDING_NAME;raw=marker.read_bytes()
        marker.write_bytes(b'{');before=self.all_bytes();dialog.check_again()
        self.assertFalse(dialog.finish_action.isEnabled());self.assertFalse(dialog.restore_action.isEnabled())
        self.assertIn('manual review',dialog.state.text());self.assertEqual(self.all_bytes(),before)
        marker.write_bytes(raw)
        destination=self.client/'Interface/AddOns/WFCore/module.lua';destination.write_bytes(b'external data')
        before=self.all_bytes();dialog.check_again()
        self.assertFalse(dialog.restore_action.isEnabled());self.assertEqual(self.all_bytes(),before)
        self.assertEqual(destination.read_bytes(),b'external data')

    def test_missing_and_conflicting_configuration_never_provisions(self):
        self.pending();dialog=self.dialog()
        state=self.config.standard;parked=state.with_name('held-state');state.rename(parked)
        before=self.all_bytes();dialog.check_again()
        self.assertFalse(dialog.finish_action.isEnabled());self.assertFalse(dialog.restore_action.isEnabled())
        self.assertEqual(self.all_bytes(),before);self.assertFalse(state.exists())
        parked.rename(state);dialog.reject()
        self.page=self.make_page(GuiAddonTransactions(self.config,custom_state=self.root/'other-state'))
        dialog=self.dialog();self.assertIn('unavailable',dialog.configuration.text())
        self.assertFalse(dialog.restore_action.isEnabled());self.assertFalse((self.root/'other-state').exists())

    def test_busy_client_is_read_only_until_reopened_with_confirmed_configuration(self):
        self.pending();before=self.all_bytes()
        with engine.installation_lock(self.client):
            dialog=self.dialog();self.assertIn('Another addon operation',dialog.state.text())
            self.assertFalse(dialog.restore_action.isEnabled());dialog.check_again()
        self.assertEqual(self.all_bytes(),before)
        dialog.check_again();self.assertFalse(dialog.restore_action.isEnabled())
        dialog.reject();dialog=self.dialog();self.assertTrue(dialog.restore_action.isEnabled())

    def test_page_selection_change_and_junction_retarget_cannot_mutate_peer(self):
        import _winapi
        self.pending();dialog=self.dialog()
        peer=self.root/'peer'/'_classic_beta_';peer.mkdir(parents=True);(peer/'Wow.exe').touch()
        self.page.remember_client(peer);before=self.all_bytes();self.yes(dialog,'complete')
        self.assertEqual(self.all_bytes(),before);self.assertFalse(dialog.finish_action.isEnabled())
        self.page.remember_client(self.client);dialog.reject();dialog=self.dialog()
        alias=self.root/'client-alias';_winapi.CreateJunction(str(self.client),str(alias))
        dialog.target=self.controller.capture_recovery(alias)
        real=engine.installation_lock;armed=True
        @contextmanager
        def retarget(client):
            nonlocal armed
            with real(client) as identity:
                if armed:
                    armed=False;alias.rmdir();_winapi.CreateJunction(str(peer),str(alias))
                yield identity
        try:
            before=self.snapshot()
            with real(peer),patch.object(engine,'installation_lock',retarget):self.yes(dialog,'rollback')
            self.assertEqual(self.snapshot(),before);self.assertFalse((peer/'Interface').exists())
            self.assertTrue((self.client/engine.PENDING_NAME).exists())
            self.assertFalse(dialog.restore_action.isEnabled())
        finally:
            if alias.is_junction():alias.rmdir()

    def test_directory_replaced_after_confirmation_is_rejected(self):
        self.pending();dialog=self.dialog();parked=self.root/'held-client'
        def confirm(*args):
            self.client.rename(parked);self.client.mkdir();(self.client/'Wow.exe').touch()
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',confirm):dialog.resolve('rollback')
        self.assertTrue((parked/engine.PENDING_NAME).exists());self.assertFalse((self.client/'Interface').exists())
        self.assertTrue(self.page._transaction_warnings);self.assertFalse(dialog.restore_action.isEnabled())

    def test_configuration_change_after_confirmation_blocks_recovery(self):
        self.pending();dialog=self.dialog();before=self.snapshot()
        path,_=self.config._paths(engine.client_identity(self.client))
        def confirm(*args):
            path.write_bytes(b'{}');return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',confirm):dialog.resolve('complete')
        self.assertEqual(self.snapshot(),before);self.assertTrue((self.client/engine.PENDING_NAME).exists())
        self.assertTrue(self.page._transaction_warnings);self.assertFalse(dialog.finish_action.isEnabled())

    def test_different_pending_transaction_after_confirmation_is_not_completed(self):
        self.pending();dialog=self.dialog();replacement=[]
        def confirm(*args):
            self.assertTrue(self.controller.service.complete(self.client).ok)
            with patch.object(engine,'_publish_completion_receipt',side_effect=OSError('synthetic receipt')):
                result=self.controller.service.install(self.payload,self.client,['WFProfessions'])
            self.assertEqual(result.category,'finalization_pending');replacement.append(self.all_bytes())
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox,'question',confirm):dialog.resolve('complete')
        self.assertEqual(self.all_bytes(),replacement[0]);self.assertTrue((self.client/engine.PENDING_NAME).exists())
        self.assertIn('unresolved',dialog.notice.text());self.assertTrue(self.page._transaction_warnings)

    def late_outcome(self,action):
        self.pending();dialog=self.dialog();real=self.controller.resolve_recovery
        def late(*args):
            result=real(*args)
            return ServiceResult('finalization_pending','lock_or_postcheck',
                                 dict(operation_result=result,late_error=OSError('private sentinel')))
        with patch.object(self.controller,'resolve_recovery',late):self.yes(dialog,action)
        self.assertIn('later operation check failed',dialog.notice.text());self.assertNotIn('private sentinel',dialog.notice.text())
        self.assertFalse((self.client/engine.PENDING_NAME).exists());self.assertTrue(self.page._transaction_warnings)
        dialog.check_again();self.page.refresh();dialog.reject()
        self.assertTrue(self.page._transaction_warnings);self.assertFalse(self.page.action.isEnabled())
        reopened=self.dialog();self.assertIn('No pending',reopened.state.text());self.assertTrue(self.page._transaction_warnings)
        return dialog

    def test_verified_installation_late_error_and_no_pending_do_not_clear_warning(self):
        self.late_outcome('complete');self.assertEqual((self.client/'Interface/AddOns/WFStorage/module.lua').read_bytes(),(self.payload/'WFStorage/module.lua').read_bytes())

    def test_verified_rollback_late_error_is_not_installation_success(self):
        self.late_outcome('rollback');self.assertEqual(self.snapshot(),self.before)

    def test_duplicate_actions_close_and_event_pumping_are_prevented(self):
        self.pending();dialog=self.dialog();real=self.controller.resolve_recovery;calls=[]
        def guarded(*args):
            calls.append(args);self.assertTrue(self.page.operation_active);self.assertTrue(dialog.busy)
            for widget in (dialog.check_action,dialog.close_action,self.page.picker,self.page.recovery_action,self.host.page_picker):self.assertFalse(widget.isEnabled())
            dialog.resolve('rollback');dialog.check_again();dialog.reject();self.page.install_selected();self.page.review_recovery()
            event=QCloseEvent();self.host.closeEvent(event);self.assertFalse(event.isAccepted())
            with patch.object(QApplication,'processEvents',side_effect=AssertionError('Event pump during mutation')):return real(*args)
        with patch.object(self.controller,'resolve_recovery',guarded):self.yes(dialog,'complete')
        self.assertEqual(len(calls),1);self.assertFalse(self.page.operation_active);self.assertFalse(dialog.busy)
        self.assertTrue(dialog.close_action.isEnabled());self.assertTrue(self.page.picker.isEnabled())

    def test_unexpected_failures_are_sanitized_and_disable_unverified_actions(self):
        self.pending();dialog=self.dialog()
        with patch.object(self.controller,'resolve_recovery',side_effect=RuntimeError('private sentinel')),\
             patch.object(self.controller,'recovery_summary',side_effect=RuntimeError('private sentinel')):
            self.yes(dialog,'rollback')
        self.assertNotIn('private sentinel',dialog.notice.text());self.assertIn('could not be verified',dialog.notice.text())
        self.assertFalse(dialog.finish_action.isEnabled());self.assertFalse(dialog.restore_action.isEnabled())
        self.assertTrue(dialog.close_action.isEnabled());self.assertFalse(self.page.operation_active)
        self.assertTrue(self.page._transaction_warnings);self.assertTrue((self.client/engine.PENDING_NAME).exists())

    def test_dialog_layout_keeps_actions_readable_at_larger_fonts(self):
        self.pending();dialog=self.dialog()
        self.check_layout(dialog)

    def test_reporting_layout_keeps_the_new_action_readable_at_larger_fonts(self):
        self.reporting_pending();dialog=self.dialog()
        self.assertTrue(dialog.report_action.isVisible())
        self.check_layout(dialog)

    def check_layout(self,dialog):
        for size in (10,16):
            # The theme's QWidget stylesheet overrides direct setFont() calls.
            self.host.settings['text_size']=size;self.host.apply_appearance()
            dialog.resize(700,540);self.app.processEvents()
            buttons=tuple(button for button in (dialog.finish_action,dialog.restore_action,dialog.report_action,
                                                dialog.check_action,dialog.close_action) if button.isVisible())
            labels=(dialog.client,dialog.addons,dialog.state,dialog.configuration,dialog.explanation,dialog.notice)
            for widget in (dialog,*buttons,*labels):
                self.assertAlmostEqual(widget.font().pointSizeF(),size)
            for button in buttons:
                self.assertGreaterEqual(button.width(),button.fontMetrics().horizontalAdvance(button.text())+12)
                self.assertTrue(dialog.rect().contains(button.geometry()))
            for label in labels:
                self.assertTrue(label.wordWrap());self.assertEqual(label.textFormat().name,'PlainText')
                self.assertGreaterEqual(label.height(),label.heightForWidth(label.width()))
                self.assertTrue(dialog.rect().contains(label.geometry()))


if __name__=='__main__':unittest.main()
