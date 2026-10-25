"""Saved-page redesign exercises temporary state only."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
from companion import Companion,QApplication
from test_copy_and_alts import seed,files
from character_links import LinkStore


def profession(kind='crafting'):
    return dict(id=197,name='Tailoring',kind=kind,skill=18,max_skill=75,observed_at=1792750000,coverage='returned-list-only',recipes=[
        dict(id=3755,name='Linen Bag',learned=True,output_id=4238,reagents_status='known',slots=[
            dict(required=True,quantity=3,alternatives=[dict(id=2996,name='Bolt of Linen Cloth')])]),
        dict(id=999,name='Recorded unlearned recipe',learned=False,output_id=None,reagents_status='unknown',slots=[])])


class RedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);seed(self.root)
        self.w=Companion(self.root);self.w.testing=True;self.w.updates_panel.timer.stop();self.w.saved_character_connection.timer.stop()
        self.w.character_overview.game_data_monitor.set_enabled(False)
        self.link=dict(source=str(self.root/'WFCore.lua'),environment='Test',realm='Test',guid='Player-1-ABC',version='1.60.1',interface=16001,build='70532',name='First')
        LinkStore(self.root).save(self.w.data,self.link,self.w.data.active)
        self.w.show();self.app.processEvents()

    def tearDown(self):self.w.close();self.w.deleteLater();self.app.processEvents();self.temp.cleanup()

    def test_storage_headers_fill_after_resizing_and_moving(self):
        w=self.w;w.show_page('Storage');self.app.processEvents();table=w.saved_inventory.items;header=table.horizontalHeader()
        for width in (680,1200):
            w.resize(width,900);self.app.processEvents()
            table.setColumnWidth(0,190);self.app.processEvents()
            self.assertGreaterEqual(header.length(),table.viewport().width())
            self.assertLessEqual(table.columnWidth(0),200)
            header.setSectionsMovable(True);header.moveSection(0,2);self.app.processEvents()
            self.assertGreaterEqual(header.length(),table.viewport().width())
            header.moveSection(2,0)

    def test_settings_groups_preserve_unsaved_controls_and_drafts(self):
        w=self.w;w.show_page('Settings');w.inventory_page.form.load({'name':'Keep this draft'})
        original=deepcopy(w.settings)
        for name,panels in w.settings_groups.items():
            w.select_settings_category(name);self.app.processEvents()
            for other,other_panels in w.settings_groups.items():
                self.assertTrue(all(panel.isHidden()==(name!=other) for panel in other_panels))
        w.select_settings_category('Appearance');w.change('text_size',14)
        w.select_settings_category('Connections');self.assertEqual(w.settings['text_size'],14)
        w.revert();self.assertEqual(w.settings,original)
        self.assertEqual(w.inventory_page.form.values()['name'],'Keep this draft')
        self.assertFalse(w.dirty_button.isHidden())
        w.select_settings_category('Appearance');w.change('text_size',13);self.assertTrue(w.save_session())
        self.assertEqual(w.data.display.data['text_size'],13)

    def test_planning_tools_remain_separate_from_saved_pages(self):
        w=self.w;w.queue.form.load({'name':'Unfinished recipe'})
        for name in ('Queue','Recipe book','Shopping list','Gathering goals','Price journal'):
            w.show_planning(name);self.assertEqual(w.page_picker.currentText(),'Planning')
            self.assertTrue(w.planning_choices[name].isChecked())
        self.assertEqual(w.queue.form.values()['name'],'Unfinished recipe')
        self.assertEqual(w.data.plan.goals,[])
        w.show_page('Auction House');self.assertEqual(w.page_picker.currentText(),'Auction House')
        self.assertIn('No saved',w.saved_auctions.status.text())

    def test_recipes_follow_character_and_compare_only_saved_stock(self):
        w=self.w;main=w.data.active;view=w.saved_crafting
        record=dict(rows=((2996,4),),coverage='complete',interrupted=False,unknown=0)
        snapshot=dict(professions=[profession()],notes=['Unlearned catalogue not captured'],source='temporary')
        original=deepcopy(w.data.plan);source_before=files(self.root)
        with patch('wfprofessions_reader.read_character',return_value=snapshot),patch('saved_professions_page.linked_snapshots',return_value={'bags':record}):
            w.show_page('Crafting');self.app.processEvents();view.refresh()
            self.assertEqual(len(view.records),2)
            view.recipes.selectRow(0);self.assertEqual(view.materials.item(0,2).text(),'4')
            self.assertEqual(view.materials.item(0,3).text(),'Unknown')
            self.assertEqual(view.materials.item(0,5).text(),'Unknown')
            view.knowledge.setCurrentText('Unlearned');self.assertEqual(view.recipes.rowCount(),1)
            self.assertEqual(view.recipes.item(0,0).text(),'Recorded unlearned recipe')
            view.search.setText('no match');self.assertEqual(view.recipes.rowCount(),0)
            view.search.clear();view.knowledge.setCurrentText('All recorded')
            w.switch_character('alt');self.app.processEvents();self.assertEqual(view.recipes.rowCount(),0)
            w.switch_character(main);self.app.processEvents();self.assertEqual(view.recipes.rowCount(),2)
            self.assertEqual(w.data.plan,original)
        for path,raw in source_before.items():
            if not path.startswith('profiles'):self.assertEqual((self.root/path).read_bytes(),raw)

    def test_professions_auto_refresh_and_missing_data_clear_previous_rows(self):
        w=self.w;view=w.saved_crafting;snapshot=dict(professions=[profession()],notes=[],source='temporary')
        with patch('wfprofessions_reader.read_character',return_value=snapshot):
            w.show_page('Crafting');self.app.processEvents();view.search.setText('Linen')
            w.queue.form.load({'name':'Keep edits'})
            with patch.object(view,'signature',return_value=('changed',)):
                view.poll();snapshot['professions'][0]['recipes'][0]['name']='New Linen Bag';view.poll()
                self.assertEqual(view.recipes.item(0,0).text(),'New Linen Bag')
                self.assertEqual(view.search.text(),'Linen')
            with patch('wfprofessions_reader.read_character',side_effect=ValueError('unreadable')):
                view.refresh();self.assertEqual(view.recipes.rowCount(),0)
                self.assertIn('unavailable',view.status.text())
            self.assertEqual(w.queue.form.values()['name'],'Keep edits')

    def test_repeated_material_demand_uses_saved_names_and_complete_counts(self):
        from saved_professions_page import snapshot_counts
        record=dict(rows=((2996,4),),coverage='complete',interrupted=False,unknown=0,names={2996:'Saved cloth'})
        self.assertEqual(snapshot_counts({'bags':record},2996),(4,None))
        self.assertEqual(snapshot_counts({'bags':dict(record,coverage='partial')},2996),(None,None))
        view=self.w.saved_crafting;prof=profession();recipe=prof['recipes'][0]
        recipe['slots']*=2;recipe['slots'][0]['alternatives'][0]['name']=None
        view.records={(197,3755):(prof,recipe)}
        empty=dict(record,rows=())
        with patch('saved_professions_page.linked_snapshots',return_value={'bags':record,'bank':empty}) as read:
            view.select_recipe((197,3755))
            self.assertEqual(read.call_count,len(self.w.data.saved_profiles))
            self.assertEqual(view.materials.item(0,0).text(),'Saved cloth')
            self.assertEqual(view.materials.item(0,5).text(),'Short by 2')

    def test_auction_sample_search_and_damage_keep_game_data_untouched(self):
        from test_wfauction_reader import fixture
        path=self.root/'WFAuctionHouse.preview.json';raw=json.dumps(fixture());path.write_text(raw)
        view=self.w.saved_auctions;view.load(path)
        self.assertIn('development sample',view.status.text());self.assertIn('SYNTHETIC',view.market.currentText())
        self.assertEqual(view.items.rowCount(),1)
        view.search.setText('2770');self.assertEqual(view.items.rowCount(),1)
        view.search.setText('missing');self.assertEqual(view.items.rowCount(),0)
        self.assertEqual(path.read_text(),raw)
        path.write_text('{broken');view.refresh();self.assertEqual(view.items.rowCount(),0)
        self.assertIn('Could not read',view.status.text());self.assertEqual(path.read_text(),'{broken')

    def test_crafting_storage_back_preserves_recipe_filters_and_exact_material(self):
        w=self.w;view=w.saved_crafting
        (self.root/'WFCore.lua').write_text('temporary fixture')
        bag=dict(identity=self.link,finished=1792750000,rows=((2996,1),(12996,5)),names={2996:'Bolt of Linen Cloth'},coverage='complete',unknown=0,interrupted=False)
        records={'bags':bag,'bank':dict(bag,rows=())}
        snapshot=dict(professions=[profession()],notes=[],source='temporary')
        before=files(self.root);w.queue.form.load({'name':'Keep draft'})
        owner=w.data.active
        def read_stock(directory,profile):return records if profile==owner else None
        with patch('wfprofessions_reader.read_character',return_value=snapshot),patch('saved_professions_page.linked_snapshots',side_effect=read_stock),patch('observed_inventory_dialog.linked_snapshots',side_effect=read_stock):
            w.show_page('Crafting');self.app.processEvents()
            view.profession.setCurrentIndex(view.profession.findData(197));view.knowledge.setCurrentText('Learned');view.search.setText('Linen')
            view.recipes.selectRow(0);view.materials.selectRow(0)
            self.assertEqual(view.materials.item(0,5).text(),'Short by 2')
            self.assertTrue(view.storage_button.isEnabled());view.storage_button.click();self.app.processEvents()
            self.assertEqual(w.page_picker.currentText(),'Storage');self.assertEqual(w.saved_inventory.character_scope.currentIndex(),1)
            self.assertEqual(w.saved_inventory.scope,'all')
            self.assertEqual(w.saved_inventory.items.rowCount(),1)
            self.assertEqual(w.saved_inventory.items.item(0,4).text(),'2996')
            w.go_back();self.app.processEvents()
            self.assertEqual(w.page_picker.currentText(),'Crafting');self.assertEqual(view.recipes.key(),(197,3755))
            self.assertEqual(view.materials.key(),(1,2996));self.assertTrue(view.storage_button.isEnabled())
            self.assertEqual(view.profession.currentData(),197);self.assertEqual(view.knowledge.currentText(),'Learned');self.assertEqual(view.search.text(),'Linen')
            view.storage_button.click();w.saved_inventory.search.clear()
            self.assertIsNone(w.saved_inventory.material);self.assertEqual(w.saved_inventory.items.rowCount(),2)
            w.go_back();w.switch_character('alt');self.app.processEvents()
            self.assertEqual(view.recipes.rowCount(),0);self.assertEqual(view.materials.rowCount(),0);self.assertFalse(view.storage_button.isEnabled())
            self.assertEqual(w.queue.drafts[next(p.id for p in w.data.profiles if p.id!='alt')][1]['name'],'Keep draft')
        for path,raw in before.items():
            if not path.startswith('profiles'):self.assertEqual((self.root/path).read_bytes(),raw)

    def test_missing_material_and_unknown_bank_never_claim_zero_stock(self):
        w=self.w;view=w.saved_crafting
        (self.root/'WFCore.lua').write_text('temporary fixture')
        bag=dict(identity=self.link,finished=1792750000,rows=(),names={},coverage='complete',unknown=0,interrupted=False)
        snapshot=dict(professions=[profession()],notes=[],source='temporary')
        records={'bags':bag}
        with patch('wfprofessions_reader.read_character',return_value=snapshot),patch('saved_professions_page.linked_snapshots',return_value=records),patch('observed_inventory_dialog.linked_snapshots',return_value=records):
            w.show_page('Crafting');view.recipes.selectRow(0);view.materials.selectRow(0)
            self.assertEqual([view.materials.item(0,i).text() for i in (2,3,5)],['0','Unknown','Unknown'])
            view.storage_button.click();self.assertEqual(w.saved_inventory.items.rowCount(),0)
            self.assertIn('unknown',w.saved_inventory.empty_notice.text().lower())
            records['bank']=dict(bag)
            w.go_back();view.refresh();view.recipes.selectRow(0)
            self.assertEqual(view.materials.item(0,5).text(),'Short by 3')

    def test_recipe_click_selects_first_material_and_double_click_opens_details(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        w=self.w;view=w.saved_crafting;prof=profession()
        bag=prof['recipes'][0]
        bag['slots'].append(dict(required=True,quantity=3,alternatives=[dict(id=2320,name='Coarse Thread')]))
        for identifier,name,item in ((2963,'Bolt of Linen Cloth',2589),(2538,'Charred Wolf Meat',2672)):
            recipe=deepcopy(bag);recipe.update(id=identifier,name=name)
            recipe['slots']=[dict(required=True,quantity=2,alternatives=[dict(id=item,name='Material')])]
            prof['recipes'].append(recipe)
        snapshot=dict(professions=[prof],notes=[],source='temporary');before=files(self.root)
        w.queue.form.load({'name':'Keep details draft'});w.resize(1200,950)
        with patch('wfprofessions_reader.read_character',return_value=snapshot),patch('saved_professions_page.linked_snapshots',return_value=None):
            w.show_page('Crafting');self.app.processEvents()
            for identifier,item in ((3755,2996),(2963,2589),(2538,2672),(3755,2996)):
                index=view.recipes.keys.index((197,identifier));cell=view.recipes.item(index,0)
                view.recipes.scrollToItem(cell);self.app.processEvents()
                QTest.mouseClick(view.recipes.viewport(),Qt.MouseButton.LeftButton,pos=view.recipes.visualItemRect(cell).center())
                self.assertEqual(view.materials.key(),(1,item));self.assertTrue(view.storage_button.isEnabled())
            QTest.mouseDClick(view.recipes.viewport(),Qt.MouseButton.LeftButton,pos=view.recipes.visualItemRect(cell).center());self.app.processEvents()
            dialog=view.recipe_dialog
            self.assertTrue(dialog.isVisible());self.assertIn('Linen Bag',dialog.windowTitle())
            self.assertEqual(w.page_picker.currentText(),'Crafting')
            self.assertEqual(dialog.materials.rowCount(),2);self.assertTrue(dialog.find_button.isEnabled())
            dialog.materials.selectRow(1);dialog.find_button.click();self.app.processEvents()
            self.assertFalse(dialog.isVisible());self.assertEqual(w.page_picker.currentText(),'Storage')
            self.assertEqual(w.saved_inventory.material,('Coarse Thread',2320))
            w.go_back();self.app.processEvents();self.assertEqual(view.materials.key(),(2,2320))
            view.recipes.selectRow(view.recipes.keys.index((197,999)))
            self.assertFalse(view.storage_button.isEnabled());view.open_recipe_details()
            self.assertFalse(view.recipe_dialog.find_button.isEnabled());view.recipe_dialog.reject()
        self.assertEqual(files(self.root),before)
        self.assertEqual(w.queue.form.values()['name'],'Keep details draft')
