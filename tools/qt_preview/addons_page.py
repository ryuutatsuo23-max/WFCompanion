"""User-triggered bundled addon installation; development sources are never offered."""
from pathlib import Path
from contextlib import contextmanager
import sys
import json
from PySide6.QtWidgets import QFileDialog, QMessageBox, QLabel, QFrame, QHBoxLayout, QVBoxLayout, QSizePolicy
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt
from app import Panel, WrappingLabel, row
label = WrappingLabel
from storage import write_json
from addon_art import logo_pixmap

if not getattr(sys,'frozen',False):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'distribution'))
from install_addons import validate_client, safe_target, package_files, package_metadata, check_legacy
from game_folder_picker import GameFolderPicker, find_clients


_DEFAULT_TRANSACTIONS=object()


def current_user_transactions():
    # Native current-user authority, never the window's state directory or an
    # environment-selected fallback. Construction does not provision anything.
    from addon_installation_configuration import InstallationConfiguration
    from addon_installation_gui import GuiAddonTransactions
    return GuiAddonTransactions(InstallationConfiguration())


class AddonsPage(Panel):
    def __init__(self,host,*,payload=None,clients=None,transactions=_DEFAULT_TRANSACTIONS):
        super().__init__(host,'Addons');self.host=host
        self.transaction_error=''
        if getattr(host,'isolation',None) is not None:
            host.isolation.verify()
            if (transactions is not _DEFAULT_TRANSACTIONS and transactions is not None) or (host.data.directory/'addon_connection.json').exists():
                raise ValueError('Isolated Addons page requires fresh state and no installer adapter.')
            transactions=None
        elif transactions is _DEFAULT_TRANSACTIONS:
            try:transactions=current_user_transactions()
            except Exception:
                # Configuration/import/account errors never select the old writer.
                transactions=None
                self.transaction_error='Addon installation is unavailable. Open Companion normally (not as administrator) and check the addon backup configuration. No installation was started.'
        self.transactions=transactions;self.operation_active=False;self._transaction_warnings={}
        self.payload=Path(payload).resolve() if payload else (Path(sys._MEIPASS)/'payload/addons' if getattr(sys,'frozen',False) else None)
        self.path=host.data.directory/'addon_connection.json';self.client=None
        self.cards={};self.icons={};self.entry_errors={}
        self.refresh_action=host.button('Refresh addon status',self.refresh)
        self.box.addWidget(row(self.refresh_action))
        self.core_status=label('');self.status=label('');self.professions_status=label('')
        self.core_action=host.button('Install Forever Core',lambda:self.install_selected('WFCore'))
        self.action=host.button('Install Forever Storage',self.install_selected)
        self.professions_action=host.button('Install Forever Professions',lambda:self.install_selected('WFProfessions'))
        for addon,title,description,status,action in (
            ('WFCore','Forever Core','Shared character saves for your Forever addons.',self.core_status,self.core_action),
            ('WFStorage','Forever Storage','Bags and bank, organized. Includes Forever Core.',self.status,self.action),
            ('WFProfessions','Forever Professions','Saved professions and recipes. Includes Forever Core.',self.professions_status,self.professions_action)):
            self.add_card(addon,title,description,status,action)
        note=label('Existing files are backed up; game saves are kept. WoW can stay open. Use /reload after updating; new addons or artwork may need a game restart.')
        self.box.addWidget(note)
        self.details=label('');self.details.setTextFormat(Qt.TextFormat.PlainText);self.details.hide()
        self.box.addWidget(host.button('Installation details',lambda:self.details.setVisible(not self.details.isVisible())))
        self.box.addWidget(self.details)
        self.notice=label('');self.notice.setTextFormat(Qt.TextFormat.PlainText);self.box.addWidget(self.notice)
        unavailable='';has_saved=self.path.exists()
        try:
            saved=json.loads(self.path.read_text(encoding='utf-8')).get('client') if self.path.exists() else None
            if saved:self.client=validate_client(saved)
        except (OSError,ValueError,KeyError,TypeError,AttributeError,RuntimeError):
            unavailable=str(locals().get('saved') or self.path)
        self.picker=GameFolderPicker(host,roots=clients,selected=self.client,auto_select=not has_saved,unavailable=unavailable,compact=True)
        self.client=self.picker.client;self.folder=self.picker.target
        self.box.insertWidget(1,self.picker)
        self.transaction_status=label('');self.transaction_status.setTextFormat(Qt.TextFormat.PlainText)
        self.transaction_status.setVisible(getattr(host,'isolation',None) is None)
        self.box.insertWidget(2,self.transaction_status)
        self.recovery_action=None;self.recovery_dialog=None
        if transactions is not None:
            self.recovery_action=host.button('Review addon recovery',self.review_recovery)
            self.box.insertWidget(3,row(self.recovery_action))

        self.picker.selectionChanged.connect(self.remember_client)
        self.refresh()

    def add_card(self,addon,title,description,status,action):
        card=QFrame();card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Maximum)
        layout=QHBoxLayout(card);layout.setContentsMargins(12,12,12,12);layout.setSpacing(16)
        icon=QLabel();icon.setFixedSize(88,88);icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setAccessibleName(title+' logo');self.icons[addon]=icon
        root=Path(__file__).resolve().parents[2]
        if addon=='WFCore':
            # Bundled resources live inside payload; extracted-payload checks use
            # the same layout without PyInstaller's frozen flag.
            path=(Path(sys._MEIPASS)/'payload' if getattr(sys,'frozen',False) else root)/'branding/forever.ico'
            if not path.is_file():path=root/'tools/distribution/public_art/wfcompanion-compass.png'
            pixmap=QIcon(str(path)).pixmap(88,88)
        else:
            pixmap=logo_pixmap(addon)
        if not pixmap.isNull():icon.setPixmap(pixmap.scaled(88,88,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else:icon.setText('WF')
        layout.addWidget(icon,0,Qt.AlignmentFlag.AlignTop)
        body=QVBoxLayout();body.setSpacing(6);layout.addLayout(body,1)
        body.addWidget(label('<b>'+title+'</b>'));body.addWidget(label(description))
        status.setWordWrap(True);status.setTextFormat(Qt.TextFormat.PlainText);body.addWidget(status)
        body.addWidget(row(action));self.box.addWidget(card);self.cards[addon]=card

    def choose(self):
        if not self.operation_active:self.picker.choose()

    def remember_client(self,client):
        if getattr(self.host,'isolation',None) is not None:return False
        if self.operation_active:return False
        try:
            write_json(self.path,dict(client=str(client) if client else None))
        except (OSError,ValueError) as exc:
            self.picker.client=self.client;self.picker.populate(find_clients(self.picker.roots+([self.client] if self.client else [])))
            self.notice.setText('Folder choice was not saved: '+str(exc));return False
        self.client=client
        self.picker.client=client
        if client:self.picker.roots.append(client)
        self.picker.populate(find_clients(self.picker.roots))
        self.notice.setText('Game folder remembered.' if client else 'No game folder selected. Continue offline or choose a folder.')
        self.refresh();return True

    def package_files(self,names=('WFCore','WFStorage')):
        if self.payload is None:raise ValueError('Release package pending. Development addon sources are not offered for installation.')
        files=[]
        for name in names:
            for source in package_files(self.payload,name):
                files.append((name,source))
        return files

    def refresh(self):
        if getattr(self.host,'isolation',None) is not None:self.host.isolation.verify()
        if self.operation_active:return
        self.action.setEnabled(False);self.core_action.setEnabled(False);self.professions_action.setEnabled(False);self.different=False;self.package_details={};self.entry_errors={}
        self.picker.describe()
        self.refresh_entry(('WFCore',),self.core_status,self.core_action,'Forever Core')
        self.different=self.refresh_entry(('WFCore','WFStorage'),self.status,self.action,'Forever Storage')
        self.professions_different=self.refresh_entry(('WFCore','WFProfessions'),self.professions_status,self.professions_action,'Forever Professions')
        identities='\n'.join(f'{name}: {info["version"]} ({info["source_commit"][:7]})' for name,info in self.package_details.items())
        errors='\n'.join(f'{name}: {error}' for name,error in self.entry_errors.items())
        backup_details=('Addon installation is unavailable; no backup location has been selected.' if self.transactions is None else
                        'Backups and receipts: shared client-bound configuration; confirmed before installation.')
        self.details.setText(identities+'\n'+errors+f'\nPackage: {self.payload}\n'+backup_details+'\n'+
            'Status compares file contents. Different files may be newer or locally modified; extra files are retained.')
        if self.transactions is not None:
            self.recovery_action.setEnabled(self.client is not None)
            try:
                advice=self.transactions.inspect(self.client)
                if advice.recovery_required:
                    self._transaction_warnings.setdefault(self._client_key(self.client),advice.message)
                warning=self._transaction_warnings.get(self._client_key(self.client),'')
                self.transaction_status.setText(warning or advice.message)
                blocked=advice.blocked or bool(warning)
            except Exception:
                blocked=True
                self.transaction_status.setText('Addon installation state could not be verified. Installation is unavailable.')
            if blocked:
                for action in (self.core_action,self.action,self.professions_action):action.setEnabled(False)
        else:
            self.transaction_status.setText(self.transaction_error or 'Addon installation is disabled in this session.')
            for action in (self.core_action,self.action,self.professions_action):action.setEnabled(False)

    def refresh_entry(self,names,status,action,title):
        try:
            files=self.package_files(names)
            metadata=package_metadata(self.payload,names)
            if self.client is None:status.setText('Select a game folder to check installed addons.');return False
            validate_client(self.client)
            check_legacy(self.client)
            present=0;matched=0
            for name,source in files:
                target=safe_target(self.client/'Interface/AddOns'/source.relative_to(self.payload),self.client,for_write=True)
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
            return different
        except (OSError,ValueError) as exc:
            self.entry_errors[title]=str(exc)
            status.setText('Preview only · installation unavailable' if self.payload is None else 'Package unavailable · see installation details')
            return False

    def install_selected(self,addon='WFStorage'):
        if getattr(self.host,'isolation',None) is not None:return
        if self.operation_active:return
        if self.transactions is None:
            self.refresh();self.notice.setText(self.transaction_status.text());return
        self._install_transaction(addon)

    @staticmethod
    def _client_key(client):return str(client).casefold() if client else ''

    def review_recovery(self):
        if self.transactions is None or self.operation_active or self.client is None:return
        if self.recovery_dialog is not None and self.recovery_dialog.isVisible():
            self.recovery_dialog.raise_();return self.recovery_dialog
        # This Qt-only module has no imports of the optional distribution service.
        from addon_recovery_dialog import AddonRecoveryDialog
        self.recovery_dialog=AddonRecoveryDialog(self)
        self.recovery_dialog.open()
        return self.recovery_dialog

    @contextmanager
    def recovery_operation(self):
        if self.operation_active:
            yield False;return
        controls=[self.picker,self.refresh_action,self.core_action,self.action,self.professions_action,self.recovery_action]
        controls.extend((getattr(self.host,'page_picker',None),getattr(self.host,'back_button',None)))
        controls=[w for w in controls if w is not None]
        enabled=[w.isEnabled() for w in controls]
        self.operation_active=True
        for widget in controls:widget.setEnabled(False)
        try:yield True
        finally:
            self.operation_active=False
            for widget,was_enabled in zip(controls,enabled):widget.setEnabled(was_enabled)
            self.refresh()

    def recovery_result(self,client,summary):
        resolved=((summary.status=='installation_complete' and summary.ok)
                  or (summary.status=='rollback_complete' and summary.verified_outcome=='rollback' and not summary.late_error))
        key=self._client_key(client)
        if resolved:self._transaction_warnings.pop(key,None)
        else:self._transaction_warnings[key]=summary.message
        self.notice.setText(summary.message)

    def recovery_uncertain(self,client):
        message='Addon recovery outcome could not be verified. Preserve backups and recovery evidence; check again before continuing.'
        self._transaction_warnings[self._client_key(client)]=message
        self.notice.setText(message)
        return message

    def _install_transaction(self,addon):
        if addon not in ('WFCore','WFStorage','WFProfessions'):return
        self.refresh()
        action={'WFCore':self.core_action,'WFStorage':self.action,'WFProfessions':self.professions_action}[addon]
        if not action.isEnabled():return
        different={'WFCore':self.core_status.text()=='Installed files differ from bundled package',
                   'WFStorage':self.different,'WFProfessions':self.professions_different}[addon]
        controller=self.transactions;chosen=self.client;payload=self.payload
        controls=[self.picker,self.refresh_action,self.core_action,self.action,self.professions_action]
        if self.recovery_action is not None:controls.append(self.recovery_action)
        controls.extend(w for w in (getattr(self.host,'page_picker',None),getattr(self.host,'back_button',None)) if w is not None)
        enabled=[w.isEnabled() for w in controls]
        self.operation_active=True
        for widget in controls:widget.setEnabled(False)
        try:
            try:request=controller.capture(chosen,payload,addon)
            except Exception:
                self.notice.setText('The selected game folder or backup configuration could not be verified. Installation was not started.')
                return
            message=('Installed files differ and may be newer or locally modified. Back them up and replace matching files with the bundled version?\n\n'
                     if different else 'Install the selected bundled addons?\n\n')
            message+='Addons: '+', '.join(request.selected)+'\nGame folder: '+str(request.client)
            message+='\nInstall into: '+str(request.client/'Interface/AddOns')
            message+='\nBackups: '+str(request.selection.state/'AddonBackups')
            message+='\nGame saves, character settings and unrelated addons are kept.'
            if getattr(request,'adoption',None) is not None:
                message+='\nUse this existing addon backup location for this client? Backups stay in place; nothing will be migrated.'
            elif request.provision:message+='\nThis also establishes the confirmed addon backup configuration. Existing backups stay in their current locations.'
            if QMessageBox.question(self.host,'Replace addon files?' if different else 'Install bundled addons?',message,
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes:return
            if self.client!=chosen or self.payload!=payload or self.transactions is not controller:
                self.notice.setText('The installation selection changed. Review it and confirm again. Installation was not started.')
                return
            # Synchronous mutation: never call processEvents, start workers or
            # display another modal dialog until the service has returned.
            try:
                result=controller.execute(request)
                summary=result.summary
            except Exception:
                warning='Addon installation outcome is uncertain. Preserve backups and recovery evidence; review status before continuing.'
                self._transaction_warnings[self._client_key(chosen)]=warning
                self.notice.setText(warning);return
            self.notice.setText(summary.message)
            if summary.status in ('recovery_pending','recovery_incomplete','pending_invalid','pending_ambiguous',
                                   'finalization_pending','installation_complete_with_error','rollback_complete_with_error'):
                self._transaction_warnings[self._client_key(chosen)]=summary.message
            if summary.ok and summary.status=='installation_complete':
                try:write_json(self.path,dict(client=str(request.client)))
                except Exception:
                    self.notice.setText(summary.message+' Folder preference could not be saved. Installation is complete; do not reinstall for this preference error.')
        finally:
            self.operation_active=False
            for widget,was_enabled in zip(controls,enabled):widget.setEnabled(was_enabled)
            self.refresh()
