"""Manual gathering, reusable recipes, queue and combined shopping list."""
from copy import deepcopy
from uuid import uuid4
from PySide6.QtWidgets import QCheckBox
from presentation import easy_mode,simple_requirement
from app import row, label
from widgets import Page,Form,Table,integer,shown
from professions import Material,Recipe,CraftGoal,parse_ingredients,SOURCES
from catalogue import item_key


class GatheringPage(Page):
    def __init__(self,host):
        super().__init__(host,'Gathering')
        self.show_details=QCheckBox('Show details');self.show_details.toggled.connect(self.refresh)
        self.box.addWidget(self.show_details)
        self.table=Table(['Material','Extra goal','Source','Legacy owned'],self.select)
        self.box.addWidget(self.table)
        self.form=Form(host,[('name','Material name',str,''),('target','Extra gathering goal',str,'0'),('source','Source',SOURCES,'Either')])
        self.box.addWidget(self.form); self.lookup_controls('Material')
        self.box.addWidget(row(self.action('New material',self.new),self.action('Apply material',self.apply),
            self.action('Remove selected',self.remove),self.action('Save plan',self.save),self.action('Edit inventory',lambda:host.show_page('Inventory & Bank'))))
        self.stock_notice=label('');self.box.addWidget(self.stock_notice)
        self.shopping=Table(['Material','Needed','Bags','Bank','Owned','Remaining','Source']); self.box.addWidget(self.shopping)
        self.refresh()

    def refresh(self):
        super().refresh()
        simple=easy_mode(self.host) and not self.show_details.isChecked()
        self.table.setColumnHidden(3,simple)
        self.stock_notice.setText('Linked characters use saved addon counts; others use manual records. Missing or outdated counts mean not checked yet.' if simple else 'Linked addon bags/bank replace manual counts for these calculations, never add to them. Exact item IDs are required for addon matching. Open Saved addon inventory for timestamps. Unobserved banks and counts predating a recorded craft remain unknown.')
        self.table.rows([(item_key(m.name,m.catalogue_ref),(m.name,m.target,m.source,m.owned)) for m in self.data.plan.materials])
        self.shopping.setHorizontalHeaderLabels(['Material','Needed','Bags','Bank','Have','Still needed','Source'] if simple else ['Material','Needed','Bags','Bank','Owned','Remaining','Source'])
        for col in (2,3):self.shopping.setColumnHidden(col,simple)
        from ownership import requirements
        self.shopping.rows([(r.key,(r.name,r.needed,r.bags,r.bank,*(simple_requirement(r) if simple else (r.owned,r.remaining)),r.source)) for r in requirements(self.data)] if not self.data.inventory_store.error and not self.data.plans_store.error else [])

    def select(self,key):
        m=next(m for m in self.data.plan.materials if item_key(m.name,m.catalogue_ref)==key)
        self.edit_id=key; self.reference=m.catalogue_ref
        self.form.load(dict(name=m.name,target=m.target,source=m.source)); self.link_label()

    def apply(self):
        v=self.form.values(); old=next((m for m in self.data.plan.materials if item_key(m.name,m.catalogue_ref)==self.edit_id),None)
        m=Material(v['name'],integer(v['target']),old.owned if old else None,v['source'],self.reference)
        plan=deepcopy(self.data.plan)
        if self.edit_id:
            if old is None: raise ValueError('Material was removed; choose New material.')
            plan.materials=[m if item_key(x.name,x.catalogue_ref)==self.edit_id else x for x in plan.materials]
        else: plan.materials.append(m)
        plan.validate(); self.data.plans[self.data.active]=plan; self.edit_id=item_key(m.name,m.catalogue_ref)
        self.dirty('Crafting')

    def remove(self):
        key=self.table.key()
        if key is None: raise ValueError('Select a material.')
        self.data.plan.materials=[m for m in self.data.plan.materials if item_key(m.name,m.catalogue_ref)!=key]
        self.dirty('Crafting')

    def save(self):
        self.data.save_records('Crafting'); self.message('Gathering and crafting plan saved together.')


class CraftEditor(Page):
    def __init__(self,host,recipes=False):
        self.recipes=recipes
        super().__init__(host,'Recipe book' if recipes else 'Crafting queue')
        self.table=Table(['Item','Profession','Output/craft'] if recipes else ['Item','Crafts','Completed','Profession','Output/craft'],self.select)
        self.box.addWidget(self.table)
        specs=[('name','Crafted item',str,''),('profession','Profession',str,''),('output_per_craft','Output per craft · blank = Unknown',str,'')]
        if not recipes: specs += [('quantity','Crafts planned',str,'1'),('completed','Crafts completed',str,'0')]
        specs += [('ingredients','Ingredients · one per line: name = quantity per craft','multiline','')]
        self.form=Form(host,specs); self.box.addWidget(self.form); self.lookup_controls()
        self.ingredient_amount=Form(host,[('amount','Selected ingredient per craft',str,'1')]); self.box.addWidget(self.ingredient_amount)
        self.box.addWidget(row(self.action('Find ingredient',lambda:host.lookup('All',self.add_ingredient)),
            self.action('New recipe' if recipes else 'New queue entry',self.new),self.action('Apply recipe' if recipes else 'Apply queue entry',self.apply),
            self.action('Remove selected',self.remove)))
        if recipes:
            self.enqueue_form=Form(host,[('quantity','Crafts to queue',str,'1')]); self.box.addWidget(self.enqueue_form)
            self.box.addWidget(self.action('Add selected recipe to queue',self.enqueue))
        else:
            self.box.addWidget(row(self.action('Move up',lambda:self.move(-1)),self.action('Move down',lambda:self.move(1)),
                self.action('Record one crafted',self.record),self.action('Copy selected to recipe book',self.copy_recipe)))
        self.box.addWidget(self.action('Save plan',self.save))
        self.box.addWidget(label('Queue entries are independent recipe copies. Recording a craft marks ingredient counts Recheck; no stock or produced items are guessed. Save plan keeps applied changes from Gathering, Recipe book and Queue.'))
        self.refresh()

    @property
    def entries(self): return self.data.plan.recipes if self.recipes else self.data.plan.goals

    def remember(self,character):
        super().remember(character)
        if not hasattr(self,'extra_drafts'): self.extra_drafts={}
        self.extra_drafts[character]=(self.ingredient_amount.values(),self.enqueue_form.values() if self.recipes else {})

    def restore(self,character):
        super().restore(character)
        amount,queue=getattr(self,'extra_drafts',{}).get(character,(self.ingredient_amount.defaults,{'quantity':'1'}))
        self.ingredient_amount.load(amount)
        if self.recipes: self.enqueue_form.load(queue)

    def refresh(self):
        super().refresh()
        self.table.rows([(e.id,(e.name,e.profession,e.output_per_craft) if self.recipes else
            (e.name,e.quantity,e.completed,e.profession,e.output_per_craft)) for e in self.entries])

    def select(self,key):
        e=next(e for e in self.entries if e.id==key)
        self.edit_id=e.id; self.reference=e.catalogue_ref; self.references={i.catalogue_ref.item_id:i.catalogue_ref for i in e.ingredients if i.catalogue_ref}
        values=dict(name=e.name,profession=e.profession,output_per_craft=e.output_per_craft,
            ingredients='\n'.join(f'{i.name}'+(f' [#{i.catalogue_ref.item_id}]' if i.catalogue_ref else '')+f' = {i.per_craft}' for i in e.ingredients))
        if not self.recipes: values.update(quantity=e.quantity,completed=e.completed)
        self.form.load(values); self.link_label()

    def add_ingredient(self,item):
        amount=integer(self.ingredient_amount.values()['amount'])
        if amount<1: raise ValueError('Ingredient quantity must be at least one.')
        ref=item.reference; self.references[ref.item_id]=ref
        raw=self.form.values()['ingredients'].rstrip()
        self.form.load({'ingredients':raw+('\n' if raw else '')+f'{ref.name} [#{ref.item_id}] = {amount}'})

    def apply(self):
        values=self.form.values(); values['ingredients']=parse_ingredients(values['ingredients'],self.references)
        values['output_per_craft']=integer(values['output_per_craft'],True)
        if not self.recipes:
            values['quantity']=integer(values['quantity']); values['completed']=integer(values['completed'])
        entry=(Recipe if self.recipes else CraftGoal)(id=self.edit_id or uuid4().hex,catalogue_ref=self.reference,**values)
        plan=deepcopy(self.data.plan); key='recipes' if self.recipes else 'goals'; entries=getattr(plan,key)
        if self.edit_id:
            if not any(e.id==self.edit_id for e in entries): raise ValueError('Entry was removed; choose New.')
            entries=[entry if e.id==self.edit_id else e for e in entries]
        else: entries.append(entry)
        setattr(plan,key,entries); plan.validate(); self.data.plans[self.data.active]=plan; self.edit_id=entry.id
        self.dirty('Crafting')

    def remove(self):
        key=self.table.key()
        if key is None: raise ValueError('Select an entry.')
        setattr(self.data.plan,'recipes' if self.recipes else 'goals',[e for e in self.entries if e.id!=key]); self.dirty('Crafting')

    def enqueue(self):
        self.data.plan.enqueue(self.table.key(),integer(self.enqueue_form.values()['quantity'])); self.dirty('Crafting')

    def move(self,direction):
        index=next((i for i,e in enumerate(self.entries) if e.id==self.table.key()),None)
        if index is None: raise ValueError('Select a queue entry.')
        target=index+direction
        if 0<=target<len(self.entries): self.entries[index],self.entries[target]=self.entries[target],self.entries[index]
        self.dirty('Crafting')

    def record(self):
        self.data.plan.record_crafted(self.table.key(),self.data.inventory); self.dirty('Crafting')

    def copy_recipe(self):
        e=next((e for e in self.entries if e.id==self.table.key()),None)
        if e is None: raise ValueError('Select a queue entry.')
        plan=deepcopy(self.data.plan)
        plan.recipes.append(Recipe(uuid4().hex,e.name,deepcopy(e.ingredients),e.profession,e.catalogue_ref,e.output_per_craft))
        plan.validate(); self.data.plans[self.data.active]=plan; self.dirty('Crafting')

    def save(self):
        self.data.save_records('Crafting'); self.message('Applied recipes, queue and gathering goals saved. Other unfinished forms unchanged.')
