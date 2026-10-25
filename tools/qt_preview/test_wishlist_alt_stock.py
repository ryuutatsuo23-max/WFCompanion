"""Other-character stock never becomes selected-character ownership or saves."""
from copy import deepcopy
from html import escape
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from companion import Companion,QApplication
from data import Data
from inventory import InventoryEntry,InventoryBook
from gear import GearItem,GearWishlist
from professions import ProfessionPlan
from wishlist_alt_stock import other_stock,total_label,location_details
from wishlist_alt_dialog import WishlistAltDialog
from presentation import simple_other_stock
from test_copy_and_alts import seed,files,STAMP,reference


def entry(key,quantity,location='Bags',ref=None):
    return InventoryEntry(key,'Example shield',quantity,location,STAMP,catalogue_ref=ref)


class WishlistAltStockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-wishlist-alt-'); self.path=Path(self.temp.name)
        seed(self.path); self.data=Data(self.path); self.char=self.data.active; self.goals=self.data.wishlist.entries

    def tearDown(self): self.temp.cleanup()

    def test_separate_character_location_totals_and_partial_unknowns(self):
        third=deepcopy(self.data.profiles[1]); third.id='third'; third.name='Third'; self.data.profiles.append(third)
        self.data.inventories[self.char]=InventoryBook([entry('main',99)])
        self.data.inventories['alt']=InventoryBook([entry('alt',3),entry('alt-bank',0,'Bank')])
        self.data.inventories['third']=InventoryBook([entry('third',None),entry('third-bank',7,'Bank')])
        before=deepcopy(self.data.inventories); disk=files(self.path)
        result=other_stock(self.data,self.goals)['source']
        self.assertEqual({c.character_id for c in result},{'alt','third'})
        self.assertEqual(total_label(result,0),'3 + Unknown'); self.assertEqual(total_label(result,1),'7')
        self.assertIn('Quantity was left blank',location_details(result,0))
        self.assertEqual(self.data.inventories,before); self.assertEqual(files(self.path),disk)

    def test_empty_missing_and_explicit_zero_are_distinct(self):
        counts=other_stock(self.data,self.goals)['source']
        self.assertEqual(total_label(counts,0),'Unknown'); self.assertEqual(total_label(counts,1),'Unknown')
        self.assertEqual(simple_other_stock(counts),'Not checked yet')
        self.data.inventories['alt']=InventoryBook([entry('a',0)])
        self.assertEqual(simple_other_stock(other_stock(self.data,self.goals)['source']),'Not checked yet')
        self.data.inventories['alt']=InventoryBook([entry('a',3)])
        self.assertEqual(simple_other_stock(other_stock(self.data,self.goals)['source']),'Yes · view characters')
        self.data.inventories['alt']=InventoryBook([entry('a',0),entry('b',0,'Bank')])
        self.assertEqual(total_label(other_stock(self.data,self.goals)['source'],0),'0')
        self.assertEqual(simple_other_stock(other_stock(self.data,self.goals)['source']),'No · recorded zero')
        self.data.profiles=self.data.profiles[:1]; self.data.inventories={}
        self.assertEqual(total_label(other_stock(self.data,self.goals)['source'],0),'No alts')
        self.assertEqual(simple_other_stock(other_stock(self.data,self.goals)['source']),'No other characters')

    def test_stale_counts_hidden_and_selected_character_switch_recomputes(self):
        self.data.inventories['alt']=InventoryBook([entry('a',20)])
        self.data.inventories[self.char]=InventoryBook([entry('m',4)])
        self.data.plans['alt']=ProfessionPlan(recheck_after={'example shield':STAMP})
        result=other_stock(self.data,self.goals)['source']
        self.assertEqual(total_label(result,0),'Unknown')
        self.assertIn('Recheck',location_details(result,0))
        self.data.active='alt'
        result=other_stock(self.data,self.goals)['source']
        self.assertEqual(total_label(result,0),'4'); self.assertEqual(result[0].character_id,self.char)

    def test_exact_ids_ambiguous_names_and_repeated_slots(self):
        a=reference(100); b=reference(101)
        self.data.inventories['alt']=InventoryBook([entry('a',2,ref=a),entry('b',7,ref=b),entry('manual-bank',50,'Bank')])
        goals=[GearItem('one',a.name,'Off hand',catalogue_ref=a),GearItem('two',b.name,'Off hand',catalogue_ref=b),
               GearItem('manual',a.name)]
        result=other_stock(self.data,goals)
        self.assertEqual(total_label(result['one'],0),'2'); self.assertEqual(total_label(result['two'],0),'7')
        self.assertEqual(total_label(result['manual'],0),'Unknown')
        self.assertEqual(total_label(result['one'],1),'Unknown')
        self.assertIn('exact item ID',location_details(result['manual'],0))
        self.data.inventories['alt']=InventoryBook([entry('only',5,ref=a)])
        manual=[GearItem('slot-one',a.name,'Main hand'),GearItem('slot-two',a.name,'Off hand')]
        result=other_stock(self.data,manual,[a])
        self.assertEqual([total_label(v,0) for v in result.values()],['5','5'])
        self.assertEqual(total_label(other_stock(self.data,manual,[a,b])['slot-one'],0),'Unknown')

    def test_unreadable_data_and_orphan_profiles_preserve_unknowns(self):
        self.data.inventories['orphan']=InventoryBook([entry('orphan',8)])
        result=other_stock(self.data,self.goals)['source']
        self.assertEqual(total_label(result,0),'8 + Unknown')
        self.assertIn('Unlisted character',location_details(result,0))
        for store in (self.data.inventory_store,self.data.plans_store):
            store.error='Unreadable'
            self.assertEqual(total_label(other_stock(self.data,self.goals)['source'],0),'Unknown')
            store.error=None
        self.data.profiles[1].name=self.data.profile.name
        self.assertIn(' · alt',location_details(other_stock(self.data,self.goals)['source'],0))


class WishlistAltUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-wishlist-alt-ui-'); self.path=Path(self.temp.name)
        seed(self.path); self.w=Companion(self.path); self.w.testing=True; self.w.timer.stop()
        # Existing assertions exercise the detailed two-location columns.
        self.w.change_experience_mode('Advanced')

    def test_easy_mode_keeps_alt_link_and_drafts(self):
        w=self.w;p=w.gear_page
        w.data.inventories[w.data.active]=InventoryBook([entry('own',0),entry('bank',None,'Bank')])
        w.data.inventories['alt']=InventoryBook([entry('alt',3)])
        w.change_experience_mode('Easy');p.refresh();p.table.selectRow(0)
        p.form.load({'name':'Unfinished goal','note':'Keep draft'})
        before=deepcopy((p.form.values(),p.filters.values(),p.edit_id,w.data.dirty,w.data.inventories,w.data.gear))
        disk=files(self.path)
        self.assertEqual(p.table.item(0,1).text(),'No · recorded zero')
        self.assertEqual(p.table.item(0,2).text(),'Not checked yet')
        self.assertEqual(p.table.item(0,4).text(),'Yes · view characters')
        self.assertTrue(p.table.isColumnHidden(5));self.assertTrue(p.table.isColumnHidden(10))
        w.show_page('Gear wishlist');w.show();self.app.processEvents()
        cell=p.table.item(0,4);p.table.scrollToItem(cell);self.app.processEvents()
        with patch.object(p,'show_other_stock') as opened:
            QTest.mouseClick(p.table.viewport(),Qt.MouseButton.LeftButton,pos=p.table.visualItemRect(cell).center())
            opened.assert_called_once_with('source')
        p.show_details.setChecked(True)
        self.assertEqual(p.table.item(0,4).text(),'3');self.assertFalse(p.table.isColumnHidden(5))
        p.show_details.setChecked(False);w.change_experience_mode('Advanced')
        self.assertFalse(p.table.isColumnHidden(10))
        self.assertEqual(before,(p.form.values(),p.filters.values(),p.edit_id,w.data.dirty,w.data.inventories,w.data.gear))
        self.assertEqual(files(self.path),disk)

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); self.app.processEvents(); self.temp.cleanup()

    def test_ownership_filters_and_goal_status_ignore_alts(self):
        w=self.w; p=w.gear_page; char=w.data.active
        w.data.inventories[char]=InventoryBook([entry('own-bag',0),entry('own-bank',0,'Bank')])
        w.data.inventories['alt']=InventoryBook([entry('alt-bag',3),entry('alt-bank',5,'Bank')])
        p.refresh()
        self.assertEqual([p.table.item(0,i).text() for i in (1,2,3,4,5,8)],['0','0','Not owned','3','5','Obtained'])
        self.assertIn('Alt: 3',p.table.item(0,4).toolTip())
        p.filter_set('ownership','Owned'); self.assertEqual(p.table.rowCount(),0)
        p.filter_set('ownership','Not owned'); self.assertEqual(p.table.rowCount(),1)
        self.assertEqual(p.summary_buttons['Owned'].text(),'Owned: 0')
        self.assertEqual(p.summary_buttons['Not owned'].text(),'Not owned: 1')
        w.data.inventories[char]=InventoryBook([]); p.filter_set('ownership','All')
        self.assertEqual(p.table.item(0,3).text(),'Unknown')
        w.preset.setCurrentText('Tank'); w.data.set_wishlist(GearWishlist([GearItem('tank','Example shield')]))
        p.refresh(); self.assertEqual(p.table.item(0,4).text(),'3')
        w.switch_character('alt'); w.data.set_wishlist(GearWishlist([GearItem('alt-goal','Example shield')]))
        p.refresh(); self.assertEqual(p.table.item(0,3).text(),'Owned'); self.assertEqual(p.table.item(0,4).text(),'Unknown')

    def test_breakdown_preserves_drafts_and_saves_with_large_fonts(self):
        w=self.w; p=w.gear_page
        w.data.inventories['alt']=InventoryBook([entry('alt',2)])
        p.refresh(); p.table.selectRow(0)
        p.form.load({'name':'Unfinished gear','note':'Do not apply'})
        w.inventory_page.form.load({'name':'Unfinished inventory','quantity':'999'})
        before=files(self.path); raw=p.form.values(); seen=[]
        w.settings['text_size']=18; w.apply_appearance()
        def inspect(dialog):
            dialog.show(); self.app.processEvents()
            seen.append([dialog.table.item(0,c).text() for c in (0,1,2)])
            self.assertGreaterEqual(dialog.table.columnWidth(0),180)
            dialog.close(); return 0
        with patch.object(WishlistAltDialog,'exec',inspect): p.show_other_stock()
        self.assertEqual(seen,[['Alt','2','Unknown']])
        self.assertEqual(p.form.values(),raw)
        self.assertEqual(w.inventory_page.form.values()['quantity'],'999')
        self.assertEqual(files(self.path),before)
        self.assertEqual(w.data.active,'first-character')

    def test_click_count_on_another_row_preserves_editor_and_selection(self):
        w=self.w; p=w.gear_page; table=p.table
        w.data.wishlist.entries.append(GearItem('second','Another shield'))
        w.data.inventories['alt']=InventoryBook([InventoryEntry('second-stock','Another shield',4,'Bags',STAMP)])
        p.refresh(); table.selectRow(table.keys.index('source'))
        p.form.load({'name':'Unfinished name','note':'Unfinished note'})
        w.inventory_page.form.load({'name':'Unfinished inventory'})
        raw=p.form.values(); edit_id=p.edit_id; selected=table.key(); before=files(self.path)
        w.settings['text_size']=18; w.apply_appearance(); w.resize(1500,1100)
        w.show_page('Gear wishlist'); w.show(); self.app.processEvents()
        seen=[]
        def inspect(dialog):
            seen.append([dialog.table.item(0,c).text() for c in (1,2)])
            return 0
        def position(column):
            cell=table.item(table.keys.index('second'),column)
            table.scrollToItem(cell); self.app.processEvents()
            return table.visualItemRect(cell).center()
        with patch.object(WishlistAltDialog,'exec',inspect):
            for column in (4,5):
                QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,pos=position(column))
                self.assertEqual(p.form.values(),raw); self.assertEqual(p.edit_id,edit_id)
                self.assertEqual(table.key(),selected)
            # Dragging away cancels the link rather than selecting another row.
            start=position(4); finish=position(5)
            QTest.mousePress(table.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(table.viewport(),finish)
            QTest.mouseRelease(table.viewport(),Qt.MouseButton.LeftButton,pos=finish)
            self.assertEqual(len(seen),2); self.assertEqual(p.form.values(),raw)
            # Filtering changes row numbers. The link must still use the item ID,
            # including when there is no selected row and its value is Unknown.
            p.filters.load({'query':'Another'}); p.refresh()
            QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,pos=position(5))
            self.assertIsNone(table.key()); self.assertEqual(p.form.values(),raw)
            self.assertEqual(p.edit_id,edit_id)
            self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished inventory')
            self.assertEqual(files(self.path),before)
            self.assertEqual([p.table.item(0,c).text() for c in (3,8)],['Unknown','Wanted'])
            self.assertEqual(seen,[['4','Unknown']]*3)
            # Ordinary item cells retain the existing editing behavior.
            QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,pos=position(0))
            self.assertEqual(p.form.values()['name'],'Another shield')
            self.assertEqual(p.edit_id,'second'); self.assertEqual(len(seen),3)

    def test_open_alt_inventory_restores_both_characters_drafts_and_filters(self):
        w=self.w; main=w.data.active; p=w.inventory_page
        w.preset.setCurrentText('Tank')
        w.gear_page.form.load({'name':'Unfinished tank gear'})
        w.gear_page.filter_set('query','Tank filter')
        w.playstyle_page.form.load({'notes':'Unfinished tank notes'})
        p.form.load({'name':'Unfinished main inventory','quantity':'???'})
        w.switch_character('alt'); w.preset.setCurrentText('Solo DPS')
        w.gear_page.form.load({'name':'Unfinished alt gear'})
        w.playstyle_page.form.load({'notes':'Unfinished alt notes'})
        p.form.load({'name':'Unfinished alt inventory','quantity':'???'})
        p.filter_set('query','Remember this filter')
        p.filter_set('location','Bank'); p.filter_set('count_status','Recheck')
        previous_filters=p.filters.values()
        unrelated=InventoryEntry('unrelated','Other item',8,'Bags',STAMP)
        w.data.inventories['alt']=InventoryBook([entry('applied',4),entry('unknown',None,'Bank'),unrelated])
        w.switch_character(main)
        if 'Inventory & Bank' not in w.settings['hidden']: w.settings['hidden'].append('Inventory & Bank')
        settings=deepcopy(w.settings)
        w.rebuild_navigation(); w.show_inventory_section(True); w.show_page('Gear wishlist')
        w.show(); self.app.processEvents()
        original=deepcopy(w.data.inventories); before=files(self.path)
        item=w.data.gear[main].entries[0]
        dialog=WishlistAltDialog(w,item,other_stock(w.data,[item])[item.id])
        try:
            dialog.show(); self.app.processEvents()
            self.assertFalse(dialog.open_button.isEnabled())
            dialog.table.selectRow(dialog.table.keys.index('alt')); self.app.processEvents()
            self.assertTrue(dialog.open_button.isEnabled())
            QTest.mouseClick(dialog.open_button,Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertFalse(dialog.isVisible())
            self.assertEqual(w.data.active,'alt'); self.assertEqual(w.preset.currentText(),'Solo DPS')
            self.assertEqual(w.pages.currentWidget(),w.scrollers['Inventory & Bank'])
            self.assertTrue(p.isVisible()); self.assertTrue(w.alt_inventory.isHidden())
            self.assertEqual(p.form.values()['name'],'Unfinished alt inventory')
            self.assertEqual(p.form.values()['quantity'],'???')
            self.assertEqual(p.filters.values(),{'query':item.name,'location':'All','count_status':'All'})
            self.assertEqual(set(p.table.keys),{'applied','unknown'})
            self.assertEqual(p.table.item(p.table.keys.index('unknown'),3).text(),'Unknown')
            self.assertTrue(p.temporary_filter_notice.isVisible())
            self.assertEqual(w.gear_page.form.values()['name'],'Unfinished alt gear')
            self.assertEqual(w.playstyle_page.form.values()['notes'],'Unfinished alt notes')
            self.assertEqual(w.settings,settings); self.assertEqual(w.data.inventories,original)
            self.assertTrue(w.wishlist_back.isVisible())
            self.assertEqual(w.wishlist_return,(main,'Tank'))
            # Only the normal active-character selection may be saved.
            after=files(self.path)
            self.assertEqual({k:v for k,v in after.items() if not k.startswith('profiles')},
                             {k:v for k,v in before.items() if not k.startswith('profiles')})
            self.assertEqual(Data(self.path).inventory.entries,[])
            # Every filter adjustment within the visit is temporary, including reset.
            p.filter_set('location','Bank'); p.filter_set('count_status','Unknown')
            self.assertEqual(p.table.keys,['unknown'])
            p.reset_filters(); p.filters.controls['query'].setText('Other item')
            self.assertEqual(p.table.keys,['unrelated'])
            self.assertEqual(w.data.inventory_filters.get('alt').query,'Remember this filter')
            p.form.load({'name':'New unfinished alt inventory'})
            QTest.mouseClick(w.wishlist_back,Qt.MouseButton.LeftButton)
            self.assertEqual(w.preset.currentText(),'Tank')
            self.assertEqual(w.pages.currentWidget(),w.scrollers['Gear wishlist'])
            self.assertIsNone(w.wishlist_return); self.assertTrue(w.wishlist_back.isHidden())
            self.assertEqual(w.gear_page.filters.values()['query'],'Tank filter')
            self.assertEqual(p.form.values()['name'],'Unfinished main inventory')
            self.assertEqual(w.gear_page.form.values()['name'],'Unfinished tank gear')
            self.assertEqual(w.playstyle_page.form.values()['notes'],'Unfinished tank notes')
            w.switch_character('alt')
            self.assertEqual(p.form.values()['name'],'New unfinished alt inventory')
            self.assertEqual(p.filters.values(),previous_filters)
            self.assertIsNone(p.temporary_filters); self.assertTrue(p.temporary_filter_notice.isHidden())
            after=files(self.path)
            self.assertEqual({k:v for k,v in after.items() if not k.startswith('profiles')},
                             {k:v for k,v in before.items() if not k.startswith('profiles')})
        finally: dialog.close(); dialog.deleteLater()

    def test_temporary_search_stays_scoped_across_characters_and_new_visits(self):
        w=self.w; main=w.data.active; p=w.inventory_page; item=w.data.wishlist.entries[0]
        p.filter_set('query','Main search')
        w.switch_character('alt'); p.filter_set('query','Alt search'); p.filter_set('location','Bank')
        original=p.filters.values(); saved=w.data.inventory_filters.path.read_bytes()
        w.switch_character(main)
        w.open_inventory_from_wishlist('alt',(main,'General'),item)
        p.filter_set('query','Temporary adjustment')
        self.assertIn(item.name,p.temporary_filter_notice.text())
        self.assertNotIn('Temporary adjustment',p.temporary_filter_notice.text())
        p.reset_filters()
        self.assertIn(item.name,p.temporary_filter_notice.text())
        p.filter_set('query','Temporary adjustment')
        w.switch_character(main)
        self.assertEqual(p.filters.values()['query'],'Main search')
        self.assertTrue(p.temporary_filter_notice.isHidden())
        w.switch_character('alt')
        self.assertEqual(p.filters.values()['query'],'Temporary adjustment')
        self.assertIn(item.name,p.temporary_filter_notice.text())
        # Reopening the same destination must snapshot its original filters,
        # not the previous visit's temporary choices.
        replacement=GearItem('replacement','Another <shield> & sword')
        w.open_inventory_from_wishlist('alt',(main,'General'),replacement)
        self.assertEqual(p.temporary_filters['previous'],original)
        self.assertEqual(p.filters.values()['query'],replacement.name)
        self.assertIn(escape(replacement.name),p.temporary_filter_notice.text())
        self.assertNotIn(item.name,p.temporary_filter_notice.text())
        self.assertEqual(p.temporary_filter_notice.textFormat(),Qt.TextFormat.RichText)
        self.assertEqual(w.data.inventory_filters.path.read_bytes(),saved)
        # A restart sees only the persisted filters, even during the visit.
        self.assertEqual(Data(self.path).inventory_filters.get('alt').query,'Alt search')
        w.back_to_wishlist(); w.switch_character('alt')
        self.assertEqual(p.filters.values(),original)
        self.assertEqual(p.temporary_filter_notice.text(),'')
        self.assertEqual(w.data.inventory_filters.path.read_bytes(),saved)

    def test_reapply_item_link_keeps_original_filters_and_editor(self):
        w=self.w; main=w.data.active; p=w.inventory_page; item=w.data.wishlist.entries[0]
        w.switch_character('alt')
        p.filter_set('query','Original search'); p.filter_set('location','Bank'); p.filter_set('count_status','Unknown')
        original=p.filters.values()
        w.data.inventories['alt']=InventoryBook([entry('bag',4),entry('bank',None,'Bank')])
        p.select('bag'); p.form.load({'name':'Unfinished entry','quantity':'???'})
        raw=p.form.values(); edit_id=p.edit_id
        w.switch_character(main); w.open_inventory_from_wishlist('alt',(main,'General'),item)
        w.resize(1600,1000); w.show(); self.app.processEvents()
        before=files(self.path)
        def adjust():
            p.filter_set('query','Something else'); p.filter_set('location','Bank'); p.filter_set('count_status','Known')
        def check():
            self.assertEqual(p.filters.values(),{'query':item.name,'location':'All','count_status':'All'})
            self.assertEqual(set(p.table.keys),{'bag','bank'})
            self.assertEqual(p.temporary_filters['previous'],original)
            self.assertEqual(p.restore_filters_preview.accessibleName(),'Will restore — Search: “Original search” · Show: Bank · Count status: Unknown')
            self.assertEqual(p.form.values(),raw); self.assertEqual(p.edit_id,edit_id)
            self.assertEqual(files(self.path),before)
        adjust()
        notice=p.temporary_filter_notice
        w.manual_inventory_scroll.ensureWidgetVisible(notice)
        self.app.processEvents()
        # Find the rendered anchor through hover events; font wrapping can move
        # the item to another line, so nominal text widths are not reliable.
        hovered=['']; notice.linkHovered.connect(lambda link:hovered.__setitem__(0,link))
        point=None
        self.app.processEvents()
        for y in range(5,notice.height(),8):
            for x in range(5,notice.width(),12):
                # Deliver to this test widget independently of desktop cursor
                # placement or another temporary test window being foreground.
                self.app.sendEvent(notice,QMouseEvent(QEvent.Type.MouseMove,QPointF(x,y),
                    QPointF(notice.mapToGlobal(QPoint(x,y))),Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
                self.app.processEvents()
                if hovered[0]=='reapply-item': point=QPoint(x,y); break
            if point is not None: break
        self.assertIsNotNone(point,f'The item link must be reachable by the mouse: {notice.geometry()}, {notice.mapToGlobal(QPoint(0,0))}, {notice.text()}')
        QTest.mouseClick(notice,Qt.MouseButton.LeftButton,pos=point)
        check()
        adjust(); notice.setFocus(); QTest.keyClick(notice,Qt.Key.Key_Return); check()
        adjust(); QTest.keyClick(notice,Qt.Key.Key_Space); check()
        QTest.mouseClick(p.restore_filters_button,Qt.MouseButton.LeftButton)
        self.assertEqual(p.filters.values(),original)
        self.assertEqual(p.form.values(),raw); self.assertEqual(files(self.path),before)
        # After Restore the same link can start another temporary search.
        notice.linkActivated.emit('reapply-item')
        check()
        w.back_to_wishlist(); w.switch_character('alt')
        # Completing the visit clears the retained link and its activation.
        self.assertIsNone(p.wishlist_search_item)
        notice.linkActivated.emit('reapply-item')
        self.assertEqual(p.filters.values(),original)

    def test_restore_filters_button_resumes_browsing_without_leaving_or_loading_drafts(self):
        w=self.w; main=w.data.active; p=w.inventory_page; item=w.data.wishlist.entries[0]
        self.assertTrue(p.restore_filters_button.isHidden())
        w.gear_page.form.load({'name':'Unfinished wishlist'})
        self.assertTrue(p.restore_filters_confirmation.isHidden())
        w.switch_character('alt')
        w.data.inventories['alt']=InventoryBook([entry('bag',4),entry('bank',None,'Bank')])
        p.filter_set('query','shield'); p.filter_set('location','Bank'); p.filter_set('count_status','Unknown')
        previous=p.filters.values()
        p.select('bag'); p.form.load({'name':'Unfinished inventory','quantity':'???','note':'Keep typing'})
        raw=p.form.values(); edit_id=p.edit_id; ref=p.reference
        w.switch_character(main)
        w.open_inventory_from_wishlist('alt',(main,'General'),item)
        p.filter_set('query','No results')
        w.settings['text_size']=18; w.apply_appearance(); w.resize(1000,850)
        w.show(); self.app.processEvents()
        self.assertTrue(p.restore_filters_button.isVisible())
        self.assertTrue(p.restore_filters_preview.isVisible())
        self.assertEqual(p.restore_filters_preview.accessibleName(),'Will restore — Search: “shield” · Show: Bank · Count status: Unknown')
        before=files(self.path); records=deepcopy(w.data.inventories)
        QTest.mouseClick(p.restore_filters_button,Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(p.restore_filters_confirmation.isVisible())
        self.assertEqual(p.restore_filters_confirmation.text(),'Previous filters restored — Search: “shield” · Show: Bank · Count status: Unknown')
        self.assertEqual(w.data.active,'alt')
        self.assertEqual(w.pages.currentWidget(),w.scrollers['Inventory & Bank'])
        self.assertEqual(p.filters.values(),previous); self.assertEqual(p.table.keys,['bank'])
        self.assertEqual(p.form.values(),raw); self.assertEqual(p.edit_id,edit_id); self.assertEqual(p.reference,ref)
        self.assertEqual(w.data.inventories,records); self.assertEqual(files(self.path),before)
        self.assertIsNone(p.temporary_filters); self.assertTrue(p.restore_filters_button.isHidden())
        self.assertTrue(p.restore_filters_preview.isHidden()); self.assertEqual(p.restore_filters_preview.text(),'')
        self.assertTrue(p.temporary_filter_notice.isVisible())
        self.assertIn('Browsing normally',p.temporary_filter_notice.text())
        self.assertIn(item.name,p.temporary_filter_notice.text())
        self.assertEqual(w.wishlist_return,(main,'General')); self.assertTrue(w.wishlist_back.isVisible())
        # After restoring, normal filter edits persist and Back must not undo them.
        p.filter_set('query','New normal search'); p.filter_set('location','All')
        self.assertTrue(p.restore_filters_confirmation.isHidden())
        normal=p.filters.values(); saved=w.data.inventory_filters.path.read_bytes()
        self.assertEqual(Data(self.path).inventory_filters.get('alt').query,'New normal search')
        # The retained link stays scoped to the alt after switching away/back.
        w.switch_character(main)
        self.assertTrue(p.temporary_filter_notice.isHidden())
        filters=p.filters.values(); p.reapply_temporary_search()
        self.assertEqual(p.filters.values(),filters)
        w.switch_character('alt')
        self.assertIn(item.name,p.temporary_filter_notice.text())
        p.temporary_filter_notice.setFocus()
        QTest.keyClick(p.temporary_filter_notice,Qt.Key.Key_Return)
        self.assertEqual(p.filters.values(),{'query':item.name,'location':'All','count_status':'All'})
        self.assertEqual(p.temporary_filters['previous'],normal)
        self.assertEqual(p.restore_filters_preview.accessibleName(),'Will restore — Search: “New normal search” · Show: All · Count status: Unknown')
        self.assertEqual(p.form.values(),raw); self.assertEqual(p.edit_id,edit_id)
        self.assertEqual(w.data.inventory_filters.path.read_bytes(),saved)
        p.filter_set('query','Temporary adjustment')
        p.reapply_temporary_search()
        self.assertEqual(p.temporary_filters['previous'],normal)
        p.restore_filters_preview.setFocus()
        QTest.keyClick(p.restore_filters_preview,Qt.Key.Key_Return)
        self.assertTrue(p.restore_filters_confirmation.isVisible())
        self.assertEqual(p.restore_filters_confirmation.text(),'Previous filters restored — Search: “New normal search” · Show: All · Count status: Unknown')
        self.assertEqual(p.filters.values(),normal)
        self.assertEqual(p.form.values(),raw); self.assertEqual(p.reference,ref)
        self.assertEqual(w.data.inventory_filters.path.read_bytes(),saved)
        w.back_to_wishlist()
        self.assertEqual(w.data.active,main)
        self.assertTrue(p.restore_filters_confirmation.isHidden())
        self.assertEqual(w.gear_page.form.values()['name'],'Unfinished wishlist')
        w.switch_character('alt')
        self.assertEqual(p.filters.values(),normal); self.assertEqual(p.form.values(),raw)
        self.assertEqual(w.data.inventory_filters.path.read_bytes(),saved)
        # Empty and markup-like searches remain readable literal text.
        p.filter_set('query',''); p.reapply_temporary_search()  # Completed visits do not reopen.
        w.open_inventory_from_wishlist('alt',(main,'General'),item)
        self.assertIn('Search: (empty)',p.restore_filters_preview.text())
        p.restore_previous_filters()
        self.assertEqual(p.restore_filters_confirmation.text(),'Previous filters restored — Search: (empty) · Show: All · Count status: Unknown')
        p.filter_set('query','<b>shield</b> & sword')
        p.reapply_temporary_search()
        self.assertIn(escape('Search: “<b>shield</b> & sword”'),p.restore_filters_preview.text())
        self.assertEqual(p.restore_filters_preview.textFormat(),Qt.TextFormat.RichText)
        self.assertEqual(p.form.values(),raw)
        # Activate the rendered preview by mouse at larger text size, preserving
        # the exact literal search and raw item editor fields.
        preview=p.restore_filters_preview
        w.manual_inventory_scroll.ensureWidgetVisible(preview); self.app.processEvents()
        hovered=['']; preview.linkHovered.connect(lambda link:hovered.__setitem__(0,link))
        point=None
        for y in range(5,preview.height(),8):
            for x in range(5,preview.width(),12):
                self.app.sendEvent(preview,QMouseEvent(QEvent.Type.MouseMove,QPointF(x,y),
                    QPointF(preview.mapToGlobal(QPoint(x,y))),Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
                if hovered[0]=='restore-filters': point=QPoint(x,y); break
            if point is not None: break
        self.assertIsNotNone(point)
        before=files(self.path)
        QTest.mouseClick(preview,Qt.MouseButton.LeftButton,pos=point)
        self.assertTrue(p.restore_filters_confirmation.isVisible())
        self.assertEqual(p.restore_filters_confirmation.text(),'Previous filters restored — Search: “<b>shield</b> & sword” · Show: All · Count status: Unknown')
        self.assertEqual(p.restore_filters_confirmation.textFormat(),Qt.TextFormat.PlainText)
        self.assertEqual(p.filters.values()['query'],'<b>shield</b> & sword')
        self.assertEqual(p.form.values(),raw); self.assertEqual(p.edit_id,edit_id)
        self.assertEqual(files(self.path),before); self.assertIsNone(p.temporary_filters)
        self.assertFalse(p.temporary_filter_notice.isHidden())
        p.reapply_temporary_search()
        self.assertTrue(p.restore_filters_confirmation.isHidden())
        preview.setFocus(); QTest.keyClick(preview,Qt.Key.Key_Space)
        self.assertTrue(p.restore_filters_confirmation.isVisible())
        self.assertEqual(p.filters.values()['query'],'<b>shield</b> & sword')
        self.assertEqual(p.form.values(),raw); self.assertEqual(files(self.path),before)
        w.switch_character(main); self.assertTrue(p.restore_filters_confirmation.isHidden())
        w.switch_character('alt'); self.assertTrue(p.restore_filters_confirmation.isHidden())

    def test_filter_feedback_wraps_at_large_fonts_and_narrow_widths(self):
        w=self.w; main=w.data.active; p=w.inventory_page; item=w.data.wishlist.entries[0]
        w.switch_character('alt'); p.form.load({'name':'Unfinished entry','quantity':'???'})
        raw=p.form.values(); before=files(self.path)
        w.show()
        def flush():
            for _ in range(3): self.app.processEvents()
        def check(widget):
            flush()
            self.assertFalse(widget.isHidden())
            self.assertGreaterEqual(widget.height()+2,widget.heightForWidth(widget.width()),widget.text())
            self.assertLessEqual(widget.geometry().right(),widget.parentWidget().contentsRect().right()+1)
            self.assertLessEqual(widget.geometry().bottom(),widget.parentWidget().contentsRect().bottom()+1)
            scroll=w.manual_inventory_scroll
            self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
            scroll.ensureWidgetVisible(widget,0,0); flush()
            self.assertTrue(scroll.viewport().rect().intersects(widget.rect().translated(widget.mapTo(scroll.viewport(),QPoint(0,0)))))
        for skin in ('WoW','Standard'):
            for size in (12,18):
                w.settings.update(ui_style=skin,text_size=size); w.apply_appearance()
                for width in (680,900):
                    for query in ('', 'Ancient ceremonial armor of the northern mountains and forgotten guardians '*2, 'W'*140):
                        query=query[:140]
                        with self.subTest(skin=skin,size=size,width=width,query=query):
                            p.end_temporary_search(); p.filters.load({'query':query,'location':'Bank','count_status':'Recheck'})
                            previous=p.filters.values()
                            w.open_inventory_from_wishlist('alt',(main,'General'),item)
                            w.manual_inventory_dialog.resize(width,740); w.show_page('Storage'); flush()
                            self.assertEqual(w.manual_inventory_dialog.width(),width)
                            check(p.restore_filters_preview); check(p.temporary_filter_notice)
                            if query=='W'*140:
                                self.assertGreaterEqual(p.restore_filters_preview.height(),p.restore_filters_preview.fontMetrics().height()*3)
                            p.restore_previous_filters(); check(p.restore_filters_confirmation)
                            if query=='W'*140:
                                self.assertGreaterEqual(p.restore_filters_confirmation.height(),p.restore_filters_confirmation.fontMetrics().height()*3)
                                self.assertIn(query,p.restore_filters_confirmation.accessibleName())
                            self.assertEqual(p.filters.values(),previous); self.assertEqual(p.form.values(),raw)
                            self.assertEqual(files(self.path),before)

    def test_long_wishlist_navigation_wraps_and_preserves_context(self):
        w=self.w; main=w.data.active; p=w.inventory_page
        w.switch_preset('Tank'); w.gear_page.filter_set('query','Tank filter')
        w.gear_page.form.load({'name':'Unfinished tank item'})
        w.playstyle_page.form.load({'notes':'Unfinished tank notes'})
        w.switch_character('alt'); p.filter_set('query','Alt filter'); p.filter_set('location','Bank')
        p.form.load({'name':'Unfinished inventory','quantity':'???'})
        original=p.filters.values(); draft=p.form.values(); saved=w.data.inventory_filters.path.read_bytes()
        w.show()
        def flush():
            for _ in range(3): self.app.processEvents()
        def check(widget):
            flush(); self.assertFalse(widget.isHidden())
            self.assertGreaterEqual(widget.height()+2,widget.heightForWidth(widget.width()))
            self.assertLessEqual(widget.geometry().right(),widget.parentWidget().contentsRect().right()+1)
            self.assertLessEqual(widget.geometry().bottom(),widget.parentWidget().contentsRect().bottom()+1)
            scroll=w.manual_inventory_scroll; self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
            scroll.ensureWidgetVisible(widget,0,0); flush()
            self.assertTrue(scroll.viewport().rect().intersects(widget.rect().translated(widget.mapTo(scroll.viewport(),QPoint(0,0)))))
        def click_link(widget,href):
            check(widget); hovered=['']; callback=lambda link:hovered.__setitem__(0,link)
            widget.linkHovered.connect(callback)
            viewport=w.manual_inventory_scroll.viewport()
            point=None
            try:
                for y in range(5,widget.height(),8):
                    for x in range(5,widget.width(),12):
                        position=QPoint(x,y)
                        if not viewport.rect().contains(widget.mapTo(viewport,position)): continue
                        self.app.sendEvent(widget,QMouseEvent(QEvent.Type.MouseMove,QPointF(position),
                            QPointF(widget.mapToGlobal(position)),Qt.MouseButton.NoButton,
                            Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
                        if hovered[0]==href: point=position; break
                    if point is not None: break
                self.assertIsNotNone(point,'Link must be reachable inside the viewport')
                QTest.mouseClick(widget,Qt.MouseButton.LeftButton,pos=point)
            finally: widget.linkHovered.disconnect(callback)
        for skin in ('WoW','Standard'):
            for size in (12,18):
                w.settings.update(ui_style=skin,text_size=size); w.apply_appearance()
                for width in (680,900):
                    for unbroken in (False,True):
                        with self.subTest(skin=skin,size=size,width=width,unbroken=unbroken):
                            name='W'*100 if unbroken else 'Guardian of the northern mountains and forgotten kingdoms'
                            item=GearItem('long','M'*140 if unbroken else 'Ancient ceremonial shield of the northern mountains and forgotten guardians')
                            next(profile for profile in w.data.profiles if profile.id==main).name=name
                            w.open_inventory_from_wishlist('alt',(main,'Tank'),item)
                            w.manual_inventory_dialog.resize(width,740); flush(); self.assertEqual(w.manual_inventory_dialog.width(),width)
                            for widget in (w.wishlist_back,w.wishlist_destination,p.temporary_filter_notice): check(widget)
                            if unbroken:
                                metrics=w.wishlist_destination.fontMetrics(); available=w.wishlist_destination.width()
                                token_lines=(metrics.horizontalAdvance(name)+available-1)//available
                                self.assertGreaterEqual(w.wishlist_destination.height(),metrics.height()*token_lines)
                                self.assertGreater(p.temporary_filter_notice.height(),p.temporary_filter_notice.fontMetrics().height()*3)
                            p.filter_set('query','Different temporary search')
                            if width==680: click_link(p.temporary_filter_notice,'reapply-item')
                            else:
                                p.temporary_filter_notice.setFocus(); QTest.keyClick(p.temporary_filter_notice,Qt.Key.Key_Return)
                            self.assertEqual(p.filters.values()['query'],item.name)
                            self.assertEqual(p.form.values(),draft)
                            # Exercise both return controls across the matrix.
                            if unbroken:
                                if width==680: click_link(w.wishlist_destination,'return-wishlist')
                                else:
                                    check(w.wishlist_destination); w.wishlist_destination.setFocus()
                                    QTest.keyClick(w.wishlist_destination,Qt.Key.Key_Return)
                            else:
                                check(w.wishlist_back); QTest.mouseClick(w.wishlist_back,Qt.MouseButton.LeftButton)
                            self.assertEqual(w.data.active,main)
                            self.assertEqual(w.data.playstyles.active(main),'Tank')
                            self.assertEqual(w.gear_page.form.values()['name'],'Unfinished tank item')
                            self.assertEqual(w.gear_page.filters.values()['query'],'Tank filter')
                            self.assertEqual(w.playstyle_page.form.values()['notes'],'Unfinished tank notes')
                            w.switch_character('alt')
                            self.assertEqual(p.filters.values(),original); self.assertEqual(p.form.values(),draft)
                            self.assertEqual(w.data.inventory_filters.path.read_bytes(),saved)

    def test_back_restores_original_retained_playstyle_without_reverting_new_edits(self):
        w=self.w; main=w.data.active
        self.assertIsNone(w.wishlist_return); self.assertTrue(w.wishlist_back.isHidden())
        w.preset.setCurrentText('Tank')
        w.gear_page.filter_set('query','Tank search')
        w.gear_page.form.load({'name':'Tank draft'})
        w.open_inventory_from_wishlist('alt',(main,'Tank'))
        # Visiting the source and changing its plan must not redirect Back.
        w.switch_character(main); w.preset.setCurrentText('Healing')
        w.gear_page.filter_set('query','Healing search')
        w.gear_page.form.load({'name':'New healing draft'})
        w.data.profile.character_class='Mage'; w.profiles_changed()
        w.switch_character('alt'); w.inventory_page.form.load({'name':'Alt draft'})
        w.settings['hidden'].append('Gear wishlist')
        settings=deepcopy(w.settings)
        w.back_to_wishlist()
        self.assertEqual(w.data.active,main)
        self.assertEqual(w.data.playstyles.active(main),'Tank')
        self.assertEqual(w.preset.currentText(),'Tank · retained')
        self.assertEqual(w.gear_page.filters.values()['query'],'Tank search')
        self.assertEqual(w.gear_page.form.values()['name'],'Tank draft')
        self.assertEqual(w.pages.currentWidget(),w.scrollers['Gear wishlist'])
        self.assertEqual(w.settings,settings)
        self.assertEqual(w.data.playstyles.available(main,'Mage'),('General','Solo DPS'))
        self.assertEqual(w.gear_page.drafts[(main,'Healing')][1]['name'],'New healing draft')
        w.switch_character('alt'); self.assertEqual(w.inventory_page.form.values()['name'],'Alt draft')

    def test_new_trip_replaces_return_target_and_missing_origin_is_preserved(self):
        w=self.w; main=w.data.active
        w.open_inventory_from_wishlist('alt',(main,'General'))
        w.open_inventory_from_wishlist(main,('alt','General'))
        self.assertEqual(w.wishlist_return,('alt','General'))
        w.back_to_wishlist(); self.assertEqual(w.data.active,'alt'); self.assertIsNone(w.wishlist_return)
        w.open_inventory_from_wishlist(main,('alt','General'))
        w.inventory_page.form.load({'name':'Do not discard'})
        w.data.profiles=[p for p in w.data.profiles if p.id!='alt']
        before=files(self.path)
        w.back_to_wishlist()
        self.assertEqual(w.data.active,main)
        self.assertEqual(w.inventory_page.form.values()['name'],'Do not discard')
        self.assertEqual(w.wishlist_return,('alt','General'))
        self.assertIn('unavailable',w.inventory_page.notice.text())
        self.assertEqual(files(self.path),before)

    def test_open_inventory_requires_an_existing_profile_and_selection(self):
        w=self.w; main=w.data.active
        w.data.inventories['orphan']=InventoryBook([entry('orphan',2)])
        item=w.data.wishlist.entries[0]; before=files(self.path)
        dialog=WishlistAltDialog(w,item,other_stock(w.data,[item])[item.id])
        try:
            dialog.open_inventory(); self.assertEqual(w.data.active,main)
            dialog.table.selectRow(dialog.table.keys.index('orphan'))
            self.assertFalse(dialog.open_button.isEnabled())
            dialog.open_inventory(); self.assertEqual(w.data.active,main)
            self.assertIn('no matching character',dialog.notice.text())
            dialog.table.selectRow(dialog.table.keys.index('alt'))
            self.assertTrue(dialog.open_button.isEnabled())
            # Revalidate at activation if the profile has become unavailable.
            w.data.profiles=[p for p in w.data.profiles if p.id!= 'alt']
            dialog.open_inventory(); self.assertFalse(dialog.open_button.isEnabled())
            self.assertEqual(w.data.active,main); self.assertEqual(files(self.path),before)
        finally: dialog.close(); dialog.deleteLater()


if __name__=='__main__': unittest.main()
