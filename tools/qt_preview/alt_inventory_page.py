"""Search every character's local records without loading any item editor."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox
from presentation import easy_mode,simple_count
from app import Panel,row,label,field
from widgets import Form,Table
from alt_inventory import snapshot,filter_items


class AltInventoryPage(Panel):
    PAGE_SIZE=100

    def __init__(self,host):
        super().__init__(host,'All characters · Inventory & Bank')
        self.host=host; self.data=host.data; self.items=[]; self.coverage=[]; self.page=0; self.stale=True
        self.box.addWidget(label('Read-only overview of applied local records, including unsaved applied changes. Editor drafts are excluded. Manual records can be incomplete; no records means Unknown, not empty.'))
        self.character=host.combo([],self.filters_changed)
        self.filters=Form(host,[('query','Search item, ID or note',str,''),('location','Location',('All','Bags','Bank'),'All'),
            ('status','Count status',('All','Known','Unknown','Recheck'),'All')])
        self.box.addWidget(row(field('Character',self.character),host.button('Refresh records',self.refresh),host.button('Reset overview filters',self.reset_filters)))
        # Keep the form at full panel width: nesting its flow layout in another
        # content-sized row collapses the fields into a tall narrow column.
        self.box.addWidget(self.filters)
        self.show_details=QCheckBox('Show details');self.box.addWidget(self.show_details)
        self.show_details.toggled.connect(self.render)
        self.notice=label(''); self.box.addWidget(self.notice)
        self.table=Table(['Item','Character','Location','Count','Status','Item ID','Entered (UTC)','Note'],height=330)
        self.table.setColumnWidth(1,210); self.box.addWidget(self.table)
        self.previous=host.button('Previous page',lambda:self.turn(-1)); self.next=host.button('Next page',lambda:self.turn(1))
        self.box.addWidget(row(self.previous,self.next,host.button('Open character inventory',self.open_character)))
        self.coverage_label=label('Recorded coverage · numbers below are entry counts, not total items or a complete game scan.')
        self.box.addWidget(self.coverage_label)
        self.coverage_table=Table(['Character','Bags entries','Bank entries','Coverage'],height=170)
        self.coverage_table.content_column=0; self.coverage_table.setColumnWidth(3,250); self.box.addWidget(self.coverage_table)
        self.pending=QTimer(self); self.pending.setSingleShot(True); self.pending.setInterval(150); self.pending.timeout.connect(self.render)
        self.filters.changed(self.filters_changed)

    def showEvent(self,event):
        super().showEvent(event)
        if self.stale: self.refresh()
        else: self.render()

    def hideEvent(self,event):
        self.pending.stop(); super().hideEvent(event)

    def invalidate(self):
        self.stale=True
        if self.isVisible(): self.refresh()

    def refresh(self):
        try:
            items,coverage=snapshot(self.data)
            selected=self.character.currentData()
            self.character.blockSignals(True); self.character.clear(); self.character.addItem('All characters',None)
            for char,name,*_ in coverage: self.character.addItem(name,char)
            self.character.setCurrentIndex(max(0,self.character.findData(selected))); self.character.blockSignals(False)
            self.items,self.coverage=items,coverage; self.stale=False; self.render()
        except (ValueError,OSError,TypeError) as error:
            self.items=[]; self.coverage=[]; self.table.rows([]); self.coverage_table.rows([])
            self.previous.setEnabled(False); self.next.setEnabled(False); self.notice.setText(str(error)); self.stale=True

    def filters_changed(self,*_):
        self.page=0
        if hasattr(self,'pending'): self.pending.start()

    def reset_filters(self):
        self.filters.load(self.filters.defaults); self.character.setCurrentIndex(0); self.page=0; self.render()

    def turn(self,step): self.page=max(0,self.page+step); self.render()

    def render(self):
        if self.stale: self.refresh(); return
        values=self.filters.values(); char=self.character.currentData()
        visible=filter_items(self.items,values['query'],char,values['location'],values['status'])
        self.page=min(self.page,max(0,(len(visible)-1)//self.PAGE_SIZE)); start=self.page*self.PAGE_SIZE
        page=visible[start:start+self.PAGE_SIZE]
        simple=easy_mode(self.host) and not self.show_details.isChecked()
        for col in (4,5,6,7):self.table.setColumnHidden(col,simple)
        self.table.horizontalHeaderItem(3).setText('Have here?' if simple else 'Count')
        self.coverage_table.setVisible(not simple);self.coverage_label.setVisible(not simple)
        self.table.rows(((r.character_id,r.entry_id),(r.name,r.character,r.location,simple_count(r.quantity,r.status) if simple else r.quantity,r.status,r.item_id,r.entered,r.note)) for r in page)
        counts={state:sum(r.status==state for r in visible) for state in ('Known','Unknown','Recheck')}
        prefix=f'Rows {start+1}–{start+len(page)} of {len(visible)}' if page else 'No matching records · missing counts remain Unknown'
        self.notice.setText(prefix+(' · Saved records, not live counts.' if simple else ' · '+ ' · '.join(f'{state}: {count}' for state,count in counts.items())))
        self.previous.setEnabled(self.page>0); self.next.setEnabled(start+self.PAGE_SIZE<len(visible))
        self.coverage_table.rows((key,(name,bags,bank,'Partial manual records' if bags or bank else 'Unknown · no records'))
            for key,name,bags,bank in self.coverage if char is None or char==key)

    def open_character(self):
        key=self.table.key()
        if key is None: self.notice.setText('Select an item row first.'); return
        if key[0] not in {p.id for p in self.data.profiles}:
            self.notice.setText('This record has no matching character profile. Its data is preserved.'); return
        self.host.switch_character(key[0]); self.host.show_inventory_section(False)
