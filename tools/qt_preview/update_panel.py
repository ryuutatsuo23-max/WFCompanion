"""Background update checks, visible progress and confirmed update/restart."""
import sys
import hashlib
from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Signal,Qt,QEvent
from PySide6.QtWidgets import QCheckBox,QMessageBox,QProgressBar,QFrame,QHBoxLayout
from app import Panel,label,row
from storage import write_json
import release_updates as releases


class Result(QObject):
    done=Signal(object,str)
    progress=Signal(int,int)


class Job(QRunnable):
    def __init__(self,work):
        super().__init__();self.work=work;self.result=Result()
    def run(self):
        try:self.result.done.emit(self.work(),'')
        except Exception as exc:self.result.done.emit(None,str(exc))


class UpdateToast(QFrame):
    """Persistent child overlay anchored inside the companion window."""
    def __init__(self,host,version,download):
        super().__init__(host)
        self.setObjectName('updateToast')
        self.setWindowTitle('WF Companion update available')
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        bg=host.colors[1]
        self.setStyleSheet(f'QFrame#updateToast {{ background-color: {bg}; border: 1px solid #bca56c; }}')
        box=QHBoxLayout(self);box.setContentsMargins(10,4,10,4)
        message=label('WF Companion '+version+' is available.')
        message.setToolTip('Download while you keep working. Restart requires confirmation.')
        message.setWordWrap(True);box.addWidget(message,1)
        self.update_button=host.button('Update',lambda:(self.accept(),download()))
        self.cancel_button=host.button('Later',self.reject)
        box.addWidget(self.update_button);box.addWidget(self.cancel_button)
        host.installEventFilter(self)
        self.reposition()

    def accept(self):self.close()
    def reject(self):self.close()

    def reposition(self):
        area=self.parentWidget().contentsRect()
        self.setFixedWidth(max(1,area.width()-32))
        self.adjustSize()
        self.move(max(area.left(),area.right()-self.width()-15),area.top()+16)
        self.raise_()

    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Type.Resize,QEvent.Type.Show):self.reposition()
        return super().eventFilter(watched,event)



class Updates(Panel):
    def __init__(self,host):
        super().__init__(host,'Companion updates');self.host=host;self.busy=False;self.release=None;self.installer=None;self.notified=set();self.prompt=None;self.auto_install=False
        self.path=host.data.directory/'updates.json';self.settings={'automatic':bool(getattr(sys,'frozen',False))}
        if self.path.exists():
            import json
            try:
                raw=json.loads(self.path.read_text());self.settings={'automatic':raw['automatic']} if type(raw.get('automatic')) is bool else self.settings
            except (ValueError,OSError):pass
        self.version_label=label(f'Installed version: {releases.VERSION}');self.box.addWidget(self.version_label)
        self.notice=label('Stable releases only. No character data is sent.');self.box.addWidget(self.notice)
        self.automatic=QCheckBox('Check for stable updates automatically');self.automatic.setChecked(self.settings['automatic']);self.automatic.toggled.connect(self.toggle)
        self.box.addWidget(self.automatic)
        self.download_button=host.button('Download update',lambda:self.download(True));self.download_button.setEnabled(False)
        self.install_button=host.button('Update and restart',self.install);self.install_button.setEnabled(False)
        self.check_button=host.button('Check for updates',self.check)
        self.box.addWidget(row(self.check_button,self.download_button,self.install_button))
        self.full_button=host.button('Download full installer instead',self.download_full);self.full_button.setEnabled(False)
        self.box.addWidget(self.full_button)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.hide();self.box.addWidget(self.progress)
        self.timer=QTimer(self);self.timer.setInterval(5*60*1000);self.timer.timeout.connect(self.auto_check)
        if self.settings['automatic']:self.timer.start();QTimer.singleShot(5000,self.auto_check)
    def auto_check(self):
        if self.settings['automatic'] and not self.installer:self.check()
    def toggle(self,value):
        try:write_json(self.path,{'automatic':value})
        except (ValueError,OSError) as exc:self.notice.setText(str(exc));return
        self.settings['automatic']=value
        if value:self.timer.start();self.check()
        else:self.timer.stop()
    def buttons(self):
        self.check_button.setEnabled(not self.busy)
        self.download_button.setEnabled(not self.busy and bool(self.release))
        self.install_button.setEnabled(not self.busy and bool(self.installer))
        self.full_button.setEnabled(not self.busy and bool(self.release))
    def run_job(self,work,done):
        if self.busy:return
        self.busy=True;self.buttons();self.job=Job(work);self.job.result.done.connect(done);self.job.result.progress.connect(self.show_progress);QThreadPool.globalInstance().start(self.job)
    def check(self):
        if getattr(self.host,'testing',False):return
        if self.busy:return
        self.notice.setText('Checking for updates…')
        self.run_job(releases.check,self.checked)
    def checked(self,result,error):
        self.busy=False;self.release=result;self.buttons()
        self.notice.setText('Update check unavailable; your installed version still works.' if error else 'No newer stable release available.' if not result else 'Stable update available: '+result['version'])
        if result and result['version'] not in self.notified:
            self.notified.add(result['version'])
            if self.prompt:self.prompt.close()
            self.prompt=UpdateToast(self.host,result['version'],lambda:self.download(True))
            self.prompt.show()
    def show_progress(self,received,total):
        percent=min(100,received*100//max(1,total))
        self.progress.setValue(percent)
        self.notice.setText(f'Downloading update: {percent}% ({received/1048576:.1f} / {total/1048576:.1f} MB)')
    def download(self,auto_install=False):
        if self.busy or not self.release:return
        if self.prompt:self.prompt.close()
        self.auto_install=auto_install;self.installer=None;self.progress.setValue(0);self.progress.show()
        self.notice.setText('Connecting to download…')
        release=dict(self.release)
        from incremental_updates import fetch
        self.run_job(lambda:fetch(release,self.host.data.directory/'updates',self.job.result.progress.emit),self.downloaded)
    def download_full(self):
        if self.busy or not self.release:return
        self.release=dict(self.release);self.release.pop('patch',None);self.download(True)
    def downloaded(self,result,error):
        self.busy=False;self.installer=result;self.buttons()
        self.installer_hash=hashlib.sha256(result.read_bytes()).hexdigest() if result else None
        self.notice.setText('Download failed; nothing was installed. Please try again. '+error if error else 'Download verified. Ready to update and restart.')
        if result:
            self.progress.setValue(100)
            if self.auto_install:self.install()
    def confirm_restart(self):
        box=QMessageBox(self.host)
        box.setWindowTitle('Update and restart')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('Update now? The companion will close, update, and reopen automatically.\n\n'
                    'This option saves Settings only. Finish and save any character or item editor fields first; unfinished fields will not survive restart.')
        checkbox=QCheckBox('Save settings before updating',box);checkbox.setChecked(True)
        # Reserve the unchecked indicator's border even when first laid out checked.
        checkbox.ensurePolished()
        checkbox.setMinimumSize(checkbox.sizeHint().width()+8,max(28,checkbox.sizeHint().height()+8))
        box.setCheckBox(checkbox)
        box.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        answer=box.exec();save=checkbox.isChecked();box.deleteLater()
        return answer==QMessageBox.StandardButton.Yes,save

    def install(self):
        if self.busy or not self.installer or not self.installer.is_file():return
        if hashlib.sha256(self.installer.read_bytes()).hexdigest()!=self.installer_hash:
            self.installer=None;self.buttons();self.notice.setText('Downloaded installer changed; download it again.');return
        if self.host.data.dirty:
            self.notice.setText('Save or discard applied records before updating. The save-settings option does not save character or item records.');return
        confirmed,save_settings=self.confirm_restart()
        if not confirmed:return
        settings_changed=self.host.settings!=self.host.saved or self.host.qt_settings!=self.host.saved_qt
        if settings_changed:
            if not save_settings:
                self.notice.setText('Save or discard unsaved settings before updating, or enable Save settings before updating.');return
            if not self.host.save_session():
                self.notice.setText('Update paused: settings could not be saved. '+self.host.session_status.text());return
        if self.host.data.dirty or self.host.settings!=self.host.saved or self.host.qt_settings!=self.host.saved_qt:
            self.notice.setText('Update paused: some changes still need saving.');return
        from update_restart import start_update
        try:
            helper=start_update(self.installer,self.installer_hash,self.host.data.directory/'updates')
            if not self.host.close_behavior.quit():helper.terminate()
        except (OSError,ValueError) as exc:self.notice.setText(str(exc))
