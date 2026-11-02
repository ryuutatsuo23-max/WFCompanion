"""Explicit, read-only-first addon recovery UI; no optional service imports.

The Addons transaction adapter opens this dialog; isolated startup excludes it. Eligibility is
advisory; consent is bound to the inspected transaction and rechecked by the service.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QLabel
from PySide6.QtWidgets import QMessageBox


NAMES={'WFCore':'Forever Core','WFStorage':'Forever Storage','WFProfessions':'Forever Professions'}


def text(value=''):
    label=QLabel(value);label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class AddonRecoveryDialog(QDialog):
    def __init__(self,page):
        super().__init__(page.host)
        self.page=page;self.controller=page.transactions;self.selected=page.client
        self.target=None;self.advice=None;self.busy=False
        self.setWindowTitle('Review addon recovery');self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setPalette(page.host.palette());self.resize(650,420)
        box=QVBoxLayout(self);box.setContentsMargins(20,20,20,20);box.setSpacing(14)
        self.client=text();self.addons=text();self.state=text();self.configuration=text();self.explanation=text()
        self.notice=text(page._transaction_warnings.get(page._client_key(self.selected),''))
        for widget in (self.client,self.addons,self.state,self.configuration,self.explanation,self.notice):box.addWidget(widget)
        box.addStretch(1)
        buttons=QGridLayout();box.addLayout(buttons)
        self.check_action=page.host.button('Check again',self.check_again)
        self.finish_action=page.host.button('Finish installation',lambda:self.resolve('complete'))
        self.restore_action=page.host.button('Restore previous files',lambda:self.resolve('rollback'))
        self.report_action=page.host.button('Finish reporting',lambda:self.resolve('report'))
        self.close_action=page.host.button('Close',self.reject)
        for button in (self.check_action,self.finish_action,self.restore_action,self.report_action,self.close_action):button.setAutoDefault(False)
        self.close_action.setDefault(True)
        buttons.addWidget(self.finish_action,0,0);buttons.addWidget(self.restore_action,0,1)
        buttons.addWidget(self.report_action,1,0,1,2)
        buttons.addWidget(self.check_action,2,0);buttons.addWidget(self.close_action,2,1)
        try:self.target=self.controller.capture_recovery(self.selected)
        except Exception:pass  # Fixed text only; keep Close and read-only inspection available.
        self.client.setText('Game client: '+str(self.target.client if self.target else self.selected))
        self.check_again()

    def same_selection(self):
        return self.page.client==self.selected and self.page.transactions is self.controller

    def disable_mutations(self):
        self.finish_action.setEnabled(False);self.restore_action.setEnabled(False);self.report_action.setEnabled(False)
        self.report_action.setVisible(False)

    def check_again(self):
        if self.busy or self.page.operation_active:return
        self.advice=None;self.disable_mutations()
        self.addons.setText('Affected addons: unavailable until evidence is verified.')
        self.configuration.setText('Backup configuration: unavailable.')
        if self.target is None or not self.same_selection():
            self.state.setText('Client selection could not be verified.')
            self.explanation.setText('Close this dialog and review the selected game folder. No recovery was attempted.')
            return
        try:self.advice=self.controller.recovery_summary(self.target)
        except Exception:
            self.state.setText('Recovery state could not be verified.')
            self.explanation.setText('Preserve all evidence. Check again or request manual review. No recovery was attempted.')
            return
        info=self.advice
        if info.pending!='none' and info.inspection!='busy':
            # Also retain evidence first observed here, not only install failures.
            self.page._transaction_warnings.setdefault(self.page._client_key(self.selected),
                'Unfinished addon installation — Recovery required. Preserve backups and recovery evidence.')
        if info.addons:self.addons.setText('Affected addons: '+', '.join(NAMES[n] for n in info.addons if n in NAMES))
        self.configuration.setText('Backup configuration: '+('available and verified.' if info.configuration=='available' else 'unavailable or conflicting.'))
        if info.inspection=='busy':
            state='Another addon operation is using this client.'
            explanation='Wait for it to finish, then check again. This dialog has not changed addon files.'
        elif info.pending=='none':
            state='No pending transaction found.'
            explanation='This does not establish whether an earlier operation succeeded. Existing warnings are kept; nothing is restored or removed.'
        elif info.pending=='unresolved' and info.may_report and info.configuration=='available':
            state=('Installed addon files are verified.' if info.verified_outcome=='installation' else
                   'Previous addon files are restored and verified.')
            explanation='Final status reporting was interrupted. Finish reporting to resolve the warning; addon files will not be installed or restored again.'
        elif info.pending=='valid' and info.configuration=='available':
            state='Unfinished addon installation — verified recovery evidence.'
            explanation=('Installed files and retained backups are verified. You can finish receipt and recovery-evidence handling, or restore the previous files.'
                         if info.may_complete else 'The previous files can be restored from verified recovery evidence. Finishing installation is not currently eligible.')
        else:
            state='Recovery requires manual review.'
            explanation='Evidence, destination files or backup configuration are missing, changed or unsafe. Preserve all backups and recovery evidence; no automatic repair is attempted.'
        if self.target.selection is None:
            explanation+=' Resolve the backup configuration or busy client, then reopen this dialog to confirm it.'
        self.state.setText(state);self.explanation.setText(explanation)
        eligible=info.pending=='valid' and info.configuration=='available' and bool(info.transaction_key) and not info.manual_review
        self.finish_action.setEnabled(eligible and info.may_complete)
        self.restore_action.setEnabled(eligible and info.may_rollback)
        self.report_action.setVisible(info.pending=='unresolved')
        self.report_action.setEnabled(info.pending=='unresolved' and info.configuration=='available' and
                                      info.may_report and bool(info.reporting_key) and not info.manual_review)

    def resolve(self,action):
        if action not in ('complete','rollback','report') or self.busy or self.page.operation_active:return
        button={'complete':self.finish_action,'rollback':self.restore_action,'report':self.report_action}[action]
        if not button.isEnabled() or self.advice is None or not self.same_selection():
            self.check_again();return
        transaction_key=self.advice.reporting_key if action=='report' else self.advice.transaction_key
        self.busy=True
        for button in (self.finish_action,self.restore_action,self.report_action,self.check_action,self.close_action):button.setEnabled(False)
        try:
            with self.page.recovery_operation() as permitted:
                if not permitted:return
                question=('Finish reporting this verified outcome? Addon files will not be installed or restored again.'
                          if action=='report' else 'Finish the verified installation and its receipt? This will not install the addons again.'
                          if action=='complete' else 'Restore the addon files from before this installation? Newly installed managed files will be removed when verified safe.')
                question+='\n\nGame client: '+str(self.target.client)+'\nGame saves and unrelated addons are kept.'
                if QMessageBox.question(self,'Confirm addon recovery',question,
                        QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
                if not self.same_selection():
                    self.notice.setText('The selected client changed. Close this dialog and review the game folder. No recovery was started.')
                    return
                # No Qt event pumping during filesystem operations.
                result=self.controller.resolve_recovery(self.target,action,transaction_key)
                summary=result.summary
                self.notice.setText(summary.message)
                self.page.recovery_result(self.selected,summary)
        except Exception:
            self.notice.setText(self.page.recovery_uncertain(self.selected))
        finally:
            self.busy=False;self.close_action.setEnabled(True);self.check_action.setEnabled(True)
            self.check_again()

    def reject(self):
        if not self.busy:super().reject()

    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
