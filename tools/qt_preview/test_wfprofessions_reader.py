"""Synthetic temporary files only; no installed addons or real saved data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wfprofessions_reader as reader


def lua(value):
    if isinstance(value, dict):
        return '{'+','.join('['+lua(k)+']='+lua(v) for k, v in value.items())+'}'
    if isinstance(value, str):
        return '"'+value.replace('\\', '\\\\').replace('"', '\\"')+'"'
    if value is None:
        return 'nil'
    if type(value) is bool:
        return 'true' if value else 'false'
    return str(value)


def known(value):
    return {'status': 'known', 'value': value}


def sample():
    return dict(id=known(3755), infoStatus='ok',
        info=dict(recipeID=known(3755), name=known('Linen Bag'), learned=known(True)),
        schematicStatus='ok', output=dict(outputItemID=known(4238), quantityMin=known(1), quantityMax=known(1)),
        slotsStatus='ok', slots=dict(status='observed', rows={1:dict(quantityRequired=known(3), required=known(True),
            choicesStatus='ok', choices=dict(status='observed', rows={1:dict(itemID=known(2996))}))}),
        requirementsStatus='ok', requirements=dict(status='observed', rows={}))


def capture():
    return dict(at=100, provenance='live-probe', client={k:known(v) for k,v in
        dict(version='1.60.1', interface=16001, build='70532').items()},
        report=dict(status='observed', windowObserved=True, coverage='returned-list-only',
            source={k:known(False) for k in ('IsTradeSkillLinked','IsTradeSkillGuild','IsTradeSkillGuildMember')},
            profession=dict(professionID=known(197), professionName=known('Tailoring'), skillLevel=known(18), maxSkillLevel=known(75)),
            counts=dict(scanned=3, learned=1, unlearned=2, unknown=0),
            sample=dict(status='observed', coverage='returned-array-ended', rows={1:sample()})))


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.link = dict(source=str(self.root/'WFCore.lua'), environment='Test', realm='Realm',
            guid='Player-1-ABC', version='1.60.1', interface=16001, build='70532', name='Example')
        self.core = dict(schema=1, producer='WFCore', characters={self.link['guid']:dict(
            identity=dict(guid=self.link['guid'], realm='Realm', firstName='Example'),
            client=dict(version='1.60.1', interface=16001, build='70532'))})
        self.char = dict(learnedTailoring=capture())
        self.db = dict(schema=1, producer='WFProfessionsProbe', characters={self.link['guid']:self.char})
        self.write()

    def write(self):
        (self.root/'WFCore.lua').write_text('WFCoreDB='+lua(self.core), encoding='utf-8')
        (self.root/'WFProfessions.lua').write_text('WFProfessionsDB={schema=1,producer="WFProfessions",characters={},settings={}}\nWFProfessionsProbeDB='+lua(self.db), encoding='utf-8')

    def test_learned_reagents_and_counts_without_writes(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        p=reader.read_character(self.link)['professions'][0]
        self.assertEqual(p['counts'], dict(scanned=3,learned=1,unlearned=2,unknown=0))
        self.assertEqual(len(p['recipes']),1)
        self.assertEqual(p['recipes'][0]['slots'][0], dict(required=True,quantity=3,
            alternatives_status='known',alternatives=[dict(id=2996,name=None)]))
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_alt_without_capture_is_unknown_not_previous_character(self):
        guid='Player-1-DEF'
        self.core['characters'][guid]=deepcopy(self.core['characters'][self.link['guid']])
        self.core['characters'][guid]['identity']['guid']=guid
        self.write()
        self.assertEqual(len(reader.read_character(self.link)['professions']),1)
        view=reader.read_character(dict(self.link,guid=guid))
        self.assertEqual(view['professions'],[])
        self.assertIn('Unknown',view['notes'][-1])

    def test_refused_attempt_keeps_success_age_and_rows(self):
        self.char['learnedTailoringAttempt']=capture()
        self.char['learnedTailoringAttempt'].update(at=110,report={'status':'unavailable'})
        self.write()
        result=reader.read_character(self.link)
        self.assertEqual(result['professions'][0]['observed_at'],100)
        self.assertEqual(result['professions'][0]['attempt']['observed_at'],110)
        self.assertIn('refused',result['notes'][-1])

    def test_unknown_required_quantity_and_currency_not_invented(self):
        row=self.char['learnedTailoring']['report']['sample']['rows'][1]
        slot=row['slots']['rows'][1]
        slot['required']={'status':'restricted'}
        slot['quantityRequired']={'status':'unknown'}
        slot['choices']['rows'][1]={'currencyID':known(2996)}
        self.write()
        slot=reader.read_character(self.link)['professions'][0]['recipes'][0]['slots'][0]
        self.assertIsNone(slot['quantity']);self.assertIsNone(slot['required'])
        self.assertEqual(slot['alternatives'],[])
        self.assertEqual(slot['alternatives_status'],'unavailable')

    def test_partial_materials_and_separate_unmet_requirements(self):
        row=self.char['learnedTailoring']['report']['sample']['rows'][1]
        row['slots']['status']='partial'
        row['requirements']['rows']={1:dict(name=known('Cooking Fire'),met=known(False))}
        self.write()
        r=reader.read_character(self.link)['professions'][0]['recipes'][0]
        self.assertEqual(r['slots'],[]);self.assertEqual(r['reagents_status'],'unavailable')
        self.assertEqual(r['requirements'][0]['met'],False)

    def test_synthetic_and_client_mismatch_rejected(self):
        for mutate in (lambda c:c.update(provenance='synthetic-probe'),
                       lambda c:c['client'].update(build=known('other'))):
            self.char['learnedTailoring']=capture();mutate(self.char['learnedTailoring']);self.write()
            with self.assertRaises(ValueError):reader.read_character(self.link)

    def test_invalid_coverage_flags_duplicate_and_sparse_rows_rejected(self):
        mutations=[lambda r:r['counts'].update(unknown=1),
            lambda r:r['source'].update(IsTradeSkillLinked=known(True)),
            lambda r:r['sample']['rows'][1]['info'].update(learned={'status':'unknown'}),
            lambda r:r['sample'].update(rows={2:sample()}),
            lambda r:(r['sample'].update(rows={1:sample(),2:sample()}),r['counts'].update(scanned=4,learned=2))]
        for mutate in mutations:
            self.char['learnedTailoring']=capture();mutate(self.char['learnedTailoring']['report']);self.write()
            with self.assertRaises(ValueError):reader.read_character(self.link)

    def test_core_link_identity_must_match(self):
        for field,value in (('realm','Other'),('build','other'),('guid','Player-1-FFF'),('interface',True)):
            with self.assertRaises(ValueError):reader.read_character(dict(self.link,**{field:value}))

    def test_target_fallback_and_learned_precedence(self):
        target=capture();target['report']['sample']['coverage']='one-exact-name-match'
        target['report']['sample']['rows'][1]['info']['learned']=known(False)
        self.char['targetRecipe']=target;self.write()
        self.assertTrue(reader.read_character(self.link)['professions'][0]['recipes'][0]['learned'])
        del self.char['learnedTailoring'];self.write()
        p=reader.read_character(self.link)['professions'][0]
        self.assertFalse(p['recipes'][0]['learned'])
        self.assertEqual(p['coverage'],'single-recipe-diagnostic')

    def test_two_professions_keep_independent_ages_requirements_and_attempts(self):
        cooking=capture();cooking['at']=120
        cooking['report']['profession'].update(professionID=known(185),professionName=known('Cooking'))
        cooking['report']['sample']['rows'][1]['requirements']['rows']={1:dict(name=known('Flint and Tinder'),met=known(False))}
        self.char['learnedCooking']=cooking
        self.char['targetRecipe']={'provenance':'synthetic-probe'}
        self.write()
        p=reader.read_character(self.link)['professions']
        self.assertEqual([(r['id'],r['observed_at']) for r in p],[(197,100),(185,120)])
        self.assertEqual(p[0]['recipes'][0]['requirements'],[])
        self.assertFalse(p[1]['recipes'][0]['requirements'][0]['met'])

    def test_oversized_file_rejected_before_parsing(self):
        with (self.root/'WFProfessions.lua').open('wb') as stream:
            stream.truncate(16*1024*1024+1)
        with self.assertRaisesRegex(ValueError,'16 MiB'):reader.read_character(self.link)

    def test_gathering_skill_summary_does_not_invent_recipes(self):
        self.char['skills']=capture()
        self.char['skills']['report']=dict(status='observed',coverage='five-profession-slots',entries={
            1:dict(name=known('Herbalism'),skillLineID=known(182),rank=known(7),maxRank=known(75)),
            2:dict(name=known('Unknown profession'),skillLineID=known(999))})
        self.write()
        p=reader.read_character(self.link)['professions']
        self.assertEqual(p[1]['kind'],'gathering');self.assertEqual(p[1]['recipes'],[])
        self.assertEqual(p[1]['coverage'],'skill-summary-only');self.assertEqual(p[2]['kind'],'unknown')

    def test_missing_file_and_nonliteral_inputs_rejected(self):
        path=self.root/'WFProfessions.lua'
        for data in ('WFProfessionsProbeDB=os.execute("bad")','WFProfessionsProbeDB={}\nWFProfessionsProbeDB={}','WFProfessionsProbeDB={'):
            path.write_text(data)
            with self.assertRaises(ValueError):reader.read_character(self.link)
        path.unlink()
        with self.assertRaises(OSError):reader.read_character(self.link)

    def test_unstable_read_rejected(self):
        original=reader.fingerprint
        calls=[]
        def changing(path):
            data,stamp=original(path);calls.append(path)
            if len(calls)==4:stamp=(stamp[0],stamp[1]+1,stamp[2])
            return data,stamp
        with patch.object(reader,'fingerprint',changing):
            with self.assertRaisesRegex(ValueError,'changed during'):reader.read_character(self.link)


if __name__=='__main__':unittest.main()
