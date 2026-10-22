"""A read-only breakdown of applied records, independent of the item editor."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QScrollArea,QWidget
from app import row,label
from widgets import Table


class WishlistAltDialog(QDialog):
    def __init__(self,host,item,characters):
        super().__init__(host)
        self.host=host
        self.item=item
        self.origin=(host.data.active,host.data.playstyles.active(host.data.active))
        self.setPalette(host.palette()); self.setWindowTitle('Other characters · wishlist stock'); self.resize(1100,700)
        box=QVBoxLayout(self); scroll=QScrollArea(); scroll.setWidgetResizable(True)
        content=QWidget(); content.setPalette(host.palette()); scroll.viewport().setPalette(host.palette())
        layout=QVBoxLayout(content); scroll.setWidget(content); box.addWidget(scroll)
        layout.addWidget(label(f'{item.name} · {item.slot}'))
        layout.addWidget(label('Other characters only. Applied local records; unfinished inventory edits are excluded. These counts do not change your ownership or goal status, and do not establish that an item can be transferred.'))
        self.table=Table(['Character','Bags','Bank','Bags details','Bank details'],height=300)
        self.table.content_column=0; layout.addWidget(self.table)
        self.table.setColumnWidth(3,260); self.table.setColumnWidth(4,260)
        self.table.rows((c.character_id,(c.character,c.counts[0].label,c.counts[1].label,c.counts[0].reason,c.counts[1].reason)) for c in characters)
        layout.addWidget(label('Unknown includes missing, blank, ambiguous or outdated records. Recheck reasons appear in the details and full text is available on hover.' if characters else 'No other characters have been recorded yet.'))
        self.notice=label('Select a character to open its Inventory & Bank. Unfinished edits stay with their characters.')
        layout.addWidget(self.notice)
        self.open_button=host.button('Open character inventory',self.open_inventory)
        self.open_button.setEnabled(False)
        box.addWidget(row(self.open_button,host.button('Close',self.accept)))
        self.table.itemSelectionChanged.connect(self.selection_changed)
        host.style_table(self.table); host.wire_nested_scrolling(self)

    def selection_changed(self):
        key=self.table.key()
        available=key is not None and key in {p.id for p in self.host.data.profiles}
        self.open_button.setEnabled(available)
        self.notice.setText('Temporarily search this character’s Inventory & Bank for this item. Back restores its filters; unfinished edits stay unchanged.' if available else
                            'This record has no matching character profile. Its data is preserved.' if key is not None else
                            'Select a character to open its Inventory & Bank. Unfinished edits stay with their characters.')

    def open_inventory(self):
        key=self.table.key()
        if key is None or key not in {p.id for p in self.host.data.profiles}:
            self.selection_changed(); return
        try:
            # Use normal character navigation: it remembers every outgoing draft
            # and restores the destination's drafts, filters and playstyle.
            self.host.open_inventory_from_wishlist(key,self.origin,self.item)
        except (ValueError,OSError,TypeError) as error:
            self.notice.setText(str(error)); return
        self.accept()
