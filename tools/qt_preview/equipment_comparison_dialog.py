"""View the current character/playstyle goals without changing editors or records."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QSizePolicy,QScrollArea,QWidget,QCheckBox
from presentation import easy_mode
from app import label
from widgets import Table
from equipment_review import SLOTS
from equipment_comparison import load_equipped,compare
from gear import GearWishlist


class EquipmentComparisonDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host
        self.setWindowTitle('Equipped gear and wishlist');self.resize(1100,780)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();box=QVBoxLayout(content);scroll.setWidget(content);outer.addWidget(scroll)
        self.show_details=QCheckBox('Show details');box.addWidget(self.show_details)
        self.identity=label('');self.identity.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.identity)
        box.addWidget(label('Historical equipped gear is shared across playstyles. Goals below belong to the selected playstyle. Bags, bank, ownership and Wanted/Obtained are unchanged. This compares item identities, not stats, suitability or upgrades.'))
        self.goals=Table(['Wishlist goal','Goal slot','Goal ID','Recorded equipped item','Equipped ID','Comparison','Captured (client local)'],height=260)
        box.addWidget(self.goals)
        self.detail=label('Select a comparison row for full details.');self.detail.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.detail)
        box.addWidget(label('Recorded equipped slots · missing slots are unknown, not confirmed empty'))
        self.equipment=Table(['Slot','Recorded item','Item ID','Quantity','Captured (client local)'],height=260)
        box.addWidget(self.equipment)
        box.addWidget(host.button('Create wishlist goal from equipped item',self.create_goal))
        self.notice=label('');self.notice.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.notice)
        for widget in (self.identity,self.detail,self.notice):
            widget.setMinimumWidth(0);widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.goals.itemSelectionChanged.connect(self.show_detail)
        self.show_details.toggled.connect(self.apply_presentation)
        outer.addWidget(host.button('Refresh comparison',self.refresh))
        outer.addWidget(host.button('Close comparison',self.accept))
        host.style_table(self.goals);host.style_table(self.equipment);host.wire_nested_scrolling(self)
        self.refresh()

    def refresh(self):
        data=self.host.data;style=data.playstyles.active(data.active)
        self.identity.setText(f'{data.profile.name} · {data.profile.character_class} · {style}')
        self.rows=[];self.goals.rows([]);self.equipment.rows([])
        self.detail.setText('Select a comparison row for full details.')
        try:
            slots,identity=load_equipped(data)
            # Read existing books only; no setdefault/create-on-read side effects.
            book=data.gear.get(data.active) if style=='General' else data.playstyles.books.get((data.active,style))
            if book is None and style!='General':book=GearWishlist.from_dict(data.playstyles.saved_preset(data.active,style)['gear'])
            goals=book.entries if book else []
            self.rows=compare(goals,slots);self.goals.rows(self.rows)
            self.equipment.rows((str(i),(name,slots[str(i)]['name'] if str(i) in slots else 'Unknown',
                                slots[str(i)]['item_id'] if str(i) in slots else '',
                                slots[str(i)]['quantity'] if str(i) in slots else '',
                                slots[str(i)].get('captured_at','Unknown') if str(i) in slots else ''))
                               for i,name in enumerate(SLOTS))
            self.notice.setText(identity+('\nNo wishlist goals in this playstyle yet. Recorded equipment is shown below the goal table.' if not goals else '\nAll applied goals are shown, regardless of wishlist filters. Unfinished editor fields are not compared or applied.'))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self.notice.setText(f'Equipment comparison unavailable: {exc}')
        self.full_notice=self.notice.text()
        self.apply_presentation()

    def apply_presentation(self):
        simple=easy_mode(self.host) and not self.show_details.isChecked()
        for col in (2,4,6):self.goals.setColumnHidden(col,simple)
        for col in (2,4):self.equipment.setColumnHidden(col,simple)
        # Presentation only: keep the original comparison evidence for details.
        for index,(_,values) in enumerate(self.rows):
            self.goals.item(index,5).setText(simple_comparison(values[5]) if simple else values[5])
        notice=getattr(self,'full_notice','')
        if simple and notice.startswith('Equipment GUID:'):
            notice='Saved equipment for this character.'+('\n'+notice.split('\n',1)[1] if '\n' in notice else '')
        self.notice.setText(notice)
        self.show_detail()

    def show_detail(self):
        i=self.goals.currentRow()
        if 0<=i<len(self.rows):
            values=self.rows[i][1]
            self.detail.setText(f'Wishlist: {values[0]}\nSlot: {values[1]}\nRecorded equipment: {values[3]}\n{simple_comparison(values[5])}' if easy_mode(self.host) and not self.show_details.isChecked() else '\n'.join(map(str,values)))
        else:self.detail.setText('Select a comparison row to see its result.')

    def create_goal(self):
        from equipment_goal_dialog import EquipmentGoalDialog
        try:
            dialog=EquipmentGoalDialog(self.host,self.equipment.key(),self)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self.notice.setText(str(exc));return
        try:
            if dialog.exec():
                self.refresh();self.notice.setText('Wishlist goal saved. Other unfinished edits are unchanged.')
        finally:dialog.deleteLater()


def simple_comparison(status):
    """Plain labels retain identity uncertainty and never imply an upgrade."""
    main,separator,other=status.partition('; same base ID recorded in ')
    labels={
        'Choose a specific slot':'Choose an equipment slot',
        'Unknown · no recorded item in this slot':'Not checked yet',
        'Unlinked goal · item identity unverified':'Link this goal to check the match',
        'Unsupported item identity':'Cannot check this item version',
        'Same base item ID · variant unverified':'Same item type · exact version not checked',
        'Different item · no upgrade rating':'Different item · not an upgrade rating',
    }
    result=labels.get(main,main)
    return result+(f'; same item type recorded in {other}' if separator else '')
