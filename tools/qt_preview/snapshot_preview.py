"""Read-only sample snapshot comparison. No import, persistence or game APIs.

This is a proposed desktop contract, not the capability probe's Lua schema.
Sample IDs are fictional. Exact base-item IDs can be compared; names alone are
review candidates. Omissions never erase local records, even in complete samples.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    item_id: int
    name: str
    location: str
    count: int | None


@dataclass(frozen=True)
class Sample:
    title: str
    bags: str
    bank: str
    items: tuple[Observation, ...]
    level: int | None = 20
    character_class: str = 'Paladin'


SAMPLES = (
    Sample('Complete bags · bank not opened', 'Complete', 'Not observed', (
        Observation(900000001, 'Sample copper ore', 'Bags', 12),
        Observation(900000002, 'Sample healing potion', 'Bags', 3))),
    Sample('Partial bags · unknown count', 'Partial', 'Not observed', (
        Observation(900000001, 'Sample copper ore', 'Bags', 4),
        Observation(900000002, 'Sample healing potion', 'Bags', None)), level=None),
    Sample('Complete bags and opened bank', 'Complete', 'Complete', (
        Observation(900000001, 'Sample copper ore', 'Bags', 12),
        Observation(900000002, 'Sample healing potion', 'Bags', 0),
        Observation(900000001, 'Sample copper ore', 'Bank', 40))),
)


def shown(value):
    return 'Unknown' if value is None else str(value)


def compare(sample, entries):
    """Return display rows without mutating records or assigning a destination.

Current counts are stored manual observations, not a claim of current game stock.
Partial snapshots cannot supply a replacement total, even when a count is known.
Variant/cross-branch references and ambiguous IDs always require human review.
"""
    rows = []
    covered = set()
    for item in sample.items:
        exact = [e for e in entries if e.location==item.location and e.catalogue_ref is not None
                 and e.catalogue_ref.item_id==item.item_id]
        named = [e for e in entries if e.location==item.location and e.name.casefold()==item.name.casefold()]
        matches = exact or named
        covered.update(e.id for e in matches)
        current = 'Unknown · no local record' if not matches else ' / '.join(shown(e.quantity) for e in matches)
        coverage = sample.bags if item.location=='Bags' else sample.bank
        if item.count is None or coverage=='Not observed':
            action, reason = 'Keep local', 'Incoming count is Unknown; do not overwrite.'
        elif coverage!='Complete':
            action, reason = 'Review partial', 'Observed quantity may be incomplete; do not replace a total.'
        elif len(matches)>1:
            action, reason = 'Review match', 'Multiple local entries match; no automatic merge.'
        elif exact and (exact[0].catalogue_ref.variant!='base' or exact[0].catalogue_ref.branch!='forever'):
            action, reason = 'Review match', 'Variant or branch differs; a base ID is insufficient.'
        elif named and not exact:
            action, reason = 'Review match', 'Name-only match or different linked ID; identity is unconfirmed.'
        elif exact:
            action = 'No count change' if exact[0].quantity==item.count else 'Would update'
            reason = 'Exact base item ID and location; source identity/freshness still need confirmation.'
        else:
            action, reason = 'Would add', 'No local match. Fictional sample item; never applied.'
        rows.append((item.location, str(item.item_id), item.name, current, shown(item.count), action, reason))
    for entry in entries:
        if entry.id not in covered:
            rows.append((entry.location, str(entry.catalogue_ref.item_id) if entry.catalogue_ref else 'Unknown',
                         entry.name, shown(entry.quantity), 'Unknown · absent', 'Keep local',
                         'Not in this sample. Absence is not an observed zero.'))
    return rows
