"""Read-only saved inventory, across characters and locations."""
from pathlib import Path
from datetime import datetime
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
        super().__init__(host);self.host=host;self.ledger={};self.errors={};self.unlinked=set();self.load_error=None
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
        self.empty_notice=label('');self.empty_notice.setWordWrap(True);self.empty_notice.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.empty_notice)
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
        self._loaded_signature=None;self._pending_signature=None;self._saved_times=None
        self.watch_timer=QTimer(self);self.watch_timer.setInterval(2000);self.watch_timer.timeout.connect(self.poll_saved_files)
        host.style_table(self.items);host.wire_nested_scrolling(self);self.refresh()

    def profiles(self):
        profiles=self.host.data.saved_profiles
        if self.character_scope.currentIndex()==1:return profiles
        active=self.host.data.active if self.embedded else self.character.currentData()
        return [p for p in profiles if p.id==active]

    def source_signature(self):
        directory=self.host.data.directory
        profiles=tuple(p.id for p in (self.host.data.saved_profiles if self.embedded else self.profiles()))
        paths={directory/'character_links.json',directory/'addon_inventory.json'}
        paths.update(Path(e['identity']['source']) for e in LinkStore(directory).records['links'] if e['profile'] in profiles)
        values=[]
        for path in sorted(paths):
            try:
                stat=path.stat();values.append((str(path),stat.st_size,stat.st_mtime_ns))
            except OSError:values.append((str(path),None,None))
        return profiles,tuple(values)

    def showEvent(self,event):
        super().showEvent(event);self.refresh_if_changed();self.watch_timer.start()

    def hideEvent(self,event):
        self.watch_timer.stop();super().hideEvent(event)

    def poll_saved_files(self):
        if not self.isVisible():return
        try:signature=self.source_signature()
        except (OSError,ValueError):self.refresh();return
        if signature==self._loaded_signature:self._pending_signature=None;return
        # Two stable observations avoid reading a save while it is being written.
        if signature!=self._pending_signature:self._pending_signature=signature;return
        self.refresh(follow_new=True)

    def sync_character_list(self):
        if self.embedded:
            self.character.blockSignals(True);self.character.clear()
            for p in self.host.data.saved_profiles:self.character.addItem(p.name,p.id)
            self.character.setCurrentIndex(self.character.findData(self.host.data.active));self.character.blockSignals(False)

    def refresh_if_changed(self):
        self.sync_character_list()
        try:signature=self.source_signature()
        except (OSError,ValueError):self.refresh();return
        if signature==getattr(self,'_attempt_signature',None):
            self.select(self.scope);return
        self.refresh()

    def refresh(self,*,follow_new=False):
        self.sync_character_list()
        self._attempt_signature=None;self.ledger={};self.errors={};self.unlinked=set();self.load_error=None
        try:signature=self.source_signature()
        except (OSError,ValueError) as exc:
            self.load_error=str(exc);self.select(self.scope);return
        fallback=None
        for profile in (self.host.data.saved_profiles if self.embedded else self.profiles()):
            try:
                snapshots=linked_snapshots(self.host.data.directory,profile.id)
                if snapshots is None:
                    self.unlinked.add(profile.id)
                    if fallback is None:fallback=ObservationStore(self.host.data.directory).ledger
                    snapshots={scope:r for (pid,scope),r in fallback.items() if pid==profile.id}
                self.ledger.update({(profile.id,scope):record for scope,record in snapshots.items()})
            except (ValueError,OSError) as exc:self.errors[profile.id]=str(exc)
        # Establish a baseline on opening/explicit refresh. Only a later stable
        # file change may select a newly saved character; never infer live login.
        times={}
        for (profile,location),record in self.ledger.items():
            stamp=record.get('finished')
            if not record.get('direct') or record.get('interrupted') or record.get('coverage')!='complete' or not isinstance(stamp,int):continue
            key=(profile,record['identity']['source'])
            times[key]=max(times.get(key,0),stamp)
        previous=self._saved_times;self._saved_times=times
        if follow_new and self.embedded and previous is not None and not self.errors:
            changed=[(stamp,key[0]) for key,stamp in times.items() if key in previous and stamp>previous[key]]
            if changed:
                newest=max(stamp for stamp,_ in changed)
                candidates={profile for stamp,profile in changed if stamp==newest}
                if len(candidates)==1:
                    target=candidates.pop()
                    if target!=self.host.data.active:
                        self.character_scope.blockSignals(True);self.character_scope.setCurrentIndex(0);self.character_scope.blockSignals(False)
                        self.host.switch_character(target)
                        return
        self.select(self.scope)
        # Navigation reuses this attempt; the watcher still retries failed reads.
        self._attempt_signature=signature
        if not self.errors:self._loaded_signature=signature;self._pending_signature=None

    def sort_items(self,column):
        self.sort_descending=not self.sort_descending if column==self.sort_column else False;self.sort_column=column
        self.items.horizontalHeader().setSortIndicator(column,Qt.SortOrder.DescendingOrder if self.sort_descending else Qt.SortOrder.AscendingOrder)
        self.select(self.scope)

    def select(self,scope):
        self.scope=scope
        for name,button in self.buttons.items():button.setChecked(name==scope)
        if self.load_error:
            self.items.rows([]);self.notice.setText('Could not read saved items; see Details.')
            self.empty_notice.setText('Saved inventory is unavailable. Check the saved-file connection in Settings, then try Refresh saved observations. Your saved records and manual plans have not been changed.')
            self.empty_notice.show();self.details.setText(self.load_error);self.search_notice.setText('');return
        rows=[];details=[];summaries=[]
        missing=0;partial=0;complete=0;unconnected=0
        profiles=self.profiles()
        for profile in profiles:
            prefix=profile.name+': ' if len(profiles)>1 else ''
            locations=[]
            if profile.id in self.unlinked and not any(pid==profile.id for pid,loc in self.ledger):unconnected+=1
            if profile.id in self.errors:
                summaries.append(prefix+'Could not read saved items; see Details.')
                details.append(profile.name+': Could not read addon observations: '+self.errors[profile.id]);continue
            for location in ('bags','bank') if scope=='all' else (scope,):
                record=self.ledger.get((profile.id,location))
                if record is None:
                    missing+=1
                    locations.append('Bags haven’t been recorded yet' if location=='bags' else 'Bank hasn’t been recorded yet')
                    details.append(f'{profile.name} · {location.title()}: Unknown — not observed.');continue
                is_partial=record.get('direct') and (record['coverage']!='complete' or record['interrupted'])
                if is_partial:partial+=1
                else:complete+=1
                stamp=record.get('finished')
                try:saved=datetime.fromtimestamp(stamp).strftime('%d %b %Y, %H:%M') if stamp is not None else None
                except (ValueError,OSError,OverflowError):saved=None
                summary=f'{location.title()} saved {saved}' if saved else f'{location.title()} saved · time unavailable'
                if is_partial:summary+=' (incomplete; some items may be missing)'
                elif not record['rows']:summary+=' (empty)'
                if not Path(record['identity']['source']).is_file():summary+=' · source unavailable'
                locations.append(summary)
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
            summaries.append(prefix+' · '.join(locations))
        total=len(rows);query=self.search.text().strip().casefold()
        rows=[entry for entry in rows if not query or query in entry[1][0].casefold() or query in str(entry[1][4])]
        def sort_key(entry):
            value=entry[1][self.sort_column]
            return (value.casefold() if isinstance(value,str) else value,entry[0])
        rows.sort(key=sort_key,reverse=self.sort_descending);self.items.rows(rows)
        self.search_notice.setText((f'Showing {len(rows)} of {total} saved items'+(' · No matching items' if not rows else '')) if query and total else f'{total} saved item'+('' if total==1 else 's'))
        if rows:empty=''
        elif total:empty='No saved items match your search. Clear the search or try another item name or ID.'
        elif not profiles:empty='No saved characters to show. Choose or add a character in Overview.'
        elif any(p.id in self.errors for p in profiles):empty='Saved inventory is unavailable for one or more characters. Check the saved-file connection in Settings, then try Refresh saved observations. This does not mean their bags or bank are empty.'
        elif unconnected==len(profiles):empty='No saved file is connected for '+('this character' if len(profiles)==1 else 'these characters')+'. Connect saved game data in Settings to see items here. Choosing an addon installation folder does not connect saved data.'
        elif partial:empty='No items were captured in this incomplete snapshot. The contents are unknown, not confirmed empty. Save again with /reload or normal logout when the game is available.'
        elif missing:
            if scope=='bank':empty='Bank has not been recorded for '+('this character' if len(profiles)==1 else 'one or more characters')+'. Visit a bank when the game is available, then /reload or log out normally to save it. Unknown does not mean empty.'
            elif not complete:empty='No saved bag items are available yet. With the addons enabled, /reload or log out normally when the game is available to save an observation. Unrecorded locations remain unknown.'
            else:empty='The recorded locations contain no saved items. Other locations have not been recorded yet; their contents remain unknown.'
        else:empty=('Bags were' if scope=='bags' else 'Bank was' if scope=='bank' else 'Bags and bank were')+' empty in the saved snapshots shown here. This describes the saved observations, not live inventory.'
        self.empty_notice.setText(empty);self.empty_notice.setVisible(bool(empty))
        self.notice.setText('\n'.join(summaries) if summaries else 'No saved characters to show.')
        self.details.setText('\n'.join(details)+'\nSaved observations, not live inventory. Manual plans and automatic count replacement are unchanged.')
