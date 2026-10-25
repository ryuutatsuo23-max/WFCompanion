"""Display-mode checks use disposable state and preserve unfinished plans."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QThreadPool
from companion import Companion,QApplication
from inventory import InventoryBook,InventoryEntry
from professions import Material,Requirement
from presentation import simple_requirement
from test_copy_and_alts import seed,files,STAMP


class PlanningPresentationTests(unittest.TestCase):
    def test_unknown_and_zero_requirements(self):
        for owned,needed,expected in ((None,5,('Not checked yet','Not checked yet')),
                                     (0,5,('0','5')),(3,5,('3','2')),
                                     (8,5,('8','Ready')),(None,0,('Not checked yet','Ready'))):
            with self.subTest(owned=owned,needed=needed):
                self.assertEqual(simple_requirement(Requirement('Ore',needed,owned,'Either')),expected)

    def test_modes_preserve_plans_drafts_selection_and_files(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True;w.timer.stop();w.probe_page.timer.stop()
            try:
                w.data.plan.materials=[Material('Ore',5),Material('Cloth',2)]
                w.data.inventories[w.data.active]=InventoryBook([
                    InventoryEntry('ore','Ore',3,'Bags',STAMP),InventoryEntry('bank','Ore',0,'Bank',STAMP)])
                g=w.gathering;s=w.shopping;g.refresh();s.refresh();g.table.selectRow(1);s.table.selectRow(1)
                g.form.load({'name':'Unfinished material','target':'???'})
                w.queue.form.load({'name':'Unfinished craft','ingredients':'Keep this draft'})
                before=deepcopy((g.form.values(),w.queue.form.values(),g.edit_id,w.data.plan,w.data.inventory,w.data.dirty))
                disk=files(root);selection=s.table.key()
                self.assertEqual([s.table.item(0,c).text() for c in (4,5)],['Unknown','Unknown'])
                self.assertEqual([s.table.item(1,c).text() for c in (4,5)],['3','2'])
                self.assertTrue(s.table.isColumnHidden(9));self.assertTrue(g.table.isColumnHidden(3))
                self.assertIn('Not enough saved information',s.total.text())
                for page in (g,s):page.show_details.setChecked(True)
                self.assertFalse(s.table.isColumnHidden(9));self.assertFalse(g.table.isColumnHidden(3))
                for page in (g,s):page.show_details.setChecked(False)
                w.change_experience_mode('Advanced');self.assertFalse(s.table.isColumnHidden(2))
                w.change_experience_mode('Easy');self.assertTrue(s.table.isColumnHidden(2))
                self.assertEqual(s.table.key(),selection)
                self.assertEqual(before,(g.form.values(),w.queue.form.values(),g.edit_id,w.data.plan,w.data.inventory,w.data.dirty))
                self.assertEqual(files(root),disk)
                w.settings['text_size']=18;w.apply_appearance();w.resize(720,700)
                for part in ('Gathering goals','Shopping list'):
                    w.show_planning(part)
                    w.show();app.processEvents()
                    self.assertEqual(w.scrollers['Planning'].horizontalScrollBar().maximum(),0)
                w.switch_character('alt');self.assertEqual(s.table.rowCount(),0)
                w.switch_character('first-character')
                self.assertEqual(g.form.values()['name'],'Unfinished material')
                self.assertEqual(w.queue.form.values()['ingredients'],'Keep this draft')
            finally:
                QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
