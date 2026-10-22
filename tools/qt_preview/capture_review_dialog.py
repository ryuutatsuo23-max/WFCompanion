"""Capture comparison with explicit, opt-in confirmation of verified bag updates."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QFileDialog,QScrollArea,QWidget,QSizePolicy,QMessageBox,QCheckBox
from app import row,label
from widgets import Table
from probe_report import CLIENT,MAX_BYTES
from capture_review import captures,proposals
from capture_import import changes,prepare,apply_reviewed,character_proposal,create_reviewed_character
from datastore_bags import review as datastore_review


class CaptureReviewDialog(QDialog):
    def __init__(self,host,path=None):
        super().__init__(host);self.host=host;self.items=[];self.preview_rows=[];self.evidence=None;self.ds_directory=None
        self.setWindowTitle('Saved captures · import review');self.resize(1050,740)
        box=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();layout=QVBoxLayout(content);scroll.setWidget(content);box.addWidget(scroll)
        layout.addWidget(label('Select verified bag or bank count changes, then review the final confirmation. Nothing is selected automatically.'))
        layout.addWidget(row(host.button('Choose probe report',self.choose)))
        self.source=label('');self.source.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.source)
        self.capture=QComboBox();self.destination=QComboBox()
        for widget in (self.capture,self.destination):
            widget.setMinimumWidth(0);widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            layout.addWidget(widget)
        self.capture.setAccessibleName('Source capture');self.destination.setAccessibleName('Preview destination character')
        self.destination.addItem('Choose destination character for comparison…',None)
        for profile in host.data.profiles:self.destination.addItem(f'{profile.name} · {profile.id}',profile.id)
        self.identity=label('');self.identity.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.identity)
        self.assist=QCheckBox('Use matching DataStore evidence for this review')
        layout.addWidget(self.assist)
        layout.addWidget(host.button('Choose DataStore saved-data folder',self.choose_datastore))
        layout.addWidget(host.button('Review new character from capture…',self.confirm_character))
        self.evidence_label=label('DataStore assistance is optional and off by default.')
        self.evidence_label.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.evidence_label)
        self.table=Table(['Item ID','Item','Stored count','Observed subtotal','Proposal','Reason'],height=280)
        layout.addWidget(self.table)
        self.detail=label('');self.detail.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.detail)
        # Long source paths and GUIDs must wrap inside a narrow review window.
        for text in (self.source,self.identity,self.detail,self.evidence_label):
            text.setMinimumWidth(0)
            text.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.table.itemSelectionChanged.connect(self.show_detail)
        layout.addWidget(label('Equipment stays separate. Missing items never become zero. Unknown slots may hide additional items. Selecting a destination does not switch characters or confirm a GUID mapping. Captures are historical stress-test observations, not live inventory.'))
        box.addWidget(host.button('Close review',self.accept))
        self.import_button=host.button('Review selected bags/bank changes…',self.confirm_import)
        box.addWidget(self.import_button)
        self.capture.currentIndexChanged.connect(self.refresh);self.destination.currentIndexChanged.connect(self.refresh)
        self.assist.toggled.connect(self.refresh)
        host.style_table(self.table);host.wire_nested_scrolling(self)
        if path is None:
            files=list((CLIENT/'WTF'/'Account').glob('*/SavedVariables/WFStressProbe.lua'))
            if files:path=max(files,key=lambda p:p.stat().st_mtime_ns)
        if path:self.load(path)
        else:self.source.setText('No saved report found. Choose a live saved report or backed-up WFStressProbe file.')

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose saved probe capture','','Lua saved data (*.lua)')
        if path:self.load(path)

    def choose_datastore(self):
        path=QFileDialog.getExistingDirectory(self,'Folder containing DataStore.lua and DataStore_Containers.lua')
        if path:self.ds_directory=Path(path);self.refresh()

    def confirm_character(self):
        try:
            index=self.capture.currentData()
            if index is None:raise ValueError('Choose a bag capture first.')
            c=self.items[index];p=character_proposal(self.host.data,c,self.evidence)
            prompt=QMessageBox(self);prompt.setWindowTitle('Confirm new character');prompt.setTextFormat(Qt.TextFormat.PlainText)
            prompt.setText(f'Create {p.name} · {p.character_class}?\nGUID: {c.owner_key}\n'
                           'This saves a new profile with General playstyle. No existing character is renamed or switched, '
                           'and no bag items are imported yet. Level stays Unknown.\n\n'+self.evidence.summary)
            prompt.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            prompt.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if prompt.exec()!=QMessageBox.StandardButton.Yes:return
            if self.report_path.read_bytes()!=self.report_bytes:raise ValueError('Probe changed; reload the report.')
            key=create_reviewed_character(self.host.data,c,self.evidence,p)
            self.host.character.addItem(p.name,key)
            self.destination.addItem(f'{p.name} · {key}',key)
            self.destination.setCurrentIndex(self.destination.findData(key))
            self.detail.setText('Character created. Select bag entries and review their separate import confirmation.')
        except (ValueError,OSError) as exc:self.detail.setText(str(exc))

    def load(self,path):
        self.items=[];self.capture.clear();self.table.rows([])
        try:
            path=Path(path)
            with path.open('rb') as stream:data=stream.read(MAX_BYTES+1)
            self.report_path=path.resolve();self.report_bytes=data;self.ds_directory=path.resolve().parent
            self.items=captures(data)
            self.source.setText(f'Source: {path}\n{len(self.items)} capture sections. Names and GUIDs are source labels; no tool profiles are changed.')
            self.capture.blockSignals(True)
            for index,c in reversed(list(enumerate(self.items))):self.capture.addItem(f'{c.at} · {c.scope} · {c.character_class} · {c.owner_label}',index)
            self.capture.blockSignals(False);self.refresh()
        except (OSError,ValueError,TypeError,KeyError):
            self.source.setText('Capture could not be read safely. No data changed.');self.identity.setText('');self.detail.setText('')

    def refresh(self,*_):
        self.evidence=None
        self.table.rows([]);self.preview_rows=[];self.detail.setText('Select a row for full proposal details.')
        index=self.capture.currentData()
        if index is None:return
        c=self.items[index];key=self.destination.currentData()
        self.evidence_label.setText('DataStore assistance is off. Probe unknowns stay unresolved.')
        if self.assist.isChecked():
            try:
                self.evidence=datastore_review(c,self.ds_directory)
                self.evidence_label.setText(f'DataStore folder: {self.ds_directory}\n'+self.evidence.summary)
            except (ValueError,OSError) as exc:self.evidence_label.setText(f'DataStore assistance blocked: {exc}')
        profile=next((p for p in self.host.data.profiles if p.id==key),None)
        self.identity.setText(f'Source character: {c.owner_label}\nClass: {c.character_class} · Build: {c.build} · Captured: {c.at}\n{c.scope}: {c.coverage}\nUnresolved slots: {c.unknown_slots}\nDestination: {profile.name if profile else "Not selected"}. Keep local identity; mapping requires review.')
        if profile is None:return
        self.identity.setText(self.identity.text()+f"\nLocal class: {profile.character_class} · Captured class: {c.character_class}. Proposed identity action: keep local name/class; review GUID association.")
        book=self.host.data.inventories.get(key)
        self.preview_rows=proposals(c,book.entries if book else [])
        self.table.rows((str(i),r) for i,r in enumerate(self.preview_rows))
        self.eligible=changes(c,book.entries if book else [],self.evidence)
        by_id={str(v[3]):k for k,v in self.eligible.items()}
        for i,r in enumerate(self.preview_rows):
            if r[0] in by_id:
                if self.evidence:
                    self.table.item(i,4).setText(f'Add reviewed {c.scope.lower()} item' if by_id[r[0]].startswith('add:') else 'Review DataStore-assisted count')
                    self.table.item(i,5).setText('Matching occupied slots and free-slot accounting; see both timestamps above.')
                    self.preview_rows[i]=(*r[:4],self.table.item(i,4).text(),self.table.item(i,5).text())
                cell=self.table.item(i,0)
                cell.setFlags(cell.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                cell.setCheckState(Qt.CheckState.Unchecked)
                cell.setData(Qt.ItemDataRole.UserRole+1,by_id[r[0]])
        self.detail.setText('Check item IDs to select updates or additions. Additions require matching DataStore item names and IDs; unlinked name conflicts stay blocked. Counts combine all variants of a base item ID.')

    def confirm_import(self):
        try:
            index=self.capture.currentData();destination=self.destination.currentData()
            if index is None:raise ValueError('Choose a source capture first.')
            c=self.items[index]
            selected=[self.table.item(i,0).data(Qt.ItemDataRole.UserRole+1)
                      for i in range(self.table.rowCount())
                      if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
            if self.report_path.read_bytes()!=self.report_bytes:raise ValueError('Probe file changed. Choose the report again before importing.')
            _,_,reviewed=prepare(self.host.data,c,destination,selected,self.evidence)
            page=self.host.inventory_page
            if destination==self.host.data.active and page.edit_id in reviewed:
                raise ValueError('An imported item is open in the inventory editor. Finish that edit or choose New entry first; its fields have been preserved.')
            profile=next(p for p in self.host.data.profiles if p.id==destination)
            lines=[f'{name} (ID {item}): {"New "+c.scope.lower()+" entry" if key.startswith("add:") else old if old is not None else "Unknown"} → {new}'
                   for key,(name,old,new,item) in reviewed.items()]
            prompt=QMessageBox(self);prompt.setWindowTitle(f'Confirm {c.scope.lower()} import')
            prompt.setTextFormat(Qt.TextFormat.PlainText)
            prompt.setText(f'Confirm that this captured character belongs to this destination.\n\nSource: {c.owner_label}\nGUID: {c.owner_key}\nCaptured: {c.at}\nDestination: {profile.name} · {profile.id}\n\n'+ '\n'.join(lines)+f'\n\nSave these selected {c.scope.lower()} totals? Existing freshness/recheck timestamps remain unchanged. Other locations, equipment, names, notes and unfinished fields are preserved. A preceding-save backup is retained.')
            prompt.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            if self.evidence:prompt.setText(prompt.text()+'\n\n'+self.evidence.summary)
            prompt.button(QMessageBox.StandardButton.Yes).setText(f'Confirm and save {c.scope.lower()} changes')
            prompt.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if prompt.exec()!=QMessageBox.StandardButton.Yes:return
            if self.report_path.read_bytes()!=self.report_bytes:raise ValueError('Probe changed during confirmation; no import performed.')
            apply_reviewed(self.host.data,c,destination,reviewed,self.evidence)
            self.refresh()
            self.detail.setText(f'Saved {len(reviewed)} reviewed {c.scope.lower()} count changes for {profile.name}. Unfinished fields and filters were preserved.')
        except (ValueError,OSError) as exc:
            self.detail.setText(str(exc))

    def show_detail(self):
        index=self.table.currentRow()
        if 0<=index<len(self.preview_rows):self.detail.setText('\n'.join(self.preview_rows[index]))
