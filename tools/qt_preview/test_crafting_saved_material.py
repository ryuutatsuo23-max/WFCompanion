from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from companion import Companion,QApplication
from observed_inventory_dialog import ObservedInventoryDialog
from professions import CraftGoal,Ingredient
from inventory import InventoryEntry,utc_now
from test_copy_and_alts import seed,files


class SavedMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);seed(self.root)
        self.host=Companion(self.root);self.host.testing=True;self.host.updates_panel.timer.stop()
        self.host.saved_character_connection.timer.stop();self.host.character_overview.game_data_monitor.set_enabled(False)
        self.record=dict(identity={'source':str(self.root/'WFCore.lua')},rows=((159,16),(1599,4),(160,2)),
            finished=1792764000,coverage='complete',unknown=0,interrupted=False,direct=True,
            names={159:'Refreshing Spring Water',1599:'Other Water',160:'Refreshing Spring Water'})
        (self.root/'WFCore.lua').write_text('read-only source marker')

    def tearDown(self):
        self.host.close();self.host.deleteLater();self.app.processEvents();self.tmp.cleanup()

    def test_id_matches_exactly_across_characters_and_refresh_preserves_sort(self):
        with patch('observed_inventory_dialog.linked_snapshots',return_value={'bags':self.record}):
            d=ObservedInventoryDialog(self.host,material=('Different name',159))
            self.assertEqual(d.items.rowCount(),2)
            self.assertTrue(all(d.items.item(i,4).text()=='159' for i in range(2)))
            self.assertTrue(all(d.items.item(i,5).text()!='Unknown' for i in range(2)))
            self.assertIn('Bank hasn',d.notice.text())
            d.sort_items(5);d.select('bags');d.refresh()
            self.assertEqual((d.sort_column,d.scope),(5,'bags'))
            self.assertEqual(self.host.data.active,'first-character')
            d.close()

    def test_exact_name_keeps_distinct_ids_without_combining_counts(self):
        with patch('observed_inventory_dialog.linked_snapshots',return_value={'bags':self.record}):
            d=ObservedInventoryDialog(self.host,material=(' refreshing spring water ',None))
            self.assertEqual(d.items.rowCount(),4)
            self.assertEqual({d.items.item(i,4).text() for i in range(4)},{'159','160'})
            d.close()

    def test_no_match_partial_and_unavailable_never_claim_empty(self):
        partial=deepcopy(self.record);partial['coverage']='partial'
        with patch('observed_inventory_dialog.linked_snapshots',return_value={'bags':partial}):
            d=ObservedInventoryDialog(self.host,material=('Absent material',None))
            self.assertIn('No matching material',d.empty_notice.text());self.assertIn('unknown',d.empty_notice.text())
            d.close()
            d=ObservedInventoryDialog(self.host,material=('Water',159))
            self.assertIn('Incomplete',d.items.item(0,5).text());d.close()
        with patch('observed_inventory_dialog.linked_snapshots',side_effect=OSError('Unavailable')):
            d=ObservedInventoryDialog(self.host,material=('Water',159))
            self.assertIn('unavailable',d.empty_notice.text());self.assertEqual(d.items.rowCount(),0);d.close()

    def test_shopping_link_and_back_preserve_drafts_manual_counts_and_disk(self):
        self.host.data.plan.goals.append(CraftGoal('demo','Test craft',2,[Ingredient('Refreshing Spring Water',1)]))
        self.host.data.dirty.add('Crafting');self.host.shopping.refresh();self.host.shopping.table.selectRow(0)
        self.host.queue.form.load({'name':'Unfinished craft draft','ingredients':'Do not replace = 3'})
        self.host.saved_inventory.search.setText('existing search');self.host.saved_inventory.select('bank')
        before=files(self.root);plans=deepcopy(self.host.data.plans);stock=deepcopy(self.host.data.inventories)
        estimates=deepcopy(self.host.shopping.estimates);draft=self.host.queue.form.values()
        with patch('observed_inventory_dialog.linked_snapshots',return_value={'bags':self.record}):
            self.host.shopping.open_saved_material();d=self.host.shopping.saved_material_dialog
            self.assertEqual(d.items.rowCount(),4);d.accept()
        self.assertEqual(self.host.queue.form.values(),draft)
        self.assertEqual(self.host.data.plans,plans);self.assertEqual(self.host.data.inventories,stock)
        self.assertEqual(self.host.shopping.estimates,estimates)
        self.assertEqual((self.host.saved_inventory.search.text(),self.host.saved_inventory.scope),('existing search','bank'))
        self.assertEqual(files(self.root),before)

    def test_partial_crafts_manual_totals_and_unknown_bank(self):
        data=self.host.data
        data.plan.goals=[CraftGoal('partial','Example',5,[Ingredient('Thread',2)],completed=2)]
        data.inventory.entries=[InventoryEntry('bags','Thread',3,'Bags',utc_now())]
        self.host.shopping.refresh();table=self.host.shopping.table
        self.assertEqual(table.item(0,1).text(),'6')
        self.assertEqual(table.item(0,4).text(),'Unknown');self.assertEqual(table.item(0,5).text(),'Unknown')
        data.inventory.entries.append(InventoryEntry('bank','Thread',1,'Bank',utc_now()))
        self.host.shopping.refresh()
        self.assertEqual(table.item(0,4).text(),'4');self.assertEqual(table.item(0,5).text(),'2')
        self.assertEqual(table.horizontalHeaderItem(4).text(),'Manually recorded')
        self.host.shopping.show_details.setChecked(True)
        self.assertEqual(table.horizontalHeaderItem(4).text(),'Manually recorded')
        self.assertEqual(table.item(0,5).text(),'2')

    def test_stale_manual_stock_and_unsaved_drafts_do_not_fabricate_counts(self):
        data=self.host.data
        data.plan.goals=[CraftGoal('partial','Example',2,[Ingredient('Thread',2)],completed=1)]
        data.inventory.entries=[InventoryEntry('bags','Thread',5,'Bags','2026-10-20T00:00:00+00:00'),
                                InventoryEntry('bank','Thread',0,'Bank','2026-10-20T00:00:00+00:00')]
        data.plan.recheck_after['thread']='2026-10-21T00:00:00+00:00'
        self.host.queue.form.load({'quantity':'99','completed':'0','ingredients':'Different draft = 12'})
        draft=self.host.queue.form.values();disk=files(self.root)
        self.host.shopping.refresh();self.host.shopping.show_details.setChecked(True)
        self.assertEqual(self.host.shopping.table.item(0,1).text(),'2')
        self.assertEqual(self.host.shopping.table.item(0,4).text(),'Unknown')
        self.assertEqual(self.host.queue.form.values(),draft);self.assertEqual(files(self.root),disk)

    def test_saved_stock_lookup_does_not_supply_manual_shopping_total(self):
        from character_links import identity,LinkStore
        from test_saved_data_settings import SAVE
        data=self.host.data
        source=self.root/'WFCore.lua';source.write_text(SAVE)
        LinkStore(self.root).save(data,identity(source,'Player-1-ABC','Test'),data.active)
        data.plan.goals=[CraftGoal('water','Example',10,[Ingredient('Refreshing Spring Water',1)])]
        data.inventory.entries=[InventoryEntry('bags','Refreshing Spring Water',3,'Bags',utc_now()),
                                InventoryEntry('bank','Refreshing Spring Water',1,'Bank',utc_now())]
        self.host.shopping.refresh();self.host.shopping.table.selectRow(0)
        with patch('observed_inventory_dialog.linked_snapshots',return_value={'bags':self.record}):
            self.host.shopping.open_saved_material();dialog=self.host.shopping.saved_material_dialog
            self.assertIn('16',[dialog.items.item(i,3).text() for i in range(dialog.items.rowCount())]);dialog.accept()
        self.assertEqual(self.host.shopping.table.item(0,4).text(),'4')
        self.assertEqual(self.host.shopping.table.item(0,5).text(),'6')
