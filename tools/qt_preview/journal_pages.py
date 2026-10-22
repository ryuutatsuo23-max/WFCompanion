"""Manual price observations, combined estimates and non-executing support plans."""
from copy import deepcopy
from datetime import date
from PySide6.QtWidgets import QCheckBox
from presentation import easy_mode,simple_requirement
from app import row, label
from widgets import Page, Form, Table
from local_journal import coin_price, money, estimate
from catalogue import item_key


class JournalPage(Page):
    def __init__(self,host):
        super().__init__(host,'Auction Journal')
        self.form=Form(host,[('name','Item name',str,''),('market','Realm / market',str,'My market'),
            ('gold','Gold per item',str,''),('silver','Silver',str,''),('copper','Copper',str,''),('date','Observed date',str,date.today().isoformat())])
        self.form.controls['date'].setPlaceholderText('YYYY-MM-DD')
        self.form.controls['date'].setToolTip('Date format: YYYY-MM-DD, for example 2026-10-21.')
        self.box.addWidget(self.form); self.lookup_controls()
        self.price_preview=label('Unit price: Unknown'); self.box.addWidget(self.price_preview)
        self.box.addWidget(row(self.action('Save price observation',self.save),self.action('New observation',self.new)))
        self.table=Table(['Item','Unit price','Date','Market','Item key'],self.select)
        self.box.addWidget(self.table)
        self.costs=Table(['Material','Remaining','Unit price','Cost','Price date']); self.box.addWidget(self.costs)
        self.total=label(''); self.box.addWidget(self.total)
        self.box.addWidget(label('Manual dated observations, not live auction prices. Blank price = Unknown. An explicit zero is a known price. Estimates use the latest date in the chosen market and the exact linked item ID or manual name.'))
        self.form.changed(self.preview_price)
        self.form.controls['market'].textChanged.connect(self.market_changed)
        self.restore(self.data.active)

    def restore(self,character):
        super().restore(character)
        if character not in self.drafts:
            records=self.data.prices.data['characters'].get(character,[])
            self.form.load({'market':records[-1]['market'] if records else 'My market'})
        self.market_changed(); self.preview_price()

    def preview_price(self,*_):
        v=self.form.values()
        try: self.price_preview.setText('Unit price: '+money(coin_price(v['gold'],v['silver'],v['copper'])))
        except ValueError as e: self.price_preview.setText(str(e))

    def market_changed(self,*_):
        self.host.shopping.form.load({'market':self.form.values()['market']}); self.host.shopping.refresh(); self.refresh_costs()

    def refresh_costs(self):
        if not hasattr(self,'costs'): return
        self.host.shopping.refresh()
        self.costs.rows([(r.key,(r.name,r.remaining,money(p['copper'] if p else None),money(cost),p['date'] if p else 'Unknown')) for r,p,cost in self.host.shopping.estimates])
        self.total.setText(self.host.shopping.total.text())

    def refresh(self):
        super().refresh()
        records=self.data.prices.data['characters'].get(self.data.active,[])
        self.table.rows([(i,(r['name'],money(r['copper']),r['date'],r['market'],r['key'])) for i,r in reversed(list(enumerate(records)))])
        self.preview_price(); self.refresh_costs()

    def select(self,key):
        r=self.data.prices.data['characters'][self.data.active][key]
        self.form.load(dict(name=r['name'],gold=r['copper']//10000,silver=r['copper']//100%100,copper=r['copper']%100,date=r['date'],market=r['market']))
        # Preserve exact ID identity when updating a historical observation even if
        # its original catalogue reference was not embedded in the legacy journal.
        self.edit_id=key; self.reference=None; self.link_label()
        self.link.setText('Historical item key: '+r['key']+' · retained if the name is unchanged')
        self.preview_price(); self.market_changed()

    def save(self):
        self.data.require_profile_saved(); v=self.form.values(); price=coin_price(v['gold'],v['silver'],v['copper'])
        if price is None:
            self.message('Price is Unknown. Enter at least one denomination to save an observation.'); return
        key=item_key(v['name'],self.reference)
        previous=self.data.prices.data['characters'].get(self.data.active,[])
        if self.edit_id is not None and self.edit_id<len(previous) and self.reference is None:
            old=previous[self.edit_id]
            if v['name']==old['name']: key=old['key']
        candidate=deepcopy(self.data.prices.data)
        candidate['characters'].setdefault(self.data.active,[]).append(dict(name=v['name'],key=key,market=v['market'],copper=price,date=v['date']))
        self.data.prices.save(candidate); self.refresh(); self.host.shopping.refresh()
        self.message('Price observation saved. Earlier observations retained.')


class ShoppingPage(Page):
    def __init__(self,host):
        super().__init__(host,'Combined shopping list')
        self.estimates=[]
        self.show_details=QCheckBox('Show details');self.show_details.toggled.connect(self.refresh)
        self.box.addWidget(self.show_details)
        self.form=Form(host,[('market','Price estimate market',str,'My market')]); self.box.addWidget(self.form)
        self.total=label(''); self.box.addWidget(self.total)
        self.table=Table(['Material','Needed','Bags','Bank','Owned','Remaining','Source','Unit price','Cost','Price date'],height=300)
        self.box.addWidget(self.table)
        self.box.addWidget(self.action('Enter price for selected material',self.enter_price))
        self.box.addWidget(label('Gathering extras and all unfinished queue entries share one list. Missing or stale stock remains Unknown. Missing prices remain Unknown. No auction purchases or game interaction occur.'))
        self.form.changed(self.market_changed); self.refresh()

    def market_changed(self,*_):
        if hasattr(self.host,'journal'):
            self.host.journal.form.load({'market':self.form.values()['market']}); self.host.journal.refresh_costs()
        else: self.refresh()

    def refresh(self):
        super().refresh()
        simple=easy_mode(self.host) and not self.show_details.isChecked()
        self.table.setHorizontalHeaderLabels(['Material','Needed','Bags','Bank','Have','Still needed','Source','Unit price','Cost','Price date'] if simple else ['Material','Needed','Bags','Bank','Owned','Remaining','Source','Unit price','Cost','Price date'])
        for col in (2,3,7,8,9):self.table.setColumnHidden(col,simple)
        if self.data.inventory_store.error or self.data.plans_store.error or self.data.prices.error:
            self.estimates=[]; self.table.rows([]); self.total.setText('Unknown · a saved stock, plan or price file could not be read. Original file preserved.'); return
        from ownership import requirements
        rows=requirements(self.data)
        self.estimates=estimate(rows,self.data.prices.data['characters'].get(self.data.active,[]),self.form.values()['market'])
        self.table.rows([(r.key,(r.name,r.needed,r.bags,r.bank,*(simple_requirement(r) if simple else (r.owned,r.remaining)),r.source,money(p['copper'] if p else None),money(cost),p['date'] if p else 'Unknown')) for r,p,cost in self.estimates])
        known=sum(cost for _,_,cost in self.estimates if cost is not None)
        unknown=sum(cost is None for _,_,cost in self.estimates)
        self.total.setText(('Estimated cost: Not enough saved information' if unknown else f'Estimated cost from saved prices: {money(known)}') if simple else f'Total: {"Unknown" if unknown else money(known)} · known subtotal: {money(known)} · {unknown} uncertain lines')

    def enter_price(self):
        result=next((r for r,_,_ in self.estimates if r.key==self.table.key()),None)
        if result is None: raise ValueError('Select a material.')
        journal=self.host.journal; journal.new(); journal.reference=result.catalogue_ref
        journal.form.load(dict(name=result.name,market=self.form.values()['market'])); journal.link_label()
        self.host.show_page('Auction Journal')


class SupportPage(Page):
    def __init__(self,host):
        super().__init__(host,'Auto-support · planning only')
        self.box.addWidget(label('Plan an assistance label per character. Keypress sending is unavailable in this offline tool; these fields do not control the game.'))
        self.form=Form(host,[('kind','Use case',('Healing','Taunting','Gathering interact','Other'),'Healing'),
            ('key','Planned key label',str,''),('note','Plan / conditions','multiline','')])
        self.box.addWidget(self.form)
        self.box.addWidget(self.action('Save support plan',self.save)); self.restore(self.data.active)

    def restore(self,character):
        super().restore(character)
        if character not in self.drafts: self.form.load(self.data.display.data.get('support',{}).get(character,self.form.defaults))

    def save(self):
        self.data.require_profile_saved()
        candidate=deepcopy(self.data.display.data)
        candidate['support'][self.data.active]=self.form.values()
        self.data.display.save(candidate)
        # Merge only the plan into the current and saved appearance snapshots.
        for values in (self.host.settings,self.host.saved): values['support']=deepcopy(candidate['support'])
        self.message('Support plan saved. Unfinished appearance and other editor fields unchanged.')
