from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from copy import deepcopy
from companion import Companion,QApplication
from saved_character_header import decode_character,HeaderObservations

LINK={'name':'Tiny Atonement','realm':'Realm','guid':'Player-1-ABC'}
MAPPING=b'DataStore_CharacterIDs={List={[1]="Default.Realm.Tiny Atonement"},Set={["Default.Realm.Tiny Atonement"]=1},Count=1};DataStore_CharacterGUIDs={[1]="Player-1-ABC"}'
INFO=b'DataStore_Characters_Info={[1]={name="Tiny Atonement",BaseInfo=2898570,lastUpdate=1792711839}}'


class HeaderTests(TestCase):
    def test_packed_fields_and_saved_time(self):
        self.assertEqual(decode_character(INFO,MAPPING,LINK),('Priest',10,1792711839))
        self.assertEqual(decode_character(INFO.replace(b'2898570',b'982018'),MAPPING,LINK)[:2],('Mage',2))

    def test_wrong_identity_and_lua_code_rejected(self):
        for mapping in (MAPPING.replace(b'Player-1-ABC',b'Player-1-DEF'),
                        MAPPING.replace(b'Realm',b'Other'),
                        MAPPING.replace(b'[1]="Player-1-ABC"',b'[1]="Player-1-ABC",[2]="Player-1-ABC"')):
            with self.assertRaises(ValueError):decode_character(INFO,mapping,LINK)
        with self.assertRaises(ValueError):decode_character(INFO+b';print("execute")',MAPPING,LINK)
        with self.assertRaises(ValueError):decode_character(INFO.replace(b'2898570',b'true'),MAPPING,LINK)

    def test_unknown_values_and_unlinked_profile(self):
        self.assertEqual(decode_character(INFO.replace(b'2898570',b'0'),MAPPING,LINK)[:2],('Unknown class',None))
        with TemporaryDirectory() as tmp:
            self.assertEqual(HeaderObservations().describe(Path(tmp),'missing')[0],'No saved character details')

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
