"""Historical record summaries, independent of the future addon schema."""
from datetime import datetime, timezone, timedelta
import re
import json
from PySide6.QtCore import Qt,QMimeData,QPoint
from PySide6.QtGui import QDrag,QPainter,QPen
from PySide6.QtWidgets import QSizePolicy,QCheckBox,QWidget,QVBoxLayout,QGroupBox,QGridLayout,QLabel,QApplication,QHBoxLayout,QGraphicsOpacityEffect
from pathlib import Path
import os
from presentation import easy_mode,simple_observation
from app import Panel, label, row
from widgets import Table
from equipment_review import EquipmentStore
from local_journal import LocalStore
from saved_inventory_view import linked_snapshots


def validate_card_preferences(value):
    if (not isinstance(value,dict) or value.get('version')!=1 or type(value.get('collapsed')) is not bool
        or not isinstance(value.get('order'),list) or len(value['order'])>1000
        or any(not isinstance(key,str) or len(key)>8192 for key in value['order'])
        or len(set(value['order']))!=len(value['order'])):
        raise ValueError('Invalid character-card preferences; original file preserved.')


class CardHandle(QLabel):
    def __init__(self,text,page,key):
        super().__init__(text);self.page=page;self.key=key;self.start=None
        self.setWordWrap(True)
        self.setContentsMargins(24,4,4,4)
        self.setTextFormat(Qt.TextFormat.PlainText);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('Drag onto another character to reorder. Keyboard: Ctrl+Left or Ctrl+Right.')
        self.setAccessibleName('Move '+text)

    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(self.palette().windowText())
        for x in (7,14):
            for y in (-6,0,6):painter.drawEllipse(QPoint(x,self.height()//2+y),2,2)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.start=event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if (self.start is not None and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint()-self.start).manhattanLength()>=QApplication.startDragDistance()):
            self.start=None;drag=QDrag(self);mime=QMimeData();mime.setData('application/x-wf-character-card',self.key.encode())
            drag.setMimeData(mime);drag.setPixmap(self.grab());drag.setHotSpot(QPoint(12,self.height()//2))
            self.page.dragging_card=True;self.setCursor(Qt.CursorShape.ClosedHandCursor)
            effect=QGraphicsOpacityEffect(self.parentWidget());effect.setOpacity(0.4)
            self.parentWidget().setGraphicsEffect(effect)
            try:drag.exec(Qt.DropAction.MoveAction)
            finally:
                self.page.dragging_card=False;self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.parentWidget().setGraphicsEffect(None)
                for i in range(self.page.cards_box.count()):
                    card=self.page.cards_box.itemAt(i).widget();card.drop_target=False;card.update()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self.start=None;super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right):
            order=self.page.card_order();i=order.index(self.key)
            target=i+(-1 if event.key()==Qt.Key.Key_Left else 1)
            if 0<=target<len(order):self.page.move_card(self.key,order[target])
            event.accept()
        else:super().keyPressEvent(event)


class CharacterCard(QGroupBox):
    def __init__(self,page,key):
        super().__init__();self.page=page;self.card_key=key;self.setAcceptDrops(True);self.drop_target=False

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.drop_target:
            painter=QPainter(self);color=self.palette().highlight().color()
            painter.setPen(QPen(color,3));painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(2,2,-3,-3),4,4)

    def valid_drag(self,event):
        source=event.source()
        return isinstance(source,CardHandle) and source.page is self.page and source.key!=self.card_key and source.key in self.page.card_order()

    def dragEnterEvent(self,event):
        if self.valid_drag(event):
            self.drop_target=True;self.update();event.acceptProposedAction()
        else:event.ignore()

    def dragMoveEvent(self,event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self,event):
        self.drop_target=False;self.update();event.accept()

    def dropEvent(self,event):
        self.drop_target=False;self.update()
        if self.valid_drag(event) and self.page.move_card(event.source().key,self.card_key):event.acceptProposedAction()
        else:event.ignore()


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
        # Direct game snapshots are independent of the manual planning ledger.
        try:direct=linked_snapshots(data.directory,p.id)
        except (ValueError,OSError,KeyError,TypeError):
            inv=['Unavailable · addon saved-file error']*2
        else:
            if direct is not None:
                for index,scope in enumerate(('bags','bank')):
                    saved=direct.get(scope)
                    if saved is None:
                        inv[index]='Not captured';continue
                    try:stamp=datetime.fromtimestamp(saved['finished'],timezone.utc).isoformat()
                    except (ValueError,TypeError,OSError,OverflowError):stamp=None
                    partial=saved['coverage']!='complete' or saved['unknown']>0 or saved['interrupted']
                    suffix=' · incomplete saved scan' if partial else ' · saved empty' if not saved['rows'] else ' · addon snapshot'
                    inv[index]=observation_status([stamp],now)+suffix
        record=equipment['characters'].get(p.id)
        mismatch=record and p.id.startswith('capture-') and p.id!='capture-'+record['guid']
        equipped='Unavailable · saved-file error' if error else 'Unavailable · GUID mismatch' if mismatch else observation_status(
            [r.get('captured_at') for r in record['slots'].values()] if record else [],now)
        result.append((p.id,(p.name,p.character_class,data.playstyles.active(p.id),*inv,equipped)))
    return result


class CharacterCards(QWidget):
    """Reflow existing cards without rebuilding buttons or disturbing focus."""
    def __init__(self):
        super().__init__()
        self.grid=QGridLayout(self);self.grid.setContentsMargins(0,0,0,0)
        self.columns=1

    def reflow(self):
        cards=[self.grid.itemAt(i).widget() for i in range(self.grid.count())]
        minimum=max(330,self.fontMetrics().horizontalAdvance('M')*34,
                    max((w.minimumSizeHint().width() for w in cards),default=0))
        columns=max(1,min(3,(self.width()+self.grid.spacing())//(minimum+self.grid.spacing())))
        while self.grid.count():self.grid.takeAt(0)
        for i,card in enumerate(cards):self.grid.addWidget(card,i//columns,i%columns)
        for column in range(3):self.grid.setColumnStretch(column,1 if column<columns else 0)
        self.columns=columns

    def resizeEvent(self,event):
        super().resizeEvent(event);self.reflow()


class CharacterOverview(Panel):
    def __init__(self,host):
        super().__init__(host,'Your characters');self.host=host
        self.dragging_card=False
        self.card_preferences=LocalStore(host.data.directory,'character_cards.json',{'version':1,'order':[],'collapsed':False},validate_card_preferences)
        title=self.box.itemAt(0).widget();header=QHBoxLayout(title);header.setContentsMargins(8,8,8,8);header.addStretch()
        self.collapse_button=host.button('Hide',self.toggle_collapsed);header.addWidget(self.collapse_button)
        self.explanation=label('');self.box.addWidget(self.explanation)
        self.cards=CharacterCards();self.cards_box=self.cards.grid
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
        if self.dragging_card:return
        selected=self.table.key();self.records=summaries(self.host.data)
        simple=not self.show_details.isChecked()
        self.explanation.setText('Saved characters · Drag a character name to reorder the cards.' if simple else 'Saved observations, not live data. Outdated means at least one record is over 24 hours old. Dates are computer local; mixed dates show the latest. Partial imports do not prove complete coverage or an empty bank.')
        self.table.setHorizontalHeaderLabels(['Character','Class','Playstyle','Bags','Bank','Equipment'] if simple else ['Character','Class','Playstyle','Bags · observation','Bank · observation','Equipment · observation'])
        self.table.rows([(key,(*values[:3],*(simple_observation(v) for v in values[3:]))) for key,values in self.records] if simple else self.records)
        if selected in self.table.keys:self.table.selectRow(self.table.keys.index(selected))
        self.describe()
        for widget in (self.table,self.detail,self.game_data_status,self.automatic_checks,self.check_button,self.detail_actions):
            widget.setVisible(self.show_details.isChecked())
        self.build_cards()
        self.apply_collapsed()

    def apply_collapsed(self):
        collapsed=self.card_preferences.data['collapsed']
        self.collapse_button.setText('Show' if collapsed else 'Hide')
        self.collapse_button.setAccessibleName('Show characters' if collapsed else 'Hide characters')
        for i in range(1,self.box.count()):
            widget=self.box.itemAt(i).widget()
            if widget:
                detail=widget in (self.table,self.detail,self.game_data_status,self.automatic_checks,self.check_button,self.detail_actions)
                widget.setVisible(not collapsed and (not detail or self.show_details.isChecked()))
        margins=self.box.contentsMargins()
        self.setMaximumHeight(self.box.itemAt(0).widget().sizeHint().height()+margins.top()+margins.bottom() if collapsed else 16777215)
        self.updateGeometry()

    def toggle_collapsed(self):
        try:self.card_preferences.save({**self.card_preferences.data,'collapsed':not self.card_preferences.data['collapsed']})
        except (ValueError,OSError) as exc:
            self.host.banner.setText(str(exc));self.host.banner.show();return
        self.apply_collapsed()

    def card_order(self):
        return [self.cards_box.itemAt(i).widget().card_key for i in range(self.cards_box.count())]

    def move_card(self,source,target):
        order=self.card_order()
        if source not in order or target not in order or source==target:return False
        index=order.index(target);order.remove(source);order.insert(index,source)
        try:self.card_preferences.save({**self.card_preferences.data,'order':order})
        except (ValueError,OSError) as exc:
            self.host.banner.setText(str(exc));self.host.banner.show();return False
        self.sort_cards();return True

    def sort_cards(self):
        widgets=[self.cards_box.itemAt(i).widget() for i in range(self.cards_box.count())]
        order=self.card_preferences.data['order'];rank={key:i for i,key in enumerate(order)}
        widgets.sort(key=lambda widget:rank.get(widget.card_key,len(rank)))
        while self.cards_box.count():self.cards_box.takeAt(0)
        for i,widget in enumerate(widgets):self.cards_box.addWidget(widget,i,0)
        self.cards.reflow()

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
        self.sort_cards()

    def add_card(self,profile,name,values,char,snapshot):
        key=profile if profile else 'saved:'+json.dumps([snapshot['directory'],char['guid'],char['source_id']])
        card=CharacterCard(self,key);card.setPalette(self.host.palette());box=QVBoxLayout(card)
        title=CardHandle(name,self,key);box.addWidget(title)
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
        box.addWidget(row(bags,professions));self.cards_box.addWidget(card,self.cards_box.count(),0)
        self.card_buttons[profile if profile else ('saved',char['source_id'])]=(bags,professions)

    def open_card_inventory(self,profile):
        if profile not in {p.id for p in self.host.data.profiles}:return
        self.table.selectRow(self.table.keys.index(profile))
        self.host.switch_character(profile)
        self.host.saved_inventory.character_scope.setCurrentIndex(0)
        self.host.show_observed_inventory()

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
