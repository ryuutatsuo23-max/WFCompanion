"""Offline probe capture review. No writes, Lua execution or automatic identity mapping."""
from dataclasses import dataclass
from collections import defaultdict
import re
from probe_report import LuaData, array, decode, owner


@dataclass(frozen=True)
class Capture:
    owner_key: str
    owner_label: str
    at: str
    scope: str
    coverage: str
    rows: tuple
    unknown_slots: int
    build: str = 'Unknown'
    character_class: str = 'Unknown'
    bag_totals_verified: bool = False
    bag_text: str = ''


def verified_bags(text):
    declared=re.search(r'^Bag range: client-declared 0\.\.(\d+)$',text,re.M)
    if not declared or int(declared[1])>10:return False
    headers=re.findall(r'^Bag (-?\d+) slots: (.*)$',text,re.M)
    sizes={int(b):int(n) for b,n in headers if n.isdigit() and int(n)<=200}
    if len(sizes)!=len(headers) or not set(range(int(declared[1])+1))<=sizes.keys():return False
    expected={(b,s) for b,n in sizes.items() for s in range(1,n+1)}
    lines=[l for l in text.splitlines() if re.match(r'^B-?\d+/',l)]
    matches=[re.fullmatch(r'B(-?\d+)/(\d+) id=(\d+) qty=(\d+)',l) for l in lines]
    if any(m is None for m in matches):return False
    return {(int(m[1]),int(m[2])) for m in matches}==expected and len(matches)==len(expected)


def slots(text, pattern):
    totals=defaultdict(int); unknown=0; seen=set()
    for line in text.splitlines():
        match=re.fullmatch(pattern,line)
        if not match: continue
        slot,item,quantity=match.groups()
        if slot in seen: raise ValueError('Duplicate slot in capture; review stopped.')
        seen.add(slot)
        if item.isdigit() and quantity.isdigit() and 0<int(item)<=2147483647 and 0<=int(quantity)<=2147483647:
            totals[int(item)]+=int(quantity)
        else: unknown+=1
    return tuple(sorted(totals.items())),unknown


def captures(data):
    decode(data)  # Existing size, schema, snapshot and literal-only safety checks.
    db=LuaData(data.decode('utf-8-sig')).decode(); result=[]
    classes={'1':'Warrior','2':'Paladin','3':'Hunter','4':'Rogue','5':'Priest','7':'Shaman','8':'Mage','9':'Warlock','11':'Druid'}
    for session in array(db['sessions'],30):
        key,name=owner(session)
        session_classes=set();session_builds=set()
        for snapshot in array(session['snapshots'],60):
            report=snapshot['report']
            class_match=re.search(r'^Player class ID: OK = (\d+)$',report,re.M)
            build_match=re.search(r'^Build: OK = (\d+)$',report,re.M)
            if class_match:session_classes.add(classes.get(class_match[1],'Unknown'))
            if build_match:session_builds.add(build_match[1])
            marker='[Full carried inventory and equipment - revision 1]\n'
            if marker not in report: continue
            text=report.split(marker,1)[1].split('\n[',1)[0]
            build=re.search(r'^Build: OK = (\d+)$',report,re.M)
            cls=re.search(r'^Player class ID: OK = (\d+)$',report,re.M)
            coverage=next((l for l in text.splitlines() if l.startswith('Scan coverage:')),'Coverage unknown')
            for scope,pattern in [('Bags',r'B(-?\d+/\d+) id=(.*?) qty=(.*)'),('Equipment',r'E(\d+) id=(.*?) qty=(.*)')]:
                rows,unknown=slots(text,pattern)
                result.append(Capture(key,name,snapshot.get('at','Unknown'),scope,coverage,rows,unknown,
                                      build[1] if build else 'Unknown',classes.get(cls[1],'Unknown') if cls else 'Unknown',
                                      scope=='Bags' and verified_bags(text),text))
        for bank in array(session.get('bankSets',{}),10):
            pages=array(bank['pages'],40)
            if any(not isinstance(p,str) or len(p)>24000 for p in pages): raise ValueError('Invalid bank page.')
            header=bank.get('header','');at=re.search(r'Capture time \(client local\): ([^\n]+)',header)
            rows,unknown=slots('\n'.join(pages),r'Bank (-?\d+/\d+) id=(.*?) qty=(.*)')
            result.append(Capture(key,name,at[1] if at else 'Unknown','Bank',bank.get('coverage','Unknown'),rows,unknown,
                                  next(iter(session_builds)) if len(session_builds)==1 else 'Unknown',
                                  next(iter(session_classes)) if len(session_classes)==1 else 'Unknown',
                                  False,'\n'.join(pages)))
    return result


def proposals(capture, entries):
    """Observed sums are never silently promoted to replacement ownership totals."""
    rows=[];matched=set()
    for item_id,count in capture.rows:
        candidates=[e for e in entries if e.location==capture.scope and e.catalogue_ref and e.catalogue_ref.item_id==item_id]
        matched.update(e.id for e in candidates)
        name=candidates[0].name if len(candidates)==1 else f'Item {item_id}'
        current=' / '.join('Unknown' if e.quantity is None else str(e.quantity) for e in candidates) or 'No linked record'
        reason='Confirm destination identity, item variant and capture freshness before any import.'
        action='Review addition' if not candidates else 'Review count change'
        if capture.scope=='Equipment':
            action='Equipment reference only';reason='Equipment is not a bags/bank total or wishlist ownership update.'
        elif not capture.owner_key:
            action='Blocked · unknown owner';reason='Historical capture has no confirmed character identity.'
        elif len(candidates)>1:
            action='Blocked · ambiguous match';reason='Multiple local records share this ID and location.'
        elif capture.unknown_slots or 'Partial' in capture.coverage or 'Unknown'==capture.coverage:
            action='Review observed subtotal';reason='Unresolved slots or partial coverage: keep stored totals unchanged.'
        elif candidates and (candidates[0].catalogue_ref.branch!='forever' or candidates[0].catalogue_ref.variant!='base'):
            action='Blocked · variant/branch';reason='A base item ID does not establish variant compatibility.'
        elif candidates and candidates[0].quantity==count: action='No count difference'
        rows.append((str(item_id),name,current,str(count),action,reason))
    if capture.scope!='Equipment':
        for e in entries:
            if e.location==capture.scope and e.id not in matched:
                rows.append((str(e.catalogue_ref.item_id) if e.catalogue_ref else 'Unknown',e.name,
                             str(e.quantity) if e.quantity is not None else 'Unknown','Not observed','Keep local',
                             'Absence is not zero. Unlinked names are not automatically matched.'))
    return rows
