"""Profile, rule and tracker editors; only explicit Apply mutates domain models."""
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4
import time
from app import row, label
from widgets import Page, Form, Table, integer
from model import Profile, Rule, Tracker, default_profile, CLASSES, ROLES


class ProfilesPage(Page):
    def __init__(self, host):
        super().__init__(host, 'Profiles & Rules')
        self.form = Form(host, [('name','Character name',str,''),('character_class','Class',CLASSES,'Unspecified'),
            ('role','Role',ROLES,'General'),('level','Level · blank = Unknown',str,''),
            ('party_name','Primary party label',str,'Party member'),('buff_name','Primary buff label',str,'Tracked buff'),
            ('cooldown_name','Primary cooldown label',str,'Tracked ability')])
        self.box.addWidget(self.form)
        self.box.addWidget(row(self.action('Apply character',self.apply_profile),self.action('New character',lambda:self.create(False)),
            self.action('Duplicate character',lambda:self.create(True)),self.action('Save profiles',self.save)))
        self.table=Table(['Rule','Trigger','On','Priority','Source','Reminder'],self.select)
        self.box.addWidget(self.table)
        self.rule=Form(host,[('name','Rule name',str,'New reminder'),('kind','Trigger',('health','buff','cooldown'),'health'),
            ('target','HP source',('self','party'),'self'),('tracker_id','Tracked source',('primary',),'primary'),
            ('threshold','Below HP %',str,'40'),('recovery','Clear at HP %',str,'50'),
            ('delay','Confirm seconds',str,'0.5'),('repeat','Repeat seconds · 0 = once',str,'0'),('priority','Priority · 1 first',str,'2'),
            ('message','Reminder',str,'Check the configured action'),('binding','Binding label · text only',str,''),
            ('enabled','Rule enabled',bool,True),('require_cooldown','Require cooldown ready',bool,False),
            ('cooldown_id','Required cooldown',('primary',),'primary')])
        self.box.addWidget(self.rule)
        self.box.addWidget(row(self.action('New rule',self.new_rule),self.action('Apply rule',self.apply_rule),self.action('Remove selected rule',self.remove)))
        self.box.addWidget(label('Apply edits, then Save profiles. Saving does not apply unfinished fields. Trackers use stable IDs; their names are shown in Party & Trackers.'))
        self.rule_id=None
        self.rule_drafts={}
        for key in ('kind','target'): self.rule.controls[key].currentTextChanged.connect(self.refresh_choices)
        self.restore(self.data.active)

    def remember(self,character):
        super().remember(character)
        self.rule_drafts[character]=(self.rule_id,self.rule.values())

    def restore(self,character):
        self.refresh_choices()
        super().restore(character)
        if character not in self.drafts: self.form.load(asdict(self.data.profile))
        self.rule_id,values=deepcopy(self.rule_drafts.get(character,(None,self.rule.defaults)))
        self.rule.load(values); self.refresh_choices(); self.rule.load(values)

    def refresh_choices(self,*_):
        p=self.data.profile
        v=self.rule.values(); kind='party' if v['kind']=='health' and v['target']=='party' else v['kind']
        sources=[Tracker('primary','Your HP')] if kind=='health' else p.trackers(kind)
        for key,values in [('tracker_id',sources),('cooldown_id',p.trackers('cooldown'))]:
            control=self.rule.controls[key]; old=control.currentData() if control.property('usesData') else control.currentText()
            control.blockSignals(True); control.setProperty('usesData',True); control.clear()
            for t in values: control.addItem(t.name,t.id)
            if old in [t.id for t in values]: control.setCurrentIndex(control.findData(old))
            control.blockSignals(False)

    def refresh(self):
        super().refresh()
        self.table.rows([(r.id,(r.name,r.kind,'Yes' if r.enabled else 'No',r.priority,r.tracker_id,r.message)) for r in self.data.profile.rules])
        self.refresh_choices()

    def replace(self,profile):
        profile.validate()
        self.data.profiles=[profile if p.id==profile.id else p for p in self.data.profiles]
        self.data.dirty.add('Profiles & Rules'); self.host.profiles_changed(); self.refresh()
        self.host.engine.reset()

    def apply_profile(self):
        p=deepcopy(self.data.profile); values=self.form.values(); values['level']=integer(values['level'],True)
        for key,value in values.items(): setattr(p,key,value)
        self.replace(p); self.message('Character applied. Save profiles to keep it.')

    def create(self,duplicate):
        if len(self.data.profiles)>=100: raise ValueError('Maximum 100 characters.')
        p=deepcopy(self.data.profile) if duplicate else default_profile()
        p.id=uuid4().hex; p.name=(p.name+' copy')[:80] if duplicate else 'New character'
        p.validate(); self.data.profiles.append(p); self.data.dirty.add('Profiles & Rules')
        self.host.switch_character(p.id)
        self.message('New character is independent. Apply its details, then Save profiles before saving other records.')

    def select(self,key):
        r=next(r for r in self.data.profile.rules if r.id==key)
        self.rule_id=r.id; self.rule.load(asdict(r)); self.refresh_choices(); self.rule.load(asdict(r))

    def new_rule(self):
        self.rule_id=None; self.rule.load(self.rule.defaults); self.refresh_choices(); self.rule.load(self.rule.defaults)

    def apply_rule(self):
        v=self.rule.values()
        for key in ('threshold','recovery','delay','repeat'): v[key]=float(v[key])
        v['priority']=integer(v['priority'])
        r=Rule(id=self.rule_id or uuid4().hex,**v); p=deepcopy(self.data.profile)
        if self.rule_id:
            if not any(x.id==self.rule_id for x in p.rules): raise ValueError('Rule removed. Choose New rule.')
            p.rules=[r if x.id==r.id else x for x in p.rules]
        else: p.rules.append(r)
        self.replace(p); self.rule_id=r.id; self.message('Rule applied. Save profiles to keep it.')

    def remove(self):
        key=self.table.key()
        if key is None: raise ValueError('Select a rule.')
        p=deepcopy(self.data.profile); p.rules=[r for r in p.rules if r.id!=key]; self.replace(p)

    def save(self):
        self.data.save_profiles(); self.message('Applied profiles and rules saved. Unfinished fields unchanged.')


class TrackersPage(Page):
    def __init__(self,host):
        super().__init__(host,'Party & Trackers')
        self.table=Table(['Category','Name','ID','Simulated reading','Identity confirmed'],self.select)
        self.box.addWidget(self.table)
        self.form=Form(host,[('kind','Category',('self','party','buff','cooldown'),'buff'),('name','Tracker name',str,''),
            ('reading','HP % / cooldown seconds · blank = Unknown',str,''),('buff','Buff state',('Present','Missing','Unknown'),'Present'),
            ('confirmed','Party identity confirmed',bool,False)])
        self.box.addWidget(self.form)
        self.box.addWidget(row(self.action('New buff/cooldown tracker',self.new),self.action('Apply tracker / reading',self.apply),
            self.action('Reload selected reading',lambda:self.select(self.table.key()) if self.table.key() else None),
            self.action('Add reminder for selected tracker',self.add_rule),self.action('Save profiles',self.save)))
        self.box.addWidget(label('Four party members plus your own HP. Up to eight buffs and eight cooldowns per character. Readings are simulated for this session; only tracker labels and rules are saved.'))
        self.refresh()

    def refresh(self):
        super().refresh(); entries=[]
        now=time.monotonic(); observation=self.host.observation(now); valid=observation.available and observation.is_fresh(now)
        entries.append((('self','primary'),('self','Your HP','primary',observation.own_hp if valid else None,'—')))
        for kind in ('party','buff','cooldown'):
            for t in self.data.profile.trackers(kind):
                value,confirmed=self.host.tracker_reading(kind,t.id)
                if not valid: value=None
                entries.append(((kind,t.id),(kind,t.name,t.id,value,'Yes' if confirmed else 'No' if kind=='party' else '—')))
        self.table.rows(entries)

    def select(self,key):
        kind,id=key
        t=Tracker('primary','Your HP') if kind=='self' else next(t for t in self.data.profile.trackers(kind) if t.id==id)
        self.edit_id=key
        value,confirmed=(None if self.host.sim.values()['own_unknown'] else self.host.hp.value(),True) if kind=='self' else self.host.tracker_reading(kind,id)
        self.form.load(dict(kind=kind,name=t.name,reading=value if kind!='buff' else '',buff=value if kind=='buff' else 'Present',confirmed=confirmed))

    def apply(self):
        v=self.form.values(); kind=v['kind']; p=deepcopy(self.data.profile)
        if self.edit_id and self.edit_id[0]!=kind: raise ValueError('Choose New to change tracker category.')
        id=self.edit_id[1] if self.edit_id else uuid4().hex
        value=v['buff'] if kind=='buff' else (None if not v['reading'].strip() else float(v['reading']))
        if kind!='buff' and value is not None and not 0<=value<=(100 if kind=='party' else 3600): raise ValueError('Reading is out of range.')
        if kind=='self':
            if value is not None and not 0<=value<=100: raise ValueError('HP must be 0–100.')
            self.host.stop_demo(); self.host.set_tracker_reading('self','primary',value,True); self.refresh(); return
        if id=='primary': setattr(p,{'party':'party_name','buff':'buff_name','cooldown':'cooldown_name'}[kind],v['name'])
        else:
            key={'party':'party_members','buff':'buffs','cooldown':'cooldowns'}[kind]
            items=getattr(p,key)
            if self.edit_id: items=[Tracker(id,v['name']) if t.id==id else t for t in items]
            else: items.append(Tracker(id,v['name']))
            setattr(p,key,items)
        p.validate(); self.data.profiles=[p if x.id==p.id else x for x in self.data.profiles]
        self.host.stop_demo(); self.host.set_tracker_reading(kind,id,value,v['confirmed']); self.edit_id=(kind,id)
        self.data.dirty.add('Profiles & Rules'); self.host.profiles_changed(); self.refresh()
        self.message('Tracker applied. Simulated values stay in this session; Save profiles keeps labels.')

    def add_rule(self):
        key=self.table.key()
        if key is None: raise ValueError('Select a tracker.')
        kind,id=key; p=deepcopy(self.data.profile); name='Your HP' if kind=='self' else next(t.name for t in p.trackers(kind) if t.id==id)
        p.rules.append(Rule(uuid4().hex,name,kind if kind not in ('party','self') else 'health',target='party' if kind=='party' else 'self',tracker_id=id))
        p.validate(); self.data.profiles=[p if x.id==p.id else x for x in self.data.profiles]
        self.data.dirty.add('Profiles & Rules'); self.host.profiles_changed(); self.message('Reminder added. Customize it in Profiles & Rules, then save.')

    def save(self):
        self.data.save_profiles(); self.message('Applied tracker names and profiles saved; simulation values and unfinished fields remain session-only.')
