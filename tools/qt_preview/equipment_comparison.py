"""Read-only wishlist comparisons against historical equipped slots, not ownership."""
from equipment_review import EquipmentStore,SLOTS

SLOT_IDS={name:str(i) for i,name in enumerate(SLOTS)}
SLOT_IDS['Relic']='18'  # Same physical slot; does not infer item eligibility.


def load_equipped(data):
    saved,_=EquipmentStore(data.directory).load()
    record=saved['characters'].get(data.active)
    if record is None:return {},'No equipment has been recorded for this character.'
    if data.active.startswith('capture-') and data.active!='capture-'+record['guid']:
        raise ValueError('Saved equipment GUID does not match this character.')
    return record['slots'],f'Equipment GUID: {record["guid"]}'


def compare(goals,equipped):
    rows=[]
    for goal in goals:
        slot=SLOT_IDS.get(goal.slot);current=equipped.get(slot) if slot is not None else None
        target=goal.catalogue_ref.item_id if goal.catalogue_ref else None
        other=[]
        if target:
            other=[SLOTS[int(s)] for s,r in equipped.items() if r['item_id']==target and s!=slot]
        if slot is None:status='Choose a specific slot'
        elif current is None:status='Unknown · no recorded item in this slot'
        elif target is None:status='Unlinked goal · item identity unverified'
        elif goal.catalogue_ref.branch!='forever' or goal.catalogue_ref.variant!='base':status='Unsupported item identity'
        elif target==current['item_id']:status='Same base item ID · variant unverified'
        else:status='Different item · no upgrade rating'
        if other:status+='; same base ID recorded in '+', '.join(other)
        rows.append((goal.id,(goal.name,goal.slot,str(target) if target else 'Unlinked',
                             current['name'] if current else 'Unknown',
                             str(current['item_id']) if current else 'Unknown',status,
                             current.get('captured_at','Unknown') if current else 'Unknown')))
    return rows
