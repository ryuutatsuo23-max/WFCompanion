"""Bounded, read-only WFStressProbe SavedVariables decoder. Never executes Lua.

Only the producer's schema-1 data and report version 0.1.0 are understood.
Reports are diagnostic samples, never character records or ownership evidence.
"""
from dataclasses import dataclass
from pathlib import Path
import re

CLIENT = Path(r'C:\Program Files (x86)\World of Warcraft\_forever_')
MAX_BYTES = 16 * 1024 * 1024


class ReportError(ValueError):
    pass


class LuaData:
    """Small grammar: one named assignment, literals and tables, line comments.

    Reject expressions, calls, metatables, duplicate keys and trailing code.
    Limits also apply to syntactically valid but hostile inputs.
    """
    def __init__(self, text, max_nodes=10000):
        self.text = text
        self.pos = 0
        self.nodes = 0
        self.max_nodes = max_nodes

    def skip(self):
        match = re.compile(r'(?:\s+|--[^\r\n]*(?:\r?\n|$))*').match(self.text, self.pos)
        self.pos = match.end()

    def take(self, token):
        self.skip()
        if self.text.startswith(token, self.pos):
            self.pos += len(token)
            return True
        return False

    def require(self, token):
        if not self.take(token):
            raise ReportError('Incomplete or unsupported SavedVariables syntax.')

    def string(self):
        quote = self.text[self.pos]
        self.pos += 1
        result = []
        escapes = {'n':'\n', 'r':'\r', 't':'\t', 'a':'\a', 'b':'\b', 'f':'\f', 'v':'\v', '\\':'\\', '"':'"', "'":"'"}
        while self.pos < len(self.text):
            char = self.text[self.pos]; self.pos += 1
            if char == quote:
                return ''.join(result)
            if char == '\\':
                if self.pos == len(self.text): break
                char = self.text[self.pos]; self.pos += 1
                if char.isascii() and char.isdigit():
                    digits = char
                    while len(digits) < 3 and self.pos < len(self.text) and self.text[self.pos] in '0123456789':
                        digits += self.text[self.pos]; self.pos += 1
                    if int(digits) > 255: raise ReportError('Invalid string escape.')
                    char = chr(int(digits))
                elif char in escapes: char = escapes[char]
                elif char == '\n': char = '\n'
                elif char == '\r' and self.pos < len(self.text) and self.text[self.pos] == '\n':
                    self.pos += 1; char = '\n'
                else: raise ReportError('Unsupported string escape.')
            elif char in '\r\n':
                raise ReportError('Unescaped newline in string.')
            result.append(char)
            if len(result) > 64000: raise ReportError('Saved string exceeds the reader limit.')
        raise ReportError('Incomplete saved string; waiting for a complete file.')

    def value(self, depth=0):
        self.nodes += 1
        if depth > 16 or self.nodes > self.max_nodes: raise ReportError('Saved data exceeds reader limits.')
        self.skip()
        if self.pos >= len(self.text): raise ReportError('Incomplete saved data.')
        if self.text[self.pos] in "\"'": return self.string()
        if self.take('{'):
            result = {}; index = 1
            while not self.take('}'):
                if self.take('['):
                    key = self.value(depth+1)
                    if type(key) not in (str, int): raise ReportError('Unsupported table key.')
                    self.require(']'); self.require('=')
                else:
                    self.skip()
                    name = re.compile(r'([A-Za-z_][A-Za-z_0-9]*)\s*=').match(self.text, self.pos)
                    if name: key = name[1]; self.pos = name.end()
                    else: key = index; index += 1
                if key in result: raise ReportError('Duplicate saved table key.')
                result[key] = self.value(depth+1)
                if self.take(',') or self.take(';'): continue
                self.require('}'); break
            return result
        match = re.compile(r'(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true\b|false\b|nil\b)').match(self.text, self.pos)
        if not match: raise ReportError('Only saved data is accepted; Lua code is never run.')
        self.pos = match.end(); token = match[0]
        if token in ('true','false','nil'): return {'true':True,'false':False,'nil':None}[token]
        if len(token) > 32: raise ReportError('Oversized number.')
        return float(token) if any(c in token for c in '.eE') else int(token)

    def decode(self):
        self.require('WFStressProbeDB'); self.require('=')
        value = self.value(); self.take(';'); self.skip()
        if self.pos != len(self.text): raise ReportError('Unexpected code after saved data.')
        return value


def array(value, limit):
    if not isinstance(value, dict) or len(value) > limit or any(type(k) is not int for k in value):
        raise ReportError('Invalid probe array.')
    if set(value) != set(range(1, len(value)+1)): raise ReportError('Incomplete probe array.')
    return [value[i] for i in range(1, len(value)+1)]


@dataclass(frozen=True)
class Snapshot:
    at: str
    reason: str
    report: str
    character_key: str = ''
    character_label: str = 'Unknown character · older or unavailable identity'


def owner(session):
    character = session.get('character')
    if not isinstance(character, dict): return '', 'Unknown character · older or unavailable identity'
    key = character.get('key')
    if not isinstance(key, str) or not re.fullmatch(r'Player-\d+-[0-9a-fA-F]+', key) or len(key)>100:
        return '', 'Unknown character · older or unavailable identity'
    def clean(field):
        value = character.get(field)
        if not isinstance(value,str) or len(value)>100: return 'Unavailable'
        return re.sub(r'[\x00-\x1f\x7f|]', ' ', value)
    name = clean('name')
    first, last = clean('firstName'), clean('lastName')
    if first not in ('Unavailable',''):
        name = first
        if last not in ('Unavailable',''): name += ' ' + last
    # Names are labels only; never merge records by either name part.
    return key, f'{name} · {clean("realm")} · {key}'


def decode(data):
    if len(data) > MAX_BYTES: raise ReportError('Report file exceeds 16 MiB.')
    try: db = LuaData(data.decode('utf-8-sig')).decode()
    except UnicodeError as e: raise ReportError('Saved file is not valid UTF-8 yet.') from e
    if not isinstance(db, dict) or type(db.get('schema')) is not int or db['schema'] != 1:
        raise ReportError('Unsupported probe schema; file left untouched.')
    snapshots = []
    for session in array(db.get('sessions'), 30):
        if not isinstance(session, dict): raise ReportError('Invalid probe session.')
        character_key, character_label = owner(session)
        for sample in array(session.get('snapshots'), 60):
            if not isinstance(sample, dict): raise ReportError('Invalid probe snapshot.')
            report = sample.get('report')
            if not isinstance(report, str) or len(report) > 32000: raise ReportError('Invalid snapshot report.')
            metadata = []
            for key in ('at','reason'):
                value = sample.get(key)
                if value is not None and (not isinstance(value, str) or len(value) > 64): raise ReportError('Invalid snapshot metadata.')
                metadata.append(value or 'Unknown')
            display_label = character_label
            if character_key:
                match = re.search(r'^Player class ID: OK = (\d+)$', report, re.M)
                classes = {'1':'Warrior','2':'Paladin','3':'Hunter','4':'Rogue','5':'Priest',
                           '7':'Shaman','8':'Mage','9':'Warlock','11':'Druid'}
                if match and match[1] in classes:
                    display_label = classes[match[1]] + ' · ' + display_label
            snapshots.append(Snapshot(*metadata, report, character_key, display_label))
    return snapshots


def summarize(report):
    """Conservative latest-snapshot verdicts; presence alone is not a read test."""
    names = ('HP','Mana','XP','Buffs','Cooldowns','Inventory')
    if not report.startswith('FOREVER API PROBE 0.1.0\n'):
        state = 'Error' if report.startswith('Probe internal error.') else 'Not tested'
        return [(name,state,'Unrecognized report or failed capture; inspect details.') for name in names]
    sections = {}; section = ''
    for line in report.splitlines():
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]; sections[section] = []
        elif ': ' in line: sections.setdefault(section, []).append(tuple(line.split(': ',1)))
    vitals = sections.get('HP, active power, mana, XP', [])
    groups = [(name,[(k,v) for k,v in vitals if k in (name,name+' maximum')], f'Checks current and maximum {name}; zero can be a valid reading.') for name in names[:3]]
    for prefix,name,note in (
        ('Helpful buffs:', 'Buffs', 'Up to 8 helpful player buffs; nil records remain Unknown.'),
        ('Cooldowns:', 'Cooldowns', 'Sampled spells only; readable cooldowns do not prove castability.'),
        ('Inventory:', 'Inventory', 'Bags 0–4, up to 4 slots each. Bank/equipment untested; no totals imported.')):
        pairs = next((v for k,v in sections.items() if k.startswith(prefix)), [])
        groups.append((name,pairs,note))
    result = []
    for name,pairs,note in groups:
        values = [v for _,v in pairs]
        reads = [(k,v) for k,v in pairs if v.startswith('OK = ')]
        if name == 'Cooldowns': reads = [(k,v) for k,v in reads if k.startswith('Cooldown.')]
        if any(v == 'Restricted' for v in values): state = 'Restricted'
        elif any(v in ('Guard unavailable','Guard error') for v in values): state = 'Unknown'
        elif any(v == 'Missing API' for v in values): state = 'Missing API'
        elif any(v in ('API error','Unexpected type','Invalid number','Unexpected slot count') for v in values): state = 'Error'
        elif name in names[:3] and len(reads) == 2: state = 'Working · sample'
        elif name == 'Buffs' and len(reads) >= 4 and all(v.startswith('OK = ') for k,v in pairs if k.startswith('Aura ' ) and '.' in k): state = 'Working · sample'
        elif name == 'Cooldowns' and len(reads) >= 4 and all(v.startswith('OK = ') for k,v in pairs if k.startswith('Cooldown')): state = 'Working · sample'
        elif reads: state = 'Partial'
        elif any(v.startswith('Unknown') for v in values): state = 'Unknown'
        else: state = 'Not tested'
        if name == 'Inventory' and reads:
            note = 'Bag API reads observed. ' + note
        if state in ('Restricted','Unknown','Missing API','Error'):
            evidence = next((f'{k}: {v}' for k,v in pairs if not v.startswith('OK = ') and v != 'Present'), '')
            note = evidence + '. ' + note
        if state == 'Not tested': note = 'No usable read test in this snapshot. ' + note
        result.append((name,state,note))
    return result


class ReportReader:
    """Worker-owned cache. Only the known account SavedVariables path is scanned."""
    def __init__(self, client=CLIENT):
        self.client = Path(client)
        self.signature = None
        self.cached = None

    def poll(self, selected=None):
        try:
            paths = [Path(selected)] if selected else list((self.client/'WTF'/'Account').glob('*/SavedVariables/WFStressProbe.lua'))
            if not paths: return None, 'No saved report yet. Enter the world with WFStressProbe enabled, then /reload.'
            path = max(paths, key=lambda p:(p.stat().st_mtime_ns,str(p)))
            stat = path.stat(); signature = (str(path),stat.st_mtime_ns,stat.st_size)
            if signature == self.signature: return self.cached, ''
            if stat.st_size > MAX_BYTES: raise ReportError('Report file exceeds 16 MiB.')
            with path.open('rb') as stream: data = stream.read(MAX_BYTES+1)
            after = path.stat()
            if (after.st_mtime_ns,after.st_size) != (stat.st_mtime_ns,stat.st_size):
                raise ReportError('Report is being saved; retrying shortly.')
            snapshots = decode(data)
            if not snapshots: raise ReportError('Probe file has no snapshots yet. Enter the world, then /reload.')
            latest = snapshots[-1]
            self.cached = (path,stat.st_mtime,latest,len(snapshots),summarize(latest.report),len(paths),tuple(snapshots))
            self.signature = signature
            return self.cached, ''
        except (OSError,ValueError) as e:
            # Do not include OS error paths (account IDs) in the short status.
            return None, str(e) if isinstance(e,ReportError) else 'Report unavailable or unreadable; retrying shortly.'
