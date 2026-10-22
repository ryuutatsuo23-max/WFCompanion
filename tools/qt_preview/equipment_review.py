"""Historical equipped slots, deliberately separate from inventory ownership totals."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import json
import re
from datastore_bags import assignments,LIMIT,MAX_GAP_SECONDS
from storage import write_json

SLOTS=('Ammo','Head','Neck','Shoulders','Shirt','Chest','Waist','Legs','Feet','Wrists',
       'Hands','Finger 1','Finger 2','Trinket 1','Trinket 2','Back','Main hand','Off hand','Ranged','Tabard')


def observed(c,directory):
    """Only identified, matching occupied slots are eligible; nil never means unequip."""
    if c.scope!='Equipment' or not c.owner_key:raise ValueError('Choose equipment with a known character GUID.')
    paths=[Path(directory)/name for name in ('DataStore.lua','DataStore_Inventory.lua')]
    sources=[];tables=[]
    for path in paths:
        with path.open('rb') as stream:raw=stream.read(LIMIT+1)
        sources.append((path,raw));tables.append(assignments(raw))
    try:
        core,ds=tables
        ids=[i for i,guid in core['DataStore_CharacterGUIDs'].items() if guid==c.owner_key]
        if len(ids)!=1:raise ValueError('Equipment GUID must match exactly one DataStore character.')
        record=ds['DataStore_Inventory_Characters'][ids[0]]
        epoch=record['lastUpdate']
        if type(epoch)!=int or not 0<epoch<4102444800:raise ValueError('Invalid equipment timestamp.')
        local=datetime.fromtimestamp(epoch);probe=datetime.strptime(c.at,'%Y-%m-%d %H:%M:%S')
        gap=abs((local-probe).total_seconds())
        if gap>MAX_GAP_SECONDS:raise ValueError('Equipment timestamps are over 120 seconds apart.')
        inventory=record['Inventory']
        rows={};seen=set()
        for line in c.bag_text.splitlines():
            if not re.match(r'^E\d',line):continue
            m=re.fullmatch(r'E(\d+) id=(.*?) qty=(.*)',line)
            if not m:raise ValueError('Malformed equipment slot.')
            slot=int(m[1])
            if slot not in range(20) or slot in seen:raise ValueError('Invalid or duplicate equipment slot.')
            seen.add(slot)
            if not m[2].isdigit() or not m[3].isdigit():continue
            item,quantity=int(m[2]),int(m[3])
            if not 0<item<=2147483647 or not 0<quantity<=2147483647:continue
            link=inventory.get(slot)
            if not isinstance(link,str):continue
            match=re.search(r'\|Hitem:(\d+):.*?\|h\[([^|\r\n]+)\]\|h',link)
            if not match or int(match[1])!=item:continue
            rows[str(slot)]={'item_id':item,'name':match[2],'quantity':quantity,'link':link,
                             'captured_at':c.at,'datastore_at':epoch,'source':'Reviewed probe + DataStore'}
        if not seen:raise ValueError('No equipment slots captured.')
    except (KeyError,TypeError,AttributeError,OverflowError) as exc:
        raise ValueError('Unsupported DataStore equipment data.') from exc
    summary=(f'Source: {c.owner_label}\nClass: {c.character_class} · GUID: {c.owner_key}\n'
             f'Probe: {c.at} (client local)\nDataStore: {local:%Y-%m-%d %H:%M:%S} (computer local), '
             f'{datetime.fromtimestamp(epoch,timezone.utc).isoformat()}\nGap: {gap:g} seconds. '
             'Local timestamps assume this computer timezone. Separate historical observations, not a simultaneous scan.\n'
             f'{len(rows)} matching occupied slots. Unknown or mismatched slots are kept unchanged, never cleared.')
    return rows,summary,sources


class EquipmentStore:
    def __init__(self,directory):
        self.path=Path(directory).resolve()/'equipment.json'

    def load(self):
        raw=self.path.read_bytes() if self.path.exists() else None
        if raw is None:return {'version':1,'characters':{}},raw
        if len(raw)>5_000_000:raise ValueError('Equipment file too large.')
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('characters'),dict):
            raise ValueError('Unsupported saved equipment; original preserved.')
        for key,record in data['characters'].items():
            if not isinstance(key,str) or not isinstance(record,dict) or not isinstance(record.get('guid'),str) or not isinstance(record.get('slots'),dict):
                raise ValueError('Invalid saved equipment identity.')
            for slot,row in record['slots'].items():
                if slot not in tuple(map(str,range(20))) or not isinstance(row,dict) or not isinstance(row.get('name'),str) or type(row.get('item_id'))!=int or type(row.get('quantity'))!=int:
                    raise ValueError('Invalid saved equipment slot.')
        return data,raw


def prepare(data,c,destination,directory):
    profile_raw=data.profile_store.path.read_bytes() if data.profile_store.path.exists() else None
    if profile_raw!=data.profile_bytes:raise ValueError('Saved character profiles changed; reopen the review.')
    p=next((p for p in data.profiles if p.id==destination),None)
    if p is None or p not in data.saved_profiles or p.character_class!=c.character_class:
        raise ValueError('Choose a saved destination with the captured class.')
    if p.id.startswith('capture-') and p.id!='capture-'+c.owner_key:
        raise ValueError('Destination is linked to a different character GUID.')
    rows,summary,sources=observed(c,directory)
    store=EquipmentStore(data.directory);saved,raw=store.load()
    current=saved['characters'].get(destination,{'guid':c.owner_key,'slots':{}})
    if current['guid']!=c.owner_key:raise ValueError('Saved equipment belongs to a different GUID.')
    # Same item/count needs no rewrite just because another snapshot has a newer time.
    proposals={slot:row for slot,row in rows.items() if any(current['slots'].get(slot,{}).get(k)!=row[k] for k in ('item_id','quantity','link'))}
    return proposals,current['slots'],summary,sources,raw


def apply_reviewed(data,c,destination,directory,selected,expected_raw,expected_sources):
    for path,raw in expected_sources:
        if path.read_bytes()!=raw:raise ValueError('Equipment evidence changed; review again.')
    proposals,_,_,_,raw=prepare(data,c,destination,directory)
    if raw!=expected_raw or not selected or any(proposals.get(slot)!=row for slot,row in selected.items()):
        raise ValueError('Equipment changes are stale or no longer eligible; review again.')
    store=EquipmentStore(data.directory);saved,raw_again=store.load()
    if raw_again!=raw:raise ValueError('Equipment changed outside this review.')
    candidate=deepcopy(saved)
    record=candidate['characters'].setdefault(destination,{'guid':c.owner_key,'slots':{}})
    record['slots'].update(deepcopy(selected))
    for path,content in expected_sources:
        if path.read_bytes()!=content:raise ValueError('Equipment evidence changed before saving.')
    write_json(store.path,candidate)
