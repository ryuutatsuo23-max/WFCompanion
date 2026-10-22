"""Read-only corroboration of probe bags/bank against this DataStore packed format.

Independent historical observations, not an atomic scan. No missing-slot-to-zero
inference is allowed without matching GUID, occupied slots and free-slot accounting.
"""
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
import re
from probe_report import LuaData

LIMIT=2_000_000
MAX_GAP_SECONDS=120
COVERAGE='Scan coverage: All declared bag slots and equipment slots attempted; Unknown rows remain unresolved'
BANK_COVERAGE='All slots in declared containers attempted; Unknown rows remain unresolved'


def assignments(raw):
    if len(raw)>LIMIT:raise ValueError('DataStore file exceeds review limit.')
    p=LuaData(raw.decode('utf-8-sig'));result={}
    while True:
        p.skip()
        if p.pos==len(p.text):return result
        m=re.match(r'[A-Za-z_][A-Za-z_0-9]*',p.text[p.pos:])
        if not m:raise ValueError('Unsupported DataStore syntax.')
        key=m[0];p.pos+=len(key);p.require('=')
        if key in result:raise ValueError('Duplicate DataStore assignment.')
        result[key]=p.value();p.take(';')


def integer(value,maximum):
    if type(value)!=int or not 0<=value<=maximum:raise ValueError('Invalid DataStore number.')
    return value


@dataclass(frozen=True)
class Evidence:
    capture: object
    files: tuple
    summary: str
    item_names: tuple = ()

    def verify(self,capture):
        if capture!=self.capture:raise ValueError('DataStore evidence belongs to another capture.')
        for path,raw in self.files:
            if Path(path).read_bytes()!=raw:raise ValueError('DataStore changed after review. Reload the report before importing.')
        return True


def review(capture,directory):
    try:return _review(capture,Path(directory).resolve())
    except (KeyError,TypeError,AttributeError,OverflowError,UnicodeError) as exc:
        raise ValueError('Unsupported or incomplete DataStore container records.') from exc


def _review(c,directory):
    bank=c.scope=='Bank'
    if c.scope not in ('Bags','Bank') or not c.owner_key or c.coverage!=(BANK_COVERAGE if bank else COVERAGE):
        raise ValueError('DataStore assistance requires an identified, fully attempted bags/bank capture.')
    files=[];tables=[]
    for name in ('DataStore.lua','DataStore_Containers.lua'):
        path=directory/name
        with path.open('rb') as stream:raw=stream.read(LIMIT+1)
        files.append((str(path),raw));tables.append(assignments(raw))
    core,containers=tables
    ids=[i for i,g in core['DataStore_CharacterGUIDs'].items() if g==c.owner_key]
    if len(ids)!=1:raise ValueError('DataStore must contain exactly one matching character GUID.')
    key=ids[0];character=containers['DataStore_Containers_Characters'][key]
    stamp=integer(character['lastUpdate'],4102444800)
    ds_time=datetime.fromtimestamp(stamp)
    probe_time=datetime.strptime(c.at,'%Y-%m-%d %H:%M:%S')
    gap=abs((ds_time-probe_time).total_seconds())
    if gap>MAX_GAP_SECONDS:raise ValueError('DataStore and probe timestamps are more than 120 seconds apart; assistance blocked.')
    declared=re.search(r'^Bag range: client-declared 0\.\.(\d+)$',c.bag_text,re.M)
    if not bank and (not declared or int(declared[1])>10):raise ValueError('Missing declared bag range.')
    headers=re.findall(r'^Container (-?\d+) slots=(.*)$' if bank else r'^Bag (-?\d+) slots: (.*)$',c.bag_text,re.M)
    sizes={int(b):integer(int(n),127) for b,n in headers if n.isdigit()}
    if bank:
        tabs=re.findall(r'^Character bank tab (\d+) container=(-?\d+)$',c.bag_text,re.M)
        if len(tabs)!=9 or {int(i) for i,b in tabs}!=set(range(1,10)):
            raise ValueError('Incomplete bank container declarations.')
        required={int(b) for i,b in tabs}
        if len(required)!=9:raise ValueError('Duplicate bank container declarations.')
        main=re.search(r'^Main bank constant container=(-?\d+)$',c.bag_text,re.M)
        if main:required.add(int(main[1]))
    else:required=set(range(int(declared[1])+1))
    if len(sizes)!=len(headers) or set(sizes)!=required:
        raise ValueError('Incomplete or unsupported bag coverage (including keyring).')
    expected={(b,s) for b,n in sizes.items() for s in range(1,n+1)}
    known={};unknown=set();seen=set()
    for line in c.bag_text.splitlines():
        if not re.match(r'^Bank -?\d+/' if bank else r'^B-?\d+/',line):continue
        m=re.fullmatch(r'Bank (-?\d+)/(\d+) id=(.*?) qty=(.*)' if bank else r'B(-?\d+)/(\d+) id=(.*?) qty=(.*)',line)
        if not m:raise ValueError('Malformed probe slot.')
        slot=(int(m[1]),int(m[2]))
        if slot in seen:raise ValueError('Duplicate probe slot.')
        seen.add(slot)
        if m[3].isdigit() and m[4].isdigit():known[slot]=(int(m[3]),int(m[4]))
        elif m[3]=='Unknown (nil)' and m[4]==('Unknown (item unidentified)' if bank else 'Unknown (nil)'):unknown.add(slot)
        else:raise ValueError('Probe slot has an access failure, not an unresolved nil slot.')
    if seen!=expected:raise ValueError('Probe is missing declared slots.')
    saved={};missing=set();details=[];total_free=0;names={}
    for bag,size in sizes.items():
        record=character['Containers'].get(bag)
        if size==0 and record is None:continue
        info=integer(record['info'],2**53-1)
        ds_size=(info>>3)&127;free=(info>>10)&127
        if ds_size!=size or free>size:raise ValueError('Bag sizes disagree.')
        occupied={}
        for slot,value in record['items'].items():
            if value is None:continue
            integer(slot,size)
            if slot==0:raise ValueError('Invalid DataStore slot zero.')
            packed=integer(value,2**53-1);item,quantity=packed>>16,packed&65535
            link=record['links'].get(slot,'')
            if not item or not quantity or not re.search(r'\|Hitem:'+str(item)+r':',link):
                raise ValueError('Item link, ID or quantity is inconsistent.')
            occupied[slot]=(item,quantity)
            name=re.search(r'\|h\[([^\r\n|]+)\]\|h',link)
            if name:names.setdefault(item,set()).add(name[1])
        if len(occupied)+free!=size:raise ValueError('Free slots do not account for every missing record.')
        saved.update({(bag,s):v for s,v in occupied.items()})
        missing.update((bag,s) for s in range(1,size+1) if s not in occupied)
        total_free+=free
        details.append(f'{"Bank container" if bank else "Bag"} {bag}: {size} slots = {len(occupied)} occupied + {free} free')
    aggregate=integer(character['bankInfo' if bank else 'bagInfo'],2**31-1)
    aggregate_note=''
    if (aggregate&1023,(aggregate>>10)&1023)!=(sum(sizes.values()),total_free):
        # Observed Forever build 70532 declares tabs 6..14 and no BANK_CONTAINER.
        # This DataStore version adds a hardcoded 98-slot legacy bank to bankInfo;
        # its free aggregate can also lag the per-container scan. Never use that
        # aggregate to resolve slots. Require the exact observed client layout,
        # empty legacy storage, and all of the per-slot checks below instead.
        forever_tabs=(bank and c.build=='70532' and set(sizes)==set(range(6,15))
                      and 'Main bank constant: Unknown (nil)' in c.bag_text.splitlines()
                      and all(int(b)==int(i)+5 for i,b in tabs)
                      and (aggregate&1023)==sum(sizes.values())+98)
        if not forever_tabs:raise ValueError('DataStore aggregate container counts disagree.')
        legacy=character['Containers'].get(-1)
        if not isinstance(legacy,dict):raise ValueError('Legacy bank evidence is missing.')
        info=integer(legacy['info'],2**53-1)
        if ((info>>3)&127)!=((info>>10)&127) or legacy.get('items')!={} or legacy.get('links')!={}:
            raise ValueError('Legacy bank has unresolved or occupied storage outside declared tabs.')
        aggregate_note=(f'DataStore aggregate excluded: {aggregate&1023} slots / {(aggregate>>10)&1023} free. '
                        f'Forever build 70532 declares {sum(sizes.values())} slots / {total_free} corroborated free; '
                        'the aggregate includes 98 legacy slots and may have a stale free count. '
                        'Legacy container -1 has no items. Only declared character tabs are imported.\n')
    if saved!=known or missing!=unknown:raise ValueError('Occupied slots, item quantities or unresolved slots disagree.')
    totals={}
    for item,quantity in saved.values():totals[item]=totals.get(item,0)+quantity
    if tuple(sorted(totals.items()))!=c.rows or len(unknown)!=c.unknown_slots:
        raise ValueError('Probe totals disagree with its slot evidence.')
    summary=(f'DataStore-assisted historical {c.scope.lower()} review: GUID matches {c.owner_key}\n'
             f'Probe: {c.at} (client local)\nDataStore: {ds_time:%Y-%m-%d %H:%M:%S} (computer local); '
             f'{datetime.fromtimestamp(stamp,timezone.utc).isoformat()}\n'
             f'Timestamp gap: {gap:g} seconds (maximum 120; assumes the client used this computer timezone).\n'
             f'All {len(known)} occupied slots match by item ID and quantity; {len(unknown)} unresolved slots '
             f'are accounted for by DataStore free-slot counts.\n'+'\n'.join(details)+'\n'
             +aggregate_note+'Separate observations, not a simultaneous scan. DataStore has one character-wide update time, '
             'not a timestamp for each bag or bank visit. Slot agreement does not establish live freshness. '
             'Original probe unknowns remain unchanged.')
    return Evidence(c,tuple(files),summary,tuple(sorted((item,next(iter(values))) for item,values in names.items() if len(values)==1)))
