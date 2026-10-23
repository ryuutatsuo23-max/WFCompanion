"""Explicit saved-character preview. Reads saves; writes only companion links."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFileDialog, QComboBox
from app import Panel, label, row
from widgets import Table
from PySide6.QtWidgets import QTableWidgetItem


def text(value):
    widget=label(value)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def find_saves(client):
    """Search only the selected client's account-level saves, never the disk."""
    if client is None:return []
    return sorted((Path(client)/'WTF'/'Account').glob('*/SavedVariables/WFCore.lua'),key=str)


class ConnectionPreview(QDialog):
    def __init__(self,host,path,*,reconnecting=False):
        super().__init__(host)
        self.host=host;self.directory=Path(path).resolve().parent;self.snapshot=None;self.reconnecting=reconnecting
        self.setWindowTitle('Reconnect moved save' if reconnecting else 'Preview saved characters');self.setModal(True);self.resize(760,480)
        box=QVBoxLayout(self)
        box.addWidget(text(str(self.directory/'WFCore.lua')))
        box.addWidget(text('Reconnect these characters to the moved save. Existing profiles and manual plans are kept; only their saved-file path changes.' if reconnecting else 'Connect these saved characters for read-only viewing. New characters get separate profiles; existing GUID links are reused. Manual plans and game saves are kept.'))
        self.characters=Table(['Character','Realm','Connection'],height=230)
        self.characters.setColumnWidth(0,210);self.characters.setColumnWidth(1,200)
        box.addWidget(self.characters)
        self.status=text('');box.addWidget(self.status)
        self.connect_button=host.button('Reconnect existing characters' if reconnecting else 'Connect saved characters',self.connect_saved)
        box.addWidget(row(host.button('Preview again',self.refresh),self.connect_button,host.button('Cancel',self.reject)))
        self.refresh()

    def refresh(self):
        self.snapshot=None;self.connect_button.setEnabled(False);self.characters.setRowCount(0)
        try:
            from character_links import LinkStore
            if self.reconnecting:
                from saved_data_reconnect import preview_reconnect
                before,identities,_,_=preview_reconnect(self.host.saved_character_connection,self.directory)
            else:before,identities,_=self.host.saved_character_connection.preview(self.directory)
            links=LinkStore(self.host.data.directory)
            self.characters.setRowCount(len(identities))
            for i,value in enumerate(identities):
                for j,cell in enumerate((value['name'],value['realm'],'Keep existing profile' if self.reconnecting else 'Already connected' if links.linked(value) else 'New separate profile')):
                    item=QTableWidgetItem(cell);item.setToolTip(cell+'\n'+value['guid']);self.characters.setItem(i,j,item)
            self.snapshot=before
            self.connect_button.setEnabled(bool(identities))
            self.status.setText(f'{len(identities)} saved characters found. No connection changes until you confirm.' if identities else 'No saved characters found. Your current connection is unchanged.')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.status.setText('Cannot preview this save: '+str(exc)+'\nYour current connection is unchanged.')

    def connect_saved(self):
        if self.snapshot is None:return
        try:
            if self.reconnecting:
                from saved_data_reconnect import reconnect
                reconnect(self.host.saved_character_connection,self.directory,self.snapshot)
            else:self.host.saved_character_connection.connect(self.directory,expected_signature=self.snapshot)
            self.host.profiles_changed()
            self.host.saved_data_settings.refresh()
            self.accept()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.snapshot=None;self.connect_button.setEnabled(False)
            self.status.setText('Could not connect: '+str(exc))


class SavedDataSettings(Panel):
    def __init__(self,host):
        super().__init__(host,'Saved game data');self.host=host
        self.current=text('');self.box.addWidget(self.current)
        self.box.addWidget(text('Connect a Forever Core save to view saved characters, bags and bank. Choosing an addon installation folder alone does not connect saves. Beta saves are supported; release-client compatibility is still pending.'))
        self.choices=QComboBox();self.choices.setMinimumContentsLength(25)
        self.choices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.box.addWidget(self.choices)
        self.box.addWidget(row(host.button('Find saved files',self.find),host.button('Choose WFCore.lua',self.choose),host.button('Preview selected file',self.preview_selected)))
        self.reconnect_button=host.button('Locate moved save...',self.choose)
        self.box.addWidget(self.reconnect_button)
        self.notice=text('Find uses the game folder selected on the Addons page. You can also choose a saved file directly.')
        self.box.addWidget(self.notice)
        self.choices.addItem('Find or choose a saved file',None)
        self.refresh()

    def refresh(self):
        from saved_character_connection import SavedCharacterConnection
        service=getattr(self.host,'saved_character_connection',None) or SavedCharacterConnection(self.host)
        directory=service.store.data['directory']
        from saved_data_reconnect import missing_source
        missing=missing_source(service)
        self.reconnect_button.setVisible(missing)
        if service.store.error:self.current.setText('Connection needs attention: '+service.store.error)
        elif directory:
            path=Path(directory)/'WFCore.lua'
            client=next((p for p in path.parents if p.name in ('_classic_beta_','_forever_')),None)
            self.current.setText(('Connected save: ' if path.is_file() else 'Connected save is unavailable: ')+str(path)+'\nClient: '+str(client or 'Not identified')+('\nCharacters and manual plans are kept. If the file moved, choose Locate moved save. If it is temporarily unavailable, restore it at this path and refresh saved observations.' if missing else ''))
        else:self.current.setText('No saved-data folder has been explicitly connected.')

    def showEvent(self,event):
        self.refresh();super().showEvent(event)

    def find(self):
        self.choices.clear()
        client=getattr(getattr(self.host,'addons_page',None),'client',None)
        try:
            paths=find_saves(client)
            for path in paths:self.choices.addItem(str(path),str(path))
            self.notice.setText(f'{len(paths)} saved files found. Select an account file, then preview its characters.' if paths else 'No Forever Core saves found in the selected game folder. Choose a saved WFCore.lua file, or select the correct client on the Addons page.')
        except OSError as exc:self.notice.setText('Could not search this folder: '+str(exc))

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose saved Forever Core data','','Forever Core save (WFCore.lua)')
        if path:self.open_preview(path)

    def preview_selected(self):
        path=self.choices.currentData()
        if path:self.open_preview(path)
        else:self.notice.setText('Find or choose a saved WFCore.lua file first.')

    def open_preview(self,path):
        from saved_data_reconnect import missing_source
        self.dialog=ConnectionPreview(self.host,path,reconnecting=missing_source(self.host.saved_character_connection));self.dialog.open()
