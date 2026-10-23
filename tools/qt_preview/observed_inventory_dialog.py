"""Browse separately saved addon observations without switching active profiles."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox
from app import label
from widgets import Table
from observed_inventory import ObservationStore
from game_data_review import observed_time
from pathlib import Path
from saved_inventory_view import linked_snapshots
from character_links import LinkStore


class ObservedInventoryDialog(QDialog):
    def __init__(self,host,*,embedded=False):
        super().__init__(host);self.host=host;self.ledger={}
        self.embedded=embedded
        if embedded:self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle('Saved addon inventory');self.resize(900,650);box=QVBoxLayout(self)
        box.addWidget(label('Saved Bags & Bank · Read-only. These snapshots do not change manual plans or enable automatic count replacement.'))
        self.character=QComboBox();box.addWidget(self.character)
        for p in host.data.saved_profiles:self.character.addItem(p.name,p.id)
        self.character.setCurrentIndex(self.character.findData(host.data.active))
        self.character.setVisible(not embedded)
        self.locations=Table(['Location','Saved state','Captured (local time)'],self.select,height=120);box.addWidget(self.locations)
        if embedded:self.locations.setMaximumHeight(130)
        self.notice=label('');self.notice.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.notice)
        self.items=Table(['Item','Quantity','Item ID'],height=300);box.addWidget(self.items,1)
        box.addWidget(host.button('Refresh saved observations',self.refresh))
        if not embedded:box.addWidget(host.button('Close',self.accept))
        self.character.currentIndexChanged.connect(self.refresh)
        self._loaded_signature=None;self._pending_signature=None
        self.watch_timer=QTimer(self);self.watch_timer.setInterval(2000)
        self.watch_timer.timeout.connect(self.poll_saved_files)
        host.style_table(self.locations);host.style_table(self.items);host.wire_nested_scrolling(self);self.refresh()

    def source_signature(self):
        directory=self.host.data.directory
        profile=self.host.data.active if self.embedded else self.character.currentData()
        paths=[directory/'character_links.json',directory/'addon_inventory.json']
        paths.extend(Path(e['identity']['source']) for e in LinkStore(directory).records['links'] if e['profile']==profile)
        values=[]
        for path in paths:
            try:
                stat=path.stat();values.append((str(path),stat.st_size,stat.st_mtime_ns))
            except OSError:values.append((str(path),None,None))
        return profile,tuple(values)

    def showEvent(self,event):
        super().showEvent(event)
        self.refresh();self.watch_timer.start()

    def hideEvent(self,event):
        self.watch_timer.stop();super().hideEvent(event)

    def poll_saved_files(self):
        if not self.isVisible():return
        try:signature=self.source_signature()
        except (OSError,ValueError):
            self.refresh();return
        if signature==self._loaded_signature:
            self._pending_signature=None;return
        # Wait for two equal observations so an in-progress save is not read.
        # A rejected read remains retryable on later ticks.
        if signature!=self._pending_signature:
            self._pending_signature=signature;return
        self.refresh()

    def refresh(self):
        selected_scope=self.locations.key() or 'bags'
        if self.embedded:
            self.character.blockSignals(True);self.character.clear()
            for p in self.host.data.saved_profiles:self.character.addItem(p.name,p.id)
            self.character.setCurrentIndex(self.character.findData(self.host.data.active))
            self.character.blockSignals(False)
        self.items.rows([])
        profile=self.character.currentData()
        try:
            signature=self.source_signature()
            snapshots=linked_snapshots(self.host.data.directory,profile)
            self.ledger=({(profile,scope):record for scope,record in snapshots.items()} if snapshots is not None
                         else ObservationStore(self.host.data.directory).ledger)
        except (ValueError,OSError) as exc:
            self.ledger={};self.locations.rows([]);self.notice.setText('Could not read addon observations: '+str(exc));return
        rows=[]
        for scope in ('bags','bank'):
            record=self.ledger.get((profile,scope))
            state=('Saved snapshot' if Path(record['identity']['source']).is_file() else 'Saved snapshot · source removed/unavailable') if record else 'Not observed · not empty'
            if record and record.get('direct') and (record['coverage']!='complete' or record['interrupted']):state='Partial saved scan · subtotals only'
            rows.append((scope,(scope.title(),state,observed_time(record['finished']) if record else '—')))
        self.locations.rows(rows);self.notice.setText('Select Bags or Bank. Saved observations are separate from manual records.')
        self.locations.selectRow(0 if selected_scope=='bags' else 1)
        self.select(selected_scope)
        self._loaded_signature=signature;self._pending_signature=None

    def select(self,scope):
        record=self.ledger.get((self.character.currentData(),scope));rows=[]
        if record:
            for item,quantity in record['rows']:
                try:matches=self.host.catalogue().search(str(item),limit=1)
                except (ValueError,OSError):matches=[]
                rows.append((item,(record.get('names',{}).get(item) or (matches[0].name if matches else f'Item #{item}'),quantity,item)))
        self.items.rows(rows)
        if record:
            partial=record.get('direct') and (record['coverage']!='complete' or record['interrupted'])
            message=('Partial saved scan · quantities are subtotals; missing items remain unknown.' if partial else
                     'Complete saved snapshot.' if record['rows'] else 'This complete saved snapshot contains no items.')
            self.notice.setText(message+' Saved '+observed_time(record['finished'])+'. Read-only; not live inventory.')
        else:self.notice.setText('No saved addon observation for this location. Unknown, not empty. Manual records are unchanged.')
