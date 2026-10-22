"""Historical record summaries, independent of the future addon schema."""
from datetime import datetime, timezone, timedelta
import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy,QCheckBox,QWidget,QVBoxLayout,QGroupBox
from pathlib import Path
import os
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
    from observed_inventory import ObservationStore
    try:ledger=ObservationStore(data.directory).ledger;addon_error=False
    except (ValueError,OSError,KeyError,TypeError):ledger={};addon_error=True
    result=[]
    for p in data.profiles:
        book=data.inventories.get(p.id)
        inv=['Unavailable · saved-file error']*2 if data.inventory_store.error else [inventory_status(book,n,now) for n in ('Bags','Bank')]
        for index,scope in enumerate(('bags','bank')):
            saved=ledger.get((p.id,scope))
            if addon_error:inv[index]='Unavailable · addon saved-file error'
            elif saved and not data.inventory_store.error:
                stamp=datetime.fromtimestamp(saved['finished'],timezone.utc).isoformat()
                inv[index]=observation_status([stamp],now)+(' · saved empty' if not saved['rows'] else ' · addon snapshot')
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
        self.cards=QWidget();self.cards_box=QVBoxLayout(self.cards)
        self.cards_box.setContentsMargins(0,0,0,0);self.box.addWidget(self.cards)
        self.box.addWidget(row(host.button('Review saved game data',self.check_game_data),
                               host.button('Read professions save',host.show_profession_observations),
                               host.button('Refresh overview',self.refresh)))
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
        self.check_button=host.button('Check for new game data',self.check_game_data)
        self.box.addWidget(self.check_button)
        self.records=[];self.table.itemSelectionChanged.connect(self.describe)
        self.detail_actions=row(host.button('Open inventory & bank',lambda:self.open_page('Inventory & Bank')),
                               host.button('Open equipment',self.open_equipment),
                               host.button('Open wishlist',lambda:self.open_page('Gear wishlist')),
                               host.button('Refresh overview',self.refresh))
        self.box.addWidget(self.detail_actions)
        host.style_table(self.table);self.refresh()

    def refresh(self):
        selected=self.table.key();self.records=summaries(self.host.data)
        simple=not self.show_details.isChecked()
        self.explanation.setText('A quick look at your saved characters. These are saved records, not live readings.' if simple else 'Saved observations, not live data. Outdated means at least one record is over 24 hours old. Dates are computer local; mixed dates show the latest. Partial imports do not prove complete coverage or an empty bank.')
        self.table.setHorizontalHeaderLabels(['Character','Class','Playstyle','Bags','Bank','Equipment'] if simple else ['Character','Class','Playstyle','Bags · observation','Bank · observation','Equipment · observation'])
        self.table.rows([(key,(*values[:3],*(simple_observation(v) for v in values[3:]))) for key,values in self.records] if simple else self.records)
        if selected in self.table.keys:self.table.selectRow(self.table.keys.index(selected))
        self.describe()
        for widget in (self.table,self.detail,self.game_data_status,self.automatic_checks,self.check_button,self.detail_actions):
            widget.setVisible(self.show_details.isChecked())
        self.build_cards()

    def build_cards(self):
        while self.cards_box.count():
            widget=self.cards_box.takeAt(0).widget()
            if widget:
                widget.hide();widget.setParent(None);widget.deleteLater()
        cache=getattr(self.host,'profession_observations',None)
        snapshot=cache.accepted if cache else None
        characters=snapshot['characters'] if snapshot else []
        from character_links import LinkStore
        try:links=LinkStore(self.host.data.directory).records['links']
        except (ValueError,OSError,KeyError,TypeError):links=[]
        used=set();self.card_buttons={}
        for profile,values in self.records:
            matches=[]
            for char in characters:
                for link in links:
                    ident=link['identity']
                    same_folder=os.path.normcase(str(Path(ident['source']).resolve().parent))==os.path.normcase(str(Path(snapshot['directory']).resolve()))
                    if (link['profile']==profile and same_folder and ident['guid']==char['guid']
                        and ident['environment']=='Test' and ident['version']=='1.60.1'
                        and ident['interface']==16001 and char.get('label')
                        and ident['realm']==char['label']['realm']):matches.append(char)
            char=matches[0] if len(matches)==1 else None
            if char:used.add(char['source_id'])
            name=char['label']['name'] if char else values[0]
            self.add_card(profile,name,values,char,snapshot)
        for char in characters:
            if char['source_id'] in used:continue
            name=char['label']['name'] if char.get('label') else f"Saved character #{char['source_id']}"
            self.add_card(None,name,None,char,snapshot)

    def add_card(self,profile,name,values,char,snapshot):
        card=QGroupBox();card.setPalette(self.host.palette());box=QVBoxLayout(card)
        title=label(name);title.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(title)
        if char and char.get('label'):
            realm=label(char['label']['realm']);realm.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(realm)
        if values:
            for caption,status in zip(('Bags','Bank'),values[3:5]):
                if status=='Not captured':status='No saved observation yet'
                elif status=='Not captured · manual records only':status='Manual records only · no saved observation'
                else:status=status.replace('Recorded ·','Saved ·').replace(' · addon snapshot','').replace(' · saved empty',' · empty')
                box.addWidget(label(f'{caption}: {status}'))
        else:box.addWidget(label('Bags & Bank: link this saved character in Review saved game data.'))
        target=None
        if char:
            target=(snapshot['directory'],char['guid'],char['source_id'])
            from profession_observations import timestamp_label
            status=timestamp_label(char['source_time'],datetime.now(timezone.utc).timestamp())
            if status not in ('Unknown age',) and not status.startswith('Clock mismatch'):
                status=datetime.fromtimestamp(char['source_time'],timezone.utc).astimezone().strftime('%d %b %Y, %H:%M')
            box.addWidget(label(f"Professions: saved {status}" if char['professions'] else 'No profession observations saved yet.'))
            if getattr(getattr(self.host,'profession_observations',None),'error',''):
                box.addWidget(label('Last refresh failed · showing the previous save.'))
        else:box.addWidget(label('No linked profession save loaded.'))
        bags=self.host.button('Bags & Bank',lambda:self.open_card_inventory(profile))
        bags.setEnabled(profile is not None)
        bags.setToolTip('Open this profile’s inventory.' if profile else 'Link this character to a profile in Review saved game data first.')
        professions=self.host.button('Professions',lambda:self.host.show_profession_observations(target))
        professions.setEnabled(target is not None)
        professions.setToolTip('Open this saved character.' if target else 'Read a professions save and link the matching game character first.')
        box.addWidget(row(bags,professions));self.cards_box.addWidget(card)
        self.card_buttons[profile if profile else ('saved',char['source_id'])]=(bags,professions)

    def open_card_inventory(self,profile):
        if profile not in {p.id for p in self.host.data.profiles}:return
        self.table.selectRow(self.table.keys.index(profile))
        from observed_inventory import ObservationStore
        try:has_saved=any(key[0]==profile for key in ObservationStore(self.host.data.directory).ledger)
        except (ValueError,OSError,KeyError,TypeError):has_saved=False
        if has_saved:
            self.host.switch_character(profile)
            self.host.show_observed_inventory()
            return
        self.open_page('Inventory & Bank')

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
