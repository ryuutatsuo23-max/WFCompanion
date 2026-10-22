"""Background update checks; installer launch is explicit and never closes editors."""
import os
import sys
import hashlib
from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Signal
from PySide6.QtWidgets import QCheckBox,QMessageBox
from app import Panel,label,row
from storage import write_json
import release_updates as releases


class Result(QObject):
    done=Signal(object,str)


class Job(QRunnable):
    def __init__(self,work):
        super().__init__();self.work=work;self.result=Result()
    def run(self):
        try:self.result.done.emit(self.work(),'')
        except Exception as exc:self.result.done.emit(None,str(exc))


class Updates(Panel):
    def __init__(self,host):
        super().__init__(host,'Companion updates');self.host=host;self.busy=False;self.release=None;self.installer=None
        self.path=host.data.directory/'updates.json';self.settings={'automatic':bool(getattr(sys,'frozen',False))}
        if self.path.exists():
            import json
            try:
                raw=json.loads(self.path.read_text());self.settings={'automatic':raw['automatic']} if type(raw.get('automatic')) is bool else self.settings
            except (ValueError,OSError):pass
        self.notice=label(f'Version {releases.VERSION} · stable releases only. No character data is sent.');self.box.addWidget(self.notice)
        self.automatic=QCheckBox('Check for stable updates automatically');self.automatic.setChecked(self.settings['automatic']);self.automatic.toggled.connect(self.toggle)
        self.box.addWidget(self.automatic)
        self.download_button=host.button('Download update',self.download);self.download_button.setEnabled(False)
        self.install_button=host.button('Open downloaded installer',self.install);self.install_button.setEnabled(False)
        self.box.addWidget(row(host.button('Check for updates',self.check),self.download_button,self.install_button))
        self.timer=QTimer(self);self.timer.setInterval(6*60*60*1000);self.timer.timeout.connect(self.check)
        if self.settings['automatic']:self.timer.start();QTimer.singleShot(5000,self.check)
    def toggle(self,value):
        try:write_json(self.path,{'automatic':value})
        except (ValueError,OSError) as exc:self.notice.setText(str(exc));return
        self.settings['automatic']=value
        if value:self.timer.start();self.check()
        else:self.timer.stop()
    def run_job(self,work,done):
        if self.busy:return
        self.busy=True;self.job=Job(work);self.job.result.done.connect(done);QThreadPool.globalInstance().start(self.job)
    def check(self):
        if getattr(self.host,'testing',False):return
        self.run_job(releases.check,self.checked)
    def checked(self,result,error):
        self.busy=False;self.release=result;self.download_button.setEnabled(bool(result))
        self.notice.setText('Update check unavailable; your installed version still works.' if error else 'No newer stable release available.' if not result else 'Stable update available: '+result['version']+'. Download when convenient.')
    def download(self):
        if self.release:self.run_job(lambda:releases.download(self.release,self.host.data.directory/'updates'),self.downloaded)
    def downloaded(self,result,error):
        self.busy=False;self.installer=result;self.install_button.setEnabled(bool(result))
        self.installer_hash=hashlib.sha256(result.read_bytes()).hexdigest() if result else None
        self.notice.setText('Download failed verification; nothing was installed.' if error else 'Download verified. Save your work, then open the installer. The installer requires the companion to be closed.')
    def install(self):
        if not self.installer or not self.installer.is_file():return
        if hashlib.sha256(self.installer.read_bytes()).hexdigest()!=self.installer_hash:
            self.install_button.setEnabled(False);self.notice.setText('Downloaded installer changed; download it again.');return
        if self.host.data.dirty:
            self.notice.setText('Save or discard applied changes before updating. Unfinished fields stay here.');return
        answer=QMessageBox.question(self.host,'Open update installer','Save any unfinished editor fields first. Open the installer now? This will not close the companion; close it yourself when ready.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Yes:os.startfile(str(self.installer))
