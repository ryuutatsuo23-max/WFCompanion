"""Read-only WFCore schema 1/2 adapter. Never applies observations to manual plans.

Uses the existing literal-only parser, not a Lua runtime. Slot observations are
historical subtotals; absent items and unresolved slots never mean zero ownership.
Unknown producer versions fail closed. No identity mapping or state-file writes.
"""
from dataclasses import dataclass
from collections import defaultdict
import re
from probe_report import LuaData, ReportError, array


class CoreData(LuaData):
    def decode(self):
        self.require('WFCoreDB'); self.require('=')
        value = self.value(); self.take(';'); self.skip()
        if self.pos != len(self.text):
            raise ReportError('Unexpected code after saved data.')
        return value


@dataclass(frozen=True)
class Observation:
    owner: str
    label: str
    scope: str
    build: str
    started_at: int | None
    finished_at: int | None
    coverage: str
    unknown_slots: int
    rows: tuple
    interrupted: bool
    schema: int = 1
    observed_slots: int = 0
    empty_slots: int = 0
    scan_status: str = 'legacy'
    realm: str = ''
    client_version: str = ''
    interface: int = 0


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def timestamp(value):
    if value is not None and not integer(value, 0, 9999999999):
        raise ReportError('Invalid observation timestamp.')
    return value


def decode(data: bytes) -> tuple[Observation, ...]:
    if not data or len(data) > 64 * 1024 * 1024:
        raise ReportError('Core save is empty or exceeds 64 MiB.')
    try:
        db = CoreData(data.decode('utf-8-sig'), max_nodes=4_000_000).decode()
    except UnicodeError as exc:
        raise ReportError('Core save must be UTF-8.') from exc
    if not isinstance(db, dict) or type(db.get('schema')) is not int or db['schema'] != 1 or db.get('producer') != 'WFCore':
        raise ReportError('Unsupported core schema or producer.')
    characters = db.get('characters')
    if 'inventorySchema' in db and (type(db['inventorySchema']) is not int or db['inventorySchema'] not in (1,2)):
        raise ReportError('Unsupported inventory schema.')
    if not isinstance(characters, dict) or len(characters) > 50:
        raise ReportError('Invalid character collection.')
    result = []
    for guid, character in characters.items():
        if not isinstance(guid, str) or not re.fullmatch(r'Player-\d+-[0-9A-Fa-f]+', guid) or len(guid) > 160:
            raise ReportError('Invalid character key.')
        if not isinstance(character, dict): raise ReportError('Invalid character.')
        identity, client = character.get('identity'), character.get('client')
        if not isinstance(identity, dict) or identity.get('guid') != guid:
            raise ReportError('Mismatched character identity.')
        if not isinstance(client, dict) or client.get('version') != '1.60.1' or client.get('interface') != 16001:
            raise ReportError('Unsupported observation client.')
        for key in ('firstName', 'lastName', 'realm'):
            if key in identity and (not isinstance(identity[key], str) or len(identity[key]) > 160):
                raise ReportError('Invalid identity label.')
        label = ' '.join(identity.get(key, '') for key in ('firstName', 'lastName')).strip() or guid
        locations = character.get('locations')
        if not isinstance(locations, dict) or not set(locations) <= {'bags', 'bank'}:
            raise ReportError('Invalid inventory locations.')
        for scope, location in locations.items():
            if not isinstance(location, dict): raise ReportError('Invalid location.')
            for kind in ('latest', 'attempt'):
                snap = location.get(kind)
                if snap is None: continue
                if isinstance(snap,dict) and type(snap.get('schema')) is int and snap['schema']==2:
                    if db.get('inventorySchema')!=2:raise ReportError('Missing schema-2 envelope declaration.')
                    from core_inventory_v2 import parse_snapshot
                    result.append(parse_snapshot(snap,guid,scope,kind));continue
                if (not isinstance(snap, dict) or snap.get('schema') != 1
                        or snap.get('addonVersion') not in ('0.1.0', '0.1.1', '0.1.2', '0.2.0', '0.2.1', '0.3.0') or snap.get('owner') != guid
                        or snap.get('scope') != scope or snap.get('accessible') is not True
                        or snap.get('coverage') not in ('attempted', 'partial')):
                    raise ReportError('Invalid snapshot contract.')
                sizes = {}
                for container in array(snap.get('containers'), 12):
                    if not isinstance(container, dict): raise ReportError('Invalid container.')
                    bag, size = container.get('id'), container.get('slots')
                    if not integer(bag, -2, 100) or not integer(size, 0, 200) or bag in sizes:
                        raise ReportError('Invalid or duplicate container.')
                    sizes[bag] = size
                totals, seen, unknown = defaultdict(int), set(), 0
                for slot in array(snap.get('slots'), 2400):
                    if not isinstance(slot, dict): raise ReportError('Invalid slot.')
                    bag, index = slot.get('bag'), slot.get('slot')
                    if not integer(bag, -2, 100) or bag not in sizes or not integer(index, 1, sizes[bag]) or (bag, index) in seen:
                        raise ReportError('Invalid or duplicate slot.')
                    seen.add((bag, index))
                    if slot.get('state') == 'unknown':
                        if 'count' in slot or 'itemID' in slot: raise ReportError('Unknown slot has ownership data.')
                        unknown += 1
                    elif slot.get('state') == 'observed' and integer(slot.get('itemID'), 1, 2147483647) and integer(slot.get('count'), 1, 2147483647):
                        totals[slot['itemID']] += slot['count']
                    else: raise ReportError('Invalid slot observation.')
                if type(snap.get('unknownSlots')) is not int or unknown != snap['unknownSlots']:
                    raise ReportError('Unknown-slot count mismatch.')
                source_client = snap.get('client')
                if not isinstance(source_client, dict) or source_client.get('version') != '1.60.1' or source_client.get('interface') != 16001:
                    raise ReportError('Unsupported snapshot client.')
                if snap['coverage'] == 'attempted' and len(seen) != sum(sizes.values()):
                    raise ReportError('Incomplete declared coverage.')
                result.append(Observation(guid, label, scope, str(source_client.get('build', 'Unknown')),
                    timestamp(snap.get('startedAt')), timestamp(snap.get('finishedAt')),
                    snap['coverage'], unknown, tuple(sorted(totals.items())), kind == 'attempt'))
    return tuple(result)
