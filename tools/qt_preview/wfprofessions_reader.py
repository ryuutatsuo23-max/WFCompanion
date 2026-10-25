"""GPL-3.0-only. Bounded, literal-only saved Professions reader; no writes.

read_character accepts a saved LinkStore identity, not a character display name.
All observations are historical. Unknown and unobserved never mean unlearned.
"""
from pathlib import Path
import re

from core_observations import CoreData
from profession_observations import globals_from, fingerprint
from probe_report import array


def table(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid Professions table.')
    return value


def number(value, low=0, high=2147483647):
    return value if type(value) is int and low <= value <= high else None


def known(value, kind):
    if not isinstance(value, dict) or value.get('status') != 'known':
        return None
    v = value.get('value')
    if type(v) is not kind:
        return None
    if kind is int:
        return number(v)
    if kind is str and (not v or len(v) > 160 or re.search(r'[\x00-\x1f\x7f|]', v)):
        return None
    return v


def required(value, kind):
    result = known(value, kind)
    if result is None:
        raise ValueError('Required Professions identity/coverage field is unknown.')
    return result


def envelope(capture, identity):
    capture = table(capture)
    if capture.get('provenance') != 'live-probe':
        raise ValueError('Synthetic or unsupported Professions provenance.')
    at = number(capture.get('at'), 1)
    if at is None:
        raise ValueError('Invalid Professions timestamp.')
    client = table(capture.get('client'))
    for key, kind in (('version', str), ('interface', int), ('build', str)):
        if required(client.get(key), kind) != identity[key]:
            raise ValueError('Professions client differs from the linked Core client.')
    return at, table(capture.get('report'))


def recipe(raw):
    raw = table(raw)
    if raw.get('infoStatus') != 'ok':
        raise ValueError('Recipe identity read was not successful.')
    info = table(raw.get('info'))
    rid = required(raw.get('id'), int)
    if rid < 1 or required(info.get('recipeID'), int) != rid:
        raise ValueError('Conflicting recipe identity.')
    output = raw.get('output') if raw.get('schematicStatus') == 'ok' else None
    output = output if isinstance(output, dict) else {}
    result = dict(id=rid, name=required(info.get('name'), str),
                  learned=known(info.get('learned'), bool),
                  output_id=number(known(output.get('outputItemID'), int), 1),
                  output_min=known(output.get('quantityMin'), int),
                  output_max=known(output.get('quantityMax'), int),
                  reagents_status='unavailable', slots=[],
                  requirements_status='unknown', requirements=[])
    slots = raw.get('slots')
    if raw.get('schematicStatus') == 'ok' and raw.get('slotsStatus') == 'ok' and isinstance(slots, dict) and slots.get('status') == 'observed':
        result['reagents_status'] = 'known'
        for slot in array(slots.get('rows'), 16):
            slot = table(slot)
            mapped = dict(required=known(slot.get('required'), bool),
                          quantity=known(slot.get('quantityRequired'), int),
                          alternatives=[], alternatives_status='unavailable')
            choices = slot.get('choices')
            if slot.get('choicesStatus') == 'ok' and isinstance(choices, dict) and choices.get('status') == 'observed':
                alternatives = array(choices.get('rows'), 8)
                seen = set()
                for choice in alternatives:
                    choice = table(choice)
                    item = number(known(choice.get('itemID'), int), 1)
                    if item is None or known(choice.get('currencyID'), int) not in (None, 0) or item in seen:
                        mapped['alternatives'] = []
                        break
                    seen.add(item)
                    mapped['alternatives'].append(dict(id=item, name=None))
                else:
                    if alternatives:
                        mapped['alternatives_status'] = 'known'
            result['slots'].append(mapped)
    req = raw.get('requirements')
    if isinstance(req, dict) and req.get('status') in ('observed', 'partial'):
        result['requirements_status'] = 'known' if req['status'] == 'observed' else 'partial'
        for row in array(req.get('rows'), 8):
            row = table(row)
            result['requirements'].append(dict(name=known(row.get('name'), str),
                                               met=known(row.get('met'), bool),
                                               type=known(row.get('type'), int)))
    return result


def profession(capture, identity, pid=None):
    at, report = envelope(capture, identity)
    if report.get('status') != 'observed' or report.get('windowObserved') is not True:
        raise ValueError('Professions success is not an observed own-window capture.')
    source = table(report.get('source'))
    if any(known(source.get(k), bool) is not False for k in
           ('IsTradeSkillLinked', 'IsTradeSkillGuild', 'IsTradeSkillGuildMember')):
        raise ValueError('Professions own-character source is unknown.')
    prof = table(report.get('profession'))
    actual = required(prof.get('professionID'), int)
    if actual not in (197, 185) or (pid is not None and actual != pid):
        raise ValueError('Unsupported or mismatched captured profession.')
    sample = table(report.get('sample'))
    rows = array(sample.get('rows'), 100 if pid is not None else 1)
    if sample.get('status') != 'observed':
        raise ValueError('Incomplete recipe sample.')
    counts = None
    if pid is not None:
        counts = table(report.get('counts'))
        if (report.get('coverage') != 'returned-list-only' or sample.get('coverage') != 'returned-array-ended'
                or number(counts.get('scanned'), 0, 2000) is None
                or number(counts.get('learned'), 0, 100) != len(rows)
                or number(counts.get('unlearned'), 0, 2000) is None
                or type(counts.get('unknown')) is not int or counts['unknown'] != 0
                or counts['scanned'] != counts['learned'] + counts['unlearned']):
            raise ValueError('Invalid learned-capture counts or coverage.')
    elif len(rows) != 1 or sample.get('coverage') != 'one-exact-name-match':
        raise ValueError('Invalid target-recipe coverage.')
    recipes = [recipe(row) for row in rows]
    if len({r['id'] for r in recipes}) != len(recipes) or (pid is not None and any(r['learned'] is not True for r in recipes)):
        raise ValueError('Duplicate recipe or invalid learned flag.')
    skill, maximum = known(prof.get('skillLevel'), int), known(prof.get('maxSkillLevel'), int)
    if skill is not None and maximum is not None and skill > maximum:
        raise ValueError('Recorded profession rank exceeds maximum.')
    return dict(id=actual, name=required(prof.get('professionName'), str), kind='crafting',
                skill=skill, max_skill=maximum, observed_at=at, recipes=recipes,
                coverage='returned-list-only' if pid is not None else 'single-recipe-diagnostic',
                counts=dict(counts) if counts is not None else None)


def read_character(core_identity):
    """Read only the linked Core path and sibling save. Raise ValueError/OSError.

    No cache, write, profile selection or inventory mutation. Both file reads are
    repeated to detect changes; this is not proof of an atomic cross-file save.
    """
    identity = dict(table(core_identity))
    if (identity.get('environment') not in ('Test', 'Live') or identity.get('version') != '1.60.1'
            or type(identity.get('interface')) is not int or identity['interface'] != 16001
            or not isinstance(identity.get('guid'), str)
            or not re.fullmatch(r'Player-\d+-[0-9A-Fa-f]+', identity['guid'])
            or any(not isinstance(identity.get(k), str) or not identity[k] for k in ('source', 'realm', 'build'))):
        raise ValueError('Unsupported or incomplete linked Core identity.')
    source = Path(identity['source']).resolve(strict=True)
    if source.name.lower() != 'wfcore.lua':
        raise ValueError('The linked source must be WFCore.lua.')
    sibling = source.with_name('WFProfessions.lua').resolve(strict=True)
    if sibling.parent != source.parent:
        raise ValueError('Professions save must be a sibling of the linked Core save.')
    first = [fingerprint(path) for path in (source, sibling)]
    core = table(CoreData(first[0][0].decode('utf-8-sig'), max_nodes=500000).decode())
    if type(core.get('schema')) is not int or core['schema'] != 1 or core.get('producer') != 'WFCore':
        raise ValueError('Unsupported Core envelope.')
    character = table(table(core.get('characters')).get(identity['guid']))
    ident, client = table(character.get('identity')), table(character.get('client'))
    if ident.get('guid') != identity['guid'] or ident.get('realm') != identity['realm']:
        raise ValueError('Core character identity changed.')
    if any(type(client.get(k)) is not type(identity[k]) or client[k] != identity[k] for k in ('version', 'interface', 'build')):
        raise ValueError('Core client differs from the saved link.')
    data = globals_from(first[1][0], {'WFProfessionsDB', 'WFProfessionsProbeDB'})
    db = table(data.get('WFProfessionsProbeDB'))
    if type(db.get('schema')) is not int or db['schema'] != 1 or db.get('producer') != 'WFProfessionsProbe':
        raise ValueError('Unsupported Professions probe envelope.')
    characters = table(db.get('characters'))
    if len(characters) > 50:
        raise ValueError('Professions character limit exceeded.')
    char = table(characters.get(identity['guid'], {}))
    result = dict(professions=[], notes=['Historical saved observations; not current craftability.',
                  'Unlearned aggregate counts do not contain individual unlearned recipes.'], source=str(sibling))
    for mode, pid in (('learnedTailoring', 197), ('learnedCooking', 185)):
        if mode in char:
            p = profession(char[mode], identity, pid)
            attempt = char.get(mode+'Attempt')
            p['attempt'] = {'status': 'unknown', 'observed_at': None}
            if attempt is not None:
                at, report = envelope(attempt, identity)
                if at >= p['observed_at']:
                    p['attempt'] = dict(status=report.get('status', 'unknown'), observed_at=at)
                    if report.get('status') in ('unavailable', 'partial'):
                        result['notes'].append(p['name']+': last attempt refused; previous capture retained.')
            result['professions'].append(p)
    if 'targetRecipe' in char and not any(p['id'] == 197 for p in result['professions']):
        p = profession(char['targetRecipe'], identity)
        if p['id'] not in {v['id'] for v in result['professions']}:
            result['professions'].append(p)
    if 'skills' in char:
        at, report = envelope(char['skills'], identity)
        if report.get('status') == 'observed' and report.get('coverage') == 'five-profession-slots':
            seen = {p['id'] for p in result['professions']}
            for row in array(report.get('entries'), 5):
                row = table(row)
                pid, name = number(known(row.get('skillLineID'), int), 1), known(row.get('name'), str)
                if pid is None or name is None or pid in seen:
                    continue
                seen.add(pid)
                rank, maximum = known(row.get('rank'), int), known(row.get('maxRank'), int)
                if rank is not None and maximum is not None and rank > maximum:
                    raise ValueError('Recorded skill-summary rank exceeds maximum.')
                # Display classification only; never infer recipe/node coverage.
                kind = 'crafting' if pid in (197, 185) else 'gathering' if name in ('Herbalism', 'Mining', 'Skinning', 'Fishing') else 'unknown'
                result['professions'].append(dict(id=pid, name=name, kind=kind,
                    skill=rank, max_skill=maximum,
                    observed_at=at, recipes=[], coverage='skill-summary-only'))
    if not result['professions']:
        result['notes'].append('No supported profession capture recorded for this character; knowledge is Unknown.')
    second = [fingerprint(path) for path in (source, sibling)]
    if [v[1] for v in first] != [v[1] for v in second]:
        raise ValueError('Saved sources changed during reading; retry after normal logout.')
    return result
