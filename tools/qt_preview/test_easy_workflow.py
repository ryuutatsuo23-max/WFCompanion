"""Walk the friend-facing workflow with disposable state, never personal saves."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest
from PySide6.QtCore import QThreadPool,Qt,QPoint
from PySide6.QtTest import QTest
from companion import Companion,QApplication
from inventory import InventoryBook,InventoryEntry
from professions import Material,ProfessionPlan
from gear import GearWishlist
from test_copy_and_alts import seed,files,STAMP


class EasyWorkflowTests(unittest.TestCase):
    def test_character_stock_wishlist_crafting_and_return(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True;w.timer.stop();w.probe_page.timer.stop()
            try:
                main=w.data.active
                w.data.inventories[main]=InventoryBook([
                    InventoryEntry('bag','Example shield',0,'Bags',STAMP),
                    InventoryEntry('bank','Example shield',0,'Bank',STAMP)])
                w.data.inventories['alt']=InventoryBook([InventoryEntry('alt-bag','Example shield',2,'Bags',STAMP)])
                w.data.plan.materials=[Material('Example shield',3)]
                w.data.gear['alt']=GearWishlist();w.data.plans['alt']=ProfessionPlan()
                w.inventory_page.form.load({'name':'Unfinished bag edit','quantity':'???'})
                w.gear_page.form.load({'name':'Unfinished goal','note':'Keep this'})
                w.queue.form.load({'name':'Unfinished recipe','ingredients':'Keep ingredients'})
                before=deepcopy((w.data.inventories,w.data.gear,w.data.plans,w.data.dirty))
                disk=files(root)
                w.apply_presentation();w.resize(1100,800);w.show_page('Overview');w.show();app.processEvents()
                self.assertTrue(w.simulation_panel.isHidden())
                w.scrollers['Overview'].ensureWidgetVisible(w.show_simulation);app.processEvents()
                QTest.mouseClick(w.show_simulation,Qt.MouseButton.LeftButton,pos=QPoint(10,w.show_simulation.height()//2))
                self.assertFalse(w.simulation_panel.isHidden())
                w.hp.setValue(47);w.show_simulation.setChecked(False)
                w.change_experience_mode('Advanced');self.assertFalse(w.simulation_panel.isHidden())
                w.change_experience_mode('Easy');self.assertTrue(w.simulation_panel.isHidden());self.assertEqual(w.hp.value(),47)
                overview=w.character_overview
                overview.table.selectRow(overview.table.keys.index(main));overview.open_page('Inventory & Bank')
                self.assertEqual(w.pages.currentWidget(),w.scrollers['Inventory & Bank'])
                self.assertEqual(w.inventory_page.table.item(0,2).text(),'No · recorded zero')
                overview.open_page('Gear wishlist');p=w.gear_page
                self.assertEqual(p.table.item(0,4).text(),'Yes · view characters')
                goal=w.data.wishlist.entries[0]
                w.open_inventory_from_wishlist('alt',(main,'General'),goal)
                self.assertEqual(w.data.active,'alt');self.assertFalse(w.wishlist_back.isHidden())
                self.assertEqual(w.inventory_page.filters.values()['query'],'Example shield')
                w.back_to_wishlist();self.assertEqual(w.data.active,main)
                self.assertEqual(p.form.values()['name'],'Unfinished goal')
                for size,width in ((12,1100),(18,720)):
                    w.settings['text_size']=size;w.apply_appearance();w.resize(width,800)
                    for tab in ('Overview','Inventory & Bank','Gear wishlist','Gathering','Crafting','Planning'):
                        w.show_page(tab)
                        if tab=='Planning':w.show_planning('Shopping list')
                        app.processEvents()
                        self.assertEqual(w.scrollers[tab].horizontalScrollBar().maximum(),0,(tab,size))
                        bar=w.scrollers[tab].verticalScrollBar();bar.setValue(bar.maximum());app.processEvents();bar.setValue(0)
                self.assertEqual(w.shopping.table.item(0,5).text(),'3')
                self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished bag edit')
                self.assertEqual(w.queue.form.values()['ingredients'],'Keep ingredients')
                self.assertEqual(before,(w.data.inventories,w.data.gear,w.data.plans,w.data.dirty))
                after=files(root)
                # Character navigation normally retains the previous profile
                # selection as a backup; all original files must be identical.
                self.assertEqual(set(after)-set(disk),{'profiles.previous.json'})
                self.assertEqual([name for name in disk if after.get(name)!=disk[name]],[])
                # Optional rendered previews are explicitly test-fixture images.
                output=os.environ.get('WOW_WORKFLOW_PREVIEWS')
                if output:
                    destination=Path(output).resolve();destination.mkdir(parents=True,exist_ok=True)
                    w.settings['text_size']=12;w.apply_appearance();w.resize(1250,900)
                    for tab,name in (('Overview','overview'),('Planning','shopping')):
                        w.show_page(tab);app.processEvents()
                        self.assertTrue(w.grab().save(str(destination/(name+'.png'))))
            finally:
                QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
