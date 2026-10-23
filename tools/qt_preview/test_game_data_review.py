from pathlib import Path
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import tempfile
import unittest
from PySide6.QtCore import QThreadPool
from companion import Companion,QApplication
from game_data_review import read,locations,sync_status
from game_data_dialog import GameDataDialog
from probe_report import ReportError
from test_copy_and_alts import seed,files


SAVE=b'''WFCoreDB={schema=1,producer="WFCore",characters={
["Player-1-ABC"]={identity={guid="Player-1-ABC",firstName="Same",lastName="Name"},
client={version="1.60.1",interface=16001},locations={bags={latest={schema=1,addonVersion="0.2.0",owner="Player-1-ABC",scope="bags",accessible=true,coverage="attempted",unknownSlots=1,
startedAt=1792600000,finishedAt=1792600001,client={version="1.60.1",interface=16001,build="70009"},
containers={{id=0,slots=2}},slots={{bag=0,slot=1,state="observed",itemID=2589,count=3},{bag=0,slot=2,state="unknown"}}}}}},
["Player-1-DEF"]={identity={guid="Player-1-DEF",firstName="Same",lastName="Name"},client={version="1.60.1",interface=16001},locations={}}
}}'''


class GameDataTests(unittest.TestCase):
    def test_read_is_literal_only_and_missing_bank_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'WFCore.lua';path.write_bytes(SAVE)
            data=read(path);self.assertEqual(data[0].rows,((2589,3),))
            self.assertIn('Needs fuller scan',sync_status(data[0])[0])
            self.assertIn('1 slot(s)',sync_status(data[0])[1])
            resolved=replace(data[0],unknown_slots=0)
            self.assertIn('Needs sync setup',sync_status(resolved)[0])
            for sample in (replace(resolved,interrupted=True),replace(resolved,coverage='partial'),
                           replace(resolved,finished_at=None),replace(resolved,finished_at=1)):
                self.assertIn('Needs fuller scan',sync_status(sample)[0])
            self.assertIn('not confirmed empty',sync_status(None)[1])
            rows=locations(data);self.assertEqual(len(rows),2)
            self.assertIsNone(rows[1][3]);self.assertEqual(rows[1][2],'bank')
            self.assertEqual(path.read_bytes(),SAVE)
            path.write_bytes(SAVE+b' print("execute")')
            with self.assertRaises(ReportError):read(path)

    def test_dialog_review_preserves_drafts_and_files(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);source=root/'WFCore.lua';source.write_bytes(SAVE)
            w=Companion(root);w.testing=True;w.timer.stop();w.probe_page.timer.stop()
            w.inventory_page.form.load({'name':'Keep unfinished','quantity':'???'})
            before=deepcopy((w.data.active,w.data.inventories,w.data.dirty,w.inventory_page.form.values()))
            disk=files(root)
            with patch('game_data_dialog.discover',return_value=[source]):
                d=GameDataDialog(w);QThreadPool.globalInstance().waitForDone();app.processEvents()
                QThreadPool.globalInstance().waitForDone();app.processEvents()
            try:
                self.assertEqual(d.files.count(),1)
                self.assertEqual(d.table.rowCount(),2)  # Single source opens automatically.
                d.check_file();QThreadPool.globalInstance().waitForDone();app.processEvents()
                self.assertEqual(d.table.rowCount(),2)
                d.table.selectRow(0);self.assertEqual(d.items.item(0,1).text(),'3')
                self.assertIn('Unknown slots: 1',d.details.text())
                d.table.selectRow(1);self.assertEqual(d.items.rowCount(),0)
                self.assertIn('not confirmed empty',d.details.text())
                self.assertEqual(before,(w.data.active,w.data.inventories,w.data.dirty,w.inventory_page.form.values()))
                self.assertEqual(files(root),disk)
                source.write_bytes(b'bad');d.check_file();QThreadPool.globalInstance().waitForDone();app.processEvents()
                self.assertEqual(d.table.rowCount(),0);self.assertIn('Could not check',d.notice.text())
            finally:
                d.close();d.deleteLater();QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
