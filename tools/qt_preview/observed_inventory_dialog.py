"""Read-only saved inventory, across characters and locations."""
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QLineEdit
from app import label,row
from widgets import Table
from observed_inventory import ObservationStore
from game_data_review import observed_time
from saved_inventory_view import linked_snapshots
from character_links import LinkStore


class ObservedInventoryDialog(QDialog):
    def __init__(self,host,*,embedded=False):
        super().__init__(host);self.host=host;self.ledger={};self.errors={}
        self.embedded=embedded;self.scope='all'
        if embedded:self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle('Saved inventory');self.resize(1000,650);box=QVBoxLayout(self)
        box.addWidget(label('Saved inventory · Read-only · Updates when the game saves.'))
        self.character=QComboBox()
        for p in host.data.saved_profiles:self.character.addItem(p.name,p.id)
        self.character.setCurrentIndex(self.character.findData(host.data.active))
        self.character.setVisible(not embedded)
        self.character_scope=QComboBox();self.character_scope.addItems(['Selected character','All characters'])
        self.buttons={}
        for scope,title in (('all','All'),('bags','Bags'),('bank','Bank')):
            button=host.button(title,lambda s=scope:self.select(s));button.setCheckable(True)
            self.buttons[scope]=button
        box.addWidget(row(self.character_scope,self.character,*self.buttons.values()))
        self.search=QLineEdit();self.search.setPlaceholderText('Search item name or ID…')
        self.search.setAccessibleName('Search saved items by name or ID');self.search.setClearButtonEnabled(True)
        box.addWidget(self.search)
        self.notice=label('');self.notice.setWordWrap(True);self.notice.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.notice)
        self.sort_column=0;self.sort_descending=False
        self.items=Table(['Item','Character','Location','Quantity','Item ID'],height=300);box.addWidget(self.items,1)
        self.items.setColumnWidth(1,180)
        header=self.items.horizontalHeader();header.setSectionsClickable(True);header.setSortIndicatorShown(True)
        header.setSortIndicator(0,Qt.SortOrder.AscendingOrder);header.sectionClicked.connect(self.sort_items)
        self.search.textChanged.connect(lambda _:self.select(self.scope))
        self.search_notice=label('');box.addWidget(self.search_notice)
        self.details=label('');self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText);self.details.hide()
        box.addWidget(row(host.button('Details',lambda:self.details.setVisible(not self.details.isVisible())),host.button('Refresh saved observations',self.refresh)))
        box.addWidget(self.details)
        if not embedded:box.addWidget(host.button('Close',self.accept))
        self.character.currentIndexChanged.connect(self.refresh);self.character_scope.currentIndexChanged.connect(self.refresh)
        self._loaded_signature=None;self._pending_signature=None
        self.watch_timer=QTimer(self);self.watch_timer.setInterval(2000);self.watch_timer.timeout.connect(self.poll_saved_files)
        host.style_table(self.items);host.wire_nested_scrolling(self);self.refresh()

    def profiles(self):
        profiles=self.host.data.saved_profiles
        if self.character_scope.currentIndex()==1:return profiles
        active=self.host.data.active if self.embedded else self.character.currentData()
        return [p for p in profiles if p.id==active]

    def source_signature(self):
        directory=self.host.data.directory;profiles=tuple(p.id for p in self.profiles())
        paths={directory/'character_links.json',directory/'addon_inventory.json'}
        paths.update(Path(e['identity']['source']) for e in LinkStore(directory).records['links'] if e['profile'] in profiles)
        values=[]
        for path in sorted(paths):
            try:
                stat=path.stat();values.append((str(path),stat.st_size,stat.st_mtime_ns))
            except OSError:values.append((str(path),None,None))
        return profiles,tuple(values)

    def showEvent(self,event):
        super().showEvent(event);self.refresh();self.watch_timer.start()

    def hideEvent(self,event):
        self.watch_timer.stop();super().hideEvent(event)

    def poll_saved_files(self):
        if not self.isVisible():return
        try:signature=self.source_signature()
        except (OSError,ValueError):self.refresh();return
        if signature==self._loaded_signature:self._pending_signature=None;return
        # Two stable observations avoid reading a save while it is being written.
        if signature!=self._pending_signature:self._pending_signature=signature;return
        self.refresh()

    def refresh(self):
        if self.embedded:
            self.character.blockSignals(True);self.character.clear()
            for p in self.host.data.saved_profiles:self.character.addItem(p.name,p.id)
            self.character.setCurrentIndex(self.character.findData(self.host.data.active));self.character.blockSignals(False)
        self.ledger={};self.errors={}
        try:signature=self.source_signature()
        except (OSError,ValueError) as exc:
            self.items.rows([]);self.notice.setText('Could not read addon observations: '+str(exc));self.details.setText('');self.search_notice.setText('');return
        fallback=None
        for profile in self.profiles():
            try:
                snapshots=linked_snapshots(self.host.data.directory,profile.id)
                if snapshots is None:
                    if fallback is None:fallback=ObservationStore(self.host.data.directory).ledger
                    snapshots={scope:r for (pid,scope),r in fallback.items() if pid==profile.id}
                self.ledger.update({(profile.id,scope):record for scope,record in snapshots.items()})
            except (ValueError,OSError) as exc:self.errors[profile.id]=str(exc)
        self.select(self.scope)
        if not self.errors:self._loaded_signature=signature;self._pending_signature=None

    def sort_items(self,column):
        self.sort_descending=not self.sort_descending if column==self.sort_column else False;self.sort_column=column
        self.items.horizontalHeader().setSortIndicator(column,Qt.SortOrder.DescendingOrder if self.sort_descending else Qt.SortOrder.AscendingOrder)
        self.select(self.scope)

    def select(self,scope):
        self.scope=scope
        for name,button in self.buttons.items():button.setChecked(name==scope)
        rows=[];details=[];unknown=0;partial=0;times=[];available=0
        for profile in self.profiles():
            if profile.id in self.errors:
                details.append(profile.name+': Could not read addon observations: '+self.errors[profile.id]);continue
            for location in ('bags','bank') if scope=='all' else (scope,):
                record=self.ledger.get((profile.id,location))
                if record is None:
                    unknown+=1;details.append(f'{profile.name} · {location.title()}: Unknown — not observed.');continue
                available+=1
                is_partial=record.get('direct') and (record['coverage']!='complete' or record['interrupted'])
                partial+=bool(is_partial);times.append(record['finished'])
                state='Partial scan; quantities are subtotals' if is_partial else 'Complete saved snapshot'
                if not Path(record['identity']['source']).is_file():state+=' · source unavailable'
                details.append(f'{profile.name} · {location.title()}: {state} · {observed_time(record["finished"])}')
                for item,quantity in record['rows']:
                    name=record.get('names',{}).get(item)
                    if not name:
                        try:matches=self.host.catalogue().search(str(item),limit=1)
                        except (ValueError,OSError):matches=[]
                        name=matches[0].name if matches else f'Item #{item}'
                    rows.append(((profile.id,location,item),(name,profile.name,location.title(),quantity,item)))
        total=len(rows);query=self.search.text().strip().casefold()
        rows=[entry for entry in rows if not query or query in entry[1][0].casefold() or query in str(entry[1][4])]
        def sort_key(entry):
            value=entry[1][self.sort_column]
            return (value.casefold() if isinstance(value,str) else value,entry[0])
        rows.sort(key=sort_key,reverse=self.sort_descending);self.items.rows(rows)
        self.search_notice.setText('No matching saved items.' if query and not rows else f'{len(rows)} of {total} saved item rows shown.' if query else f'{total} saved item rows.')
        messages=[]
        if self.errors:messages.append(f'Could not read addon observations for {len(self.errors)} character(s); see Details.')
        if unknown:messages.append(f'{unknown} location(s) Unknown — not observed.')
        if partial:messages.append(f'{partial} partial scan(s): quantities are subtotals.')
        if available and not total and not partial:messages.append('This complete saved snapshot contains no items.' if available==1 else 'These complete saved snapshots contain no items.')
        if times:
            messages.append('Saved '+observed_time(max(times))+'.' if len(set(times))==1 else 'Saved times vary; see Details.')
        if not messages:messages.append('No saved observations. Unknown, not empty.')
        self.notice.setText(' '.join(messages))
        self.details.setText('\n'.join(details)+'\nSaved observations, not live inventory. Manual plans and automatic count replacement are unchanged.')
