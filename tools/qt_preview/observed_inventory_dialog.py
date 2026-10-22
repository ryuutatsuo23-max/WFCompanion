"""Browse separately saved addon observations without switching active profiles."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox
from app import label
from widgets import Table
from observed_inventory import ObservationStore
from game_data_review import observed_time
from pathlib import Path


class ObservedInventoryDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.ledger={}
        self.setWindowTitle('Saved addon inventory');self.resize(900,650);box=QVBoxLayout(self)
        box.addWidget(label('Saved addon snapshots, not live inventory. Linked characters use these counts for wishlist and crafting checks. Manual records remain separate; unopened banks stay unknown.'))
        self.character=QComboBox();box.addWidget(self.character)
        for p in host.data.saved_profiles:self.character.addItem(p.name,p.id)
        self.character.setCurrentIndex(self.character.findData(host.data.active))
        self.locations=Table(['Location','Saved state','Captured (local time)'],self.select,height=120);box.addWidget(self.locations)
        self.notice=label('');self.notice.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.notice)
        self.items=Table(['Item','Quantity','Item ID'],height=300);box.addWidget(self.items)
        box.addWidget(host.button('Refresh saved observations',self.refresh))
        box.addWidget(host.button('Close',self.accept));self.character.currentIndexChanged.connect(self.refresh)
        host.style_table(self.locations);host.style_table(self.items);host.wire_nested_scrolling(self);self.refresh()

    def refresh(self):
        self.items.rows([])
        try:self.ledger=ObservationStore(self.host.data.directory).ledger
        except (ValueError,OSError) as exc:
            self.ledger={};self.locations.rows([]);self.notice.setText('Could not read addon observations: '+str(exc));return
        profile=self.character.currentData();rows=[]
        for scope in ('bags','bank'):
            record=self.ledger.get((profile,scope))
            state=('Saved snapshot' if Path(record['identity']['source']).is_file() else 'Saved snapshot · source removed/unavailable') if record else 'Not observed · not empty'
            rows.append((scope,(scope.title(),state,observed_time(record['finished']) if record else '—')))
        self.locations.rows(rows);self.notice.setText('Select Bags or Bank. Link an addon character in Overview to start automatic observation updates.')
        if self.locations.key():self.select(self.locations.key())

    def select(self,scope):
        record=self.ledger.get((self.character.currentData(),scope));rows=[]
        if record:
            for item,quantity in record['rows']:
                try:matches=self.host.catalogue().search(str(item),limit=1)
                except (ValueError,OSError):matches=[]
                rows.append((item,(matches[0].name if matches else f'Item #{item}',quantity,item)))
        self.items.rows(rows)
        self.notice.setText(('Complete saved snapshot · '+observed_time(record['finished'])+' · '+record['identity']['environment']+' environment. Item names use the local catalogue.' if record['rows'] else 'This complete saved snapshot contains no items.') if record else 'No saved addon observation for this location. Existing manual records are unchanged.')
