"""Adversarial schema-2 validation using the addon's synthetic contract fixture."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
from core_observations import CoreData,decode
from probe_report import ReportError
from game_data_review import sync_status
from test_game_data_review import SAVE


def lua(value):
    if value is True:return 'true'
    if value is False:return 'false'
    if value is None:return 'nil'
    if isinstance(value,str):return json.dumps(value)
    if isinstance(value,int):return str(value)
    return '{'+','.join('['+lua(k)+']='+lua(v) for k,v in value.items())+'}'


class SchemaTwoTests(unittest.TestCase):
    def setUp(self):
        raw=(Path(__file__).resolve().parents[2]/'tests/fixtures/WFCore_schema2_example.lua').read_text(encoding='utf-8')
        self.db=CoreData(raw,max_nodes=4_000_000).decode()

    def decoded(self,db=None):return decode(('WFCoreDB='+lua(db or self.db)).encode())

    def test_complete_empty_partial_and_legacy_stay_separate(self):
        values=self.decoded();self.assertEqual(len(values),3)
        bank=next(o for o in values if o.scope=='bank')
        self.assertEqual((bank.empty_slots,bank.observed_slots,bank.rows),(4,0,()))
        self.assertIn('Complete saved scan',sync_status(bank)[0])
        bags=[o for o in values if o.scope=='bags']
        self.assertEqual(len(bags),2);self.assertEqual(sum(o.interrupted for o in bags),1)
        self.assertIn('Needs fuller scan',sync_status(next(o for o in bags if o.interrupted))[0])
        legacy=CoreData(SAVE.decode()).decode()['characters']['Player-1-ABC']
        self.db['characters']['Player-1-ABC']['locations']['bank']['legacyV1']=deepcopy(legacy['locations']['bags'])
        self.assertEqual(len(self.decoded()),3)  # Archive is not another current scan.
        legacy['identity']['guid']='Player-1-DEF'
        legacy['locations']['bags']['latest']['owner']='Player-1-DEF'
        self.db['characters']['Player-1-DEF']=legacy
        self.assertEqual([o.schema for o in self.decoded()].count(1),1)

    def test_tampered_evidence_is_rejected(self):
        cases=[lambda s:s.update(owner='Player-1-DEF'),
               lambda s:s['identity'].update(guid='Player-1-DEF'),
               lambda s:s.update(addonVersion='9.0'),
               lambda s:s.update(finishedAt=1),
               lambda s:s.update(expectedSlots=99),
               lambda s:s.update(emptySlots=3),
               lambda s:s.update(completed=False),
               lambda s:s['slots'][1].update(presence=True),
               lambda s:s['slots'][1].update(itemStatus='error'),
               lambda s:s['slots'][1].update(itemID=100),
               lambda s:s['slots'][1].update(slot=2),
               lambda s:s['containers'][1].update(freeSlotsEnd=3),
               lambda s:s['containers'][1].update(sizeStable=False),
               lambda s:s['containers'][1].update(observedSlots=True),
               lambda s:s['expectedContainers'].pop(9)]
        for mutate in cases:
            with self.subTest(mutation=cases.index(mutate)):
                db=deepcopy(self.db);mutate(db['characters']['Player-1-ABC']['locations']['bank']['latest'])
                with self.assertRaises(ReportError):self.decoded(db)
        for schema in (None,3,True):
            db=deepcopy(self.db);db['inventorySchema']=schema
            with self.assertRaises(ReportError):self.decoded(db)

    def test_storage_split_keeps_contract_and_evidence_checks(self):
        from dataclasses import replace
        baseline=self.decoded()
        for record in self.db['characters'].values():
            for location in record['locations'].values():
                for kind in ('latest','attempt'):
                    if kind in location:location[kind]['addonVersion']='0.7.0'
        parsed=self.decoded()
        self.assertEqual(tuple(replace(o,producer_version='') for o in parsed),
                         tuple(replace(o,producer_version='') for o in baseline))
        self.assertTrue(all(o.producer_version=='0.7.0' for o in parsed))
        self.db['characters']['Player-1-ABC']['locations']['bank']['latest']['slots'][1]['presence']=True
        with self.assertRaises(ReportError):self.decoded()


if __name__=='__main__':unittest.main()
