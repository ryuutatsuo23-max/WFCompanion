"""Historical record summaries, independent of the future addon schema."""
from datetime import datetime, timezone, timedelta
import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy,QCheckBox
from presentation import easy_mode,simple_observation
from app import Panel, label, row
from widgets import Table
from equipment_review import EquipmentStore


def observation_status(values, now):
    if not values:return 'Not captured'
    dates=[]
    for value in values:
        try:
            stamp=datetime.fromisoformat(value)
            if stamp.tzinfo is None:stamp=stamp.astimezone()
            dates.append(stamp.astimezone(timezone.utc))
        except (ValueError,TypeError):return 'Recorded · date unknown'
    if any(d>now+timedelta(minutes=5) for d in dates):return 'Recorded · check clock'
    state='Outdated' if min(dates)<now-timedelta(hours=24) else 'Recorded'
    return f'{state} · {max(dates).astimezone():%Y-%m-%d %H:%M}'+(' · mixed dates' if min(dates)!=max(dates) else '')


def inventory_status(book, location, now):
    entries=[e for e in book.entries if e.location==location] if book else []
    observations=[]
    for e in entries:
        if e.source!='Reviewed probe':continue
        # Count updates retain historical timestamps: never label them fresh scans.
        match=re.search(r'Historical capture (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)',e.note)
        observations.append(match[1] if match else e.updated_at)
    result=observation_status(observations,now)
    if entries and not observations:result+=' · manual records only'
    return result


def summaries(data,now=None):
    now=now or datetime.now(timezone.utc)
    try:equipment,_=EquipmentStore(data.directory).load();error=False
    except (ValueError,OSError,KeyError,TypeError):equipment={'characters':{}};error=True
    result=[]
    for p in data.profiles:
        book=data.inventories.get(p.id)
        inv=['Unavailable · saved-file error']*2 if data.inventory_store.error else [inventory_status(book,n,now) for n in ('Bags','Bank')]
        record=equipment['characters'].get(p.id)
        mismatch=record and p.id.startswith('capture-') and p.id!='capture-'+record['guid']
        equipped='Unavailable · saved-file error' if error else 'Unavailable · GUID mismatch' if mismatch else observation_status(
            [r.get('captured_at') for r in record['slots'].values()] if record else [],now)
        result.append((p.id,(p.name,p.character_class,data.playstyles.active(p.id),*inv,equipped)))
    return result


class CharacterOverview(Panel):
    def __init__(self,host):
        super().__init__(host,'Your characters');self.host=host
        self.explanation=label('');self.box.addWidget(self.explanation)
        self.show_details=QCheckBox('Show details');self.box.addWidget(self.show_details)
        self.show_details.toggled.connect(self.refresh)
        self.table=Table(['Character','Class','Playstyle','Bags · observation','Bank · observation','Equipment · observation'],height=230)
        self.box.addWidget(self.table)
        self.detail=label('Select a character for details and quick links.')
        self.detail.setTextFormat(Qt.TextFormat.PlainText);self.detail.setMinimumWidth(0)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.box.addWidget(self.detail)
        from game_data_monitor import GameDataMonitor
        self.game_data_status=label('Checking for saved addon data…');self.box.addWidget(self.game_data_status)
        self.automatic_checks=QCheckBox('Check saved game data automatically');self.automatic_checks.setChecked(True)
        self.box.addWidget(self.automatic_checks)
        self.game_data_monitor=GameDataMonitor(host)
        self.game_data_monitor.status.connect(self.game_data_status.setText)
        self.automatic_checks.toggled.connect(self.game_data_monitor.set_enabled)
        self.box.addWidget(host.button('Check for new game data',self.check_game_data))
        self.records=[];self.table.itemSelectionChanged.connect(self.describe)
        self.box.addWidget(row(host.button('Open inventory & bank',lambda:self.open_page('Inventory & Bank')),
                               host.button('Open equipment',self.open_equipment),
                               host.button('Open wishlist',lambda:self.open_page('Gear wishlist')),
                               host.button('Refresh overview',self.refresh)))
        host.style_table(self.table);self.refresh()

    def refresh(self):
        selected=self.table.key();self.records=summaries(self.host.data)
        simple=easy_mode(self.host) and not self.show_details.isChecked()
        self.explanation.setText('A quick look at your saved characters. These are saved records, not live readings.' if simple else 'Saved observations, not live data. Outdated means at least one record is over 24 hours old. Dates are computer local; mixed dates show the latest. Partial imports do not prove complete coverage or an empty bank.')
        self.table.setHorizontalHeaderLabels(['Character','Class','Playstyle','Bags','Bank','Equipment'] if simple else ['Character','Class','Playstyle','Bags · observation','Bank · observation','Equipment · observation'])
        self.table.rows([(key,(*values[:3],*(simple_observation(v) for v in values[3:]))) for key,values in self.records] if simple else self.records)
        if selected in self.table.keys:self.table.selectRow(self.table.keys.index(selected))
        self.describe()

    def describe(self):
        record=next((values for key,values in self.records if key==self.table.key()),None)
        if record and easy_mode(self.host) and not self.show_details.isChecked():record=(*record[:3],*(simple_observation(v) for v in record[3:]))
        self.detail.setText('\n'.join(f'{title}: {value}' for title,value in zip(
            ('Character','Class','Selected playstyle','Bags','Bank','Equipment'),record)) if record else 'Select a character for details and quick links.')

    def select_character(self):
        key=self.table.key()
        if key not in {p.id for p in self.host.data.profiles}:
            self.detail.setText('Select a character first.');return False
        self.host.switch_character(key)
        return True

    def open_page(self,name):
        if not self.select_character():return
        if name=='Inventory & Bank':self.host.show_inventory_section(False)
        else:self.host.show_gear_section(False)
        self.host.show_page(name)

    def open_equipment(self):
        if self.select_character():self.host.gear_page.show_equipment_comparison()

    def check_game_data(self):
        from game_data_dialog import GameDataDialog
        dialog=GameDataDialog(self.host)
        try:dialog.exec()
        finally:dialog.deleteLater()
