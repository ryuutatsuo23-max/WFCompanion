"""Explicit slot-by-slot equipment proposals; no bags, bank or wishlist mutation."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QFileDialog,QMessageBox,QSizePolicy,QScrollArea,QWidget
from app import label
from widgets import Table
from probe_report import CLIENT,MAX_BYTES
from capture_review import captures
from equipment_review import SLOTS,prepare,apply_reviewed


class EquipmentReviewDialog(QDialog):
    def __init__(self,host,path=None):
        super().__init__(host);self.host=host;self.items=[];self.proposed={};self.review=None
        self.setWindowTitle('Review equipped items');self.resize(1000,760)
        box=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();layout=QVBoxLayout(content);scroll.setWidget(content);box.addWidget(scroll)
        layout.addWidget(label('Equipped slots only. Select changes, then confirm before saving. Bags, bank and wishlist ownership stay separate.'))
        layout.addWidget(host.button('Choose probe report',self.choose))
        layout.addWidget(host.button('Choose DataStore folder',self.choose_directory))
        self.capture=QComboBox();self.destination=QComboBox()
        for widget in (self.capture,self.destination):
            widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed);layout.addWidget(widget)
        self.destination.addItem('Choose destination character…',None)
        for p in host.data.profiles:self.destination.addItem(f'{p.name} · {p.character_class}',p.id)
        self.evidence=label('Choose a source and destination.');self.evidence.setTextFormat(Qt.TextFormat.PlainText)
        self.evidence.setMinimumWidth(0);self.evidence.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        layout.addWidget(self.evidence)
        self.table=Table(['Equipped slot','Stored item','Proposed item','Quantity','Action'],height=350)
        host.style_table(self.table);layout.addWidget(self.table)
        self.notice=label('Nothing is selected automatically.');self.notice.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.notice)
        box.addWidget(host.button('Review selected equipment changes…',self.confirm_import))
        box.addWidget(host.button('Close',self.accept))
        self.capture.currentIndexChanged.connect(self.refresh);self.destination.currentIndexChanged.connect(self.refresh)
        host.wire_nested_scrolling(self)
        if path is None:
            found=list((CLIENT/'WTF'/'Account').glob('*/SavedVariables/WFStressProbe.lua'))
            if found:path=max(found,key=lambda p:p.stat().st_mtime_ns)
        if path:self.load(path)

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose saved probe','','Lua saved data (*.lua)')
        if path:self.load(path)

    def choose_directory(self):
        path=QFileDialog.getExistingDirectory(self,'Folder containing DataStore.lua and DataStore_Inventory.lua')
        if path:self.directory=Path(path);self.refresh()

    def load(self,path):
        self.items=[];self.capture.clear();self.review=None
        try:
            self.path=Path(path).resolve();self.directory=self.path.parent
            with self.path.open('rb') as stream:self.raw=stream.read(MAX_BYTES+1)
            self.items=[c for c in captures(self.raw) if c.scope=='Equipment']
            for i,c in reversed(list(enumerate(self.items))):self.capture.addItem(f'{c.owner_label} · {c.at}',i)
            self.refresh()
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))

    def refresh(self,*_):
        self.proposed={};self.review=None;self.table.rows([])
        i=self.capture.currentData();destination=self.destination.currentData()
        if i is None or destination is None:return
        try:
            c=self.items[i]
            result=prepare(self.host.data,c,destination,self.directory)
            self.proposed,current,summary,sources,raw=result;self.review=result
            self.evidence.setText(f'Probe file: {self.path}\nDataStore folder: {self.directory}\n'+summary)
            rows=[]
            for slot,name in enumerate(SLOTS):
                key=str(slot);old=current.get(key);new=self.proposed.get(key)
                rows.append((key,(name,old['name'] if old else 'Not recorded',
                                  new['name'] if new else 'Keep stored / no eligible change',
                                  new['quantity'] if new else old['quantity'] if old else '',
                                  ('Add' if not old else 'Replace equipped slot') if new else 'Keep unchanged')))
            self.table.rows(rows)
            for i in range(20):
                if str(i) in self.proposed:
                    cell=self.table.item(i,0);cell.setFlags(cell.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    cell.setCheckState(Qt.CheckState.Unchecked)
            self.notice.setText('Unknown/mismatched slots never remove saved equipment. Select occupied slots to add or replace.')
        except (ValueError,OSError) as exc:self.evidence.setText(str(exc))

    def confirm_import(self):
        try:
            if not self.review:raise ValueError('Choose a valid capture and saved destination first.')
            c=self.items[self.capture.currentData()];destination=self.destination.currentData()
            selected={str(i):self.proposed[str(i)] for i in range(20)
                      if self.table.item(i,0).checkState()==Qt.CheckState.Checked and str(i) in self.proposed}
            if not selected:raise ValueError('Select at least one equipped slot.')
            if self.path.read_bytes()!=self.raw:raise ValueError('Probe changed; reload it before importing.')
            _,current,summary,sources,raw=self.review
            profile=next(p for p in self.host.data.profiles if p.id==destination)
            lines=[f'{SLOTS[int(s)]}: {current.get(s,{}).get("name","Not recorded")} → {r["name"]} (ID {r["item_id"]}, quantity {r["quantity"]})' for s,r in selected.items()]
            prompt=QMessageBox(self);prompt.setWindowTitle('Confirm equipped slots');prompt.setTextFormat(Qt.TextFormat.PlainText)
            prompt.setText(f'Destination: {profile.name} · {profile.id}\n\n'+summary+'\n\n'+'\n'.join(lines)+'\n\nSave only these equipped slots? Bags, bank, wishlist counts and unfinished fields are unchanged.')
            prompt.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel)
            prompt.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if prompt.exec()!=QMessageBox.StandardButton.Yes:return
            if self.path.read_bytes()!=self.raw:raise ValueError('Probe changed during confirmation.')
            apply_reviewed(self.host.data,c,destination,self.directory,selected,raw,sources)
            self.refresh();self.notice.setText(f'Saved {len(selected)} equipped slots for {profile.name}.')
        except (ValueError,OSError) as exc:self.notice.setText(str(exc))
