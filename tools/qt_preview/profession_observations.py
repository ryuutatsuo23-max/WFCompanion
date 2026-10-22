"""Original GPL-3.0-only reader for the inspected DataStore 2026.10.14 layout.

No Lua execution or writes. The session cache is intentionally separate from
profiles, recipes, goals and inventory. Source GUIDs never select a local profile.
"""
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import time

from probe_report import LuaData, ReportError

CRAFTS = {'DataStore_Crafts_' + s for s in
          ('Characters', 'ArcheologyItems', 'RecipeCategories', 'Reagents')}
MAPPING = {'DataStore_' + s for s in ('GuildIDs', 'GuildFactions', 'CharacterIDs',
           'CharacterGUIDs', 'CharacterGuilds', 'AltGroups', 'ConnectedRealms', 'RealmNames')}
LIMIT = 16 * 1024 * 1024
GUID = re.compile(r'Player-\d+-[0-9A-Fa-f]+')


def table(value, maximum=20000):
    if not isinstance(value, dict) or len(value) > maximum:
        raise ReportError('Unsupported or oversized DataStore table.')
    return value


def integer(value, low=0, high=2**53-1):
    if type(value) is not int or not low <= value <= high:
        raise ReportError('Invalid packed integer or record ID.')
    return value


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ReportError('Invalid profession/category label.')
    return value


def globals_from(data, allowed):
    if not data or len(data) > LIMIT:
        raise ReportError('Saved file is empty or exceeds 16 MiB.')
    try:
        reader = LuaData(data.decode('utf-8-sig'), max_nodes=500000)
    except UnicodeError as exc:
        raise ReportError('Saved file is not UTF-8.') from exc
    result = {}
    while True:
        reader.skip()
        if reader.pos == len(reader.text):
            return result
        match = re.match(r'[A-Za-z_][A-Za-z_0-9]*', reader.text[reader.pos:])
        name = match[0] if match else ''
        if name not in allowed or name in result:
            raise ReportError('Unexpected or duplicate saved global; no Lua is executed.')
        reader.require(name); reader.require('=')
        result[name] = table(reader.value())
        reader.take(';')


def timestamp_label(value, now):
    if type(value) is not int or not 0 < value <= 253402300799:
        return 'Unknown age'
    if value > now:
        return 'Clock mismatch: source timestamp is in the future'
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def character_labels(mapping):
    """Optional display metadata only; reciprocal numeric mapping is required."""
    ids = mapping.get('DataStore_CharacterIDs')
    if ids is None:
        return {}
    table(ids, 3)
    listed = table(ids.get('List', {}), 1000)
    keyed = table(ids.get('Set', {}), 1000)
    count = integer(ids.get('Count'), 0, 1000)
    if count != len(listed) or count != len(keyed) or set(listed) != set(range(1, count+1)):
        raise ReportError('Character label list/set mismatch.')
    labels = {}
    for index, key in listed.items():
        text(key)
        if type(keyed.get(key)) is not int or keyed[key] != index:
            raise ReportError('Character label list/set conflict.')
        parts = key.split('.', 2)
        if len(parts) != 3 or not all(p.strip() for p in parts):
            raise ReportError('Unsupported character display key.')
        labels[index] = {'name': parts[2], 'realm': parts[1]}
    return labels


def decode(crafts_bytes, mapping_bytes, now=None):
    now = time.time() if now is None else now
    crafts = globals_from(crafts_bytes, CRAFTS)
    mapping = globals_from(mapping_bytes, MAPPING)
    labels = character_labels(mapping)
    if 'DataStore_Crafts_Characters' not in crafts:
        raise ReportError('Unsupported Crafts format: character table missing.')
    guids = table(mapping.get('DataStore_CharacterGUIDs', {}), 1000)
    for key, value in guids.items():
        integer(key, 1, 1000000)
        if not isinstance(value, str) or len(value) > 160 or not GUID.fullmatch(value):
            raise ReportError('Invalid DataStore GUID mapping.')
    if any(n > 1 for n in Counter(guids.values()).values()):
        raise ReportError('Conflicting GUID mapping; previous observations retained.')
    categories = table(crafts.get('DataStore_Crafts_RecipeCategories', {}))
    for key, value in categories.items():
        integer(key, 1, 2**31-1); text(value)
    characters = []
    for key, char in table(crafts['DataStore_Crafts_Characters'], 1000).items():
        integer(key, 1, 1000000); table(char)
        indices = table(char.get('Indices', {}), 100)
        ranks = table(char.get('Ranks', {}), 100)
        professions = table(char.get('Professions', {}), 100)
        for name, index in indices.items():
            text(name); integer(index, 1, 100)
            if index not in professions or table(professions[index]).get('Name') != name:
                raise ReportError('Profession index/name mapping conflict.')
        for index, packed in ranks.items():
            integer(index, 1, 100); integer(packed, 0, 2**32-1)
            if index not in professions:
                raise ReportError('Rank has no matching profession.')
        parsed = []
        for index, profession in professions.items():
            integer(index, 1, 100); table(profession)
            name = text(profession.get('Name'))
            if indices.get(name) != index:
                raise ReportError('Profession index/name mapping conflict.')
            packed = ranks.get(index)
            rank = maximum = None
            if packed is not None:
                integer(packed, 0, 2**32-1)
                rank, maximum = packed & 0xffff, packed >> 16
                if rank > maximum:
                    raise ReportError('Recorded skill exceeds maximum; review required.')
            recipes = {}
            for category, entries in table(profession.get('Crafts', {}), 2000).items():
                integer(category, 1, 2**31-1); table(entries)
                if set(entries) != set(range(1, len(entries)+1)):
                    raise ReportError('Recipe array must be contiguous.')
                for packed in entries.values():
                    integer(packed)
                    recipe = integer(packed >> 7, 1, 2**31-1)
                    fields = (bool(packed & 4), packed & 3, (packed >> 3) & 3, (packed >> 5) & 3)
                    if fields[2] > fields[3]:
                        raise ReportError('Recipe rank exceeds maximum.')
                    if recipe in recipes and recipes[recipe]['fields'] != fields:
                        raise ReportError('Conflicting duplicate recipe ID.')
                    entry = recipes.setdefault(recipe, {'id': recipe, 'fields': fields, 'categories': {}})
                    entry['categories'][category] = categories.get(category, 'Category name unknown')
                    if len(recipes) > 20000:
                        raise ReportError('Too many recipe records.')
            parsed.append({'index': index, 'name': name, 'rank': rank, 'max': maximum,
                           'recipes': list(recipes.values()), 'coverage': 'unknown'})
        characters.append({'source_id': key, 'guid': guids.get(key),
                           'label': labels.get(key) if guids.get(key) else None,
                           'source_time': char.get('lastUpdate'),
                           'freshness': timestamp_label(char.get('lastUpdate'), now),
                           'professions': parsed})
    return {'provider': 'DataStore_Crafts', 'adapter': 1, 'state': 'cached',
            'coverage': 'unknown', 'read_time': now, 'characters': characters}


def fingerprint(path):
    before = path.stat()
    if before.st_size > LIMIT:
        raise ReportError('Saved file exceeds 16 MiB.')
    with path.open('rb') as stream:
        data = stream.read(LIMIT+1)
    after = path.stat()
    stamp = lambda s: (s.st_size, s.st_mtime_ns)
    if stamp(before) != stamp(after) or len(data) != after.st_size:
        raise ReportError('Saved file changed during reading; try again after logout.')
    return data, (after.st_size, after.st_mtime_ns, sha256(data).hexdigest())


def read_directory(directory):
    directory = Path(directory).resolve(strict=True)
    # A single selected account supplies both files. Never accept arbitrary pairs.
    if (directory.name.lower() != 'savedvariables' or
        directory.parent.parent.name.lower() != 'account' or
        directory.parent.parent.parent.name.lower() != 'wtf' or
        directory.parent.parent.parent.parent.name.lower() != '_classic_beta_'):
        raise ReportError('Select one Beta WTF/Account/<account>/SavedVariables folder.')
    paths = [directory / name for name in ('DataStore_Crafts.lua', 'DataStore.lua')]
    if any(p.resolve(strict=True).parent != directory for p in paths):
        raise ReportError('Saved files must belong to the selected account directory.')
    first = [fingerprint(p) for p in paths]
    snapshot = decode(first[0][0], first[1][0])
    second = [fingerprint(p) for p in paths]
    if [f[1] for f in first] != [f[1] for f in second]:
        raise ReportError('Saved files changed during reading; previous observations retained.')
    snapshot['directory'] = str(directory)
    snapshot['files'] = {p.name: {'bytes': f[1][0], 'mtime_ns': f[1][1], 'sha256': f[1][2]}
                         for p, f in zip(paths, first)}
    snapshot['provenance'] = ('Inspected 2026.10.14 packed layout; cache writer version unverified. '
                              'Stable reads do not prove an atomic cross-file snapshot. '
                              'GUID mapping is source-local; no companion profile is linked.')
    return snapshot


class ObservationCache:
    """RAM-only latest accepted observation plus independent refresh status."""
    def __init__(self):
        self.accepted = None
        self.error = ''
        self.attempt_time = None

    def refresh(self, directory):
        self.attempt_time = time.time()
        try:
            candidate = read_directory(directory)
        except (OSError, ValueError, TypeError, AttributeError, OverflowError) as exc:
            self.error = str(exc)
            return False
        self.accepted = candidate
        self.error = ''
        return True
