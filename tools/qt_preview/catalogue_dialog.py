"""Local item picker; SQL ownership filters run before the result limit."""
from dataclasses import asdict
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QScrollArea, QWidget
from app import row, label
from widgets import Form, Table, integer, shown
from search_filters import SearchFilters
from item_stock import catalogue_stock, ownership_state, ownership_selection, OWNERSHIP_FILTERS, unknown_stock
from ownership import counts as ownership_counts


class ItemPicker(QDialog):
    def __init__(self, host, scope, choose):
        super().__init__(host)
        # Top-level dialogs do not inherit their parent's palette by default.
        # Match the dialog panel colour, including the auto-filled scroll body.
        palette = QPalette(host.palette())
        palette.setColor(QPalette.ColorRole.Window, QColor(host.colors[1]))
        self.setPalette(palette)
        self.host,self.scope,self.choose=host,scope,choose
        self.character=host.data.active
        self.setWindowTitle('Local item search · selected character')
        self.resize(1100,750)
        layout=QVBoxLayout(self)
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        content=QWidget(); box=QVBoxLayout(content); scroll.setWidget(content); layout.addWidget(scroll)
        # QScrollArea enables an auto-filled content surface; explicitly colour
        # that surface too, rather than only the dialog's outer margin.
        content.setPalette(palette)
        scroll.viewport().setPalette(palette)
        self.catalogue=host.catalogue()
        options=self.catalogue.filter_options(scope)
        saved=host.data.search_filters.get(self.character,scope)
        self.form=Form(host,[('query','Search name or ID',str,''),
            ('category','Category',('All','Gear','Material','Other') if scope=='All' else (scope,),saved.category),
            ('equip_slot','Slot',('Any',*options['slots']),saved.equip_slot or 'Any'),
            ('item_type','Type',('Any',*options['types']),saved.item_type or 'Any'),
            ('min_level','Minimum required level',str,''),('max_level','Maximum required level',str,''),
            ('use_character_level','Use character level',bool,saved.use_character_level),
            ('include_unknown_levels','Include Unknown levels',bool,saved.include_unknown_levels),
            ('ownership','Ownership',OWNERSHIP_FILTERS,saved.ownership)])
        values=asdict(saved); values.update(equip_slot=saved.equip_slot or 'Any',item_type=saved.item_type or 'Any')
        self.form.load(values)
        box.addWidget(self.form)
        level=shown(host.data.profile.level)
        box.addWidget(label(f'Character level: {level}. Unknown required levels do not establish usability.'))
        self.status=label(''); box.addWidget(self.status)
        self.table=Table(['Item','Bags','Bank','Ownership','Slot','Type','Required level','ID'],self.selected,280)
        box.addWidget(self.table)
        self.detail=label(''); self.detail.setTextInteractionFlags(self.detail.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.detail)
        self.use=host.button('Use selected item',self.accept_item)
        layout.addWidget(row(self.use,host.button('Cancel',self.reject)))
        self.pending=QTimer(self); self.pending.setSingleShot(True); self.pending.setInterval(180)
        self.pending.timeout.connect(self.refresh)
        self.form.changed(lambda *_:self.pending.start())
        self.results={}
        # Search is created after the workspace's appearance pass. Apply the
        # same table font and measured headers before presenting results.
        host.style_table(self.table)
        host.wire_nested_scrolling(self)
        self.refresh(persist=False)

    def refresh(self,persist=True):
        try:
            values=self.form.values()
            category=values['category']
            filters=SearchFilters(category=category,equip_slot=None if values['equip_slot']=='Any' or category not in ('All','Gear') else values['equip_slot'],
                item_type=None if values['item_type']=='Any' else values['item_type'],min_level=integer(values['min_level'],True),
                max_level=integer(values['max_level'],True),include_unknown_levels=values['include_unknown_levels'],
                use_character_level=values['use_character_level'],ownership=values['ownership'])
            filters.validate(self.scope)
            data=self.host.data
            refs=self.catalogue.ownership_references()
            owned=ownership_counts(data,[(r.item_id,r.name,r) for r in refs])
            unavailable=data.inventory_store.error or data.plans_store.error
            if unavailable: owned=unknown_stock(refs,'Saved stock unavailable.')
            ids,exclude=ownership_selection(owned,filters.ownership)
            maximum=data.profile.level if filters.use_character_level else filters.max_level
            items=self.catalogue.search(values['query'],category=category,equip_slot=filters.equip_slot,item_type=filters.item_type,
                min_level=filters.min_level,max_level=maximum,include_unknown_levels=filters.include_unknown_levels,item_ids=ids,exclude_item_ids=exclude)
            self.counts={i.reference.item_id:owned[i.reference.item_id] for i in items}
            if unavailable: self.counts=unknown_stock([i.reference for i in items],'Saved stock unavailable.')
            self.results={i.reference.item_id:i for i in items}
            self.table.rows([(i.reference.item_id,(i.reference.name,*[c.label for c in self.counts[i.reference.item_id]],
                ownership_state(self.counts[i.reference.item_id]),i.reference.equip_slot or 'Unknown',i.item_type,i.required_level,i.reference.item_id)) for i in items])
            self.status.setText(f'{len(items)} results · up to 50 · {self.catalogue.item_count} local records · Source-checked, not live verified')
            if persist: data.search_filters.save(self.character,self.scope,filters)
            self.selected(self.table.key())
        except (ValueError,OSError) as error:
            self.status.setText(str(error)); self.results={}; self.table.rows([]); self.detail.clear(); self.use.setEnabled(False)

    def selected(self,key):
        item=self.results.get(key)
        self.use.setEnabled(item is not None)
        if item:
            ref=item.reference
            self.detail.setText(f'Item level: {shown(item.item_level)} · Required level: {shown(item.required_level)} · Build: {ref.client_build or "Unknown"}\n'
                + '\n'.join(f'{c.label}: {c.reason}' for c in self.counts[key])+'\n'
                + '\n'.join(e['url'] for e in item.evidence)+'\n'+item.variant_note+'\n'+self.catalogue.coverage_note)
        else: self.detail.clear()

    def accept_item(self):
        item=self.results.get(self.table.key())
        if item:
            try: self.choose(item); self.accept()
            except (ValueError,OSError) as error: self.status.setText(str(error))

    def done(self,result):
        if self.pending.isActive():
            self.pending.stop(); self.refresh()
        super().done(result)
