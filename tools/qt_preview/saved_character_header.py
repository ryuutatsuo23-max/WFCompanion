"""Read-only GUID-linked Core schema-1 details; no DataStore or manual fallback.

observedAt describes the saved observation attempt, not disk or inventory time.
Missing, unsupported or invalid fields remain Unknown, including after refresh.
"""
from pathlib import Path
from datetime import datetime
import re
from character_links import LinkStore,key
from core_observations import CoreData

CLASSES={1:('WARRIOR','Warrior'),2:('PALADIN','Paladin'),3:('HUNTER','Hunter'),
         4:('ROGUE','Rogue'),5:('PRIEST','Priest'),6:('DEATHKNIGHT','Death Knight'),
         7:('SHAMAN','Shaman'),8:('MAGE','Mage'),9:('WARLOCK','Warlock'),
         10:('MONK','Monk'),11:('DRUID','Druid'),12:('DEMONHUNTER','Demon Hunter'),13:('EVOKER','Evoker')}
FIELDS=('classID','classToken','className','level','observedAt')
UNKNOWN=('Unknown class',None,None)


def decode_details(details):
    if not isinstance(details,dict) or type(details.get('schema')) is not int or details['schema']!=1:return UNKNOWN
    status=details.get('status')
    if not isinstance(status,dict) or any(status.get(k) not in ('ok','unknown') for k in FIELDS):return UNKNOWN
    def number(field,high):
        value=details.get(field)
        return value if status[field]=='ok' and type(value) is int and 1<=value<=high else None
    def text(field,pattern=None):
        value=details.get(field)
        if status[field]!='ok' or not isinstance(value,str) or not value.strip():return None
        if len(value.encode('utf-8'))>160 or any(ord(c)<32 or ord(c)==127 or c=='|' for c in value):return None
        return value if pattern is None or re.fullmatch(pattern,value) else None
    class_id=number('classID',255);token=text('classToken',r'[A-Z]+');name=text('className')
    known=CLASSES.get(class_id)
    if known and token and token!=known[0]:character_class='Unknown class'
    else:character_class=name or next((v[1] for v in CLASSES.values() if v[0]==token),None) or (known[1] if known else 'Unknown class')
    return character_class,number('level',1000),number('observedAt',9007199254740991)


def decode_character(raw,linked):
    # Header details are independent of inventory snapshot validity.
    if not raw or len(raw)>64*1024*1024:raise ValueError('Core save is empty or exceeds 64 MiB.')
    db=CoreData(raw.decode('utf-8-sig'),max_nodes=4_000_000).decode()
    if not isinstance(db,dict) or type(db.get('schema')) is not int or db['schema']!=1 or db.get('producer')!='WFCore':
        raise ValueError('Unsupported core schema or producer.')
    characters=db.get('characters')
    if not isinstance(characters,dict) or len(characters)>50:raise ValueError('Invalid character collection.')
    guid=linked.get('guid')
    if not isinstance(guid,str) or len(guid)>160 or not re.fullmatch(r'Player-\d+-[0-9A-Fa-f]+',guid):
        raise ValueError('Invalid linked GUID.')
    character=characters.get(guid)
    if not isinstance(character,dict):raise ValueError('Linked GUID is absent or invalid in the Core save.')
    ident=character.get('identity');client=character.get('client')
    if not isinstance(ident,dict) or ident.get('guid')!=guid:raise ValueError('Mismatched character identity.')
    if not isinstance(client,dict) or client.get('version')!='1.60.1' or type(client.get('interface')) is not int or client['interface']!=16001:
        raise ValueError('Unsupported observation client.')
    for field in ('firstName','lastName','realm'):
        if field in ident and (not isinstance(ident[field],str) or len(ident[field])>160):raise ValueError('Invalid identity label.')
    name=' '.join(ident.get(k,'') for k in ('firstName','lastName')).strip() or linked['guid']
    if (ident.get('realm'),name,client.get('version'),client.get('interface'))!=(linked['realm'],linked['name'],linked['version'],linked['interface']):
        raise ValueError('Core identity differs from the saved character link.')
    return decode_details(character.get('details'))


class HeaderObservations:
    def __init__(self):self.cache={}

    def describe(self,directory,profile):
        try:
            linked=next((e['identity'] for e in LinkStore(directory).records['links'] if e['profile']==profile),None)
            if linked is None:return 'No saved character details','Manual character; no saved-game link.'
            source=Path(linked['source']);before=source.stat()
            signature=(key(linked),linked['name'],before.st_size,before.st_mtime_ns)
            previous=self.cache.get(profile)
            if previous and previous[0]==signature:return previous[1]
            if before.st_size>64*1024*1024:raise ValueError('Core save exceeds 64 MiB.')
            with source.open('rb') as stream:raw=stream.read(64*1024*1024+1)
            character_class,level,stamp=decode_character(raw,linked)
            after=source.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or len(raw)!=after.st_size:
                raise ValueError('Core save changed during reading; waiting for a stable save.')
            try:saved=datetime.fromtimestamp(stamp).strftime('%d %b %Y, %H:%M') if stamp is not None else None
            except (ValueError,OSError,OverflowError):saved=None
            freshness='Saved observation '+saved if saved else 'Observation time Unknown'
            result=(f'{character_class} · Level {level if level is not None else "Unknown"} · {freshness}',
                    'Latest saved Forever Core character observation. Missing or unsupported details remain Unknown. Observation time is not inventory freshness, disk-save time or live identity.')
            self.cache[profile]=(signature,result)
            return result
        except (ValueError,OSError,OverflowError) as exc:
            return 'Unknown class · Level Unknown · Observation time Unknown',str(exc)
