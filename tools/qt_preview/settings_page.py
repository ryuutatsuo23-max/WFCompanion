"""Persistent Qt appearance preview, independent of all character editors."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QLabel, QListWidget
from app import Preview, Panel, row, field, label, THEMES, FONT_CHOICES
from display_settings import DEFAULT, validate_preferences
from appearance_catalogue import companion_themes

TABS=('Overview','Gathering','Crafting','Inventory & Bank','Gear wishlist','Profiles & Rules','Party & Trackers','Activity','Auction Journal','Auto-support','Addons','Settings')


class SettingsMixin:
    def change_windows_startup(self,value):
        from windows_startup import set_enabled,enabled
        try:
            set_enabled(value);self.startup_status.setText('Starts when you sign in.' if value else 'Automatic startup is off.')
        except OSError as exc:
            self.startup_check.blockSignals(True);self.startup_check.setChecked(not value);self.startup_check.blockSignals(False)
            self.startup_status.setText('Could not change Windows startup: '+str(exc))

    def theme_choices(self):
        return companion_themes(self.settings['theme'])

    def build_settings(self,layout):
        layout.addWidget(self.getting_started)
        from saved_data_settings import SavedDataSettings
        self.saved_data_settings=SavedDataSettings(self)
        layout.addWidget(self.saved_data_settings)
        self.planning_settings=Panel(self,'Planning settings');layout.addWidget(self.planning_settings)
        self.planning_settings.box.addWidget(field('Playstyle',self.preset))
        self.planning_settings.box.addWidget(label('For the selected character’s gear wishlist and checklist. Changes are remembered immediately; inventory and saved character details stay separate.'))
        from windows_startup import checkbox
        startup=Panel(self,'Windows startup');layout.addWidget(startup)
        self.startup_check=checkbox();startup.box.addWidget(self.startup_check)
        self.startup_status=label('Off by default. Changes apply immediately.');startup.box.addWidget(self.startup_status)
        self.startup_check.toggled.connect(self.change_windows_startup)
        from close_behavior import CloseBehavior, CHOICES
        self.close_behavior=CloseBehavior(self)
        closing=Panel(self,'Closing the window');layout.addWidget(closing)
        self.close_choice=self.combo(list(CHOICES),self.close_behavior.save)
        self.close_status=label(self.close_behavior.store.error or 'Changes apply immediately. Tray mode keeps your session running.')
        self.close_choice.blockSignals(True)
        self.close_choice.setCurrentText(next(k for k,v in CHOICES.items() if v==self.close_behavior.store.data['action']))
        self.close_choice.blockSignals(False)
        closing.box.addWidget(field('When I close the window',self.close_choice))
        closing.box.addWidget(self.close_status)
        from update_panel import Updates
        self.updates_panel=Updates(self);layout.addWidget(self.updates_panel)
        self.dirty_button=self.button('No unsaved settings',self.save_session)
        layout.addWidget(self.dirty_button,0,Qt.AlignmentFlag.AlignLeft)
        experience=Panel(self,'Display mode');layout.addWidget(experience)
        self.experience_mode=self.combo(['Easy','Advanced'],self.change_experience_mode)
        experience.box.addWidget(row(field('Mode',self.experience_mode)))
        experience.box.addWidget(label('Easy simplifies Overview, Inventory & Bank, Gear wishlist, Gathering and the Crafting shopping list. Advanced shows dates and record details. Show details is also available on these pages. All data and unfinished edits are kept.'))
        workspace=Panel(self,'Workspace · visible tabs'); layout.addWidget(workspace)
        workspace.box.addWidget(label('Choose your workspace. Hiding a tab keeps its records and unfinished fields. Settings is always available.'))
        self.tab_checks={}
        for name in TABS[:-1]:
            c=QCheckBox(name.replace('&','&&')); c.toggled.connect(lambda checked,n=name:self.toggle_tab(n,checked)); self.tab_checks[name]=c
        self.tab_check_row=row(*self.tab_checks.values()); workspace.box.addWidget(self.tab_check_row)
        self.visible=self.tab_checks['Overview']
        self.tab_order=QListWidget(); self.tab_order.setMinimumHeight(170); self.tab_order.setMaximumHeight(230)
        workspace.box.addWidget(self.tab_order)
        workspace.box.addWidget(row(self.button('Move up',lambda:self.move_tab(-1)),self.button('Move down',lambda:self.move_tab(1)),self.button('Reset tab order',self.reset_order)))
        appearance=Panel(self,'Appearance'); layout.addWidget(appearance)
        self.theme=self.combo(self.theme_choices(),lambda value:self.change('theme',value) if value else None)
        appearance.box.addWidget(row(field('Theme',self.theme)))
        self.classic=QCheckBox('Use theme fonts')
        self.classic.toggled.connect(lambda v:self.font_change('classic_fonts',v))
        appearance.box.addWidget(self.classic)
        self.font_choice=self.combo([*FONT_CHOICES,*[f for f in ('Friz Quadrata TT','Arial Narrow','Morpheus','Skurri') if f in self.fonts.available]],self.choose_font)
        self.text_size=self.combo([str(i) for i in range(9,19)],lambda value:self.change('text_size',int(value)))
        self.font_choice.setToolTip('Used when theme fonts are off.')
        appearance.box.addWidget(row(field('Font style',self.font_choice),field('Text size · points',self.text_size)))
        self.font_status=label(''); appearance.box.addWidget(self.font_status)
        self.show_art=QCheckBox('Show theme artwork'); self.show_art.toggled.connect(lambda v:self.change('show_artwork',v))
        self.art_mode=self.combo(['Full background','Header'],lambda value:self.change('artwork_mode',value))
        appearance.box.addWidget(row(self.show_art,self.art_mode))
        self.opacity=self.slider(0,60,20,lambda value:self.change('panel_transparency',value)); self.opacity.setObjectName('transparencySlider')
        self.percent=QLabel(); self.percent.setMinimumWidth(65)
        appearance.box.addWidget(label('Panel transparency · 0% solid, 60% most artwork'))
        appearance.box.addWidget(row(self.opacity,self.percent))
        sound=Panel(self,'Sound'); layout.addWidget(sound)
        self.sound_check=QCheckBox('Reminder sound'); self.sound_check.toggled.connect(lambda v:self.change('sound',v))
        self.volume=self.slider(0,100,50,lambda v:self.change('volume',v)); self.volume_label=QLabel()
        self.volume_label.setMinimumWidth(65)
        sound.box.addWidget(row(self.sound_check,QLabel('Volume'),self.volume,self.volume_label,self.button('Test sound',lambda:self.play_sound(True))))
        saving=Panel(self,'Save settings'); layout.addWidget(saving)
        saving.box.addWidget(row(self.button('Save settings / finish setup',self.save_session),self.button('Revert unsaved settings',self.revert),self.button('Restore defaults',self.defaults)))
        self.session_status=label('Settings preview instantly. Save keeps only these settings, never unfinished character edits.'); saving.box.addWidget(self.session_status)
        saving.box.addWidget(label('Original tool and its saved files remain separate. Qt uses its own verified starting copy. Changes made in one tool do not automatically synchronize to the other.'))

    def open_setup_guide(self):
        from first_run import SetupGuide
        self.setup_guide=SetupGuide(self);self.setup_guide.open()

    def toggle_tab(self,name,checked):
        hidden=set(self.settings['hidden'])
        hidden.discard(name) if checked else hidden.add(name)
        self.change('hidden',[n for n in TABS if n in hidden])

    def move_tab(self,direction):
        i=self.tab_order.currentRow(); j=i+direction
        if i<0 or not 0<=j<self.tab_order.count(): return
        names=[self.tab_order.item(n).text() for n in range(self.tab_order.count())]
        names[i],names[j]=names[j],names[i]; self.change('order',names); self.sync_order(); self.tab_order.setCurrentRow(j)

    def reset_order(self): self.change('order',[]); self.sync_order()

    def ordered_tabs(self):
        return [n for n in self.settings['order'] if n in TABS]+[n for n in TABS if n not in self.settings['order']]

    def sync_order(self):
        selected=self.tab_order.currentItem().text() if self.tab_order.currentItem() else None
        self.tab_order.clear(); self.tab_order.addItems(self.ordered_tabs())
        if selected in self.ordered_tabs(): self.tab_order.setCurrentRow(self.ordered_tabs().index(selected))
        flow=self.tab_check_row.layout()
        while flow.count(): flow.takeAt(0)
        for name in self.ordered_tabs():
            if name in self.tab_checks: flow.addWidget(self.tab_checks[name])
        flow.invalidate()

    def change(self,key,value):
        if key in ('hidden','order','sound','volume'):
            self.settings[key]=value
            if key in ('hidden','order'):
                self.settings['overview_visible']='Overview' not in self.settings['hidden']; self.rebuild_navigation()
            self.refresh_settings_status()
        else: super().change(key,value)

    def choose_font(self,value):
        if value in FONT_CHOICES:
            self.settings['font_family']=value; self.qt_settings['font_override']=''
        else: self.qt_settings['font_override']=value
        self.apply_appearance(); self.refresh_settings_status()

    def font_change(self,key,value):
        self.qt_settings[key]=value; self.apply_appearance(); self.refresh_settings_status()

    def change_experience_mode(self,value):
        self.qt_settings['experience_mode']=value
        self.apply_presentation();self.refresh_settings_status()

    def apply_presentation(self):
        if hasattr(self,'simulation_inputs'):
            simple=self.qt_settings.get('experience_mode','Easy')=='Easy'
            self.show_simulation.setVisible(simple)
            for panel in (self.simulation_panel,self.simulation_inputs):
                panel.setVisible(not simple or self.show_simulation.isChecked())
        for name in ('character_overview','inventory_page','alt_inventory','gear_page','gathering','shopping'):
            page=getattr(self,name,None)
            if page is not None:page.refresh()

    def sync_controls(self):
        Preview.sync_controls(self)
        self.experience_mode.blockSignals(True)
        self.experience_mode.setCurrentText(self.qt_settings.get('experience_mode','Easy'))
        self.experience_mode.blockSignals(False)
        self.apply_presentation()
        for name,c in self.tab_checks.items():
            c.blockSignals(True); c.setChecked(name not in self.settings['hidden']); c.blockSignals(False)
        for c,value in ((self.classic,self.qt_settings['classic_fonts']),(self.sound_check,self.settings['sound'])):
            c.blockSignals(True); c.setChecked(value); c.blockSignals(False)
        self.font_choice.blockSignals(True); self.font_choice.setCurrentText(self.qt_settings['font_override'] or self.settings['font_family']); self.font_choice.blockSignals(False)
        self.volume.blockSignals(True); self.volume.setValue(self.settings['volume']); self.volume.blockSignals(False)
        self.sync_order(); self.rebuild_navigation(); self.refresh_settings_status()

    def refresh_settings_status(self):
        if not hasattr(self,'dirty_button'): return
        self.percent.setText(f"{self.settings['panel_transparency']}%")
        self.volume_label.setText(f"{self.settings['volume']}%")
        self.dirty_button.setText('Unsaved settings · click to save' if self.settings!=self.saved or self.qt_settings!=self.saved_qt else 'No unsaved settings')
        self.font_status.setText(self.fonts.status())

    def save_session(self):
        try:
            # Retain older custom appearance values for compatibility, although
            # their editors are no longer part of Settings.
            values={key:deepcopy(self.settings[key]) for key in DEFAULT}; values.update(version=5,setup=True)
            validate_preferences(values); self.data.qt.validate(self.qt_settings)
            self.data.display.save(values)
            self.settings['setup']=True; self.saved=deepcopy(self.settings)
            self.data.qt.save(self.qt_settings); self.saved_qt=deepcopy(self.qt_settings)
            self.session_status.setText('Settings saved in Qt’s separate folder. Character editor drafts unchanged.')
        except (ValueError,OSError) as e:
            self.session_status.setText(str(e)); self.refresh_settings_status(); return False
        self.refresh_settings_status(); return True

    def revert(self):
        self.settings=deepcopy(self.saved); self.qt_settings=deepcopy(self.saved_qt)
        self.apply_appearance(); self.sync_controls()

    def defaults(self):
        support=deepcopy(self.settings['support'])
        self.settings=deepcopy(DEFAULT); self.settings.update(overview_visible=True,support=support)
        self.qt_settings=dict(version=1,classic_fonts=True,font_override='')
        self.apply_appearance(); self.sync_controls()
