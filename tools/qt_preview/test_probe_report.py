"""SavedVariables fixtures are data, including deliberately executable Lua to reject."""
import json
from pathlib import Path
import tempfile
import unittest
from probe_report import decode, summarize, ReportReader, ReportError, MAX_BYTES

HEADER = 'FOREVER API PROBE 0.1.0\n'
REPORT = HEADER + '''[Build and context]
Version: OK = 1.60.1
Build: OK = 70245
[HP, active power, mana, XP]
HP: OK = 50
HP maximum: OK = 100
Mana: OK = 0
Mana maximum: OK = 0
XP: OK = 0
XP maximum: OK = 0
[Helpful buffs: player only, first 8 indices]
Aura 1.spellId: OK = 42
Aura 1.applications: OK = 1
Aura 1.duration: OK = 60
Aura 1.expirationTime: OK = 70
Aura index 2: Unknown (nil)
[Cooldowns: selected spell or first 4 known spells in action slots 1-12]
C_Spell.GetSpellCooldown: Present
C_SpellBook.IsSpellKnown: Present
No readable known spell found. Macros/items are not resolved; optional spell ID can be entered later.
[Inventory: bags 0-4, at most 4 slots per bag]
Bag 0 slot count: OK = 8
Bag 0 slot 1 record: Unknown (nil)
Bag 1 slot count: OK = 0
'''


def saved(report=REPORT):
    return ('WFStressProbeDB = { ["schema"] = 1, ["sessions"] = { { ["snapshots"] = { { ["at"] = "2026-10-21 19:01:00", ["reason"] = "Logout/reload", ["report"] = '+json.dumps(report)+' }, }, }, }, }').encode()


class ReaderTests(unittest.TestCase):
    def test_expanded_history_keeps_same_names_distinct(self):
        sessions=[]
        for i in range(30):
            sessions.append('{character={key="Player-123-'+format(i,'X')+'",name="Same Name",realm="Same Realm"},snapshots={{report="sample"}}}')
        raw=('WFStressProbeDB={schema=1,sessions={'+','.join(sessions)+'}}').encode()
        result=decode(raw)
        self.assertEqual(len(result),30)
        self.assertEqual(len({s.character_key for s in result}),30)
        self.assertEqual(len({s.character_label for s in result}),30)
        with self.assertRaises(ReportError):
            decode(('WFStressProbeDB={schema=1,sessions={'+','.join(sessions+[sessions[0]])+'}}').encode())

    def test_unknown_owner_never_inferred_from_report(self):
        self.assertEqual(decode(saved())[0].character_key,'')
        self.assertIn('Unknown character',decode(saved())[0].character_label)

    def test_full_names_are_labels_and_ids_remain_distinct(self):
        labels=[]; keys=[]
        for key,last in [('ABC','Kaiske'),('DEF','Alt')]:
            character=f'{{ character={{key="Player-123-{key}",name="Dragohorse",firstName="Dragohorse",lastName="{last}",realm="Realm"}}, ["snapshots"]'.encode()
            sample=decode(saved().replace(b'{ ["snapshots"]',character))[0]
            self.assertIn('Dragohorse '+last,sample.character_label)
            labels.append(sample.character_label);keys.append(sample.character_key)
        self.assertNotEqual(keys[0],keys[1])
        self.assertNotEqual(labels[0],labels[1])

    def test_recorded_class_disambiguates_first_names(self):
        raw=saved(REPORT+'\nPlayer class ID: OK = 2\n').replace(
            b'{ ["snapshots"]',b'{ character={key="Player-123-ABC",name="Dragohorse",realm="Realm"}, ["snapshots"]')
        sample=decode(raw)[0]
        self.assertTrue(sample.character_label.startswith('Paladin · Dragohorse'))
        self.assertNotIn('Kaiske',sample.character_label)

    def test_real_schema_and_empty_new_session_keeps_latest_snapshot(self):
        data = saved().decode().replace('}, }, }, }','}, }, {snapshots={}}, }, }')
        self.assertEqual(decode(data.encode())[-1].report,REPORT)

    def test_lua_saved_string_escapes_comments_and_indexed_arrays(self):
        raw = saved('hello\n"world"\\end').decode().replace('{ ["at"]','[1] = { ["at"]').replace('"Logout/reload"', '"Logout\\047reload" -- comment\n')
        item = decode(raw.encode())[0]
        self.assertEqual(item.reason,'Logout/reload')
        self.assertEqual(item.report,'hello\n"world"\\end')

    def test_code_and_ambiguous_data_rejected(self):
        for data in (b'WFStressProbeDB = os.execute("bad")',saved()+b'; print("bad")',
                     b'WFStressProbeDB = {schema=1,schema=1,sessions={}}',
                     b'WFStressProbeDB = {schema=true,sessions={}}',
                     saved().replace(b'"schema"] = 1',b'"schema"] = 2'),
                     b'WFStressProbeDB = '+b'{'*20+b'}'*20,
                     saved()[:-7], b'WFStressProbeDB = {schema=1,sessions={[2]={}}}'):
            with self.subTest(data=data[:50]), self.assertRaises(ReportError): decode(data)

    def test_size_limit(self):
        with self.assertRaises(ReportError): decode(b' '*(MAX_BYTES+1))

    def test_summary_never_confuses_presence_zero_or_partial_inventory(self):
        rows = {n:s for n,s,_ in summarize(REPORT)}
        self.assertEqual(rows,{'HP':'Working · sample','Mana':'Working · sample','XP':'Working · sample','Buffs':'Working · sample','Cooldowns':'Not tested','Inventory':'Partial'})
        for value,status in [('Restricted','Restricted'),('Guard unavailable','Unknown'),('Missing API','Missing API'),('API error','Error'),('Unknown (nil)','Partial')]:
            rows = {n:s for n,s,_ in summarize(REPORT.replace('HP maximum: OK = 100','HP maximum: '+value))}
            self.assertEqual(rows['HP'],status)

    def test_context_and_unrecognized_report(self):
        for report in (HEADER+'[Character checks]\nUnavailable: login/world/player context is not confirmed.',REPORT.replace('0.1.0','0.2.0')):
            self.assertTrue(all(s=='Not tested' for _,s,_ in summarize(report)))
        self.assertTrue(all(s=='Error' for _,s,_ in summarize('Probe internal error.')))

    def test_cooldown_read_restricted_and_nil_buffs(self):
        text = REPORT.replace('C_Spell.GetSpellCooldown: Present', 'Cooldown.startTime: OK = 0\nCooldown.duration: OK = 0\nCooldown.isEnabled: OK = true\nCooldown.modRate: OK = 1')
        self.assertEqual(dict((n,s) for n,s,_ in summarize(text))['Cooldowns'],'Working · sample')
        text = text.replace('Cooldown.duration: OK = 0','Cooldown.duration: Restricted')
        self.assertEqual(dict((n,s) for n,s,_ in summarize(text))['Cooldowns'],'Restricted')
        self.assertEqual(summarize(HEADER+'[Helpful buffs: player only, first 8 indices]\nAura index 1: Unknown (nil)')[3][1],'Unknown')

    def test_discovery_partial_write_recovery_no_writes_and_primary_only(self):
        with tempfile.TemporaryDirectory() as root:
            client = Path(root); reader = ReportReader(client)
            self.assertIsNone(reader.poll()[0])
            path = client/'WTF/Account/test/SavedVariables/WFStressProbe.lua'
            path.parent.mkdir(parents=True); path.with_suffix('.lua.bak').write_bytes(saved())
            self.assertIsNone(reader.poll()[0])
            path.write_bytes(saved()); loaded,error = reader.poll()
            self.assertFalse(error); self.assertEqual(path.read_bytes(),saved())
            self.assertIs(reader.poll()[0],loaded)
            path.write_bytes(b'WFStressProbeDB = {')
            self.assertIsNone(reader.poll()[0]); self.assertIs(reader.cached,loaded)
            path.write_bytes(saved(REPORT.replace('HP: OK = 50','HP: Restricted')))
            updated,error = reader.poll(); self.assertFalse(error); self.assertEqual(updated[4][0][1],'Restricted')
            path.unlink(); self.assertIsNone(reader.poll()[0])


if __name__ == '__main__': unittest.main()
