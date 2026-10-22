"""Per-playstyle manual checklists and build notes with independent raw drafts."""
from copy import deepcopy
from uuid import uuid4
from app import row, label
from widgets import Page, Form, Table
from playstyles import validate_plan,PRESETS


class PlaystyleOptions(Page):
    def __init__(self,host):
        super().__init__(host,'Available playstyles')
        self.box.addWidget(label('These are planning roles, not talent specializations. Adjust choices for this character if needed. Hidden plans and unfinished edits are kept; re-enable a playstyle to access them.'))
        self.form=Form(host,[(name,name,bool,False) for name in PRESETS[1:]])
        self.box.addWidget(self.form)
        self.box.addWidget(row(self.action('Save playstyle choices',self.save),self.action('Use class defaults',self.defaults)))
        self.form.changed(lambda:self.drafts.__setitem__(self.data.active,self.form.values()))
        self.restore(self.data.active)

    def remember(self,char): pass  # Changed signals retain only actually edited choices.

    def restore(self,char): self.refresh(); self.message('')

    def refresh(self):
        super().refresh()
        available=self.data.playstyles.available(self.data.active,self.data.profile.character_class)
        self.form.load(self.drafts.get(self.data.active,{name:name in available for name in PRESETS[1:]}))

    def persist(self,choices):
        self.data.require_profile_saved(); self.data.playstyles.patch(self.data.active,'available',choices)
        self.drafts.pop(self.data.active,None); self.host.sync_preset(); self.refresh()
        self.message('Playstyle choices saved. Plans and unfinished edits unchanged.')

    def save(self): self.persist([name for name,on in self.form.values().items() if on])
    def defaults(self): self.persist(None)


class PlaystylePage(Page):
    def __init__(self,host):
        super().__init__(host,'Checklist & build notes')
        self.context=label(''); self.box.addWidget(self.context)
        self.box.addWidget(label('Manual plans for this playstyle. Apply confirms an edit; Save keeps applied notes and steps. Switching playstyles keeps unfinished fields for this session.'))
        self.table=Table(['Step','Status'],self.select,height=200)
        self.table.content_column=0; self.table.setColumnWidth(1,140); self.table.fit_content_column()
        self.box.addWidget(self.table)
        self.step=Form(host,[('text','Checklist step',str,''),('done','Completed',bool,False)])
        self.step.controls['text'].setMinimumWidth(330)
        self.box.addWidget(self.step)
        self.box.addWidget(row(self.action('New step',self.new_step),self.action('Apply step',self.apply_step),
            self.action('Mark done / open',self.toggle),self.action('Remove selected step',self.remove)))
        self.form=Form(host,[('notes','Build notes · manual, up to 10,000 characters','multiline','')])
        self.box.addWidget(self.form)
        self.box.addWidget(row(self.action('Apply notes',self.apply_notes),self.action('Save checklist & notes',self.save)))
        self.step_id=None; self.step_drafts={}
        self.restore(self.data.active)

    def key(self,char=None):
        char=char or self.data.active
        return (char,self.data.playstyles.active(char))

    @property
    def plan(self): return self.data.playstyles.plan(self.data.active)

    def remember(self,char):
        key=self.key(char); super().remember(key)
        self.step_drafts[key]=(self.step_id,self.step.values())

    def restore(self,char):
        key=self.key(char); super().restore(key)
        if key not in self.drafts: self.form.load({'notes':self.plan['notes']})
        self.step_id,values=deepcopy(self.step_drafts.get(key,(None,self.step.defaults)))
        self.step.load(values); self.message('')

    def refresh(self):
        super().refresh()
        self.context.setText(f'{self.data.profile.name} · {self.data.playstyles.active(self.data.active)}')
        self.table.rows((item['id'],(item['text'],'Done' if item['done'] else 'Open')) for item in self.plan['checklist'])

    def apply_plan(self,candidate):
        validate_plan(candidate)
        self.data.playstyles.plans[self.key()]=candidate
        self.data.dirty.add(('Playstyle plan',*self.key()))
        self.refresh(); self.message('Applied in this session. Save checklist & notes to keep it.')

    def select(self,id):
        item=next((i for i in self.plan['checklist'] if i['id']==id),None)
        if item: self.step_id=id; self.step.load(item)

    def new_step(self):
        self.step_id=None; self.step.load(self.step.defaults)

    def apply_step(self):
        candidate=deepcopy(self.plan); values=self.step.values()
        if self.step_id and not any(i['id']==self.step_id for i in candidate['checklist']):
            raise ValueError('This step was removed. Choose New step or select an existing row.')
        id=self.step_id or uuid4().hex
        item={'id':id,**values}
        if self.step_id: candidate['checklist']=[item if i['id']==id else i for i in candidate['checklist']]
        else: candidate['checklist'].append(item)
        self.apply_plan(candidate); self.step_id=id

    def selected(self):
        id=self.table.key()
        if not any(i['id']==id for i in self.plan['checklist']): raise ValueError('Select a checklist step.')
        return id

    def toggle(self):
        id=self.selected(); candidate=deepcopy(self.plan)
        for item in candidate['checklist']:
            if item['id']==id: item['done']=not item['done']
        self.apply_plan(candidate)

    def remove(self):
        id=self.selected(); candidate=deepcopy(self.plan)
        candidate['checklist']=[i for i in candidate['checklist'] if i['id']!=id]
        self.apply_plan(candidate)

    def apply_notes(self):
        candidate=deepcopy(self.plan); candidate['notes']=self.form.values()['notes']; self.apply_plan(candidate)

    def save(self):
        self.data.require_profile_saved(); self.data.playstyles.save_plan(self.data.active)
        self.data.dirty.discard(('Playstyle plan',*self.key()))
        self.message('Applied checklist and notes saved. Unfinished fields and wishlist edits unchanged.')
