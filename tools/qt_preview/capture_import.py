"""Explicitly reviewed existing bag totals only; no identity inference or draft saves."""
from copy import deepcopy
from datetime import datetime,timezone
from inventory import InventoryStore,InventoryBook,InventoryEntry
from catalogue import CatalogueRef
from model import default_profile


def character_proposal(data,capture,evidence):
    if capture.scope!='Bags':raise ValueError('Use an identified bag capture to create a character first.')
    if evidence is None:raise ValueError('Matching DataStore evidence is required for character creation.')
    evidence.verify(capture)
    p=default_profile();p.id='capture-'+capture.owner_key;p.name=capture.owner_label.split(' · ')[0]
    p.character_class=capture.character_class;p.validate()
    if any(x.id==p.id or x.name.casefold()==p.name.casefold() for x in data.profiles):
        raise ValueError('A matching character already exists. Choose it as the destination; no duplicate created.')
    if data.profiles!=data.saved_profiles or 'Profiles & Rules' in data.dirty:
        raise ValueError('Save applied profile changes first. Unfinished fields are preserved.')
    if data.profile_store.error:raise ValueError(data.profile_store.error)
    return p


def create_reviewed_character(data,capture,evidence,reviewed):
    p=character_proposal(data,capture,evidence)
    if p!=reviewed:raise ValueError('Character proposal changed; review again.')
    current=data.profile_store.path.read_bytes() if data.profile_store.path.exists() else None
    if current!=data.profile_bytes:raise ValueError('Profiles changed outside the companion; no character created.')
    candidate=[*data.profiles,p]
    data.profile_store.save(candidate,data.active)
    data.profiles=candidate;data.saved_profiles=deepcopy(candidate)
    data.profile_bytes=data.profile_store.path.read_bytes()
    return p.id


def new_reference(capture,item,name):
    ref=CatalogueRef(item,name,None,'local-capture:WFStressProbe+DataStore',capture.at[:10],
                     'reviewed-capture-v1',client_build=capture.build)
    ref.validate();return ref


def changes(capture, entries, evidence=None):
    if capture.scope not in ('Bags','Bank'):return {}
    assisted=evidence is not None and evidence.verify(capture)
    if not assisted and (capture.scope!='Bags' or not capture.owner_key or capture.unknown_slots
            or not capture.bag_totals_verified
            or capture.coverage!='Scan coverage: All declared bag slots and equipment slots attempted; Unknown rows remain unresolved'):return {}
    result={}
    for item_id,quantity in capture.rows:
        matches=[e for e in entries if e.location==capture.scope and e.catalogue_ref and e.catalogue_ref.item_id==item_id]
        if not matches and assisted:
            name=dict(evidence.item_names).get(item_id)
            if name and not any(e.location==capture.scope and e.name.casefold()==name.casefold() for e in entries):
                new_reference(capture,item_id,name)
                result[f'add:{"bank:" if capture.scope=="Bank" else ""}{item_id}']=(name,None,quantity,item_id)
            continue
        if len(matches)!=1:continue
        e=matches[0]
        if e.catalogue_ref.branch=='forever' and e.catalogue_ref.variant=='base' and e.quantity!=quantity:
            result[e.id]=(e.name,e.quantity,quantity,item_id)
    return result


def prepare(data, capture, destination, selected, evidence=None):
    if data.inventory_store.error:raise ValueError(data.inventory_store.error)
    profile=next((p for p in data.profiles if p.id==destination),None)
    if profile is None or profile not in data.saved_profiles:
        raise ValueError('Save the destination character profile before importing.')
    if capture.character_class=='Unknown' or profile.character_class!=capture.character_class:
        raise ValueError('The captured and destination classes must match.')
    if destination.startswith('capture-') and destination!='capture-'+capture.owner_key:
        raise ValueError('Captured GUID does not match the destination character.')
    current=data.profile_store.path.read_bytes() if data.profile_store.path.exists() else None
    if current!=data.profile_bytes:raise ValueError('Profiles changed outside the companion. Reopen before importing.')
    if 'Inventory & Bank' in data.dirty:
        raise ValueError('Save applied Inventory & Bank changes before importing. Unfinished fields are preserved.')
    store=InventoryStore(data.directory);saved=store.load()
    if store.error:raise ValueError(store.error)
    # Do not save any unrelated in-memory entries, even if a dirty flag was missed.
    nonempty=lambda books:{k:v for k,v in books.items() if v.entries}
    if nonempty(saved)!=nonempty(data.inventories):
        raise ValueError('Inventory changed since loading. Reopen the review after resolving unsaved or external changes.')
    book=saved.get(destination)
    available=changes(capture,book.entries if book else [],evidence)
    if not selected or not set(selected)<=available.keys():
        raise ValueError('Select eligible reviewed bags/bank changes. Unknown owners, uncorroborated subtotals and equipment cannot be imported.')
    return store,saved,{key:available[key] for key in selected}


def apply_reviewed(data,capture,destination,reviewed,evidence=None):
    store,saved,current=prepare(data,capture,destination,tuple(reviewed),evidence)
    if current!=reviewed:raise ValueError('Counts changed after confirmation. Review them again.')
    candidate=deepcopy(saved)
    candidate.setdefault(destination,InventoryBook())
    existing_ids={e.id for e in candidate[destination].entries}
    for key,(name,old,quantity,item) in current.items():
        if key.startswith('add:') and key not in existing_ids:
            captured=datetime.strptime(capture.at,'%Y-%m-%d %H:%M:%S').astimezone(timezone.utc).isoformat()
            candidate[destination].entries.append(InventoryEntry(key,name,quantity,capture.scope,captured,
                note=f'Historical capture {capture.at}; base item total.',source='Reviewed probe',
                catalogue_ref=new_reference(capture,item,name)))
    for e in candidate[destination].entries:
        if e.id in current:
            e.quantity=current[e.id][2];e.source='Reviewed probe'
            # Import time is not a fresh observation; preserve existing recheck status.
    store.save(candidate)  # Atomic replacement, preceding-save backup and external-change guard.
    data.inventories[destination]=candidate[destination]
    data.inventory_store.loaded_bytes=store.loaded_bytes
