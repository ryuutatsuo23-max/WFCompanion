from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from copy import deepcopy
import json
from companion import Companion,QApplication
from saved_character_header import decode_character,decode_details,HeaderObservations,FIELDS,UNKNOWN
from test_core_inventory_v2 import lua

LINK={'name':'Tiny Atonement','realm':'Realm','guid':'Player-1-ABC','version':'1.60.1','interface':16001,'environment':'Test','build':'70532','source':'unused'}
DETAILS=dict(schema=1,classID=5,classToken='PRIEST',className='Priest',level=10,observedAt=1792711839,status={k:'ok' for k in FIELDS})

def saved(details=DETAILS):
    character=dict(identity=dict(guid=LINK['guid'],firstName='Tiny',lastName='Atonement',realm='Realm'),client=dict(version='1.60.1',interface=16001),locations={})
    if details is not None:character['details']=details
    return ('WFCoreDB='+lua(dict(schema=1,producer='WFCore',characters={LINK['guid']:character}))).encode()

class HeaderTests(TestCase):
    def test_core_details_without_datastore(self):
        self.assertEqual(decode_character(saved(),LINK),('Priest',10,1792711839))

    def test_inventory_damage_does_not_hide_header_details(self):
        from core_observations import CoreData,decode
        db=CoreData(saved().decode()).decode()
        db['inventorySchema']=99
        db['characters'][LINK['guid']]['locations']={'bags':{'latest':{'schema':99}}}
        db['characters']['Player-1-DEF']={'locations':'damaged'}
        raw=('WFCoreDB='+lua(db)).encode()
        with self.assertRaises(ValueError):decode(raw)
        self.assertEqual(decode_character(raw,LINK),('Priest',10,DETAILS['observedAt']))

    def test_header_envelope_and_linked_identity_stay_strict(self):
        from core_observations import CoreData
        baseline=CoreData(saved().decode()).decode()
        changes=[lambda db:db.update(schema=True),lambda db:db.update(producer='Other'),
                 lambda db:db.update(characters=False),lambda db:db['characters'].update({LINK['guid']:False}),
                 lambda db:db['characters'][LINK['guid']]['identity'].update(guid='Player-1-DEF'),
                 lambda db:db['characters'][LINK['guid']]['identity'].update(firstName=12),
                 lambda db:db['characters'][LINK['guid']].update(client=False),
                 lambda db:db['characters'][LINK['guid']]['client'].update(version='future')]
        for change in changes:
            db=deepcopy(baseline);change(db)
            with self.assertRaises(ValueError):decode_character(('WFCoreDB='+lua(db)).encode(),LINK)

    def test_missing_future_and_malformed_status_are_unknown(self):
        for details in (None,{},dict(DETAILS,schema=2),dict(DETAILS,schema=True),dict(DETAILS,status={}),dict(DETAILS,status=dict.fromkeys(FIELDS,'yes'))):
            self.assertEqual(decode_character(saved(details),LINK),UNKNOWN)

    def test_unknown_replaces_stale_values_and_keeps_partial_fields(self):
        record=deepcopy(DETAILS);record['status']['level']='unknown';record['status']['observedAt']='unknown'
        self.assertEqual(decode_details(record),('Priest',None,None))
        record['status']['className']='unknown'
        self.assertEqual(decode_details(record)[0],'Priest')
        record['status']['classToken']='unknown';record['status']['classID']='unknown'
        self.assertEqual(decode_details(record),UNKNOWN)

    def test_invalid_values_and_conflicting_class(self):
        for value in (True,0,-1,1001,'10'):
            self.assertIsNone(decode_details(dict(DETAILS,level=value))[1])
        for value in (True,0,9007199254740992,'now'):
            self.assertIsNone(decode_details(dict(DETAILS,observedAt=value))[2])
        self.assertEqual(decode_details(dict(DETAILS,classToken='MAGE'))[0],'Unknown class')
        record=deepcopy(DETAILS);record.update(classID=0,classToken='bad-token',className='|cfffFake')
        self.assertEqual(decode_details(record)[0],'Unknown class')

    def test_guid_realm_client_and_executable_content_rejected(self):
        for field,value in (('guid','Player-1-DEF'),('realm','Other'),('version','Other'),('interface',1),('name','Other')):
            with self.assertRaises(ValueError):decode_character(saved(),dict(LINK,**{field:value}))
        with self.assertRaises(ValueError):decode_character(saved()+b';print("execute")',LINK)

    def test_refresh_cache_unknown_and_alt_isolation_without_writes(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'WFCore.lua';source.write_bytes(saved())
            linked=dict(LINK,source=str(source))
            (root/'character_links.json').write_text(json.dumps({'version':1,'links':[{'profile':'one','identity':linked}]}))
            header=HeaderObservations();before=source.read_bytes()
            self.assertIn('Priest',header.describe(root,'one')[0]);self.assertEqual(source.read_bytes(),before)
            with patch('saved_character_header.decode_character',side_effect=AssertionError('redundant parse')):
                self.assertIn('Priest',header.describe(root,'one')[0])
            source.write_bytes(saved(dict(DETAILS,level=11))+b'\n')
            self.assertIn('Level 11',header.describe(root,'one')[0])
            self.assertEqual(header.describe(root,'alt')[0],'No saved character details')
            source.write_bytes(saved(None))
            self.assertIn('Level Unknown',header.describe(root,'one')[0])
            source.write_bytes(saved(dict(DETAILS,observedAt=9007199254740991)))
            text=header.describe(root,'one')[0]
            self.assertIn('Priest',text);self.assertIn('Observation time Unknown',text)

    def test_planning_control_moves_without_changing_manual_profiles(self):
        from companion import Companion,QApplication
        from PySide6.QtCore import QThreadPool
        from test_copy_and_alts import seed
        app=QApplication.instance() or QApplication([])
        with TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True
            w.updates_panel.timer.stop();w.saved_character_connection.timer.stop()
            original=deepcopy(w.data.profiles)
            try:
                self.assertTrue(w.planning_settings.isAncestorOf(w.preset))
                with patch.object(w.header_observations,'describe',return_value=('Priest · Level 10 · Saved yesterday','Saved only')):
                    w.refresh_character_header()
                self.assertEqual(w.character_info.text(),'Priest · Level 10 · Saved yesterday')
                self.assertEqual(w.data.profiles,original)
                w.show_page('Settings');w.preset.setCurrentText('Tank')
                self.assertEqual(w.data.playstyles.active(w.data.active),'Tank')
                self.assertEqual(w.data.profiles,original)
            finally:
                w.close();w.deleteLater();QThreadPool.globalInstance().waitForDone();app.processEvents()


if __name__=='__main__':main()
