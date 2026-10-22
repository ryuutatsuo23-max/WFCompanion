"""Read-only view of applied inventory records. No cross-character stock pooling."""
from dataclasses import dataclass
from inventory import InventoryBook,entered_time
from professions import ProfessionPlan,stock_time


@dataclass(frozen=True)
class AltItem:
    character_id: str
    character: str
    entry_id: str
    name: str
    location: str
    quantity: int | None
    status: str
    item_id: int | None
    entered: str
    note: str


def character_labels(data):
    labels={p.id:p.name for p in data.profiles}
    for char in data.inventories: labels.setdefault(char,f'Unlisted character · {char}')
    # Equal display names still represent separate characters. Stable IDs are
    # used for filtering and row keys; disambiguate the visible labels too.
    for char,name in list(labels.items()):
        if sum(p.name==name for p in data.profiles)>1: labels[char]=f'{name} · {char}'
    return labels


def snapshot(data):
    if data.inventory_store.error: raise ValueError('Inventory file unavailable. Counts are Unknown; no empty inventories are inferred.')
    labels=character_labels(data)
    rows=[]; coverage=[]
    for char,name in sorted(labels.items(),key=lambda pair:(pair[1].casefold(),pair[0])):
        book=data.inventories.get(char,InventoryBook()); book.validate()
        plan=data.plans.get(char,ProfessionPlan())
        if not data.plans_store.error: plan.validate()
        aliases=plan.aliases(book) if not data.plans_store.error else {}
        locations={location:sum(e.location==location for e in book.entries) for location in ('Bags','Bank')}
        coverage.append((char,name,locations['Bags'] or None,locations['Bank'] or None))
        for entry in book.entries:
            cutoff=book.cutoff_for(entry,plan.recheck_after,aliases) if not data.plans_store.error else None
            state=('Unknown' if data.plans_store.error else 'Recheck' if cutoff and entered_time(entry.updated_at)<=stock_time(cutoff)
                   else 'Unknown' if entry.quantity is None else 'Known')
            rows.append(AltItem(char,name,entry.id,entry.name,entry.location,entry.quantity if state=='Known' else None,
                state,entry.catalogue_ref.item_id if entry.catalogue_ref else None,entry.updated_at,entry.note))
    rows.sort(key=lambda r:(r.name.casefold(),r.character.casefold(),r.character_id,r.location,r.entry_id))
    return rows,coverage


def filter_items(rows,query='',character=None,location='All',status='All'):
    query=query.strip().casefold()
    return [r for r in rows if (character is None or r.character_id==character)
            and (location=='All' or r.location==location) and (status=='All' or r.status==status)
            and query in f'{r.name} {r.note} {r.item_id if r.item_id is not None else ""}'.casefold()]
