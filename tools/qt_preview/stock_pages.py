"""Inventory and wishlist editors using the original stock/undo/filter models."""
from copy import deepcopy
from dataclasses import asdict
from html import escape
import re
from uuid import uuid4
from PySide6.QtCore import Qt, QEvent, QSize
from PySide6.QtWidgets import QLabel,QCheckBox
from presentation import easy_mode,simple_count,simple_other_stock
from app import row, label
from widgets import Page, Form, Table, integer, shown
from inventory import InventoryEntry, InventoryBook, utc_now, entered_time
from inventory_filters import InventoryFilters, COUNT_FILTERS
from inventory_undo import RemovedEntry
from gear import GearItem, GearWishlist, SLOTS, PRIORITIES, STATUSES
from gear_filters import GearFilters
from gear_undo import RemovedGoal
from item_stock import recorded_stock, ownership_state, OWNERSHIP_FILTERS, RecordedCount
from professions import stock_time
from catalogue import wishlist_slots
from playstyles import PresetFilters, PresetUndo
from wishlist_alt_stock import other_stock,total_label,location_details
from ownership import counts as ownership_counts
from wishlist_alt_dialog import WishlistAltDialog
from wishlist_table import WishlistTable


def inventory_filter_summary(filters):
    search=f'“{filters["query"]}”' if filters['query'] else '(empty)'
    return f"Search: {search} · Show: {filters['location']} · Count status: {filters['count_status']}"


def wrap_filter_feedback(text):
    """Display-only break opportunities; stored searches and link actions stay exact."""
    return re.sub(r'\S{17,}',lambda match:'\u200b'.join(match[0][i:i+12] for i in range(0,len(match[0]),12)),text)


class FilterFeedbackLabel(QLabel):
    """Allow long search tokens to wrap inside the available page width."""
    def __init__(self):
        super().__init__('')
        self.setWordWrap(True)

    def minimumSizeHint(self):
        hint=super().minimumSizeHint()
        return QSize(min(160,hint.width()),hint.height())


class StockPage(Page):
    def __init__(self, host, gear=False):
        self.gear = gear
        self.temporary_filters = None  # One wishlist visit; never written to a store.
        self.wishlist_search_item = None  # Retained link while browsing normally.
        self.kind = 'Gear wishlist' if gear else 'Inventory & Bank'
        super().__init__(host, self.kind)
        self.show_details=QCheckBox('Show details')
        self.show_details.toggled.connect(self.refresh)
        self.box.addWidget(self.show_details)
        if not gear:
            self.simple_notice=label('Manual records below. Linked characters use Saved addon inventory for ownership checks; these counts are kept separately.')
            self.box.addWidget(self.simple_notice)
            self.import_preview_button = self.action('Sample import preview', self.show_import_preview)
            self.box.addWidget(row(self.import_preview_button))
        self.filters = Form(host, [('query','Search',str,''),
            ('status' if gear else 'location','Goal status' if gear else 'Show',('All',*STATUSES) if gear else ('All','Bags','Bank'),'All'),
            ('ownership' if gear else 'count_status','Ownership' if gear else 'Count status',OWNERSHIP_FILTERS if gear else COUNT_FILTERS,'All')])
        self.box.addWidget(self.filters)
        self.temporary_filter_notice = FilterFeedbackLabel()
        self.temporary_filter_notice.setTextFormat(Qt.TextFormat.RichText)
        self.temporary_filter_notice.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse|Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.temporary_filter_notice.setOpenExternalLinks(False)
        self.temporary_filter_notice.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.temporary_filter_notice.linkActivated.connect(lambda _:self.run(self.reapply_temporary_search))
        self.temporary_filter_notice.installEventFilter(self)
        self.temporary_filter_notice.hide()
        self.restore_filters_button = self.action('Restore previous filters',self.restore_previous_filters)
        self.restore_filters_button.hide()
        self.restore_filters_button.setToolTip('Resume normal inventory browsing. Your wishlist return link and unfinished edits stay available.')
        self.restore_filters_preview = FilterFeedbackLabel()
        self.restore_filters_preview.setTextFormat(Qt.TextFormat.RichText)
        self.restore_filters_preview.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse|Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.restore_filters_preview.setOpenExternalLinks(False)
        self.restore_filters_preview.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.restore_filters_preview.linkActivated.connect(lambda _:self.run(self.restore_previous_filters))
        self.restore_filters_preview.installEventFilter(self)
        self.restore_filters_preview.hide()
        self.restore_filters_confirmation = FilterFeedbackLabel()
        self.restore_filters_confirmation.setTextFormat(Qt.TextFormat.PlainText)
        self.restore_filters_confirmation.hide()
        self.box.addWidget(row(self.restore_filters_button))
        self.box.addWidget(self.restore_filters_preview)
        self.box.addWidget(self.restore_filters_confirmation)
        self.box.addWidget(self.temporary_filter_notice)
        self.filter_indicator = self.action('All items shown', self.reset_filters)
        self.box.addWidget(row(self.action('Reset filters',self.reset_filters),self.filter_indicator))
        self.summary_buttons = {}
        choices = OWNERSHIP_FILTERS if gear else COUNT_FILTERS
        for choice in choices:
            self.summary_buttons[choice] = self.action(choice,lambda c=choice:self.filter_set('ownership' if gear else 'count_status',c))
        self.box.addWidget(row(*self.summary_buttons.values()))
        self.location_buttons = {}
        if not gear:
            for choice in ('All','Bags','Bank'):
                self.location_buttons[choice] = self.action(choice,lambda c=choice:self.filter_set('location',c))
            self.box.addWidget(row(*self.location_buttons.values()))
        self.table = (WishlistTable(['Item','Bags','Bank','Ownership','Other bags','Other bank','Slot','Priority','Goal status','BiS','Source'],
                                   self.select,lambda key:self.run(lambda:self.show_other_stock(key))) if gear else
                      Table(['Item','Location','Count','Status','Entered (UTC)','Note'],self.select))
        self.box.addWidget(self.table)
        if gear:
            self.box.addWidget(row(self.action('Other characters’ stock',self.show_other_stock)))
            self.box.addWidget(row(self.action('Compare equipped gear',self.show_equipment_comparison)))
            self.stock_explanation=label('');self.box.addWidget(self.stock_explanation)
        self.undo_button = self.action('Undo last removal',self.undo)
        self.undo_preview = self.action('Nothing to restore',self.undo)
        self.box.addWidget(row(self.action('New entry',self.new),self.action('Remove selected',self.remove),self.undo_button,self.undo_preview))
        specs = [('name','Item name',str,'')]
        specs += ([('slot','Slot',SLOTS,'Unspecified'),('priority','Priority',PRIORITIES,'Normal'),
                   ('status','Goal status',STATUSES,'Wanted'),('source','Source',str,''),('note','Note',str,''),('bis_candidate','Personal BiS candidate',bool,False)] if gear else
                  [('quantity','Count · blank = Unknown',str,'1'),('location','Location',('Bags','Bank'),'Bags'),('note','Note',str,'')])
        self.form = Form(host,specs)
        self.box.addWidget(self.form)
        self.lookup_controls('Gear' if gear else 'All')
        self.box.addWidget(row(self.action('Apply entry',self.apply),self.action('Save wishlist' if gear else 'Save inventory',self.save)))
        self.box.addWidget(label('Recorded ownership is separate from Wanted/Obtained. Missing counts remain Unknown. Apply confirms a manual inventory observation; Undo preserves its original timestamp.'))
        self.filters.changed(self.filter_changed)
        self.restore(self.data.active)

    @property
    def book(self): return self.data.wishlist if self.gear else self.data.inventory

    def show_import_preview(self):
        from snapshot_preview_dialog import SnapshotPreviewDialog
        dialog = SnapshotPreviewDialog(self.host)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def show_equipment_comparison(self):
        from equipment_comparison_dialog import EquipmentComparisonDialog
        dialog=EquipmentComparisonDialog(self.host)
        try:dialog.exec()
        finally:dialog.deleteLater()

    @property
    def filter_store(self):
        if self.gear and self.data.playstyles.active(self.data.active)!='General': return PresetFilters(self.data.playstyles,self.data.active)
        return self.data.gear_filters if self.gear else self.data.inventory_filters
    @property
    def undo_store(self):
        if self.gear and self.data.playstyles.active(self.data.active)!='General': return PresetUndo(self.data.playstyles,self.data.active)
        return self.data.gear_undo if self.gear else self.data.inventory_undo

    def remember(self,character):
        super().remember((character,self.data.playstyles.active(character)) if self.gear else character)

    def restore(self, character):
        self.restore_filters_confirmation.hide()
        temporary = self.temporary_filters
        self.filters.load(temporary['current'] if temporary and temporary['character']==character
                          else asdict(self.filter_store.get(character)))
        super().restore((character,self.data.playstyles.active(character)) if self.gear else character)
        if self.gear: self.message('')

    def begin_temporary_search(self, name):
        """Reuse ordinary name search without loading an item or saving filters."""
        if self.gear: return
        filters = InventoryFilters(query=name)
        filters.validate()
        self.end_temporary_search()
        self.wishlist_search_item = (self.data.active,name)
        self.temporary_filters = {'character':self.data.active, 'item_name':name, 'previous':self.filters.values(),
                                  'current':asdict(filters)}
        self.filters.load(asdict(filters)); self.refresh()

    def end_temporary_search(self,keep_link=False):
        self.restore_filters_confirmation.hide()
        temporary = self.temporary_filters
        self.temporary_filters = None
        if not keep_link: self.wishlist_search_item = None
        if temporary and temporary['character']==self.data.active:
            self.filters.load(temporary['previous'])
        self.refresh()

    def restore_previous_filters(self):
        if self.temporary_filters and self.temporary_filters['character']==self.data.active:
            self.end_temporary_search(keep_link=True)
            confirmation='Previous filters restored — '+inventory_filter_summary(self.filters.values())
            self.restore_filters_confirmation.setText(wrap_filter_feedback(confirmation))
            self.restore_filters_confirmation.setAccessibleName(confirmation)
            self.restore_filters_confirmation.show()

    def reapply_temporary_search(self):
        item = self.wishlist_search_item
        if not item or item[0]!=self.data.active: return
        temporary = self.temporary_filters
        if temporary is None:
            # Starting another search captures the latest normal browsing filters.
            self.begin_temporary_search(item[1])
            return
        if not temporary or temporary['character']!=self.data.active: return
        # Keep the original restore snapshot; only replace this visit's view.
        temporary['current'] = asdict(InventoryFilters(query=temporary['item_name']))
        self.filters.load(temporary['current']); self.refresh()

    def eventFilter(self, watched, event):
        if watched in (self.temporary_filter_notice,getattr(self,'restore_filters_preview',None)) and event.type()==QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space):
                if not event.isAutoRepeat():
                    self.run(self.restore_previous_filters if watched is self.restore_filters_preview else self.reapply_temporary_search)
                return True
        return super().eventFilter(watched,event)

    def dirty(self,kind):
        super().dirty(self.data.gear_dirty_key() if self.gear else kind)

    def filter_changed(self,*_):
        self.restore_filters_confirmation.hide()
        def update():
            if self.gear and self.data.playstyles.active(self.data.active)!='General': self.data.require_profile_saved()
            filters = (GearFilters if self.gear else InventoryFilters)(**self.filters.values())
            if self.temporary_filters and self.temporary_filters['character']==self.data.active:
                filters.validate()
                self.temporary_filters['current'] = asdict(filters)
            else:
                self.filter_store.save(self.data.active,filters)
            self.refresh()
        self.run(update)

    def filter_set(self,key,value):
        self.filters.load({key:value}); self.filter_changed()

    def reset_filters(self):
        self.filters.load(self.filters.defaults); self.filter_changed()

    def sync_temporary_notice(self):
        temporary = self.temporary_filters is not None and self.temporary_filters['character']==self.data.active
        linked = self.wishlist_search_item is not None and self.wishlist_search_item[0]==self.data.active
        name=self.wishlist_search_item[1] if linked else ''
        caption='Temporary wishlist search for' if temporary else 'Wishlist item'
        help_text=('Filter changes here are not saved. Restore previous filters to browse normally, or go Back to wishlist.' if temporary else
                   'Browsing normally. Click the item to search again; your current filters will remain restorable.')
        self.temporary_filter_notice.setText(
            f'{caption}: <a href="reapply-item" style="color: {self.host.colors[3]};">{escape(wrap_filter_feedback(name))}</a><br>{help_text}' if linked else '')
        self.temporary_filter_notice.setAccessibleName(f'Reapply temporary wishlist search for: {name}' if linked else '')
        self.temporary_filter_notice.setToolTip('Click the item name to search for it again, with Show and Count status set to All. Previous filters and unfinished edits stay unchanged.' if linked else '')
        self.temporary_filter_notice.setVisible(linked)
        self.restore_filters_button.setVisible(temporary)
        previous=self.temporary_filters['previous'] if temporary else None
        preview='Will restore — '+inventory_filter_summary(previous) if previous else ''
        self.restore_filters_preview.setText(f'<a href="restore-filters" style="color: {self.host.colors[3]};">{escape(wrap_filter_feedback(preview))}</a>' if temporary else '')
        self.restore_filters_preview.setAccessibleName(preview)
        self.restore_filters_preview.setToolTip('Click to restore these filters. Your wishlist item link and unfinished edits stay available.' if temporary else '')
        self.restore_filters_preview.setVisible(temporary)

    def refresh(self):
        super().refresh()
        if not hasattr(self,'form'): return
        self.sync_temporary_notice()
        filters = self.filters.values()
        entries = self.book.entries
        if self.gear:
            refs = self.host.stock_references([(e.name,e.catalogue_ref) for e in entries])
            counts = ownership_counts(self.data,[(e.id,e.name,e.catalogue_ref) for e in entries],references=refs)
            if self.data.inventory_store.error or self.data.plans_store.error:
                counts={e.id:(RecordedCount(reason='Saved stock unavailable.'),)*2 for e in entries}
            states = {key:ownership_state(value) for key,value in counts.items()}
            self.alt_counts=other_stock(self.data,entries,refs)
            visible = self.book.find(filters['query'],filters['status'])
            visible = [e for e in visible if filters['ownership']=='All' or states[e.id]==filters['ownership']]
            rows = [(e.id,(e.name,counts[e.id][0].label,counts[e.id][1].label,states[e.id],
                          total_label(self.alt_counts[e.id],0),total_label(self.alt_counts[e.id],1),
                          e.slot,e.priority,e.status,'Yes' if e.bis_candidate else 'No',e.source)) for e in visible]
        else:
            aliases=self.data.plan.aliases(self.book)
            states={}
            for e in entries:
                cutoff=self.book.cutoff_for(e,self.data.plan.recheck_after,aliases)
                states[e.id]='Recheck' if cutoff and entered_time(e.updated_at)<=stock_time(cutoff) else 'Unknown' if e.quantity is None else 'Known'
                if self.data.plans_store.error or self.data.inventory_store.error: states[e.id]='Unknown'
            visible=[e for e in self.book.find(filters['query'],filters['location']) if filters['count_status']=='All' or states[e.id]==filters['count_status']]
            rows=[(e.id,(e.name,e.location,e.quantity if states[e.id]=='Known' else None,states[e.id],e.updated_at,e.note)) for e in visible]
            for choice,b in self.location_buttons.items():
                b.setText(f'{choice}: {sum(choice=="All" or e.location==choice for e in entries)}')
        simple=easy_mode(self.host) and not self.show_details.isChecked()
        if self.gear:
            self.table.setHorizontalHeaderLabels(['Item','In bags','In bank','Ownership','On other characters','Other bank','Slot','Priority','Goal status','BiS','Source'] if simple else ['Item','Bags','Bank','Ownership','Other bags','Other bank','Slot','Priority','Goal status','BiS','Source'])
            for col in (3,5,9,10):self.table.setColumnHidden(col,simple)
            self.stock_explanation.setText('Linked characters use saved addon counts; others use manual records. Other characters’ items stay separate. Missing records mean not checked.' if simple else 'Bags, Bank and Ownership use linked addon snapshots, otherwise manual records. These sources are never summed. Hover a count for its source and capture time. Other bags/bank remain separate; “+ Unknown” means incomplete records.')
            if simple:
                rows=[(e.id,(e.name,*(simple_count(c.quantity,'Unknown' if c.quantity is None else 'Known') for c in counts[e.id]),states[e.id],simple_other_stock(self.alt_counts[e.id]),total_label(self.alt_counts[e.id],1),e.slot,e.priority,e.status,'Yes' if e.bis_candidate else 'No',e.source)) for e in visible]
        else:
            self.import_preview_button.setVisible(not simple)
            self.simple_notice.setVisible(simple)
            for col in (3,4,5):self.table.setColumnHidden(col,simple)
            self.table.horizontalHeaderItem(2).setText('Have here?' if simple else 'Count')
            if simple:
                rows=[(e.id,(e.name,e.location,simple_count(e.quantity,states[e.id]),states[e.id],e.updated_at,e.note)) for e in visible]
        self.table.rows(rows)
        if self.gear:
            for index,key in enumerate(self.table.keys):
                for location in (0,1):
                    self.table.item(index,1+location).setToolTip(counts[key][location].reason)
                for location in (0,1):
                    cell=self.table.item(index,4+location)
                    font=cell.font(); font.setUnderline(True); cell.setFont(font)
                    cell.setToolTip('Click to view other characters’ bags and bank. Editor fields stay unchanged.' if simple else 'Click to view other characters’ stock. Editor fields stay unchanged.\n'+location_details(self.alt_counts[key],location))
        for choice,b in self.summary_buttons.items(): b.setText(f'{choice}: {sum(choice=="All" or states[e.id]==choice for e in entries)}')
        active=filters != self.filters.defaults
        self.filter_indicator.setText(f'Filters active · {len(entries)-len(visible)} hidden · click to reset' if active else 'All items shown')
        record=self.undo_store.records.get(self.data.active)
        can_restore=record is not None and not any(e.id==record.item.id for e in entries)
        self.undo_button.setEnabled(can_restore); self.undo_preview.setEnabled(can_restore)
        self.undo_preview.setText(f'Will restore: {record.item.name} · {record.item.slot if self.gear else record.item.location}' if can_restore else 'Nothing to restore')

    def show_other_stock(self,key=None):
        item=next((e for e in self.book.entries if e.id==(self.table.key() if key is None else key)),None)
        if item is None: raise ValueError('Select a wishlist row to see other characters’ stock.')
        self.refresh()  # Updates only tables; does not reload raw editor fields.
        dialog=WishlistAltDialog(self.host,item,self.alt_counts[item.id]); dialog.exec(); dialog.deleteLater()

    def select(self,key):
        entry=next((e for e in self.book.entries if e.id==key),None)
        if entry:
            self.edit_id=entry.id; self.reference=entry.catalogue_ref
            self.form.load(asdict(entry)); self.link_label()

    def use_item(self,item,key='name'):
        super().use_item(item,key)
        if self.gear: self.form.load({'slot':wishlist_slots(item.reference.equip_slot)[0]})

    def apply(self,confirm=True):
        values=self.form.values()
        existing=next((e for e in self.book.entries if e.id==self.edit_id),None)
        if self.edit_id and not existing:
            raise ValueError('This entry was removed. Choose New entry or select an existing row.')
        if not self.gear:
            values['quantity']=integer(values['quantity'],True)
            values['updated_at']=utc_now() if confirm or existing is None else existing.updated_at
        entry=(GearItem if self.gear else InventoryEntry)(id=self.edit_id or uuid4().hex,catalogue_ref=self.reference,**values)
        candidate=deepcopy(self.book)
        if existing: candidate.entries=[entry if e.id==entry.id else e for e in candidate.entries]
        else: candidate.entries.append(entry)
        candidate.validate()
        if self.gear: self.data.set_wishlist(candidate)
        else: self.data.inventories[self.data.active]=candidate
        self.edit_id=entry.id
        self.dirty(self.kind)
        self.refresh()
        return True

    def save(self):
        self.data.save_records(self.kind)
        self.message('Applied entries saved locally. Unfinished fields are unchanged; use Apply entry before saving an edit.')

    def remove(self):
        selected=self.table.key()
        found=next(((i,e) for i,e in enumerate(self.book.entries) if e.id==selected),None)
        if found is None: raise ValueError('Select a row to remove.')
        record=(RemovedGoal if self.gear else RemovedEntry)(found[0],deepcopy(found[1]))
        if self.gear and self.data.playstyles.active(self.data.active)!='General': self.data.require_profile_saved()
        self.undo_store.save({**self.undo_store.records,self.data.active:record})
        self.book.entries.pop(found[0])
        self.dirty(self.kind)
        self.refresh()  # Keep current draft; removal never secretly applies it.

    def undo(self):
        record=self.undo_store.records.get(self.data.active)
        if record is None: raise ValueError('No removal to undo for this character.')
        candidate=deepcopy(self.book)
        candidate.entries.insert(min(record.index,len(candidate.entries)),deepcopy(record.item))
        candidate.validate()
        if self.gear: self.data.set_wishlist(candidate)
        else: self.data.inventories[self.data.active]=candidate
        # Keep recovery on disk until the restored item itself has been saved.
        self.dirty(self.kind); self.refresh()
        self.message('Restored the entry with its original details. Save to keep it; unfinished edits are unchanged.')
