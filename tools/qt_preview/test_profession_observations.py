"""Invented fixtures only; never reads a game installation or personal saves."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import profession_observations as po


def lua(value):
    if isinstance(value, dict):
        return '{' + ','.join('['+lua(k)+']='+lua(v) for k, v in value.items()) + '}'
    if type(value) is bool:
        return 'true' if value else 'false'
    return json.dumps(value)


def fixture():
    return {1: {'lastUpdate': 1000, 'Indices': {'Example craft': 1}, 'Ranks': {1: 4915212},
                'Professions': {1: {'Name': 'Example craft', 'Crafts': {7: {1: 115200174}}}}},
            2: {'Professions': {}, 'Indices': {}, 'Ranks': {}}}


def inputs(chars=None, guids=None, categories=None):
    chars = fixture() if chars is None else chars
    guids = {1: 'Player-999-ABC1', 2: 'Player-999-ABC2'} if guids is None else guids
    return (('DataStore_Crafts_Characters='+lua(chars)+'\nDataStore_Crafts_RecipeCategories='
             +lua({7: 'Example category'} if categories is None else categories)).encode(),
            ('DataStore_CharacterGUIDs='+lua(guids)).encode())


class ReaderTests(unittest.TestCase):
    def test_packed_rank_recipe_and_provenance(self):
        result = po.decode(*inputs(), now=2000)
        p = result['characters'][0]['professions'][0]
        self.assertEqual((p['rank'], p['max']), (12, 75))
        self.assertEqual(p['recipes'][0]['id'], 900001)
        self.assertEqual(p['recipes'][0]['fields'], (True, 2, 1, 1))
        self.assertEqual(p['recipes'][0]['categories'], {7: 'Example category'})
        self.assertEqual(result['state'], 'cached')
        self.assertEqual(result['coverage'], 'unknown')

    def test_zero_missing_and_unknown_categories(self):
        for ranks, expected in (({}, None), ({1: 0}, 0)):
            c = fixture(); c[1]['Ranks'] = ranks
            p = po.decode(*inputs(c, categories={}))['characters'][0]['professions'][0]
            self.assertEqual(p['rank'], expected)
            self.assertEqual(p['recipes'][0]['categories'][7], 'Category name unknown')

    def test_unlearned_and_empty_are_not_complete_knowledge(self):
        c = fixture(); c[1]['Professions'][1]['Crafts'][7][1] &= ~4
        p = po.decode(*inputs(c))['characters'][0]['professions'][0]
        self.assertFalse(p['recipes'][0]['fields'][0])
        for empty in ({}, None):
            c = fixture()
            if empty is None: del c[1]['Professions'][1]['Crafts']
            else: c[1]['Professions'][1]['Crafts'] = empty
            p = po.decode(*inputs(c))['characters'][0]['professions'][0]
            self.assertEqual(p['recipes'], []); self.assertEqual(p['coverage'], 'unknown')

    def test_missing_mapping_and_two_accounts_never_merge(self):
        a = po.decode(*inputs(guids={}))
        self.assertIsNone(a['characters'][0]['guid'])
        b = po.decode(*inputs(guids={1: 'Player-777-DEF1'}))
        self.assertNotEqual(b['characters'][0]['guid'], po.decode(*inputs())['characters'][0]['guid'])
        self.assertEqual(len(b['characters']), 2)

    def test_bad_mapping_and_indices(self):
        for guids in ({1: 'Player-999-ABC1', 2: 'Player-999-ABC1'}, {1: 'name'}, {True: 'Player-999-ABC1'}):
            with self.assertRaises(ValueError): po.decode(*inputs(guids=guids))
        c = fixture(); c[1]['Indices']['Example craft'] = 2
        with self.assertRaises(ValueError): po.decode(*inputs(c))

    def test_display_names_require_reciprocal_mapping_and_guid(self):
        a, b = inputs()
        ids = {'List': {1: 'Default.Realm One.Example Hero', 2: 'Default.Realm Two.Example Hero'},
               'Set': {'Default.Realm One.Example Hero': 1, 'Default.Realm Two.Example Hero': 2}, 'Count': 2}
        data = b + b'\nDataStore_CharacterIDs=' + lua(ids).encode()
        chars = po.decode(a, data)['characters']
        self.assertEqual(chars[0]['label'], {'name': 'Example Hero', 'realm': 'Realm One'})
        self.assertNotEqual(chars[0]['guid'], chars[1]['guid'])
        _, missing = inputs(guids={})
        self.assertIsNone(po.decode(a, missing+b'\nDataStore_CharacterIDs='+lua(ids).encode())['characters'][0]['label'])
        ids['Set']['Default.Realm One.Example Hero'] = 2
        with self.assertRaises(ValueError): po.decode(a, b+b'\nDataStore_CharacterIDs='+lua(ids).encode())

    def test_numeric_domains(self):
        for value in (True, 1.0, -1, 2**53, 0, '115200174'):
            c = fixture(); c[1]['Professions'][1]['Crafts'][7][1] = value
            with self.assertRaises(ValueError): po.decode(*inputs(c))
        for value in (True, 1.0, -1, 2**32, 76+(75<<16)):
            c = fixture(); c[1]['Ranks'][1] = value
            with self.assertRaises(ValueError): po.decode(*inputs(c))

    def test_duplicates_and_rank_chain(self):
        c = fixture(); c[1]['Professions'][1]['Crafts'][8] = {1: 115200174}
        p = po.decode(*inputs(c))['characters'][0]['professions'][0]
        self.assertEqual(len(p['recipes']), 1)
        self.assertEqual(len(p['recipes'][0]['categories']), 2)
        c[1]['Professions'][1]['Crafts'][8][1] &= ~4
        with self.assertRaises(ValueError): po.decode(*inputs(c))

    def test_literal_only_and_limits(self):
        a, b = inputs()
        bad = [a+b' print(1)', a+b' DataStore_Crafts_Characters={}', a[:-1],
               b'DataStore_Crafts_Characters={[1]={},[1]={}}',
               b'DataStore_Crafts_Characters=os.execute("x")',
               b'DataStore_Crafts_Characters='+b'{'*20+b'}'*20,
               b'DataStore_Crafts_Characters={x=setmetatable({},{})}']
        for value in bad:
            with self.subTest(value=value[:50]):
                with self.assertRaises(ValueError): po.decode(value, b)
        with patch.object(po, 'LIMIT', 10):
            with self.assertRaises(ValueError): po.decode(a, b)

    def test_timestamp_unknown_future(self):
        for value in (None, -1, True, '100', 0):
            self.assertEqual(po.timestamp_label(value, 2000), 'Unknown age')
        self.assertIn('Clock mismatch', po.timestamp_label(3000, 2000))

    def test_read_only_cache_failure_retention_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root/'_classic_beta_'/'WTF'/'Account'/'Invented'/'SavedVariables'
            d.mkdir(parents=True)
            a, b = inputs()
            (d/'DataStore_Crafts.lua').write_bytes(a); (d/'DataStore.lua').write_bytes(b)
            for name in ('recipes.json', 'goals.json', 'stock.json', 'completion.json', 'WFCore.lua'):
                (root/name).write_bytes(b'unchanged')
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            cache = po.ObservationCache(); self.assertTrue(cache.refresh(d)); accepted = cache.accepted
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})
            original = po.fingerprint; calls = []
            def changing(path):
                data, stamp = original(path); calls.append(path)
                return data, (stamp[0], stamp[1]+(1 if len(calls)>2 else 0), stamp[2])
            with patch.object(po, 'fingerprint', changing):
                self.assertFalse(cache.refresh(d))
            self.assertIs(cache.accepted, accepted); self.assertTrue(cache.error)
            (d/'DataStore_Crafts.lua').write_bytes(a[:-1])
            self.assertFalse(cache.refresh(d)); self.assertIs(cache.accepted, accepted)
            self.assertFalse(cache.refresh(root)); self.assertIs(cache.accepted, accepted)
            self.assertEqual((d/'DataStore.lua').read_bytes(), b)


if __name__ == '__main__':
    unittest.main()
