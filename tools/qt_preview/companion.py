"""Full offline Qt companion. Original Tk source and personal state are untouched.

Run with --state-dir for disposable testing. Normal startup makes one verified
copy of legacy JSON saves, then works exclusively in qt_preview/state.
"""
from copy import deepcopy
from pathlib import Path
from datetime import datetime
from html import escape
import argparse
import math
import struct
import sys
import tempfile
import time
import wave
from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QStackedWidget, QLabel, QProgressBar, QMessageBox, QAbstractScrollArea, QCheckBox
from app import Preview, Panel, Title, row, field, label
from data import Data, STATE, import_legacy
from fonts import Fonts
from settings_page import SettingsMixin, TABS
from widgets import Form, Table, Page
from display_settings import DEFAULT
from model import ReminderEngine, Observation, PartyReading
from stock_pages import StockPage, FilterFeedbackLabel, wrap_filter_feedback
from planning_pages import GatheringPage, CraftEditor
from journal_pages import JournalPage, ShoppingPage, SupportPage
from profile_pages import ProfilesPage, TrackersPage
from catalogue_dialog import ItemPicker
from probe_page import ProbePage
from playstyles import PRESETS
from playstyle_page import PlaystylePage, PlaystyleOptions
from wishlist_copy_dialog import WishlistCopyDialog
from alt_inventory_page import AltInventoryPage
from character_overview import CharacterOverview
from catalogue import ItemCatalogue
from local_journal import LocalStore
from window_placement import DEFAULT as WINDOW_DEFAULT, validate as validate_window, visible_rect


class Companion(SettingsMixin, Preview):
    def __init__(self,directory=STATE):
        self.data=Data(directory); self.fonts=Fonts(); self.catalogue_db=None
        self.engine=ReminderEngine(); self.paused=False; self.running_demo=False; self.frozen_at=None
        self.readings={}; self.sim_drafts={}; self.activity=[]; self.decision_codes={}; self.last_sound=-100
        self.ready=False; self.testing=False; self.audio=None; self.audio_temp=None
        self.wishlist_return=None  # Session-only navigation; never a draft/save snapshot.
        super().__init__()
        self.setWindowTitle('WoW Forever · Qt Companion · Offline')
        self.ready=True
        self.placement=LocalStore(directory,'window_placement.json',WINDOW_DEFAULT,validate_window)
        rect=self.placement.data['normal']
        if rect:
            areas=[(s.availableGeometry().left(),s.availableGeometry().top(),s.availableGeometry().right()+1,s.availableGeometry().bottom()+1) for s in QApplication.screens()]
            w,h,x,y=visible_rect(rect,areas); self.resize(w,h); self.move(x,y)
            if self.placement.data['maximized']: self.setWindowState(Qt.WindowState.WindowMaximized)
        self.timer.start()
        if not self.settings['setup']: self.show_page('Settings')
        from first_run import show_if_needed
        QTimer.singleShot(0, lambda: show_if_needed(self))
        errors=self.data.errors()
        self.banner.setText('Offline · '+ ('Saved-file errors: '+' | '.join(errors) if errors else 'Simulated combat and manual character plans · Qt data copy'))
        self.log('Session','Started','Offline. No game, screen, network or input backend.')

    def build(self):
        self.settings={**deepcopy(DEFAULT),**deepcopy(self.data.display.data)}
        # Match the older tool's implicit appearance for pre-v3/v4 saves.
        for key,implicit in (('artwork_mode','Header'),('panel_transparency',0)):
            if key not in self.data.display.data: self.settings[key]=implicit
        self.settings.update(version=5,overview_visible='Overview' not in self.settings['hidden'])
        self.saved=deepcopy(self.settings); self.qt_settings=deepcopy(self.data.qt.data); self.saved_qt=deepcopy(self.qt_settings)
        layout=QVBoxLayout(self); layout.setContentsMargins(16,12,16,12)
        layout.addWidget(Title(self,'WoW Forever'))
        self.banner=label('Offline companion'); layout.addWidget(self.banner)
        self.character=self.combo([],lambda _:self.switch_character(self.character.currentData()))
        self.preset=self.combo(PRESETS,self.switch_preset)
        self.character_info=QLabel(''); layout.addWidget(row(field('Character profile',self.character),field('Playstyle',self.preset),self.character_info))
        self.navigation=row(); layout.addWidget(self.navigation)
        self.pages=QStackedWidget(); layout.addWidget(self.pages,1)
        self.nav_buttons={name:self.button(name,lambda n=name:self.show_page(n)) for name in TABS}
        self.overview_button=self.nav_buttons['Overview']; self.settings_button=self.nav_buttons['Settings']
        self.scrolls=[]; self.page_layouts=[]; self.editors=[]; self.scrollers={}
        for name in TABS:
            scroll=QScrollArea(); scroll.setFrameShape(QScrollArea.Shape.NoFrame); scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); scroll.viewport().setAutoFillBackground(False)
            content=QWidget(); box=QVBoxLayout(content); box.setContentsMargins(0,0,10,0); box.setSpacing(12); box.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(content); content.setAutoFillBackground(False)
            self.pages.addWidget(scroll); self.scrolls.append(scroll); self.page_layouts.append(box); self.scrollers[name]=scroll
        def add(name,page): self.page_layouts[TABS.index(name)].addWidget(page); self.editors.append(page); return page
        self.build_overview(self.page_layouts[0])
        self.gathering=add('Gathering',GatheringPage(self))
        self.page_layouts[TABS.index('Crafting')].addWidget(row(*[self.button(n,lambda name=n:self.show_craft(name)) for n in ('Queue','Recipe book','Shopping list')]))
        self.queue=add('Crafting',CraftEditor(self)); self.recipes=add('Crafting',CraftEditor(self,True)); self.shopping=add('Crafting',ShoppingPage(self))
        self.show_craft('Queue')
        self.wishlist_back=self.button('Back to wishlist',self.back_to_wishlist); self.wishlist_back.hide()
        self.wishlist_destination=FilterFeedbackLabel(); self.wishlist_destination.setTextFormat(Qt.TextFormat.RichText)
        self.wishlist_destination.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse|Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.wishlist_destination.setOpenExternalLinks(False)
        self.wishlist_destination.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.wishlist_destination.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wishlist_destination.linkActivated.connect(lambda _:self.back_to_wishlist())
        self.wishlist_destination.installEventFilter(self)
        self.wishlist_destination.setMaximumWidth(440); self.wishlist_destination.hide()
        self.page_layouts[TABS.index('Inventory & Bank')].addWidget(row(self.wishlist_back,self.wishlist_destination,self.button('Selected character',lambda:self.show_inventory_section(False)),self.button('All characters',lambda:self.show_inventory_section(True))))
        self.page_layouts[TABS.index('Inventory & Bank')].addWidget(self.button('Saved addon inventory',self.show_observed_inventory))
        self.inventory_page=add('Inventory & Bank',StockPage(self))
        self.alt_inventory=AltInventoryPage(self); self.page_layouts[TABS.index('Inventory & Bank')].addWidget(self.alt_inventory)
        self.show_inventory_section(False)
        self.playstyle_context=label('')
        self.page_layouts[TABS.index('Gear wishlist')].addWidget(self.playstyle_context)
        self.page_layouts[TABS.index('Gear wishlist')].addWidget(row(self.button('Wishlist',lambda:self.show_gear_section(False)),self.button('Copy from General',self.copy_general_items),self.button('Checklist & notes',lambda:self.show_gear_section(True)),self.button('Playstyle choices',lambda:self.playstyle_options.setVisible(not self.playstyle_options.isVisible()))))
        self.playstyle_options=add('Gear wishlist',PlaystyleOptions(self)); self.playstyle_options.hide()
        self.gear_page=add('Gear wishlist',StockPage(self,True))
        self.playstyle_page=add('Gear wishlist',PlaystylePage(self)); self.show_gear_section(False)
        self.profile_page=add('Profiles & Rules',ProfilesPage(self)); self.tracker_page=add('Party & Trackers',TrackersPage(self))
        self.probe_page=ProbePage(self); self.page_layouts[TABS.index('Activity')].addWidget(self.probe_page)
        activity=Panel(self,'Activity · this session'); self.page_layouts[TABS.index('Activity')].addWidget(activity)
        self.activity_table=Table(['Time','Character','Source','State','Details'],height=450); activity.box.addWidget(self.activity_table)
        activity.box.addWidget(row(self.button('Copy log',self.copy_log),self.button('Clear log',self.clear_log)))
        activity.box.addWidget(label('Only state changes and reminders are logged. Up to 200 rows; never saved automatically.'))
        self.journal=add('Auction Journal',JournalPage(self)); self.support=add('Auto-support',SupportPage(self))
        self.build_settings(self.page_layouts[TABS.index('Settings')])
        self.footer=label(''); self.pause_button=self.button('Pause reminders',self.toggle_pause)
        footer_row=QHBoxLayout(); footer_row.addWidget(self.footer,1); footer_row.addWidget(self.pause_button); layout.addLayout(footer_row)
        self.profiles_changed(); self.rebuild_navigation()
        self.wire_nested_scrolling(self)

    def wire_nested_scrolling(self,root):
        for box in root.findChildren(QAbstractScrollArea):
            if not isinstance(box,QScrollArea): box.viewport().installEventFilter(self)

    def eventFilter(self,watched,event):
        if watched is getattr(self,'wishlist_destination',None) and event.type()==QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space):
                if not event.isAutoRepeat(): self.back_to_wishlist()
                return True
        if event.type()==QEvent.Type.Wheel and isinstance(watched.parentWidget(),QAbstractScrollArea):
            inner=watched.parentWidget()
            if not isinstance(inner,QScrollArea):
                bar=inner.verticalScrollBar(); delta=event.angleDelta().y()
                if delta and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier or
                              delta>0 and bar.value()==bar.minimum() or delta<0 and bar.value()==bar.maximum()):
                    outer=inner.parentWidget()
                    while outer and not isinstance(outer,QScrollArea): outer=outer.parentWidget()
                    if outer:
                        outer_bar=outer.verticalScrollBar()
                        movement=event.pixelDelta().y() or round(delta/120*max(20,self.fontMetrics().height())*3)
                        outer_bar.setValue(outer_bar.value()-movement); event.accept(); return True
        return super().eventFilter(watched,event)

    def build_overview(self,layout):
        self.character_overview=CharacterOverview(self);layout.addWidget(self.character_overview)
        self.show_simulation=QCheckBox('Show combat simulation (example values)')
        layout.addWidget(self.show_simulation)
        self.show_simulation.toggled.connect(lambda _:self.apply_presentation())
        panel=Panel(self,'Combat simulation'); layout.addWidget(panel)
        self.simulation_panel=panel
        self.hp_bars=[]; self.hp_values=[]; cards=[]
        for text in ('Your HP','Party member HP'):
            value=label('100%'); bar=QProgressBar(); bar.setRange(0,100); bar.setTextVisible(False); bar.setFixedWidth(280); bar.setMinimumHeight(32)
            card=field(text,value); card.layout().addWidget(bar); cards.append(card); self.hp_values.append(value); self.hp_bars.append(bar)
        panel.box.addWidget(row(*cards)); self.buff_text=label(''); self.cooldown_text=label(''); self.reminder=label('No reminder right now')
        self.tracker_summary=label('')
        for c in (self.buff_text,self.cooldown_text,self.reminder,self.tracker_summary): panel.box.addWidget(c)
        self.decisions=Table(['Rule','State','Why','Binding label'],height=190); panel.box.addWidget(self.decisions)
        self.scenario=self.combo(['Calm','Low HP','Missing buff','Cooldown ending','Uncertain readings'],self.scenario_changed)
        self.demo_button=self.button('Play demo',self.toggle_demo)
        panel.box.addWidget(row(field('Try example',self.scenario),self.demo_button,self.button('Reset simulation',self.reset_demo)))
        inputs=Panel(self,'Simulation controls'); layout.addWidget(inputs)
        self.simulation_inputs=inputs
        self.hp=self.slider(0,100,100,lambda _:None); self.party=self.slider(0,100,82,lambda _:None); self.cooldown=self.slider(0,60,15,lambda _:None)
        for slider in (self.hp,self.party,self.cooldown): slider.actionTriggered.connect(self.stop_demo)
        self.cooldown.valueChanged.connect(self.clear_primary_cooldown)
        self.cooldown.actionTriggered.connect(self.clear_primary_cooldown)
        inputs.box.addWidget(row(field('Your HP %',self.hp),field('Primary party HP %',self.party),field('Primary cooldown seconds',self.cooldown)))
        self.sim=Form(self,[('buff','Primary buff',('Present','Missing','Unknown'),'Present'),('readings','Readings',('Normal','Unknown','Frozen'),'Normal'),
            ('confirmed','Primary party identity confirmed',bool,True),('own_unknown','Your HP Unknown',bool,False),('party_unknown','Party HP Unknown',bool,False),
            ('cooldown_unknown','Cooldown Unknown',bool,False),('buff_seconds','Buff remaining seconds · simulation',str,'60')])
        inputs.box.addWidget(self.sim); inputs.box.addWidget(label('All values are simulated. Cooldown ready does not establish castability. Customize rules in Profiles & Rules and additional readings in Party & Trackers.'))
        self.sim.changed(self.stop_demo)

    def profiles_changed(self):
        self.character.blockSignals(True); self.character.clear()
        for p in self.data.profiles: self.character.addItem(p.name,p.id)
        self.character.setCurrentIndex(self.character.findData(self.data.active)); self.character.blockSignals(False)
        p=self.data.profile; self.character_info.setText(f'{p.character_class} · {p.role} · Level {p.level if p.level is not None else "Unknown"}')
        self.sync_preset()
        self.sync_wishlist_return()
        self.alt_inventory.invalidate()
        for name in ('profile_page','tracker_page'):
            if hasattr(self,name): getattr(self,name).refresh()

    def sync_preset(self):
        name=self.data.playstyles.active(self.data.active)
        available=self.data.playstyles.available(self.data.active,self.data.profile.character_class)
        self.preset.blockSignals(True); self.preset.clear()
        for choice in available: self.preset.addItem(choice,choice)
        if name not in available: self.preset.addItem(name+' · retained',name)
        self.preset.setCurrentIndex(self.preset.findData(name)); self.preset.blockSignals(False)
        self.playstyle_options.refresh()
        self.playstyle_context.setText(f'{self.data.profile.name} · {name} · Inventory & Bank shared across this character’s playstyles. General keeps the original wishlist.')

    def switch_preset(self,name,allow_retained=False):
        if name.endswith(' · retained'): name=name.removesuffix(' · retained')
        if not hasattr(self,'gear_page'): return False
        if name==self.data.playstyles.active(self.data.active): return True
        if name not in PRESETS or (not allow_retained and name not in self.data.playstyles.available(self.data.active,self.data.profile.character_class)): return False
        char=self.data.active
        self.gear_page.remember(char); self.playstyle_page.remember(char)
        try:
            self.data.playstyles.select(char,name,persist=char in {p.id for p in self.data.saved_profiles})
        except (ValueError,OSError) as error:
            self.gear_page.message(error); self.banner.setText(str(error)); self.sync_preset(); return False
        self.gear_page.restore(char); self.playstyle_page.restore(char); self.sync_preset()
        return True

    def show_gear_section(self,plan):
        self.gear_page.setVisible(not plan); self.playstyle_page.setVisible(plan)

    def copy_general_items(self):
        dialog=WishlistCopyDialog(self); dialog.exec(); dialog.deleteLater()

    def show_inventory_section(self,all_characters):
        self.inventory_page.setVisible(not all_characters); self.alt_inventory.setVisible(all_characters)

    def show_observed_inventory(self):
        from observed_inventory_dialog import ObservedInventoryDialog
        dialog=ObservedInventoryDialog(self)
        try:dialog.exec()
        finally:dialog.deleteLater()

    def open_inventory_from_wishlist(self,character,origin,item=None):
        if character not in {p.id for p in self.data.profiles}: raise ValueError('Character profile is unavailable.')
        self.inventory_page.end_temporary_search()
        self.switch_character(character)
        if item is not None: self.inventory_page.begin_temporary_search(item.name)
        self.show_inventory_section(False); self.show_page('Inventory & Bank')
        self.wishlist_return=origin
        self.sync_wishlist_return()

    def sync_wishlist_return(self):
        active=self.wishlist_return is not None
        if active:
            character,preset=self.wishlist_return
            name=next((p.name for p in self.data.profiles if p.id==character),'Unavailable character')
            destination=f'Return to: {name} · {preset}'
            self.wishlist_destination.setText(f'<a href="return-wishlist" style="color: {self.colors[3]};">{escape(wrap_filter_feedback(destination))}</a>')
            self.wishlist_destination.setAccessibleName(destination)
            self.wishlist_destination.setToolTip(destination+' · Click to return. Filters and unfinished edits stay unchanged.')
            self.wishlist_back.setToolTip(destination+'. Filters and unfinished edits stay with their characters.')
        else:
            self.wishlist_destination.clear(); self.wishlist_destination.setAccessibleName(''); self.wishlist_destination.setToolTip(''); self.wishlist_back.setToolTip('')
        self.wishlist_back.setVisible(active); self.wishlist_destination.setVisible(active)

    def back_to_wishlist(self):
        if self.wishlist_return is None: return
        character,preset=self.wishlist_return
        if character not in {p.id for p in self.data.profiles}:
            self.inventory_page.message('The original character profile is unavailable. Your records and drafts are preserved.')
            return
        try:
            self.switch_character(character)
            # A previously used playstyle may now be hidden by class choices.
            # Restore that retained plan without changing the user's choices.
            if not self.switch_preset(preset,allow_retained=True): return
            self.show_gear_section(False); self.show_page('Gear wishlist')
        except (ValueError,OSError,TypeError) as error:
            self.inventory_page.message(error); return
        self.inventory_page.end_temporary_search()
        self.wishlist_return=None; self.sync_wishlist_return()

    def switch_character(self,id):
        if not id or id==self.data.active: return
        old=self.data.active
        for page in self.editors: page.remember(old)
        self.sim_drafts[old]=(self.hp.value(),self.party.value(),self.cooldown.value(),self.sim.values())
        self.data.active=id; self.running_demo=False; self.demo_button.setText('Play demo'); self.engine.reset(); self.frozen_at=None
        values=self.sim_drafts.get(id,(100,82,15,self.sim.defaults)); self.hp.setValue(values[0]); self.party.setValue(values[1])
        self.cooldown.blockSignals(True); self.cooldown.setValue(values[2]); self.cooldown.blockSignals(False); self.sim.load(values[3])
        for page in self.editors: page.restore(id)
        self.profiles_changed()
        # Persist selection against the last saved profiles, not raw or applied drafts.
        if id in {p.id for p in self.data.saved_profiles}:
            current=self.data.profile_store.path.read_bytes() if self.data.profile_store.path.exists() else None
            if current==self.data.profile_bytes and not self.data.profile_store.error:
                try:
                    self.data.profile_store.save(self.data.saved_profiles,id); self.data.profile_bytes=self.data.profile_store.path.read_bytes()
                except (ValueError,OSError) as e: self.banner.setText(str(e))

    def rebuild_navigation(self):
        flow=self.navigation.layout()
        while flow.count(): flow.takeAt(0)
        for name in self.ordered_tabs():
            b=self.nav_buttons[name]; visible=name=='Settings' or name not in self.settings['hidden']; b.setVisible(visible)
            if visible: flow.addWidget(b)
        flow.invalidate()
        current=next((n for n,s in self.scrollers.items() if s==self.pages.currentWidget()),'Overview')
        if current in self.settings['hidden']: self.show_page('Settings')

    def show_page(self,name):
        if name in self.scrollers:
            if name=='Overview' and hasattr(self,'character_overview'):self.character_overview.refresh()
            # Cross-links may open a hidden page for this visit without changing
            # the saved visible-tab choices or destroying any drafts.
            self.pages.setCurrentWidget(self.scrollers[name])

    def show_craft(self,name):
        for caption,page in [('Queue',self.queue),('Recipe book',self.recipes),('Shopping list',self.shopping)]: page.setVisible(caption==name)

    def catalogue(self):
        if self.catalogue_db is None: self.catalogue_db=ItemCatalogue(self.data.directory)
        return self.catalogue_db

    def stock_references(self,entries):
        return self.catalogue().stock_references(entries) if entries else []

    def lookup(self,scope,choose):
        dialog=ItemPicker(self,scope,choose); dialog.exec(); dialog.deleteLater()

    def stock_changed(self):
        for page in self.editors:
            if isinstance(page,(GatheringPage,CraftEditor,ShoppingPage,StockPage)): page.refresh()
        if hasattr(self,'journal'): self.journal.refresh_costs()
        if hasattr(self,'alt_inventory'): self.alt_inventory.invalidate()

    def tracker_reading(self,kind,id):
        if id=='primary':
            v=self.sim.values()
            return {'party':(None if v['party_unknown'] else self.party.value(),v['confirmed']),
                    'buff':(v['buff'],False),'cooldown':(None if v['cooldown_unknown'] else self.readings.get(self.data.active,{}).get(('cooldown','primary'),(self.cooldown.value(),False))[0],False)}[kind]
        return self.readings.get(self.data.active,{}).get((kind,id),('Present' if kind=='buff' else 82 if kind=='party' else 15,kind=='party'))

    def set_tracker_reading(self,kind,id,value,confirmed):
        if kind=='self':
            self.hp.setValue(round(value or 0)); self.sim.load({'own_unknown':value is None}); return
        if id=='primary':
            if kind=='buff': self.sim.load({'buff':value})
            elif kind=='party': self.party.setValue(round(value or 0)); self.sim.load({'party_unknown':value is None,'confirmed':confirmed})
            else:
                # The quick slider covers 0–60s; the tracker editor retains exact
                # longer readings without clamping them to that display range.
                self.cooldown.blockSignals(True); self.cooldown.setValue(round(value or 0)); self.cooldown.blockSignals(False)
                self.readings.setdefault(self.data.active,{})[('cooldown','primary')]=(value,False)
                self.sim.load({'cooldown_unknown':value is None})
        else: self.readings.setdefault(self.data.active,{})[(kind,id)]=(value,confirmed)

    def clear_primary_cooldown(self,*_):
        self.readings.get(self.data.active,{}).pop(('cooldown','primary'),None)

    def observation(self,now):
        v=self.sim.values(); mode=v['readings']
        if mode=='Frozen' and self.frozen_at is None: self.frozen_at=now
        if mode!='Frozen': self.frozen_at=None
        readings={k:{t.id:self.tracker_reading(k,t.id) for t in self.data.profile.trackers(k)} for k in ('party','buff','cooldown')}
        return Observation(self.frozen_at if self.frozen_at is not None else now,
            None if v['own_unknown'] else self.hp.value(),readings['party']['primary'][0],v['buff'],readings['cooldown']['primary'][0],
            v['confirmed'],mode!='Unknown',
            {k:PartyReading(*x) for k,x in readings['party'].items() if k!='primary'},
            {k:x[0] for k,x in readings['buff'].items() if k!='primary'},
            {k:x[0] for k,x in readings['cooldown'].items() if k!='primary'})

    def demo_tick(self):
        if not self.ready: return
        now=time.monotonic()
        if self.running_demo:
            self.clear_primary_cooldown()
            elapsed=now-self.demo_started; t=elapsed%40
            if self.scenario.currentText()=='Cooldown ending':
                self.cooldown.setValue(max(0,3-int(elapsed)))
                for i,tracker in enumerate(self.data.profile.cooldowns): self.set_tracker_reading('cooldown',tracker.id,max(0,5+i*2-elapsed),False)
                if elapsed>=3+len(self.data.profile.cooldowns)*2: self.running_demo=False; self.demo_button.setText('Play demo')
            else:
                self.hp.setValue(32 if 6<=t<14 else 72 if 14<=t<28 else 90 if t>=28 else 100)
                self.party.setValue(28 if 6<=t<14 else 66 if 14<=t<28 else 92 if t>=28 else 82)
                self.cooldown.setValue(max(0,15-int(t)) if t<34 else 46-int(t))
                self.sim.load({'buff':'Missing' if 14<=t<23 else 'Unknown' if 23<=t<28 else 'Present','readings':'Unknown' if 23<=t<28 else 'Normal','buff_seconds':str(max(0,60-int(t)))})
                for i,tracker in enumerate(self.data.profile.party_members): self.set_tracker_reading('party',tracker.id,(22,48,65)[i] if 6<=t<14 else 82+i*5,True)
                for i,tracker in enumerate(self.data.profile.buffs): self.set_tracker_reading('buff',tracker.id,'Missing' if 14+i*2<=t<23 else 'Present',False)
                for i,tracker in enumerate(self.data.profile.cooldowns): self.set_tracker_reading('cooldown',tracker.id,max(0,19+i*4-t) if t<34 else 50+i*4-t,False)
        obs=self.observation(now)
        for bar,value,hp in zip(self.hp_bars,self.hp_values,(obs.own_hp,obs.party_hp)):
            known=obs.available and obs.is_fresh(now) and hp is not None
            bar.setValue(round(hp) if known else 0); value.setText(f'{hp:g}%' if known else 'Unknown')
        p=self.data.profile
        known=obs.available and obs.is_fresh(now) and obs.buff!='Unknown'
        self.buff_text.setText(f'{p.buff_name}: {obs.buff if known else "Unknown"} · remaining: {(self.sim.values()["buff_seconds"] or "Unknown")+"s" if known else "Unknown"}')
        self.cooldown_text.setText(f'{p.cooldown_name}: '+('Unknown' if not obs.available or not obs.is_fresh(now) or obs.cooldown is None else f'{obs.cooldown:g}s remaining' if obs.cooldown else 'Ready · castability unknown'))
        valid=obs.available and obs.is_fresh(now)
        party=[obs.party_value(t.id) for t in p.trackers('party')]
        confirmed=[r.hp for r in party if valid and r.identity_confirmed and r.hp is not None]
        buffs=[obs.buff_value(t.id) if valid else 'Unknown' for t in p.trackers('buff')]
        cooldowns=[obs.cooldown_value(t.id) if valid else None for t in p.trackers('cooldown')]
        lowest=f'{min(confirmed):g}%' if confirmed else 'Unknown'
        self.tracker_summary.setText(f'Party: {len(confirmed)}/{len(party)} confirmed · Lowest HP: {lowest} · Buffs missing: {buffs.count("Missing")} ({buffs.count("Unknown")} unknown) · Cooldowns ready: {cooldowns.count(0)} ({cooldowns.count(None)} unknown)')
        decisions,notices=self.engine.evaluate(p.rules,obs,now,self.paused)
        self.decisions.rows([(d.rule_id,(d.name,d.code,d.detail,d.binding)) for d in decisions])
        active=next((d for d in decisions if d.code=='active'),None)
        self.reminder.setText(active.message+(' · '+active.binding if active.binding else '') if active else 'Reminders paused' if self.paused else 'No reminder right now')
        for d in decisions:
            code=(d.code,d.detail if d.code!='confirming' else '')
            if self.decision_codes.get((p.id,d.rule_id))!=code:
                self.log(d.name,d.code,d.detail); self.decision_codes[p.id,d.rule_id]=code
        for d in notices: self.log(d.name,'Reminder',d.message)
        if notices and now-self.last_sound>=3: self.play_sound(); self.last_sound=now
        if self.pages.currentWidget()==self.scrollers['Party & Trackers']: self.tracker_page.refresh()
        names={p.id:p.name for p in self.data.profiles}
        dirty=', '.join(sorted(key if isinstance(key,str) else f'{key[0]} · {names.get(key[1],"Character")} · {key[2]}' for key in self.data.dirty))
        self.footer.setText('Offline · '+('Applied changes need saving: '+dirty if dirty else 'Simulated data · No input backend'))

    def toggle_demo(self):
        self.running_demo=not self.running_demo; self.demo_started=time.monotonic()
        if self.running_demo:
            self.scenario.blockSignals(True); self.scenario.setCurrentText('Calm'); self.scenario.blockSignals(False)
            self.sim.load(self.sim.defaults); self.engine.reset()
        self.demo_button.setText('Stop demo' if self.running_demo else 'Play demo')

    def stop_demo(self,*_):
        self.running_demo=False; self.demo_button.setText('Play demo')

    def reset_demo(self):
        self.running_demo=False; self.demo_button.setText('Play demo'); self.hp.setValue(100); self.party.setValue(82); self.cooldown.setValue(15)
        self.sim.load(self.sim.defaults); self.readings[self.data.active]={}; self.engine.reset(); self.frozen_at=None

    def scenario_changed(self,name):
        self.reset_demo()
        if name=='Low HP':
            self.hp.setValue(32); self.party.setValue(28)
            for i,t in enumerate(self.data.profile.party_members): self.set_tracker_reading('party',t.id,(22,48,65)[i],True)
        elif name=='Missing buff':
            self.sim.load({'buff':'Missing','buff_seconds':'0'})
            for t in self.data.profile.buffs: self.set_tracker_reading('buff',t.id,'Missing',False)
        elif name=='Cooldown ending':
            self.cooldown.setValue(3); self.running_demo=True; self.demo_started=time.monotonic(); self.demo_button.setText('Stop demo')
        elif name=='Uncertain readings': self.sim.load({'readings':'Unknown'})

    def toggle_pause(self):
        self.paused=not self.paused; self.engine.reset(); self.pause_button.setText('Resume reminders' if self.paused else 'Pause reminders')

    def log(self,source,state,detail):
        self.activity.append((datetime.now().strftime('%H:%M:%S'),self.data.profile.name,source,state,detail)); self.activity=self.activity[-200:]
        self.activity_table.rows(list(enumerate(self.activity)))

    def copy_log(self): QApplication.clipboard().setText('\n'.join('\t'.join(r) for r in self.activity))
    def clear_log(self): self.activity=[]; self.activity_table.rows([])

    def play_sound(self,force=False):
        if self.testing or (not force and not self.settings['sound']): return
        try:
            if sys.platform == 'win32':
                import winsound
                import io
                data=io.BytesIO()
                with wave.open(data,'wb') as f:
                    f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
                    volume=self.settings['volume']/100
                    f.writeframes(b''.join(struct.pack('<h',round(volume*5000*math.sin(i*2*math.pi*660/22050)*min(1,i/200,(4409-i)/200))) for i in range(4410)))
                winsound.PlaySound(data.getvalue(),winsound.SND_MEMORY | winsound.SND_NODEFAULT)
                return
            if self.audio is None:
                from PySide6.QtMultimedia import QSoundEffect
                self.audio_temp=tempfile.TemporaryDirectory(prefix='wow-qt-sound-')
                path=Path(self.audio_temp.name)/'reminder.wav'
                with wave.open(str(path),'wb') as f:
                    f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
                    f.writeframes(b''.join(struct.pack('<h',round(5000*math.sin(i*2*math.pi*660/22050)*min(1,i/200,(4409-i)/200))) for i in range(4410)))
                self.audio=QSoundEffect(self); self.audio.setSource(QUrl.fromLocalFile(str(path)))
            self.audio.setVolume(self.settings['volume']/100); self.audio.play()
        except (ImportError,OSError) as e: self.session_status.setText('Sound unavailable: '+str(e))

    def apply_appearance(self):
        fallback=self.settings['font_family']; roles=self.qt_settings['classic_fonts']
        self.appearance_font_family=self.fonts.family('Friz Quadrata TT',fallback) if roles else self.fonts.family(self.qt_settings['font_override'],fallback)
        super().apply_appearance()
        title=self.fonts.family('Morpheus',fallback) if roles else self.appearance_font_family
        numbers=self.fonts.family('Skurri',fallback) if roles else self.appearance_font_family
        size=self.settings['text_size']
        for widget in self.findChildren(Title): widget.setStyleSheet(f'font-family: "{title}"; font-size: {size+2}pt;'); widget.updateGeometry()
        for widget in self.findChildren(Table): self.style_table(widget)
        for widget in self.hp_values: widget.setStyleSheet(f'font-family: "{numbers}";font-size: {size+8}pt;'); widget.updateGeometry()
        self.sync_wishlist_return()
        if hasattr(self,'inventory_page'): self.inventory_page.sync_temporary_notice()

    def style_table(self,widget):
        family=self.fonts.family('Arial Narrow',self.settings['font_family']) if self.qt_settings['classic_fonts'] else self.appearance_font_family
        widget.setStyleSheet(f'QTableWidget, QHeaderView {{font-family: "{family}";font-size: {self.settings["text_size"]}pt;}}')
        widget.fit_headers()
        widget.verticalHeader().setDefaultSectionSize(max(30,widget.fontMetrics().height()+12))

    def closeEvent(self,event):
        if not self.testing and self.data.dirty:
            if QMessageBox.question(self,'Unsaved applied records','Some applied records have not been saved. Close and discard unsaved changes?',QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Discard:
                event.ignore(); return
        if not self.testing:
            rect=self.normalGeometry()
            try: self.placement.save(dict(version=1,normal=[rect.width(),rect.height(),rect.x(),rect.y()],maximized=self.isMaximized()))
            except (ValueError,OSError): pass
        self.character_overview.game_data_monitor.set_enabled(False)
        self.timer.stop()
        if self.catalogue_db: self.catalogue_db.close()
        if self.audio: self.audio.stop(); self.audio.setSource(QUrl())
        if self.audio_temp: self.audio_temp.cleanup()
        super().closeEvent(event)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--state-dir',type=Path); args=parser.parse_args()
    application=QApplication(sys.argv)
    directory=args.state_dir.resolve() if args.state_dir else STATE
    try:
        if args.state_dir is None: import_legacy()
        window=Companion(directory); window.show(); return application.exec()
    except (ValueError,OSError) as e:
        QMessageBox.critical(None,'Qt companion could not open',str(e)); return 1


if __name__=='__main__': raise SystemExit(main())
