"""Exercise the real worker and Activity panel with disposable saves and reports."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from PySide6.QtTest import QTest
from PySide6.QtCore import QThreadPool
from companion import Companion, QApplication
from probe_report import ReportReader
from test_probe_report import saved, REPORT


def fingerprint(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


class ProbePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def wait(self,page):
        for _ in range(500):
            self.app.processEvents()
            if not page.busy: return
            QTest.qWait(10)
        self.fail('Report worker did not finish.')

    def test_refresh_preserves_drafts_settings_and_all_files(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); state = root/'state'; client = root/'client'
            path = client/'WTF/Account/test/SavedVariables/WFStressProbe.lua'
            path.parent.mkdir(parents=True); path.write_bytes(saved())
            w = Companion(state); w.testing = True; w.timer.stop()
            try:
                page = w.probe_page; self.wait(page); page.reader = ReportReader(client)
                w.inventory_page.form.load({'name':'Unfinished inventory','quantity':'not yet entered'})
                w.profile_page.form.load({'name':'Unfinished character'})
                before = fingerprint(root); settings = deepcopy(w.settings)
                w.settings['text_size'] = 18; w.apply_appearance()
                w.show_page('Activity');w.toggle_diagnostics(); w.show(); page.refresh(); self.wait(page)
                self.assertEqual(page.table.item(0,1).text(),'Working · sample')
                self.assertTrue(page.timer.isActive())
                self.assertEqual(fingerprint(root),before)
                self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished inventory')
                self.assertEqual(w.profile_page.form.values()['name'],'Unfinished character')
                self.assertEqual(w.settings,{**settings,'text_size':18})
                self.assertIn('Unknown character',page.owner.text())
                page.history.setCurrentIndex(1)
                pinned=page.history.currentData()
                page.refresh(); self.wait(page)
                self.assertEqual(page.history.currentData(),pinned)
                self.assertEqual(fingerprint(root),before)
                self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished inventory')
                page.history.setCurrentIndex(0)
                path.write_bytes(b'WFStressProbeDB = {'); page.refresh(); self.wait(page)
                self.assertIn('not current',page.notice.text())
                self.assertEqual(page.table.item(0,1).text(),'Working · sample')
                path.write_bytes(saved(REPORT.replace('HP: OK = 50','HP: Restricted')))
                page.refresh(); self.wait(page)
                self.assertEqual(page.table.item(0,1).text(),'Restricted')
                # Actual QTimer path, including a changed file after a reload.
                page.timer.setInterval(20); path.write_bytes(saved())
                for _ in range(200):
                    QTest.qWait(10)
                    if page.table.item(0,1).text()=='Working · sample': break
                self.assertEqual(page.table.item(0,1).text(),'Working · sample')
                w.show_page('Overview'); self.app.processEvents()
                self.assertFalse(page.timer.isActive())
                self.assertEqual(fingerprint(root),before)
            finally:
                page.timer.stop(); QThreadPool.globalInstance().waitForDone(); self.app.processEvents()
                w.close(); w.deleteLater(); self.app.processEvents()


if __name__ == '__main__': unittest.main()
