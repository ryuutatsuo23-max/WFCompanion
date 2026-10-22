"""A read-only source picker; checkboxes never load the wishlist editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QScrollArea,QWidget
from app import row,label,field
from widgets import Form,Table
from gear import GearWishlist
from wishlist_copy import copy_general,copy_status


class WishlistCopyDialog(QDialog):
    def __init__(self,host):
        super().__init__(host); self.host=host; self.data=host.data; self.character=self.data.active
        self.setPalette(host.palette()); self.setWindowTitle('Copy General wishlist items'); self.resize(1060,720)
        layout=QVBoxLayout(self); scroll=QScrollArea(); scroll.setWidgetResizable(True)
        content=QWidget(); content.setPalette(host.palette()); scroll.viewport().setPalette(host.palette())
        box=QVBoxLayout(content); scroll.setWidget(content); layout.addWidget(scroll)
        box.addWidget(label('Tick applied General entries to copy. Originals and unfinished fields stay unchanged. Copies need Save wishlist in the destination playstyle.'))
        choices=self.data.playstyles.available(self.character,self.data.profile.character_class)[1:]
        self.target=host.combo(choices,lambda _:self.refresh())
        current=self.data.playstyles.active(self.character)
        if current in choices: self.target.setCurrentText(current)
        self.search=Form(host,[('query','Search General items',str,'')]); self.search.changed(self.refresh)
        box.addWidget(row(field('Copy to',self.target),self.search))
        self.table=Table(['Copy','Item','Slot','Goal status','Destination'],height=300); box.addWidget(self.table)
        self.table.setColumnWidth(0,70); self.table.setColumnWidth(4,270)
        box.addWidget(row(host.button('Tick all ready rows',lambda:self.tick_rows(True)),host.button('Clear ticks',lambda:self.tick_rows(False))))
        self.status=label(''); box.addWidget(self.status)
        layout.addWidget(row(host.button('Copy checked items',self.copy),host.button('Close',self.accept)))
        self.ready=set(); host.style_table(self.table); host.wire_nested_scrolling(self); self.refresh()

    def checked(self):
        return {key for index,key in enumerate(self.table.keys) if self.table.item(index,0).checkState()==Qt.CheckState.Checked}

    def tick_rows(self,checked):
        for index,key in enumerate(self.table.keys):
            self.table.item(index,0).setCheckState(Qt.CheckState.Checked if checked and key in self.ready else Qt.CheckState.Unchecked)

    def refresh(self,*_):
        if not hasattr(self,'table'): return
        checked=self.checked(); self.ready=set()
        try:
            if self.data.active!=self.character: raise ValueError('Character changed. Reopen this dialog.')
            if self.data.gear_store.error or self.data.playstyles.store.error: raise ValueError('Saved wishlist unavailable; original files preserved.')
            target=self.target.currentText()
            if not target: raise ValueError('Enable a destination in Playstyle choices first.')
            source=self.data.gear.get(self.character,GearWishlist())
            destination=self.data.playstyles.book(self.character,target)
            entries=source.find(self.search.values()['query']); rows=[]
            for item in entries:
                state=copy_status(item,destination)
                if state=='Ready to copy': self.ready.add(item.id)
                rows.append((item.id,('',item.name,item.slot,item.status,state)))
            self.table.rows(rows)
            for index,key in enumerate(self.table.keys):
                cell=self.table.item(index,0)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|(Qt.ItemFlag.ItemIsUserCheckable if key in self.ready else Qt.ItemFlag.NoItemFlags))
                cell.setCheckState(Qt.CheckState.Checked if key in checked and key in self.ready else Qt.CheckState.Unchecked)
            self.status.setText(f'{len(entries)} General entries shown · {len(self.ready)} ready to copy. Existing destination entries are never overwritten.')
        except (ValueError,OSError) as error:
            self.table.rows([]); self.status.setText(str(error))

    def copy(self):
        try:
            target=self.target.currentText()
            count,skipped=copy_general(self.data,self.character,target,self.checked())
            self.host.gear_page.refresh(); self.refresh()
            message=f'Copied {count} to {target}; skipped {len(skipped)}. Choose {target} and Save wishlist to keep the copies. Editor drafts unchanged.'
            self.status.setText(message); self.host.gear_page.message(message)
        except (ValueError,OSError) as error: self.status.setText(str(error))
