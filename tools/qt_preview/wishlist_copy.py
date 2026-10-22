"""Copy applied General entries to a role without moving, saving or merging drafts."""
from copy import deepcopy
from uuid import uuid4
from gear import GearWishlist
from item_values import material_key


def copy_status(item,destination):
    for other in destination.entries:
        if item.slot != other.slot: continue
        if item.key==other.key: return 'Already listed · kept unchanged'
        if material_key(item.name)==material_key(other.name) and (item.catalogue_ref is None or other.catalogue_ref is None):
            return 'Name/ID conflict · kept unchanged'
    return 'Ready to copy'


def copy_general(data,character,target,selected):
    if character!=data.active: raise ValueError('The selected character changed. Reopen the copy dialog.')
    if target=='General' or target not in data.playstyles.available(character,data.profile.character_class):
        raise ValueError('Choose an available destination playstyle.')
    if data.gear_store.error or data.playstyles.store.error:
        raise ValueError(data.gear_store.error or data.playstyles.store.error)
    source=data.gear.get(character,GearWishlist()); source.validate()
    ids=set(selected)
    if not ids: raise ValueError('Tick at least one General item to copy.')
    if ids-{item.id for item in source.entries}: raise ValueError('General entries changed. Refresh the copy list.')
    candidate=deepcopy(data.playstyles.book(character,target)); candidate.validate()
    copied=0; skipped=[]
    for item in source.entries:
        if item.id not in ids: continue
        state=copy_status(item,candidate)
        if state!='Ready to copy': skipped.append((item.name,state)); continue
        clone=deepcopy(item); clone.id=uuid4().hex
        candidate.entries.append(clone); copied+=1
    # Validate the complete operation before replacing the destination. A size
    # limit/error never leaves a partially copied wishlist behind.
    candidate.validate()
    if copied:
        data.playstyles.books[(character,target)]=candidate
        data.dirty.add(('Gear wishlist',character,target))
    return copied,skipped
