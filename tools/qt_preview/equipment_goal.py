"""Explicit, single-goal saves without committing other applied/editor drafts."""
from copy import deepcopy
from uuid import uuid4
from catalogue import CatalogueRef
from gear import GearItem, GearWishlist
from equipment_review import SLOTS
from equipment_comparison import load_equipped
from playstyles import blank_preset


def proposed_goal(data, slot):
    slots, _ = load_equipped(data)
    if slot not in slots or slot == '0':
        raise ValueError('Select a recorded equipped item in a supported gear slot.')
    record = slots[slot]
    name = SLOTS[int(slot)]
    ref_slot = {'Main hand':'Main Hand', 'Off hand':'Off Hand',
                'Finger 1':'Finger', 'Finger 2':'Finger',
                'Trinket 1':'Trinket', 'Trinket 2':'Trinket'}.get(name, name)
    ref = CatalogueRef(record['item_id'], record['name'], ref_slot,
                       'local-capture:WFStressProbe+DataStore', record['captured_at'][:10],
                       'reviewed-capture-v1')
    goal = GearItem(uuid4().hex, record['name'], name, source='Reviewed equipped capture',
                    note='Planning goal from historical equipment; not an upgrade rating.', catalogue_ref=ref)
    goal.validate()
    return goal, deepcopy(record)


def save_goal(data, character, target, slot, expected, goal):
    if data.active != character:
        raise ValueError('Character changed. Reopen the review.')
    data.require_profile_saved()
    current = data.profile_store.path.read_bytes() if data.profile_store.path.exists() else None
    if current != data.profile_bytes:
        raise ValueError('Character profiles changed outside this window. Reopen before saving.')
    if target == 'General' or target not in data.playstyles.available(character, data.profile.character_class):
        raise ValueError('Choose an available role playstyle.')
    fresh, record = proposed_goal(data, slot)
    if record != expected or (goal.name, goal.slot, goal.catalogue_ref) != (fresh.name, fresh.slot, fresh.catalogue_ref):
        raise ValueError('Equipped item changed. Reopen the review.')
    saved = GearWishlist.from_dict(data.playstyles.saved_preset(character, target)['gear'])
    cached = deepcopy(data.playstyles.books.get((character, target), saved))
    # Validate both copies before touching disk: duplicates and ambiguous names
    # in either saved records or applied drafts must never be silently merged.
    saved.entries.append(deepcopy(goal)); saved.validate()
    cached.entries.append(deepcopy(goal)); cached.validate()
    payload = deepcopy(data.playstyles.store.data)
    owner = payload['characters'].setdefault(character, {'active':data.playstyles.active(character), 'presets':{}})
    owner['presets'].setdefault(target, blank_preset())['gear'] = saved.to_dict()
    data.playstyles.store.save(payload)
    data.playstyles.books[(character, target)] = cached
    # Existing dirty flags deliberately survive; only this new goal was saved.
