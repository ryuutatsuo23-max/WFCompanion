"""User-triggered bundled addon installation; development sources are never offered."""
from pathlib import Path
import sys
import json
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import Qt
from app import Panel, label, row
from storage import write_json

if not getattr(sys,'frozen',False):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'distribution'))
from install_addons import install, validate_client, safe_target, package_files, package_metadata, check_legacy


class AddonsPage(Panel):
    def __init__(self,host,*,payload=None,clients=None):
        super().__init__(host,'Addons');self.host=host
        self.payload=Path(payload).resolve() if payload else (Path(sys._MEIPASS)/'payload/addons' if getattr(sys,'frozen',False) else None)
        self.path=host.data.directory/'addon_connection.json';self.client=None
        self.folder=label('Choose your WoW Forever client folder.');self.folder.setWordWrap(True)
        self.folder.setTextFormat(Qt.TextFormat.PlainText);self.box.addWidget(self.folder)
        self.box.addWidget(row(host.button('Choose game folder',self.choose),host.button('Refresh',self.refresh)))
        self.status=label('');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.box.addWidget(label('Forever Core'))
        self.box.addWidget(label('Shared character records and save guidance. Required by Forever Storage and Forever Professions.'))
        self.core_status=label('');self.core_status.setWordWrap(True);self.box.addWidget(self.core_status)
        self.core_action=host.button('Install Forever Core',lambda:self.install_selected('WFCore'));self.box.addWidget(self.core_action)
        self.box.addWidget(label('Forever Storage'))
        self.box.addWidget(label('View and organize bags and bank in game.'))
        self.box.addWidget(self.status)
        self.box.addWidget(label('Includes required Forever Core.'))
        self.action=host.button('Install Forever Storage',self.install_selected);self.box.addWidget(self.action)
        self.box.addWidget(label('Forever Professions'))
        description=label('View saved professions and recipes in game. Includes required Forever Core.\nCompanion import is not available yet.');description.setWordWrap(True);self.box.addWidget(description)
        self.professions_status=label('');self.professions_status.setWordWrap(True);self.professions_status.setTextFormat(Qt.TextFormat.PlainText);self.box.addWidget(self.professions_status)
        self.professions_action=host.button('Install Forever Professions',lambda:self.install_selected('WFProfessions'));self.box.addWidget(self.professions_action)
        note=label('Existing addon files are backed up. Game saves and other addons are kept.\n'
                   'WoW can stay open during copying. Reload updated addons with /reload; newly added addons or assets may require a full game restart.')
        note.setWordWrap(True);self.box.addWidget(note)
        self.details=label('');self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText);self.details.hide()
        self.box.addWidget(host.button('Details',lambda:self.details.setVisible(not self.details.isVisible())))
        self.box.addWidget(self.details)
        self.notice=label('');self.notice.setWordWrap(True);self.notice.setTextFormat(Qt.TextFormat.PlainText);self.box.addWidget(self.notice)
        try:
            if self.path.exists():self.client=validate_client(json.loads(self.path.read_text(encoding='utf-8'))['client'])
        except (OSError,ValueError,KeyError,TypeError):
            self.notice.setText('The saved game folder is unavailable. Choose it again.')
        if self.client is None:
            candidates=clients if clients is not None else [Path(r'C:\Program Files (x86)\World of Warcraft')/name for name in ('_forever_','_classic_beta_')]
            found=[]
            for candidate in candidates:
                try:found.append(validate_client(candidate))
                except (OSError,ValueError):pass
            if len(found)==1:self.client=found[0]
            elif len(found)>1:self.notice.setText('Multiple clients found. Choose the one you want to use.')
        self.refresh()

    def choose(self):
        selected=QFileDialog.getExistingDirectory(self,'Choose WoW Forever client folder',str(self.client or ''))
        if selected:
            try:
                client=validate_client(selected)
                write_json(self.path,dict(client=str(client)));self.client=client
                self.notice.setText('Game folder remembered.');self.refresh()
            except (OSError,ValueError) as exc:self.notice.setText(str(exc))

    def package_files(self,names=('WFCore','WFStorage')):
        if self.payload is None:raise ValueError('Release package pending. Development addon sources are not offered for installation.')
        files=[]
        for name in names:
            for source in package_files(self.payload,name):
                files.append((name,source))
        return files

    def refresh(self):
        self.action.setEnabled(False);self.core_action.setEnabled(False);self.professions_action.setEnabled(False);self.different=False;self.package_details={}
        self.folder.setText(str(self.client) if self.client else 'Choose your WoW Forever client folder.')
        self.refresh_entry(('WFCore',),self.core_status,self.core_action,'Forever Core')
        self.different=self.refresh_entry(('WFCore','WFStorage'),self.status,self.action,'Forever Storage')
        self.professions_different=self.refresh_entry(('WFCore','WFProfessions'),self.professions_status,self.professions_action,'Forever Professions')

    def refresh_entry(self,names,status,action,title):
        try:
            files=self.package_files(names)
            metadata=package_metadata(self.payload,names)
            if self.client is None:status.setText('Select a game folder to check installed addons.');return False
            validate_client(self.client)
            check_legacy(self.client)
            present=0;matched=0
            for name,source in files:
                target=safe_target(self.client/'Interface/AddOns'/source.relative_to(self.payload),self.client)
                if target.exists():
                    present+=1
                    if target.read_bytes()==source.read_bytes():matched+=1
            # Missing files need installation, not permission to replace an
            # existing revision. Matching dependency files are not a conflict.
            different=present!=matched
            status.setText('Installed · matches bundled package' if matched==len(files) else
                                'Installed files differ from bundled package' if different else
                                'Ready to install missing files' if present else 'Not installed')
            action.setText('Install bundled '+title if different else 'Installed' if matched==len(files) else 'Install '+title)
            action.setEnabled(matched!=len(files))
            self.package_details.update(metadata)
            identities='\n'.join(f'{name}: {info["version"]} ({info["source_commit"][:7]})' for name,info in self.package_details.items())
            self.details.setText(identities+f'\nPackage: {self.payload}\nBackups and installation receipts: {self.host.data.directory / "AddonBackups"}\n'
                                 'Status compares file contents, not version labels. Different files may be newer or locally modified. Extra existing files are retained.')
            return different
        except (OSError,ValueError) as exc:status.setText(str(exc));return False

    def install_selected(self,addon='WFStorage'):
        if addon not in ('WFCore','WFStorage','WFProfessions'):return
        self.refresh()
        action={'WFCore':self.core_action,'WFStorage':self.action,'WFProfessions':self.professions_action}[addon]
        different={'WFCore':self.core_status.text()=='Installed files differ from bundled package','WFStorage':self.different,'WFProfessions':self.professions_different}[addon]
        if not action.isEnabled():return
        if different and QMessageBox.question(self.host,'Replace addon files?',
                'Installed files differ and may be newer or locally modified. Back them up and replace matching files with the bundled version?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
        action.setEnabled(False)
        try:
            install(self.payload,self.client,[addon],self.host.data.directory/'AddonBackups')
            write_json(self.path,dict(client=str(self.client)))
            title={'WFCore':'Forever Core','WFStorage':'Forever Storage and Forever Core','WFProfessions':'Forever Professions and Forever Core'}[addon]
            self.notice.setText('Installed '+title+'. Existing code was backed up; your game saves are unchanged. See the reload/restart note above.')
        except (OSError,ValueError) as exc:self.notice.setText('Installation did not finish: '+str(exc))
        self.refresh()
