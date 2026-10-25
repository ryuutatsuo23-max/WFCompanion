"""Selected-character Forever Professions observations and read-only stock lookup."""
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QComboBox,QLineEdit,QDialog
from controls import ComboBox as QComboBox
from app import row,label
from widgets import Table
from character_links import LinkStore
from saved_inventory_view import linked_snapshots
from addon_art import saved_heading


def saved_counts(directory,profile,item):
    """Unknown is distinct from zero; complete snapshots alone establish absence."""
    try:records=linked_snapshots(directory,profile)
    except (OSError,ValueError):records=None
    return snapshot_counts(records,item)


def snapshot_counts(records,item):
    result=[]
    for location in ('bags','bank'):
        record=(records or {}).get(location)
        if record is None:result.append(None);continue
        count=sum(qty for key,qty in record['rows'] if key==item)
        complete=record.get('coverage')=='complete' and not record.get('interrupted') and not record.get('unknown')
        result.append(count if complete else None)
    return tuple(result)


class SavedProfessionsPage(QWidget):
    def __init__(self,host,kind):
        super().__init__();self.host=host;self.kind=kind;self.records={};self._signature=None;self._pending=None
        box=QVBoxLayout(self)
        self.heading=saved_heading('WFProfessions','Saved '+kind+' · Read-only · Updates when the game saves.')
        box.addWidget(self.heading)
        self.status=label('');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.status)
        self.profession=QComboBox();self.profession.addItem('All professions',None)
        self.knowledge=QComboBox();self.knowledge.addItems(['All recorded','Learned','Unlearned','Unknown'])
        self.search=QLineEdit();self.search.setPlaceholderText('Search recipe name or ID…');self.search.setClearButtonEnabled(True)
        box.addWidget(row(self.profession,self.knowledge));box.addWidget(self.search)
        self.recipes=Table(['Recipe','Profession','Knowledge','Recipe ID'],self.select_recipe,height=260)
        self.recipes.setToolTip('Select a recipe to compare materials. Double-click for recipe details.')
        self.recipes.itemDoubleClicked.connect(lambda _:self.open_recipe_details())
        box.addWidget(self.recipes)
        self.empty=label('');self.empty.setWordWrap(True);box.addWidget(self.empty)
        self.material_notice=label('Select a saved recipe to compare its materials with Storage.');self.material_notice.setWordWrap(True);box.addWidget(self.material_notice)
        self.material_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.materials=Table(['Material','Required','Saved bags','Saved bank','Other characters','Comparison'],height=170)
        self.storage_button=host.button('Find material in Storage',self.open_material_storage)
        self.storage_button.setEnabled(False)
        self.materials.itemSelectionChanged.connect(self.sync_material_action)
        box.addWidget(self.storage_button)
        box.addWidget(self.materials)
        box.addWidget(label('Saved quantities may be old. Other characters’ items may not be transferable. Manual counts stay separate.'))
        self.details=label('');self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText);self.details.hide()
        box.addWidget(row(host.button('Refresh saved professions',self.refresh),host.button('Connections',self.open_connections),host.button('Details',lambda:self.details.setVisible(not self.details.isVisible()))))
        box.addWidget(self.details)
        self.profession.currentIndexChanged.connect(self.filter_recipes);self.knowledge.currentIndexChanged.connect(self.filter_recipes);self.search.textChanged.connect(self.filter_recipes)
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.poll)
        host.style_table(self.recipes);host.style_table(self.materials)

    def open_connections(self):
        self.host.show_page('Settings');self.host.select_settings_category('Connections')

    def sync_material_action(self):
        key=self.materials.key()
        self.storage_button.setEnabled(key is not None and key[1] is not None)
        if key is not None and key[1] is not None:
            name=self.materials.item(self.materials.currentRow(),0).text()
            self.storage_button.setToolTip('Find '+name+' across saved characters. Select another material below to change the lookup.')
        else:self.storage_button.setToolTip('No recorded item ID is available for the selected material.')

    def open_recipe_details(self):
        key=self.recipes.key()
        if key not in self.records:return
        self.select_recipe(key)
        self.recipe_dialog=RecipeDetailsDialog(self,key)
        self.recipe_dialog.open()

    def open_material_storage(self):
        key=self.materials.key()
        if key is None or key[1] is None:return
        name=self.materials.item(self.materials.currentRow(),0).text()
        self.host.saved_inventory.find_material(name,key[1])
        self.host.show_page('Storage')

    def signature(self):
        links=LinkStore(self.host.data.directory).records['links']
        paths={self.host.data.directory/'character_links.json'}
        for entry in links:
            core=Path(entry['identity']['source']);paths.update((core,core.with_name('WFProfessions.lua')))
        values=[]
        for path in sorted(paths):
            try:s=path.stat();values.append((str(path),s.st_size,s.st_mtime_ns))
            except OSError:values.append((str(path),None,None))
        return self.host.data.active,tuple(values)

    def showEvent(self,event):
        super().showEvent(event);self.refresh();self.timer.start()

    def hideEvent(self,event):self.timer.stop();super().hideEvent(event)

    def poll(self):
        try:signature=self.signature()
        except (ValueError,OSError):self.refresh();return
        if signature==self._signature:self._pending=None;return
        if signature!=self._pending:self._pending=signature;return
        self.refresh()

    def refresh(self):
        active=self.host.data.active
        same_character=getattr(self,'_record_character',None)==active
        if not same_character:
            self.recipes.rows([])
        self._record_character=active
        material_key=self.materials.key() if same_character else None
        self.records={};self.materials.rows([]);self.material_notice.setText('Select a saved recipe to compare its materials with Storage.')
        old=self.profession.currentData();self.profession.blockSignals(True);self.profession.clear();self.profession.addItem('All professions',None)
        self.status.setText('No Forever Professions observations connected for this character. Connect saved game data in Settings; the companion reads WFProfessions.lua beside WFCore.lua.')
        self.details.clear()
        try:
            from wfprofessions_reader import read_character
            links=[e for e in LinkStore(self.host.data.directory).records['links'] if e['profile']==self.host.data.active]
            if len(links)>1:raise ValueError('Multiple character links require review.')
            if links:
                snapshot=read_character(links[0]['identity']);summaries=[]
                for profession in snapshot['professions']:
                    if profession['kind']!=self.kind:continue
                    self.profession.addItem(profession['name'],profession['id'])
                    skill=profession.get('skill');maximum=profession.get('max_skill');stamp=profession.get('observed_at')
                    saved=datetime.fromtimestamp(stamp).strftime('%d %b %Y, %H:%M') if stamp else 'time unknown'
                    summaries.append(f"{profession['name']} · Skill {skill if skill is not None else 'Unknown'}/{maximum if maximum is not None else 'Unknown'} · Saved {saved}")
                    for recipe in profession['recipes']:self.records[(profession['id'],recipe['id'])]=(profession,recipe)
                self.status.setText('\n'.join(summaries) or 'No '+self.kind+' profession observations recorded for this character yet.')
                self.details.setText(snapshot.get('source','')+'\n'+'\n'.join(snapshot.get('notes',[])))
            self._signature=self.signature();self._pending=None
        except (ValueError,OSError,KeyError,TypeError,OverflowError) as exc:
            self.status.setText('Saved professions are unavailable. Check the connection in Settings; existing plans are unchanged.')
            self.details.setText(str(exc))
        if self.profession.findData(old)>=0:self.profession.setCurrentIndex(self.profession.findData(old))
        self.profession.blockSignals(False);self.filter_recipes()
        if material_key in self.materials.keys:self.materials.selectRow(self.materials.keys.index(material_key))
        self.sync_material_action()

    def filter_recipes(self):
        rows=[];query=self.search.text().strip().casefold();state=self.knowledge.currentText()
        for key,(profession,recipe) in self.records.items():
            knowledge='Learned' if recipe['learned'] is True else 'Unlearned' if recipe['learned'] is False else 'Unknown'
            if self.profession.currentData() not in (None,profession['id']):continue
            if state!='All recorded' and state!=knowledge:continue
            if query and query not in recipe['name'].casefold() and query not in str(recipe['id']):continue
            rows.append((key,(recipe['name'],profession['name'],knowledge,recipe['id'])))
        rows.sort(key=lambda value:(value[1][0].casefold(),value[0]));self.recipes.rows(rows)
        self.empty.setText(f'{len(rows)} of {len(self.records)} recorded recipes. Missing recipes are unknown, not unlearned.' if rows else
            'No matching recorded recipes. Unlearned lists and gathering recipes may not have been captured; missing records do not mean the character knows none.')
        key=self.recipes.key()
        if key in self.records:self.select_recipe(key)
        else:
            self.materials.rows([]);self.material_notice.setText('Select a saved recipe to compare its materials with Storage.')
        self.sync_material_action()

    def select_recipe(self,key):
        if key not in self.records:return
        recipe=self.records[key][1];slots=recipe['slots'];rows=[]
        if recipe['reagents_status']!='known':
            self.materials.rows([]);self.sync_material_action();self.material_notice.setText('Reagent requirements were not fully recorded for '+recipe['name']+'.');return
        requirements=recipe.get('requirements',[])
        extra=' · '.join((r.get('name') or 'Unknown requirement')+(': met in save' if r.get('met') is True else ': not met in save' if r.get('met') is False else ': unknown') for r in requirements)
        self.material_notice.setText(recipe['name']+' · Requirements for one craft. Alternatives share a slot; quantities are not a guarantee that the recipe can be crafted.'+('\n'+extra if extra else ''))
        # Read each character once, so a multi-reagent comparison uses the same
        # observations throughout and does not repeatedly parse saved files.
        snapshots={}
        for profile in self.host.data.saved_profiles:
            try:snapshots[profile.id]=linked_snapshots(self.host.data.directory,profile.id)
            except (OSError,ValueError):snapshots[profile.id]=None
        # Repeated fixed requirements share stock; compare their total demand.
        demands={}
        for slot in slots:
            if slot['required'] is True and slot['quantity'] is not None and len(slot['alternatives'])==1:
                item=slot['alternatives'][0]['id'];demands[item]=demands.get(item,0)+slot['quantity']
        for number,slot in enumerate(slots,1):
            choices=slot['alternatives'];quantity=slot['quantity']
            if not choices:rows.append(((number,None),(f'Slot {number} · item unknown',quantity,None,None,None,'Unknown')))
            for choice in choices:
                item=choice['id'];bags,bank=snapshot_counts(snapshots.get(self.host.data.active),item)
                other=0;uncertain=False
                for profile in self.host.data.saved_profiles:
                    if profile.id==self.host.data.active:continue
                    counts=snapshot_counts(snapshots.get(profile.id),item)
                    other+=sum(value for value in counts if value is not None);uncertain|=None in counts
                total=None if bags is None or bank is None else bags+bank
                needed=demands.get(item,quantity)
                comparison=('Optional' if slot['required'] is False else 'Alternative choice' if len(choices)>1 else
                    'Unknown' if slot['required'] is None or needed is None or total is None else
                    'Enough saved' if total>=needed else f'Short by {needed-total}')
                name=choice.get('name')
                if not name:
                    name=next((record.get('names',{}).get(item) for snapshot in snapshots.values()
                        for record in (snapshot or {}).values() if record.get('names',{}).get(item)),None)
                rows.append(((number,item),(name or f'Item #{item}',quantity,bags,bank,str(other)+(' + unknown' if uncertain else ''),comparison)))
        self.materials.rows(rows)
        if self.materials.key() is None:
            first=next((i for i,key in enumerate(self.materials.keys) if key[1] is not None),None)
            if first is not None:self.materials.selectRow(first)
        self.sync_material_action()


class RecipeDetailsDialog(QDialog):
    """Read-only recipe comparison captured when opened; no planning mutations."""
    def __init__(self,page,key):
        super().__init__(page.host)
        self.page=page;self.owner=page.host.data.active
        profession,recipe=page.records[key]
        self.setWindowTitle(recipe['name']+' — saved recipe');self.setModal(True);self.resize(1000,570)
        box=QVBoxLayout(self)
        def text(value):
            widget=label(value);widget.setWordWrap(True);widget.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(widget)
        text(recipe['name'])
        knowledge='Learned' if recipe['learned'] is True else 'Unlearned' if recipe['learned'] is False else 'Knowledge unknown'
        stamp=profession.get('observed_at')
        saved=datetime.fromtimestamp(stamp).strftime('%d %b %Y, %H:%M') if stamp else 'time unknown'
        text(f'{page.host.data.profile.name} · {profession["name"]} · {knowledge} · Recipe ID {recipe["id"]}\nSaved {saved}')
        text(page.material_notice.text())
        self.materials=Table(['Material','Required','Saved bags','Saved bank','Other characters','Comparison'],height=200)
        self.materials.rows([(key,[page.materials.item(i,c).text() for c in range(page.materials.columnCount())]) for i,key in enumerate(page.materials.keys)])
        box.addWidget(self.materials)
        text('Saved observations, not live stock. Unknown banks stay unknown. Other characters’ items may not be transferable; manual plans stay unchanged.')
        self.find_button=page.host.button('Find material in Storage',self.open_storage)
        self.find_button.setEnabled(False)
        self.materials.itemSelectionChanged.connect(self.sync_action)
        box.addWidget(row(self.find_button,page.host.button('Close',self.reject)))
        selected=page.materials.key()
        if selected in self.materials.keys:self.materials.selectRow(self.materials.keys.index(selected))
        self.sync_action();page.host.style_table(self.materials)

    def sync_action(self):
        key=self.materials.key()
        self.find_button.setEnabled(key is not None and key[1] is not None and self.owner==self.page.host.data.active)

    def open_storage(self):
        self.sync_action()
        if not self.find_button.isEnabled():return
        key=self.materials.key();name=self.materials.item(self.materials.currentRow(),0).text()
        # Keep the chosen ingredient selected when Back returns to this recipe.
        if key in self.page.materials.keys:self.page.materials.selectRow(self.page.materials.keys.index(key))
        self.page.host.saved_inventory.find_material(name,key[1])
        self.accept();self.page.host.show_page('Storage')
