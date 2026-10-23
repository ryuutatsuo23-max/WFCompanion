"""User-driven backup preview and explicit restore-and-close."""
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFileDialog,QPlainTextEdit,QMessageBox
from app import Panel,row
from saved_data_settings import text
import companion_backup as backups


def require_saved(host):
    if host.data.dirty or host.settings!=host.saved or host.qt_settings!=host.saved_qt:
        raise ValueError('Save or revert applied changes and Settings before backup or restore. Finish any editor drafts first.')


class RestorePreview(QDialog):
    def __init__(self,host,path):
        super().__init__(host);self.host=host;self.path=Path(path);self.review=None
        self.setWindowTitle('Preview companion backup');self.setModal(True);self.resize(720,480)
        box=QVBoxLayout(self);box.addWidget(text(str(self.path)))
        self.summary=QPlainTextEdit();self.summary.setReadOnly(True);box.addWidget(self.summary)
        box.addWidget(text('Restore replaces saved companion settings, profiles and plans with this backup. It also removes supported records that were not present in the backup. A recovery backup is saved first. Game saves and addons are never restored or changed.'))
        box.addWidget(text('Finish and save any editor drafts first. The companion will close after restoration; reopen it to load the restored data.'))
        self.status=text('');box.addWidget(self.status)
        self.restore_button=host.button('Restore and close companion',self.restore)
        self.restore_button.setAutoDefault(False)
        self.restore_button.setEnabled(False)
        cancel=host.button('Cancel',self.reject);cancel.setDefault(True)
        box.addWidget(row(self.restore_button,cancel))
        try:
            require_saved(host)
            self.review=backups.inspect(path);self.current=backups.snapshot(host.data.directory)
            missing=[p for p in self.review['sources'] if not Path(p).is_file()]
            self.summary.setPlainText('Created: '+datetime.fromisoformat(self.review['created']).astimezone().strftime('%d %b %Y, %H:%M')+
                '\nCharacters: '+(', '.join(self.review['characters']) or 'None')+
                f"\nSaved companion files: {len(self.review['files'])}"+
                ('\nUnavailable linked saves (reconnect in Settings afterward):\n'+'\n'.join(missing) if missing else '\nLinked save paths are available.' if self.review['sources'] else '\nNo linked game saves in this backup.'))
            self.restore_button.setEnabled(True)
        except (OSError,ValueError) as exc:self.status.setText('Cannot restore this backup: '+str(exc)+'\nNothing has been changed.')

    def restore(self):
        if self.review is None or not self.restore_button.isEnabled():return
        try:
            require_saved(self.host)
            follow=getattr(self.host,'character_follow',None)
            if follow is not None and not follow.shutdown():raise ValueError('Wait for character capture to stop, then try again.')
            self.recovery=backups.restore(self.host.data.directory,self.path,self.review['sha256'],self.current)
        except (OSError,ValueError) as exc:
            self.restore_button.setEnabled(False)
            self.status.setText('Restore did not complete: '+str(exc)+'\nKeep the recovery backup. Reopen the preview before trying again.')
            if (self.host.data.directory/'restore-pending.json').exists():
                self.host.testing=True
                self.host.saved_character_connection.timer.stop()
                self.host.character_overview.game_data_monitor.set_enabled(False)
                QMessageBox.critical(self,'Restore needs recovery','The companion must close to protect partially restored data. Keep the Backups folder; recovery will be attempted when reopening.\n\n'+str(exc))
                self.close_companion()
            return
        self.close_companion()

    def close_companion(self):
        # Prevent close handling from saving the pre-restore window/settings.
        self.host.testing=True
        self.host.saved_character_connection.timer.stop()
        self.host.updates_panel.timer.stop()
        self.host.character_overview.game_data_monitor.set_enabled(False)
        self.accept();self.host.close()


class BackupSettings(Panel):
    def __init__(self,host):
        super().__init__(host,'Companion backup & restore');self.host=host
        self.box.addWidget(text('Back up saved companion settings, characters, plans and saved-file links. Game saves, addons, editor drafts and earlier backups are not included. Save your edits before creating a backup.'))
        self.box.addWidget(row(host.button('Create companion backup',self.create),host.button('Preview backup to restore',self.choose)))
        self.status=text('Backups contain personal character names and file paths. Keep them private.');self.box.addWidget(self.status)

    def create(self):
        try:require_saved(self.host)
        except ValueError as exc:self.status.setText(str(exc));return
        default=self.host.data.directory/'Backups'/('WFCompanion-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
        path,_=QFileDialog.getSaveFileName(self,'Save companion backup',str(default),'Companion backup (*.zip)')
        if not path:return
        try:
            backups.create(self.host.data.directory,path)
            self.status.setText('Backup saved: '+str(path))
        except (OSError,ValueError) as exc:self.status.setText('Backup was not created: '+str(exc))

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'Preview companion backup',str(self.host.data.directory/'Backups'),'Companion backup (*.zip)')
        if path:self.open_preview(path)

    def open_preview(self,path):
        self.dialog=RestorePreview(self.host,path);self.dialog.open()
