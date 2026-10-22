"""Read-only ownership: linked addon snapshots OR manual counts, never their sum."""
from dataclasses import replace
from datetime import datetime,timezone
from character_links import LinkStore,key
from observed_inventory import ObservationStore
from inventory import InventoryBook
from professions import ProfessionPlan,stock_time
from catalogue import item_key
from item_values import material_key
from item_stock import RecordedCount,recorded_stock


def counts(data,records,profile=None,references=()):
    records=list(records);profile=profile or data.active
    unknown=lambda reason:{row:(RecordedCount(reason=reason),)*2 for row,_,_ in records}
    try:
        links=LinkStore(data.directory)
        link=next((e for e in links.records['links'] if e['profile']==profile),None)
        plan=data.plans.get(profile,ProfessionPlan())
        if data.plans_store.error:return unknown('Saved plan unavailable.')
        plan.validate()
        if link is None:
            if data.inventory_store.error:return unknown('Saved stock unavailable.')
            return recorded_stock(records,data.inventories.get(profile,InventoryBook()),plan,references)
        ledger=ObservationStore(data.directory).ledger
        totals={scope:dict(ledger[(profile,scope)]['rows']) for scope in ('bags','bank') if (profile,scope) in ledger}
        result={}
        for row,name,ref in records:
            values=[]
            for scope in ('bags','bank'):
                record=ledger.get((profile,scope))
                reason='Addon location not observed; manual counts remain separate.'
                quantity=None
                if ref is None:reason='Choose an exact item ID to match addon counts.'
                elif record and key(record['identity'])==key(link['identity']) and record['build']=='70532':
                    ref.validate()
                    stamp=datetime.fromtimestamp(record['finished'],timezone.utc)
                    cutoffs=[plan.recheck_after.get(k) for k in (item_key(name,ref),material_key(name))]
                    if any(c and stamp<=stock_time(c) for c in cutoffs):
                        reason='Recheck after a recorded craft; saved addon scan predates it.'
                    else:
                        quantity=totals[scope].get(ref.item_id,0)
                        reason=f"Addon {scope} snapshot · {stamp.isoformat()} · {record['identity']['environment']}"
                values.append(RecordedCount(quantity,reason))
            result[row]=tuple(values)
        return result
    except (ValueError,TypeError,OSError,KeyError,OverflowError):
        return unknown('Addon links or observations unavailable; no manual fallback assumed.')


def requirements(data):
    """Keep plan arithmetic and craft invalidation, replacing only read-only stock."""
    rows=data.plan.requirements(data.inventory)
    stock=counts(data,[(r.key,r.name,r.catalogue_ref) for r in rows])
    result=[]
    for row in rows:
        bags,bank=(c.quantity for c in stock[row.key])
        total=None if bags is None or bank is None else bags+bank
        result.append(replace(row,bags=bags,bank=bank,owned=total))
    return result
