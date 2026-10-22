"""Session-only destination selection and sample comparison; no Apply path."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QScrollArea, QWidget, QComboBox
from types import SimpleNamespace
from app import row, label, field
from widgets import Table
from snapshot_preview import SAMPLES, compare, shown


class SnapshotPreviewDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle('Character & inventory import · sample preview')
        self.resize(1080, 750); self.setPalette(host.palette())
        box = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); content.setPalette(host.palette()); scroll.viewport().setPalette(host.palette())
        layout = QVBoxLayout(content); scroll.setWidget(content); box.addWidget(scroll)
        layout.addWidget(label('SAMPLE DATA · Review only · Nothing will be applied or saved'))
        layout.addWidget(label('Explore how a future character/inventory import could look. These fictional reports are not live game data and are not the capability probe format.'))
        self.sample = host.combo([s.title for s in SAMPLES], lambda _: self.refresh())
        self.destination = QComboBox(); self.destination.setMaximumWidth(470)
        self.destination.addItem('Choose a destination character…', None)
        self.destination.addItem('Example character · sample records', None)
        for profile in host.data.profiles:
            self.destination.addItem(f'{profile.name} · {profile.id}', profile.id)
        self.destination.currentIndexChanged.connect(self.refresh)
        layout.addWidget(row(field('Sample scenario', self.sample), field('Preview destination', self.destination)))
        self.source = label(''); self.source.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.source)
        self.identity = label(''); self.identity.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.identity)
        self.profile_table = Table(['Field', 'Local value', 'Sample value', 'Review'], height=150)
        layout.addWidget(self.profile_table)
        self.summary = label(''); layout.addWidget(self.summary)
        self.table = Table(['Location','Item ID','Item','Stored count','Sample count','Preview','Reason'], height=240)
        layout.addWidget(self.table)
        self.details = label('Select an item row to read its full details.')
        self.details.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.details)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.table.setColumnWidth(2,240); self.table.setColumnWidth(6,340)
        layout.addWidget(label('Stored counts are prior manual observations, not live stock. Unknown and partial counts never replace a known total. Unlisted local items stay unchanged; name-only matches need review. Your filters, playstyle and unfinished editors are excluded.'))
        layout.addWidget(label('Next step after live API verification: source identity/build checks, stale-report handling and an explicit reviewed apply action. No sample can be applied in this version.'))
        box.addWidget(row(host.button('Close preview', self.accept)))
        host.style_table(self.table); host.style_table(self.profile_table); host.wire_nested_scrolling(self)
        self.refresh()

    def show_details(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.preview_rows):
            location, item_id, name, current, incoming, action, reason = self.preview_rows[index]
            self.details.setText(f'{name} · ID {item_id} · {location}\nStored: {current} · Sample: {incoming}\n{action}: {reason}')

    def refresh(self, *_):
        if not hasattr(self, 'table'):
            return
        sample = SAMPLES[self.sample.currentIndex()]
        self.source.setText(f'Fictional source: Sample adventurer · Sample realm · Dwarf {sample.character_class}\n'
                            f'Source ID: sample-character-01 · Build: Unknown · Observation time: Unknown\n'
                            f'Bags: {sample.bags} · Bank: {sample.bank} · Level: {shown(sample.level)}')
        key = self.destination.currentData()
        profile = next((p for p in self.host.data.profiles if p.id==key), None)
        example = self.destination.currentIndex()==1
        if example:
            profile = SimpleNamespace(name='Example character (fictional)', character_class='Paladin', level=18)
        self.preview_rows = []
        self.details.setText('Select an item row to read its full details.')
        if profile is None:
            self.identity.setText('Choose a destination to compare. No character is matched automatically.')
            self.table.rows([]); self.profile_table.rows([]); self.summary.setText('No destination selected.'); return
        self.identity.setText(f'Preview destination: {profile.name}. This selection does not switch your active character or confirm source identity.')
        self.profile_table.rows([
            ('name', ('Name', profile.name, 'Sample adventurer', 'Keep local display name')),
            ('class', ('Class', profile.character_class, sample.character_class, 'Compare only · confirm identity')),
            ('level', ('Level', shown(profile.level), shown(sample.level), 'Keep local' if sample.level is None else 'Compare only')),
        ])
        # Avoid Data.inventory: its setdefault would create a record as a side effect.
        book = self.host.data.inventories.get(key)
        entries = book.entries if book else []
        if example:
            # In-memory fixtures only; deliberately include both an exact ID and
            # an unlinked manual name to demonstrate the review distinction.
            from inventory import InventoryEntry
            from catalogue import CatalogueRef
            ref = CatalogueRef(900000001,'Sample copper ore',None,'https://example.invalid/',
                               '2026-01-01','fictional-sample')
            entries = [InventoryEntry('ore','Sample copper ore',6,'Bags','2026-01-01T00:00:00+00:00',catalogue_ref=ref),
                       InventoryEntry('bank','Sample copper ore',27,'Bank','2026-01-01T00:00:00+00:00',catalogue_ref=ref),
                       InventoryEntry('potion','Sample healing potion',1,'Bags','2026-01-01T00:00:00+00:00')]
        rows = compare(sample, entries)
        self.preview_rows = rows
        self.table.rows((str(i), values) for i, values in enumerate(rows))
        self.show_details()
        updates = sum(r[5]=='Would update' for r in rows); adds = sum(r[5]=='Would add' for r in rows)
        reviews = sum(r[5].startswith('Review') for r in rows); keeps = len(rows)-updates-adds-reviews
        self.summary.setText(f'Preview only: {adds} additions · {updates} count updates · {reviews} need review · {keeps} kept/no count change. Nothing applied.')
