"""Offline auction snapshots; no market operations or fabricated live listings."""
from datetime import datetime
from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QComboBox,QLineEdit,QFileDialog,QHBoxLayout,QLabel
from PySide6.QtGui import QPixmap
from controls import ComboBox as QComboBox
from app import row,label
from widgets import Table
from local_journal import money


class SavedAuctionsPage(QWidget):
    def __init__(self,host):
        super().__init__();self.host=host;self.path=None;self.snapshot=None
        box=QVBoxLayout(self)
        self.status=label('No saved Auction House listings loaded. The new addon is being prepared offline; live capture is not enabled yet.')
        self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText)
        heading=QHBoxLayout();box.addLayout(heading)
        self.logo=QLabel();self.logo.setAccessibleName('Forever Auction House logo');self.logo.setFixedSize(88,88)
        base=Path(sys._MEIPASS)/'payload' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
        pixmap=QPixmap(str(base/'addons/WFAuctionHouse/branding/forever-auction-house-logo.png'))
        if not pixmap.isNull():
            self.logo.setPixmap(pixmap.scaled(88,88,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            heading.addWidget(self.logo)
        else:self.logo.hide()
        heading.addWidget(self.status,1)
        self.market=QComboBox();self.market.addItem('No saved markets',None)
        self.search=QLineEdit();self.search.setPlaceholderText('Search saved item name or ID…');self.search.setClearButtonEnabled(True)
        box.addWidget(row(self.market,self.search))
        self.saved=label('');self.saved.setWordWrap(True);self.saved.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.saved)
        self.items=Table(['Item','Quantity','Bid','Buyout','Unit price','Item ID'],height=350);box.addWidget(self.items)
        self.summary=label('');box.addWidget(self.summary)
        box.addWidget(label('Historical listings only. Availability and expiry are unknown. No buying, bidding, selling or cancelling occurs.'))
        self.details=label('');self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText);self.details.hide()
        box.addWidget(row(host.button('Open offline sample',self.choose),host.button('Refresh',self.refresh),host.button('Details',lambda:self.details.setVisible(not self.details.isVisible()))))
        box.addWidget(self.details)
        self.search.textChanged.connect(self.filter_rows);self.market.currentIndexChanged.connect(self.filter_rows)
        host.style_table(self.items)

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'Open offline Auction House sample','','Offline samples (*.json)')
        if path:self.load(Path(path))

    def refresh(self):
        if self.path:self.load(self.path)

    def load(self,path):
        from wfauction_reader import read_market
        old=self.market.currentData();self.market.blockSignals(True);self.market.clear()
        self.snapshot=None;self.path=path
        try:
            self.snapshot=read_market(path)
            for market in self.snapshot['markets']:self.market.addItem(market['label'],market['key'])
            self.status.setText('Offline development sample · Not captured game listings. Live Auction House capture remains pending.')
            self.details.setText(self.snapshot.get('source',str(path))+'\n'+'\n'.join(self.snapshot.get('notes',[])))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self.status.setText('Could not read this listing file. No listings have been replaced or written.');self.details.setText(str(exc))
        index=self.market.findData(old)
        if index>=0:self.market.setCurrentIndex(index)
        self.market.blockSignals(False);self.filter_rows()

    def filter_rows(self):
        market=next((m for m in (self.snapshot or {}).get('markets',[]) if m['key']==self.market.currentData()),None)
        rows=[];query=self.search.text().strip().casefold()
        for record in market['rows'] if market else []:
            name=record.get('name') or 'Item #'+str(record.get('item_id') or 'Unknown')
            if query and query not in name.casefold() and query not in str(record.get('item_id','')):continue
            rows.append((record['id'],(name,record['quantity'],money(record['bid']),'No buyout' if record['buyout']==0 else money(record['buyout']),money(record['unit_price']),record['item_id'])))
        self.items.rows(rows)
        stamp=market.get('observed_at') if market else None
        try:time=datetime.fromtimestamp(stamp).strftime('%d %b %Y, %H:%M') if stamp else 'Unknown'
        except (ValueError,OSError,OverflowError):time='Unknown'
        self.saved.setText(f"Saved {time} · Coverage: {market['coverage']}" if market else '')
        self.summary.setText(f"{len(rows)} of {len(market['rows'])} saved listings" if market else 'No saved listings to show.')
