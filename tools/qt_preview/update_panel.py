"""Background update checks, visible progress and confirmed update/restart."""
import sys
import hashlib
from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Signal
from PySide6.QtWidgets import QCheckBox,QMessageBox,QProgressBar
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


class Updates(Panel):
    def __init__(self,host):
        super().__init__(host,'Companion updates');self.host=host;self.busy=False;self.release=None;self.installer=None;self.notified=set();self.prompt=None;self.auto_install=False
        self.path=host.data.directory/'updates.json';self.settings={'automatic':bool(getattr(sys,'frozen',False))}
        if self.path.exists():
            import json
            try:
                raw=json.loads(self.path.read_text());self.settings={'automatic':raw['automatic']} if type(raw.get('automatic')) is bool else self.settings
            except (ValueError,OSError):pass
        self.notice=label(f'Version {releases.VERSION} Â· stable releases only. No character data is sent.');self.box.addWidget(self.notice)
        self.automatic=QCheckBox('Check for stable updates automatically');self.automatic.setChecked(self.settings['automatic']);self.automatic.toggled.connect(self.toggle)
        self.box.addWidget(self.automatic)
        self.download_button=host.button('Download update',lambda:self.download(True));self.download_button.setEnabled(False)
        self.install_button=host.button('Update and restart',self.install);self.install_button.setEnabled(False)
        self.check_button=host.button('Check for updates',self.check)
        self.box.addWidget(row(self.check_button,self.download_button,self.install_button))
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.hide();self.box.addWidget(self.progress)
        self.timer=QTimer(self);self.timer.setInterval(6*60*60*1000);self.timer.timeout.connect(self.check)
        if self.settings['automatic']:self.timer.start();QTimer.singleShot(5000,self.check)
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
            box=QMessageBox(self.host);box.setWindowTitle('WFCompanion update available')
            box.setText('Version '+result['version']+' is available. Download it now? You can keep working during the download. Restart requires your confirmation.')
            accept=box.addButton('Download update',QMessageBox.ButtonRole.AcceptRole)
            box.addButton('Cancel',QMessageBox.ButtonRole.RejectRole)
            box.finished.connect(lambda _:self.download(True) if box.clickedButton()==accept else None)
            self.prompt=box;box.open()
    def show_progress(self,received,total):
        percent=min(100,received*100//max(1,total))
        self.progress.setValue(percent)
        self.notice.setText(f'Downloading update: {percent}% ({received/1048576:.1f} / {total/1048576:.1f} MB)')
    def download(self,auto_install=False):
        if self.busy or not self.release:return
        self.auto_install=auto_install;self.installer=None;self.progress.setValue(0);self.progress.show()
        self.notice.setText('Connecting to download…')
        release=dict(self.release)
        self.run_job(lambda:releases.download(release,self.host.data.directory/'updates',self.job.result.progress.emit),self.downloaded)
    def downloaded(self,result,error):
        self.busy=False;self.installer=result;self.buttons()
        self.installer_hash=hashlib.sha256(result.read_bytes()).hexdigest() if result else None
        self.notice.setText('Download failed; nothing was installed. Please try again. '+error if error else 'Download verified. Ready to update and restart.')
        if result:
            self.progress.setValue(100)
            if self.auto_install:self.install()
    def install(self):
        if self.busy or not self.installer or not self.installer.is_file():return
        if hashlib.sha256(self.installer.read_bytes()).hexdigest()!=self.installer_hash:
            self.installer=None;self.buttons();self.notice.setText('Downloaded installer changed; download it again.');return
        if self.host.data.dirty or self.host.settings!=self.host.saved or self.host.qt_settings!=self.host.saved_qt:
            self.notice.setText('Save or discard unsaved settings and applied records before updating.');return
        answer=QMessageBox.question(self.host,'Update and restart',
            'Save any unfinished editor fields first; they will not survive restart. Update now? Your saved settings and records are kept. The companion will close, update with a progress window, and reopen automatically.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
        if answer!=QMessageBox.StandardButton.Yes:return
        from update_restart import start_update
        try:
            helper=start_update(self.installer,self.installer_hash,self.host.data.directory/'updates')
            if not self.host.close():helper.terminate()
        except (OSError,ValueError) as exc:self.notice.setText(str(exc))
