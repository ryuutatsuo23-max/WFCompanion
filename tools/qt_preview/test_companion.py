"""Real Qt workflows in temporary folders; original personal files are hash-checked."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from companion import Companion, QApplication, TABS
from data import Data, import_legacy, SAVE_FILES
from app import SOURCE
from model import default_profile
from storage import ProfileStore, write_json
from inventory import InventoryEntry, InventoryBook, InventoryStore, utc_now
from gear import GearItem, GearWishlist, GearStore
from professions import Material, Recipe, Ingredient, CraftGoal, ProfessionPlan, PlanStore
from catalogue_dialog import ItemPicker


def fingerprint(directory):
    return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()} if directory.exists() else {}


class CompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.personal=fingerprint(SOURCE/'state')

    @classmethod
    def tearDownClass(cls):
        assert fingerprint(SOURCE/'state')==cls.personal

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-qt-test-')
        self.directory=Path(self.temp.name)
        p=default_profile(); second=deepcopy(p); second.id='alt'; second.name='Alt'
        ProfileStore(self.directory).save([p,second],p.id)
        self.w=Companion(self.directory); self.w.testing=True; self.w.timer.stop()

    def tearDown(self):
        self.w.close(); self.app.processEvents(); self.w.deleteLater(); self.app.processEvents(); self.temp.cleanup()

    def select(self,page,index=0): page.table.selectRow(index); self.app.processEvents()

    def inventory(self,name='Copper Ore',quantity='10',location='Bags'):
        p=self.w.inventory_page; p.new(); p.form.load(dict(name=name,quantity=quantity,location=location)); p.apply(); return p

    def test_all_tabs_loaded_once_and_drafts_survive_switches(self):
        w=self.w; widgets=[w.pages.widget(i) for i in range(w.pages.count())]
        self.assertEqual(w.pages.count(),len(TABS))
        self.inventory().save(); w.inventory_page.form.load({'name':'Unfinished item'})
        w.profile_page.form.load({'name':'Unfinished profile'})
        w.profile_page.rule.load({'message':'Unfinished rule'})
        w.recipes.enqueue_form.load({'quantity':'7'}); w.recipes.ingredient_amount.load({'amount':'12'})
        w.switch_character('alt'); self.assertEqual(w.inventory_page.form.values()['name'],'')
        w.switch_character('first-character')
        self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished item')
        self.assertEqual(w.profile_page.form.values()['name'],'Unfinished profile')
        self.assertEqual(w.profile_page.rule.values()['message'],'Unfinished rule')
        self.assertEqual(w.recipes.enqueue_form.values()['quantity'],'7')
        self.assertEqual(w.recipes.ingredient_amount.values()['amount'],'12')
        for name in reversed(TABS):
            w.nav_buttons[name].click()
            self.assertEqual(w.pages.currentWidget(),w.scrollers[name])
        self.assertEqual(widgets,[w.pages.widget(i) for i in range(w.pages.count())])
        self.assertEqual(Data(self.directory).inventory.entries[0].name,'Copper Ore')

    def test_inventory_filters_undo_and_raw_draft_persist_separately(self):
        p=self.inventory(); p.save(); original=deepcopy(p.book.entries[0]); self.select(p)
        p.form.load({'name':'Not applied','quantity':'nonsense'})
        p.remove(); p.save()
        self.assertEqual(p.form.values()['quantity'],'nonsense')
        p.filter_set('query','Copper'); p.filter_set('count_status','Unknown')
        loaded=Data(self.directory)
        self.assertEqual(loaded.inventory.entries,[])
        self.assertEqual(loaded.inventory_undo.records[loaded.active].item,original)
        self.assertEqual(loaded.inventory_filters.get(loaded.active).query,'Copper')
        p.undo(); self.assertEqual(p.book.entries[0],original)
        self.assertEqual(p.form.values()['name'],'Not applied')
        p.reset_filters(); self.assertEqual(p.form.values()['quantity'],'nonsense')
        p.save(); self.assertEqual(Data(self.directory).inventory.entries[0],original)
        with self.assertRaises(ValueError): p.undo()

    def test_wishlist_ownership_filters_and_undo_are_independent(self):
        self.inventory('Manual Sword','1').save()
        p=self.w.gear_page; p.form.load(dict(name='Manual Sword',slot='Main hand',status='Wanted')); p.apply(); p.save()
        self.assertEqual(p.table.item(0,3).text(),'Owned'); self.assertEqual(p.table.item(0,8).text(),'Wanted')
        p.form.load({'note':'unfinished note'}); p.filter_set('ownership','Not owned'); self.assertEqual(p.table.rowCount(),0)
        p.filter_set('query','Manual'); p.filter_set('status','Obtained')
        self.assertEqual(Data(self.directory).gear_filters.get(self.w.data.active).status,'Obtained')
        p.reset_filters(); self.select(p); p.form.load({'note':'still unfinished'}); p.remove(); p.save()
        p.undo(); self.assertEqual(p.form.values()['note'],'still unfinished'); p.save()
        self.assertEqual(Data(self.directory).wishlist.entries[0].note,'')

    def test_crafting_queue_shopping_prices_and_recheck(self):
        w=self.w
        self.inventory(quantity='2').save(); self.inventory(quantity='0',location='Bank').save()
        w.gathering.form.load(dict(name='Copper Ore',target='3')); w.gathering.apply()
        r=w.recipes; r.form.load(dict(name='Copper Bar',profession='Mining',output_per_craft='1',ingredients='Copper Ore = 2')); r.apply()
        self.select(r); r.enqueue_form.load({'quantity':'4'}); r.enqueue()
        requirement=w.data.plan.requirements(w.data.inventory)[0]
        self.assertEqual((requirement.needed,requirement.owned,requirement.remaining),(11,2,9))
        q=w.queue; self.select(q); q.form.load({'name':'Unfinished output'})
        w.journal.form.load(dict(name='Copper Ore',gold='1',silver='2',copper='3')); w.journal.save()
        self.assertEqual(w.shopping.estimates[0][2],9*10203)
        q.record()
        self.assertEqual(w.data.plan.goals[0].completed,0)
        q.record_confirm.click(); q.save()
        self.assertEqual(w.data.plan.goals[0].completed,1)
        self.assertEqual(q.form.values()['name'],'Unfinished output')
        self.assertIsNone(w.data.plan.requirements(w.data.inventory)[0].owned)
        self.assertIsNone(w.shopping.estimates[0][2])
        reloaded=Data(self.directory)
        self.assertEqual(reloaded.plan.goals[0].completed,1)
        self.assertEqual(reloaded.plan.recipes[0].name,'Copper Bar')
        self.assertTrue(reloaded.plan.recheck_after)
        # Explicitly applying unchanged readings confirms new observations.
        for i in range(len(w.inventory_page.book.entries)):
            w.inventory_page.select(w.inventory_page.book.entries[i].id); w.inventory_page.apply()
        self.assertEqual(w.data.plan.requirements(w.data.inventory)[0].owned,2)

    def test_settings_preserve_data_defaults_and_character_drafts(self):
        w=self.w; before=(self.directory/'profiles.json').read_bytes()
        w.profile_page.form.load({'name':'Unsaved profile'}); w.inventory_page.form.load({'name':'Unsaved item'})
        w.change('theme','Orgrimmar · Horde'); w.change('text_size',18); w.change('panel_transparency',56)
        w.toggle_tab('Gathering',False); w.settings['order']=['Settings','Crafting']; w.sync_order(); w.save_session()
        self.assertEqual((self.directory/'profiles.json').read_bytes(),before)
        self.assertFalse((self.directory/'inventory.json').exists())
        loaded=Data(self.directory); self.assertEqual(loaded.display.data['panel_transparency'],56)
        hidden=deepcopy(w.settings['hidden']); w.reset_order(); self.assertEqual(w.settings['hidden'],hidden)
        w.revert(); self.assertEqual(w.settings['order'],['Settings','Crafting'])
        self.assertIs(w.tab_check_row.layout().itemAt(0).widget(),w.tab_checks['Crafting'])
        w.defaults(); self.assertEqual(w.settings['panel_transparency'],20)
        self.assertEqual(w.profile_page.form.values()['name'],'Unsaved profile')
        self.assertEqual(Data(self.directory).display.data['theme'],'Orgrimmar · Horde')

    def test_profiles_rules_trackers_saved_but_not_simulated_readings(self):
        w=self.w; p=w.profile_page
        p.form.load(dict(name='Character',level='24',character_class='Mage')); p.apply_profile()
        p.rule.load(dict(name='Test low health',kind='health',delay='0',threshold='45',recovery='60',priority='1')); p.apply_rule()
        p.rule.load({'message':'unfinished'}); p.save()
        self.assertEqual(Data(self.directory).profile.level,24)
        self.assertNotEqual(Data(self.directory).profile.rules[-1].message,'unfinished')
        t=w.tracker_page; t.form.load(dict(kind='buff',name='Special buff',buff='Missing')); t.apply(); t.save()
        self.assertEqual(Data(self.directory).profile.buffs[-1].name,'Special buff')
        self.assertEqual(w.tracker_reading('buff',t.edit_id[1])[0],'Missing')
        w.set_tracker_reading('cooldown','primary',1800.5,False)
        w.switch_character('alt'); w.switch_character('first-character')
        self.assertEqual(w.tracker_reading('cooldown','primary')[0],1800.5)
        w.cooldown.setValue(25); self.assertEqual(w.tracker_reading('cooldown','primary')[0],25)
        w.hp.setValue(20); w.demo_tick(); self.assertIn('Check',w.reminder.text())
        w.sim.load({'readings':'Unknown'}); w.demo_tick(); self.assertTrue(all(w.decisions.item(i,1).text()=='blocked' for i in range(w.decisions.rowCount())))

    def test_external_file_conflict_is_preserved(self):
        self.inventory().save(); path=self.directory/'inventory.json'; external=path.read_bytes()+b'\n'; path.write_bytes(external)
        with self.assertRaises(ValueError): self.w.inventory_page.save()
        self.assertEqual(path.read_bytes(),external)
        path=self.directory/'profiles.json'; external=path.read_bytes()+b'\n'; path.write_bytes(external)
        with self.assertRaises(ValueError): self.w.data.save_profiles()
        self.assertEqual(path.read_bytes(),external)

    def test_catalogue_selection_filters_and_unknown_details(self):
        # Public builds deliberately have an empty catalogue. Exercise selection
        # with explicit temporary evidence instead of a private developer dataset.
        from catalogue import ItemCatalogue
        sample=self.directory/'test-catalogue.json'
        evidence=dict(url='https://example.com/test-copper',checked_on='2026-10-25',reported_build=None)
        sample.write_text(json.dumps(dict(version=1,revision='test-selection-v1',items=[dict(
            reference=dict(item_id=2770,name='Copper Ore',equip_slot=None,
                           source_url=evidence['url'],checked_on=evidence['checked_on'],sample_revision='test-selection-v1'),
            category='Material',item_type='Metal',required_level=None,item_level=None,
            variant_note='Synthetic selection fixture',evidence=[evidence])])),encoding='utf-8')
        w=self.w;w.catalogue_db=ItemCatalogue(self.directory,sample_path=sample)
        self.assertEqual(w.catalogue_db.error,'')
        dialog=ItemPicker(w,'Material',lambda item:w.inventory_page.use_item(item))
        dialog.form.load({'query':'Copper Ore'}); dialog.refresh()
        self.assertGreater(dialog.table.rowCount(),0); dialog.table.selectRow(0); self.app.processEvents()
        dialog.accept_item(); self.assertIsNotNone(w.inventory_page.reference)
        self.assertEqual(w.inventory_page.form.values()['name'],'Copper Ore')
        dialog.deleteLater()
        p=w.inventory_page; p.form.load({'quantity':'0'}); p.apply(); p.save()
        dialog=ItemPicker(w,'All',lambda _:None); dialog.form.load({'query':'Copper Ore','ownership':'Unknown','use_character_level':True}); dialog.refresh()
        self.assertGreater(dialog.table.rowCount(),0)
        self.assertEqual(dialog.table.item(0,3).text(),'Unknown')
        self.assertTrue(Data(self.directory).search_filters.get(w.data.active,'All').use_character_level)
        dialog.done(0); dialog.deleteLater()

    def test_font_roles_and_paint_only_transparency(self):
        w=self.w; w.show(); w.show_page('Settings'); w.change('theme','Stormwind · Alliance'); w.change('text_size',18); w.sync_controls(); QTest.qWait(40)
        from fonts import FILES, ART_DIRECTORY
        if all((ART_DIRECTORY/'wow_fonts'/f).exists() for f in FILES.values()):
            from fonts import PUBLIC_FILES
            self.assertEqual(set(w.fonts.available),set(FILES) | set(PUBLIC_FILES))
        self.assertEqual(w.fonts.family('Missing optional font','Segoe UI'),'Segoe UI')
        s=w.scrollers['Settings']; s.ensureWidgetVisible(w.opacity); QTest.qWait(20)
        styles,loads=w.style_updates,w.art_loads; geometry=w.opacity.geometry()
        for value in (0,15,60,25,40,20):
            w.opacity.setValue(value); self.app.processEvents()
            self.assertEqual(w.opacity.geometry(),geometry)
        self.assertEqual((w.style_updates,w.art_loads),(styles,loads))

        for name in TABS:
            w.show_page(name); self.app.processEvents(); w.resize(900,800); self.app.processEvents(); w.resize(1250,950); self.app.processEvents()
        self.assertEqual((w.style_updates,w.art_loads),(styles,loads))

    def test_nested_wheel_legacy_appearance_and_support_save_isolation(self):
        w=self.w; w.show(); w.resize(1000,800); w.change('text_size',18); w.show_page('Settings'); QTest.qWait(30)
        outer=w.scrollers['Settings'].verticalScrollBar(); outer.setValue(min(300,outer.maximum()))
        before=outer.value(); self.assertGreater(before,0)
        viewport=w.tab_order.viewport(); pos=QPointF(10,10)
        event=QWheelEvent(pos,QPointF(viewport.mapToGlobal(QPoint(10,10))),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.ShiftModifier,Qt.ScrollPhase.NoScrollPhase,False)
        self.app.sendEvent(viewport,event); self.assertLess(outer.value(),before)
        self.assertFalse(hasattr(w,'custom'))
        # Old saved overrides remain compatible even though their editors were removed.
        w.settings['background']='#234567'; w.apply_appearance()
        self.assertEqual(w.settings['background'],'#234567')
        self.assertNotEqual(Data(self.directory).display.data['background'],'#234567')
        w.inventory_page.form.load({'name':'Unfinished item'})
        w.support.form.load({'note':'Manual support plan'}); w.support.save()
        loaded=Data(self.directory)
        self.assertEqual(loaded.display.data['support'][loaded.active]['note'],'Manual support plan')
        self.assertNotEqual(loaded.display.data['background'],'#234567')
        self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished item')
        w.save_session(); self.assertEqual(Data(self.directory).display.data['background'],'#234567')


class ImportTests(unittest.TestCase):
    def test_valid_saved_models_survive_copy_and_independent_edits(self):
        with tempfile.TemporaryDirectory() as raw:
            base=Path(raw); source=base/'legacy'; dest=base/'qt'
            profile=default_profile(); ProfileStore(source).save([profile],profile.id)
            original=Data(source)
            original.inventory.entries.append(InventoryEntry('ore','Copper Ore',0,'Bank',utc_now()))
            original.plan.materials.append(Material('Copper Ore',7,None,'Either'))
            original.wishlist.entries.append(GearItem('goal','Manual Sword'))
            for kind in ('Inventory & Bank','Crafting','Gear wishlist'): original.save_records(kind)
            before=fingerprint(source); import_legacy(source,dest); copied=Data(dest)
            self.assertEqual(copied.profiles,original.profiles)
            self.assertEqual(copied.plan,original.plan)
            self.assertEqual(copied.inventory,original.inventory)
            self.assertEqual(copied.wishlist,original.wishlist)
            copied.inventory.entries[0].quantity=12; copied.save_records('Inventory & Bank')
            self.assertEqual(fingerprint(source),before)
            self.assertEqual(Data(source).inventory.entries[0].quantity,0)

    def test_byte_exact_allowlist_once_and_conflict_guards(self):
        with tempfile.TemporaryDirectory() as raw:
            base=Path(raw); source=base/'legacy'; dest=base/'qt'; source.mkdir()
            for name in SAVE_FILES:
                (source/name).write_bytes(b'{"legacy":true}\n')
                (source/name.replace('.json','.previous.json')).write_bytes(b'previous bytes')
            (source/'item_catalogue.sqlite3').write_bytes(b'cache')
            before=fingerprint(source); import_legacy(source,dest)
            manifest=json.loads((dest/'qt_import_manifest.json').read_text())
            self.assertEqual(len(manifest['files']),2*len(SAVE_FILES))
            for name,digest in manifest['files'].items(): self.assertEqual(hashlib.sha256((dest/name).read_bytes()).hexdigest(),digest)
            self.assertFalse((dest/'item_catalogue.sqlite3').exists()); self.assertEqual(fingerprint(source),before)
            (dest/'inventory.json').write_bytes(b'new Qt data'); import_legacy(source,dest)
            self.assertEqual((dest/'inventory.json').read_bytes(),b'new Qt data')
            with self.assertRaises(ValueError): import_legacy(source,source)
            with self.assertRaises(ValueError): import_legacy(source,source/'nested')
            other=base/'occupied'; other.mkdir(); (other/'unrelated.txt').write_text('keep')
            with self.assertRaises(ValueError): import_legacy(source,other)
            self.assertEqual((other/'unrelated.txt').read_text(),'keep')


if __name__=='__main__': unittest.main()
