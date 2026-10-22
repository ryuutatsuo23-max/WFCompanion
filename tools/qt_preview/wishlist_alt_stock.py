"""Informational alt counts; never feed these totals into ownership or crafting."""
from dataclasses import dataclass
from alt_inventory import character_labels
from inventory import InventoryBook
from professions import ProfessionPlan
from item_stock import RecordedCount,recorded_stock
from ownership import counts as ownership_counts


@dataclass(frozen=True)
class CharacterStock:
    character_id: str
    character: str
    counts: tuple[RecordedCount,RecordedCount]


def other_stock(data,entries,references=()):
    records=[(e.id,e.name,e.catalogue_ref) for e in entries]
    references=list(references)
    result={key:[] for key,_,_ in records}
    if not records: return result
    for char,name in sorted(character_labels(data).items(),key=lambda pair:(pair[1].casefold(),pair[0])):
        if char==data.active: continue
        try:
            if data.inventory_store.error or data.plans_store.error:
                raise ValueError('Saved stock unavailable.')
            counts=ownership_counts(data,records,char,references)
        except (ValueError,TypeError):
            # Invalid/unreadable records never establish an empty inventory.
            counts={key:(RecordedCount(reason='Saved stock unavailable.'),)*2 for key,_,_ in records}
        for key in result: result[key].append(CharacterStock(char,name,counts[key]))
    return result


def total_label(characters,location):
    if not characters: return 'No alts'
    counts=[c.counts[location].quantity for c in characters]
    known=[value for value in counts if value is not None]
    if not known: return 'Unknown'
    total=str(sum(known))
    return total+' + Unknown' if len(known)!=len(counts) else total


def location_details(characters,location):
    if not characters: return 'No other character records.'
    return '\n'.join(f'{c.character}: {c.counts[location].label} · {c.counts[location].reason}' for c in characters)
