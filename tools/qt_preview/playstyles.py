"""Offline per-character playstyles. Legacy General gear remains in its own files.

Explicit section saves patch only that section of the last saved document, never
in-memory editors or applied changes in another preset. LocalStore guards external
changes and retains a previous-file backup. No game APIs or personal character data.
"""
from copy import deepcopy
from dataclasses import asdict
from gear import GearWishlist
from gear_filters import GearFilters
from gear_undo import RemovedGoal
from local_journal import LocalStore
from model import text

PRESETS = ('General','Tank','Healing','Solo DPS')
# Editable planning defaults from the user's nine-class overview, not talent
# trees or live capability detection. Feral supports both Tank and Solo DPS plans.
CLASS_PLAYSTYLES = {
    'Druid':PRESETS[1:], 'Paladin':PRESETS[1:],
    'Warrior':('Tank','Solo DPS'),
    'Priest':('Healing','Solo DPS'), 'Shaman':('Healing','Solo DPS'),
    'Hunter':('Solo DPS',), 'Mage':('Solo DPS',),
    'Rogue':('Solo DPS',), 'Warlock':('Solo DPS',),
}


def blank_plan():
    return {'notes':'','checklist':[]}


def blank_preset():
    return {'gear':{'entries':[]},'plan':blank_plan(),'filters':asdict(GearFilters()),'undo':None}


def validate_plan(plan):
    if not isinstance(plan,dict) or set(plan) != {'notes','checklist'}:
        raise ValueError('Invalid playstyle plan.')
    notes=plan['notes']
    if not isinstance(notes,str) or len(notes)>10000 or any(ord(c)<32 and c not in '\n\r\t' for c in notes):
        raise ValueError('Build notes must be text, up to 10,000 characters.')
    items=plan['checklist']
    if not isinstance(items,list) or len(items)>100: raise ValueError('Keep up to 100 checklist steps per preset.')
    ids=set()
    for item in items:
        if not isinstance(item,dict) or set(item)!={'id','text','done'}: raise ValueError('Invalid checklist step.')
        text(item['id'],'Checklist ID'); text(item['text'],'Checklist step',300)
        if item['id'] in ids or type(item['done']) is not bool: raise ValueError('Invalid checklist ID or completion state.')
        ids.add(item['id'])


def validate(data):
    if not isinstance(data,dict) or set(data)!={'version','characters'} or type(data['version']) is not int or data['version']!=1:
        raise ValueError('Unsupported playstyle save format.')
    characters=data['characters']
    if not isinstance(characters,dict) or len(characters)>100: raise ValueError('Keep up to 100 characters.')
    for char,record in characters.items():
        text(char,'Character ID')
        if not isinstance(record,dict) or set(record) not in ({'active','presets'},{'active','presets','available'}) or record['active'] not in PRESETS:
            raise ValueError('Invalid active playstyle.')
        available=record.get('available')
        if available is not None and (not isinstance(available,list) or any(n not in PRESETS[1:] for n in available) or len(available)!=len(set(available))):
            raise ValueError('Invalid playstyle choices.')
        if not isinstance(record['presets'],dict) or set(record['presets'])-set(PRESETS): raise ValueError('Invalid playstyle list.')
        for name,preset in record['presets'].items():
            if not isinstance(preset,dict) or set(preset)!=set(blank_preset()): raise ValueError('Invalid playstyle fields.')
            GearWishlist.from_dict(preset['gear']); validate_plan(preset['plan'])
            GearFilters.from_dict(preset['filters'])
            if preset['undo'] is not None: RemovedGoal.from_dict(preset['undo'])
            if name=='General' and (preset['gear']['entries'] or preset['undo'] is not None or preset['filters']!=asdict(GearFilters())):
                raise ValueError('General wishlist uses the original gear files.')


class Playstyles:
    def __init__(self,directory):
        self.store=LocalStore(directory,'playstyle_presets.json',{'version':1,'characters':{}},validate)
        self.selections={key:value['active'] for key,value in self.store.data['characters'].items()}
        self.books={}; self.plans={}

    def active(self,char): return self.selections.get(char,'General')

    def available(self,char,character_class):
        custom=self.store.data['characters'].get(char,{}).get('available')
        return ('General',*(custom if custom is not None else CLASS_PLAYSTYLES.get(character_class,PRESETS[1:])))

    def saved_preset(self,char,name=None):
        return deepcopy(self.store.data['characters'].get(char,{}).get('presets',{}).get(name or self.active(char),blank_preset()))

    def book(self,char,name=None):
        key=(char,name or self.active(char))
        if key not in self.books: self.books[key]=GearWishlist.from_dict(self.saved_preset(*key)['gear'])
        return self.books[key]

    def plan(self,char):
        key=(char,self.active(char))
        if key not in self.plans: self.plans[key]=self.saved_preset(*key)['plan']
        return self.plans[key]

    def patch(self,char,section,value):
        text(char,'Character ID')
        payload=deepcopy(self.store.data)
        record=payload['characters'].setdefault(char,{'active':self.active(char),'presets':{}})
        if section in ('active','available'): record[section]=value
        else:
            name=self.active(char)
            preset=record['presets'].setdefault(name,blank_preset())
            preset[section]=deepcopy(value)
        # LocalStore validates; write_json enforces its matching 5 MB read/write
        # bound before touching any file and keeps the preceding save.
        self.store.save(payload)

    def select(self,char,name,persist=True):
        if name not in PRESETS: raise ValueError('Choose a playstyle from the list.')
        if persist: self.patch(char,'active',name)
        self.selections[char]=name

    def save_gear(self,char): self.patch(char,'gear',self.book(char).to_dict())
    def save_plan(self,char): self.patch(char,'plan',self.plan(char))


class PresetFilters:
    def __init__(self,presets,char): self.presets,self.char=presets,char
    def get(self,char): return GearFilters.from_dict(self.presets.saved_preset(char)['filters'])
    def save(self,char,filters):
        filters.validate(); self.presets.patch(char,'filters',asdict(filters))


class PresetUndo:
    def __init__(self,presets,char): self.presets,self.char=presets,char
    @property
    def records(self):
        value=self.presets.saved_preset(self.char)['undo']
        return {self.char:RemovedGoal.from_dict(value)} if value else {}
    def save(self,records):
        value=records.get(self.char)
        if value: value.validate()
        self.presets.patch(self.char,'undo',asdict(value) if value else None)
