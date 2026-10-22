"""Copy and alt-overview tests use disposable records, never personal saves."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from companion import Companion,QApplication
from data import Data
from model import default_profile
from storage import ProfileStore
from gear import GearItem,GearWishlist,GearStore
from inventory import InventoryEntry,InventoryBook
from professions import ProfessionPlan
from catalogue import CatalogueRef
from wishlist_copy import copy_general,copy_status
from wishlist_copy_dialog import WishlistCopyDialog
from alt_inventory import snapshot,filter_items


STAMP='2026-10-20T12:00:00+00:00'


def files(path):
    return {str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*') if p.is_file()}


def seed(path):
    first=default_profile(); first.character_class='Paladin'
    second=deepcopy(first); second.id='alt'; second.name='Alt'; second.character_class='Mage'
    ProfileStore(path).save([first,second],first.id)
    GearStore(path).save({first.id:GearWishlist([GearItem('source','Example shield','Off hand','High','Obtained','Example vendor','Keep note',True)])})


def reference(item_id,name='Example shield'):
    return CatalogueRef(item_id,name,'Off Hand','https://warcraftforever.games/','2026-10-20','test')


class CopyAndAltModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-copy-model-'); self.path=Path(self.temp.name)
        seed(self.path); self.data=Data(self.path); self.char=self.data.active

    def tearDown(self): self.temp.cleanup()

    def test_copy_preserves_fields_originals_and_files_and_is_repeat_safe(self):
        before=files(self.path); original=deepcopy(self.data.gear)
        self.assertEqual(copy_general(self.data,self.char,'Tank',['source']),(1,[]))
        copied=self.data.playstyles.book(self.char,'Tank').entries[0]
        source=self.data.gear[self.char].entries[0]
        self.assertNotEqual(copied.id,source.id)
        self.assertEqual({k:v for k,v in asdict(copied).items() if k!='id'},
                         {k:v for k,v in asdict(source).items() if k!='id'})
        self.assertEqual(self.data.gear,original); self.assertEqual(files(self.path),before)
        self.assertEqual(self.data.playstyles.active(self.char),'General')
        count,skipped=copy_general(self.data,self.char,'Tank',['source'])
        self.assertEqual(count,0); self.assertEqual(len(skipped),1)
        copied.note='Independent edit'; self.assertEqual(source.note,'Keep note')
        self.assertEqual(self.data.playstyles.book(self.char,'Healing').entries,[])
        self.assertEqual(self.data.playstyles.book('alt','Tank').entries,[])

    def test_conflicts_slots_and_linked_ids(self):
        source=self.data.gear[self.char].entries[0]
        linked=deepcopy(source); linked.id='linked'; linked.catalogue_ref=reference(100)
        destination=GearWishlist([linked])
        self.assertIn('conflict',copy_status(source,destination))
        other=deepcopy(linked); other.catalogue_ref=reference(101)
        self.assertEqual(copy_status(other,destination),'Ready to copy')
        other.slot='Main hand'; other.catalogue_ref=None
        self.assertEqual(copy_status(other,destination),'Ready to copy')
        self.data.playstyles.books[(self.char,'Tank')]=destination
        self.assertEqual(copy_general(self.data,self.char,'Tank',['source'])[0],0)
        self.assertEqual(destination.entries,[linked])

    def test_capacity_error_is_atomic_and_invalid_targets_rejected(self):
        destination=GearWishlist([GearItem(str(i),f'Existing {i}') for i in range(500)])
        self.data.playstyles.books[(self.char,'Tank')]=destination
        before=deepcopy(destination); dirty=deepcopy(self.data.dirty)
        with self.assertRaises(ValueError): copy_general(self.data,self.char,'Tank',['source'])
        self.assertEqual(destination,before); self.assertEqual(self.data.dirty,dirty)
        for char,target,ids in [('alt','Tank',['source']),(self.char,'General',['source']),(self.char,'Healing',['missing'])]:
            with self.assertRaises(ValueError): copy_general(self.data,char,target,ids)
        self.data.profile.character_class='Warrior'
        with self.assertRaises(ValueError): copy_general(self.data,self.char,'Healing',['source'])
        self.data.gear_store.error='Unreadable General'
        with self.assertRaisesRegex(ValueError,'Unreadable'): copy_general(self.data,self.char,'Solo DPS',['source'])

    def test_only_explicit_destination_save_persists_copy(self):
        original=(self.path/'gear_wishlist.json').read_bytes()
        copy_general(self.data,self.char,'Tank',['source'])
        self.data.playstyles.select(self.char,'Tank')
        self.assertEqual(Data(self.path).wishlist.entries,[])
        self.data.playstyles.save_plan(self.char)
        self.assertEqual(Data(self.path).wishlist.entries,[])
        self.data.save_records('Gear wishlist')
        self.assertEqual(Data(self.path).wishlist.entries[0].name,'Example shield')
        self.assertEqual((self.path/'gear_wishlist.json').read_bytes(),original)
        self.assertNotIn(('Gear wishlist',self.char,'Tank'),self.data.dirty)

    def test_alt_counts_unknown_recheck_zero_and_coverage_are_separate(self):
        self.data.profiles[1].name=self.data.profile.name
        self.data.inventories={self.char:InventoryBook([
            InventoryEntry('zero','Zero item',0,'Bags',STAMP),
            InventoryEntry('unknown','Unknown item',None,'Bank',STAMP),
            InventoryEntry('stale','Old item',80,'Bags',STAMP)]),
            'alt':InventoryBook([InventoryEntry('alt-item','Zero item',7,'Bank',STAMP,note='For crafting')]),
            'orphan':InventoryBook([InventoryEntry('orphan-item','Unlinked record',2,'Bags',STAMP)])}
        self.data.plans[self.char]=ProfessionPlan(recheck_after={'old item':STAMP})
        original=deepcopy(self.data.inventories); before=files(self.path)
        rows,coverage=snapshot(self.data)
        self.assertEqual([(r.quantity,r.status) for r in rows if r.entry_id=='zero'],[(0,'Known')])
        self.assertEqual([(r.quantity,r.status) for r in rows if r.entry_id=='stale'],[(None,'Recheck')])
        self.assertEqual(len(filter_items(rows,status='Unknown')),1)
        self.assertEqual(filter_items(rows,'crafting','alt','Bank')[0].quantity,7)
        self.assertEqual(len(filter_items(rows,'Zero item')),2)
        self.assertTrue(all(r.character_id in r.character for r in rows if r.character_id!='orphan'))
        self.assertIn(('alt',self.data.profiles[1].name+' · alt',None,1),coverage)
        self.assertEqual(self.data.inventories,original); self.assertEqual(files(self.path),before)

    def test_missing_or_broken_records_never_imply_empty_inventory(self):
        rows,coverage=snapshot(self.data)
        self.assertEqual(rows,[]); self.assertTrue(all(c[2:]==(None,None) for c in coverage))
        self.data.inventories[self.char]=InventoryBook([InventoryEntry('x','Example shield',9,'Bags',STAMP,catalogue_ref=reference(123))])
        self.assertEqual(filter_items(snapshot(self.data)[0],'123')[0].quantity,9)
        self.data.plans_store.error='Unreadable planning file'
        self.assertEqual(snapshot(self.data)[0][0].status,'Unknown')
        self.assertIsNone(snapshot(self.data)[0][0].quantity)
        self.data.inventory_store.error='Unreadable inventory'
        with self.assertRaisesRegex(ValueError,'unavailable'): snapshot(self.data)


class CopyAndAltUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-copy-ui-'); self.path=Path(self.temp.name)
        seed(self.path); self.w=Companion(self.path); self.w.testing=True; self.w.timer.stop()

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); self.app.processEvents(); self.temp.cleanup()

    def test_dialog_preserves_source_destination_and_other_editor_drafts(self):
        w=self.w; w.gear_page.form.load({'name':'Raw General','note':'Do not apply'})
        w.preset.setCurrentText('Tank'); w.gear_page.form.load({'name':'Raw Tank'})
        w.playstyle_page.form.load({'notes':'Unfinished Tank notes'})
        w.inventory_page.form.load({'name':'Raw bag entry','quantity':'???'})
        before=files(self.path)
        dialog=WishlistCopyDialog(w)
        try:
            self.assertEqual(dialog.target.currentText(),'Tank')
            dialog.tick_rows(True); self.assertEqual(dialog.checked(),{'source'})
            dialog.copy(); self.assertEqual(len(w.data.wishlist.entries),1)
            self.assertEqual(dialog.checked(),set()); self.assertEqual(dialog.ready,set())
            self.assertEqual(w.gear_page.form.values()['name'],'Raw Tank')
            self.assertEqual(w.playstyle_page.form.values()['notes'],'Unfinished Tank notes')
            self.assertEqual(w.inventory_page.form.values()['quantity'],'???')
            self.assertEqual(files(self.path),before)
            dialog.target.setCurrentText('Healing'); dialog.tick_rows(True); dialog.copy()
            self.assertEqual(w.data.playstyles.active(w.data.active),'Tank')
            self.assertEqual(len(w.data.playstyles.book(w.data.active,'Healing').entries),1)
            w.gear_page.save()
            self.assertEqual(Data(self.path).wishlist.entries[0].name,'Example shield')
            self.assertEqual(Data(self.path).playstyles.book(w.data.active,'Healing').entries,[])
            w.preset.setCurrentText('General')
            self.assertEqual(w.gear_page.form.values()['name'],'Raw General')
            w.preset.setCurrentText('Tank')
            self.assertEqual(w.gear_page.form.values()['name'],'Raw Tank')
        finally: dialog.close(); dialog.deleteLater()

    def test_alt_search_pagination_and_navigation_preserve_drafts(self):
        w=self.w; char=w.data.active
        w.inventory_page.form.load({'name':'Unfinished main','quantity':'???'})
        w.switch_character('alt'); w.inventory_page.form.load({'name':'Unfinished alt'})
        w.switch_character(char)
        w.data.inventories[char]=InventoryBook([InventoryEntry(str(i),f'Example {i:03}',i,'Bags',STAMP) for i in range(105)])
        w.data.inventories['alt']=InventoryBook([InventoryEntry('a','Alt bank item',None,'Bank',STAMP)])
        before=files(self.path); page=w.alt_inventory; page.refresh()
        self.assertEqual(page.table.rowCount(),100); self.assertTrue(page.next.isEnabled())
        page.turn(1); self.assertEqual(page.table.rowCount(),6)
        page.filters.load({'query':'Alt bank','location':'Bank','status':'Unknown'}); page.render()
        self.assertEqual(page.table.rowCount(),1); self.assertEqual(page.table.item(0,3).text(),'Not checked yet')
        self.assertEqual(w.data.active,char); self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished main')
        self.assertEqual(files(self.path),before)
        page.table.selectRow(0); page.open_character()
        self.assertEqual(w.data.active,'alt'); self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished alt')
        page.reset_filters(); self.assertEqual(w.data.active,'alt')
        w.switch_character(char); self.assertEqual(w.inventory_page.form.values()['quantity'],'???')
        self.assertEqual(len(w.data.inventory.entries),105)

    def test_alt_refresh_and_large_font_layout(self):
        w=self.w; page=w.alt_inventory
        w.settings['text_size']=18; w.apply_appearance(); w.resize(1500,1050)
        w.show_page('Inventory & Bank'); w.show_inventory_section(True); w.show()
        for _ in range(4): self.app.processEvents()
        self.assertLess(page.filters.height(),150)
        self.assertEqual(page.coverage_table.item(0,1).text(),'Unknown')
        w.inventory_page.form.load({'name':'Applied material','quantity':'0'})
        w.inventory_page.apply(); self.app.processEvents()
        self.assertEqual(page.table.rowCount(),1); self.assertEqual(page.table.item(0,3).text(),'No · recorded zero')
        w.inventory_page.form.load({'name':'Raw material','quantity':'999'})
        page.refresh(); self.assertEqual(page.table.item(0,0).text(),'Applied material')
        page.filters.controls['query'].setText('Raw material')
        w.show_inventory_section(False); self.app.processEvents()
        w.show_inventory_section(True); self.app.processEvents()
        self.assertEqual(page.table.rowCount(),0)
        page.reset_filters(); self.assertEqual(page.table.rowCount(),1)


if __name__=='__main__': unittest.main()
