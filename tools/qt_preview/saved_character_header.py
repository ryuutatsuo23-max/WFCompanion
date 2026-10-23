"""Read-only header metadata from the inspected DataStore Characters layout.

BaseInfo bits 0..6 hold level, 7..10 class ID (installed 2026.10.14
DataStore_Characters ScanBaseInfo/GetCharacterLevel/GetCharacterClass).
Never writes manual profile values or treats a file timestamp as character age.
"""
from pathlib import Path
from datetime import datetime
from character_links import LinkStore,identity,key
from profession_observations import globals_from,MAPPING,character_labels,fingerprint,integer,table,GUID

CLASSES={1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',
         7:'Shaman',8:'Mage',9:'Warlock',10:'Monk',11:'Druid',12:'Demon Hunter',13:'Evoker'}
GLOBALS={'DataStore_Characters_Info','DataStore_Characters_GuildRanks','DataStore_Characters_Options'}


def decode_character(raw,mapping_raw,linked):
    mapping=globals_from(mapping_raw,MAPPING);labels=character_labels(mapping)
    guids=table(mapping.get('DataStore_CharacterGUIDs',{}),1000)
    for index,guid in guids.items():
        integer(index,1,1000000)
        if not isinstance(guid,str) or not GUID.fullmatch(guid):raise ValueError('Invalid character GUID mapping.')
    if len(set(guids.values()))!=len(guids):raise ValueError('Ambiguous character GUID mapping.')
    matches=[index for index,guid in guids.items() if guid==linked['guid']]
    if len(matches)!=1:raise ValueError('No matching saved character details.')
    index=matches[0];expected={'name':linked['name'],'realm':linked['realm']}
    if labels.get(index)!=expected:raise ValueError('Saved character name or realm differs from its link.')
    info=table(globals_from(raw,GLOBALS).get('DataStore_Characters_Info',{}),1000)
    record=table(info.get(index,{}))
    if record.get('name')!=linked['name']:raise ValueError('Character details disagree with the GUID mapping.')
    packed=record.get('BaseInfo');integer(packed,0,2**32-1)
    level=packed&127;character_class=CLASSES.get((packed>>7)&15,'Unknown class')
    stamp=record.get('lastUpdate')
    if stamp is not None:integer(stamp,1,9999999999)
    return character_class,level or None,stamp


class HeaderObservations:
    def __init__(self):self.cache={}

    def describe(self,directory,profile):
        try:
            linked=next((e['identity'] for e in LinkStore(directory).records['links'] if e['profile']==profile),None)
            if linked is None:return 'No saved character details','Manual character; no saved-game link.'
            source=Path(linked['source']);paths=[source,source.with_name('DataStore.lua'),source.with_name('DataStore_Characters.lua')]
            signature=(key(linked),linked['name'],tuple((p.stat().st_size,p.stat().st_mtime_ns) for p in paths))
            previous=self.cache.get(profile)
            if previous and previous[0]==signature:return previous[1]
            try:
                current=identity(source,linked['guid'],linked['environment'])
                if key(current)!=key(linked) or current['name']!=linked['name']:raise ValueError('Core identity differs from the saved link.')
                mapping=fingerprint(paths[1]);info=fingerprint(paths[2])
                values=decode_character(info[0],mapping[0],linked)
                after=tuple((p.stat().st_size,p.stat().st_mtime_ns) for p in paths)
                if after!=signature[2]:raise ValueError('Character save changed during reading.')
                character_class,level,stamp=values
                saved=datetime.fromtimestamp(stamp).strftime('%d %b %Y, %H:%M') if stamp else 'Unknown time'
                result=(f'{character_class} · Level {level if level is not None else "Unknown"} · Saved {saved}',
                        'Saved character details from DataStore. Inventory may have a different saved time. This is not live character identity.')
                self.cache[profile]=(signature,result)
                return result
            except (ValueError,OSError,OverflowError) as exc:
                # Failed reads are retried; a partially written save is temporary.
                return 'Unknown class · Level Unknown · Saved time unavailable',str(exc)
        except (ValueError,OSError) as exc:
            return 'Unknown class · Level Unknown · Saved time unavailable',str(exc)
