"""Exercise per-character/preset saves and raw drafts without personal data I/O."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from PySide6.QtTest import QTest
from companion import Companion, QApplication
from data import Data
from gear import GearItem,GearWishlist,GearStore
from gear_filters import GearFilters,GearFilterStore
from gear_undo import RemovedGoal,GearUndoStore
from model import default_profile
from storage import ProfileStore
from playstyles import Playstyles,PRESETS,CLASS_PLAYSTYLES,validate,validate_plan


def hashes(path):
    return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}


class PlaystyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-playstyle-test-'); self.path=Path(self.temp.name)
        p=default_profile(); p.character_class='Paladin'
        second=deepcopy(p); second.id='alt'; second.name='Mage friend'; second.character_class='Mage'
        ProfileStore(self.path).save([p,second],p.id)
        GearStore(self.path).save({p.id:GearWishlist([GearItem('old','Existing shield')])})
        GearFilterStore(self.path).save(p.id,GearFilters(query='Existing'))
        GearUndoStore(self.path).save({p.id:RemovedGoal(0,GearItem('removed','Old removed shield'))})
        self.before=hashes(self.path)
        self.w=Companion(self.path); self.w.testing=True; self.w.timer.stop()

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); self.app.processEvents(); self.temp.cleanup()

    def preset(self,name):
        self.w.preset.setCurrentText(name); self.app.processEvents()
        self.assertEqual(self.w.data.playstyles.active(self.w.data.active),name)

    def gear(self,name,save=True):
        page=self.w.gear_page; page.new(); page.form.load({'name':name}); page.apply()
        if save: page.save()
        return page

    def test_existing_files_and_general_remain_unchanged_on_selection(self):
        after=hashes(self.path)
        self.assertTrue(all(after[key]==value for key,value in self.before.items()))
        self.assertFalse((self.path/'playstyle_presets.json').exists())
        self.assertEqual(self.w.data.wishlist.entries[0].name,'Existing shield')
        for name in PRESETS[1:]:
            self.preset(name); self.assertEqual(self.w.data.wishlist.entries,[])
        self.preset('General')
        self.assertEqual(self.w.gear_page.filters.values()['query'],'Existing')
        self.assertIn('Old removed shield',self.w.gear_page.undo_preview.text())
        after=hashes(self.path)
        self.assertTrue(all(after[key]==value for key,value in self.before.items()))

    def test_character_and_preset_drafts_survive_with_shared_inventory(self):
        w=self.w; p=w.inventory_page
        p.form.load({'name':'Shared shield','quantity':'1'}); p.apply(); p.save()
        p.form.load({'name':'Unfinished inventory','quantity':'???'})
        w.profile_page.form.load({'name':'Unfinished profile'})
        self.preset('Tank'); self.gear('Shared shield')
        self.assertEqual(w.gear_page.table.item(0,3).text(),'Owned')
        w.gear_page.form.load({'name':'Unfinished tank gear'})
        w.playstyle_page.form.load({'notes':'Unfinished tank\nnotes'})
        w.playstyle_page.step.load({'text':'Unfinished tank step'})
        self.preset('Healing'); self.gear('Healing item')
        w.gear_page.form.load({'name':'Unfinished healing gear'})
        w.switch_character('alt'); self.preset('Solo DPS'); self.gear('Mage solo plan')
        self.assertEqual(w.data.inventory.entries,[])
        w.switch_character('first-character')
        self.assertEqual(w.preset.currentText(),'Healing')
        self.assertEqual(w.gear_page.form.values()['name'],'Unfinished healing gear')
        self.preset('Tank')
        self.assertEqual(w.gear_page.form.values()['name'],'Unfinished tank gear')
        self.assertEqual(w.playstyle_page.form.values()['notes'],'Unfinished tank\nnotes')
        self.assertEqual(w.playstyle_page.step.values()['text'],'Unfinished tank step')
        self.assertEqual(w.inventory_page.form.values()['quantity'],'???')
        self.assertEqual(w.profile_page.form.values()['name'],'Unfinished profile')
        self.assertEqual(w.data.inventory.entries[0].name,'Shared shield')
        w.demo_tick()

    def test_save_boundaries_and_restart(self):
        w=self.w; self.preset('Tank'); self.gear('Unsaved applied tank',save=False)
        plan=w.playstyle_page
        plan.form.load({'notes':'Applied tank notes\nSecond line'}); plan.apply_notes()
        plan.step.load({'text':'Bring shield'}); plan.apply_step()
        plan.form.load({'notes':'Unfinished new notes'}); plan.step.load({'text':'Unfinished step'})
        plan.save()
        restarted=Data(self.path)
        self.assertEqual(restarted.wishlist.entries,[])
        self.assertEqual(restarted.playstyles.plan(restarted.active)['notes'],'Applied tank notes\nSecond line')
        self.assertEqual(len(restarted.playstyles.plan(restarted.active)['checklist']),1)
        w.gear_page.save()
        plan.form.load({'notes':'Applied but unsaved notes'}); plan.apply_notes()
        self.preset('Healing'); self.gear('Saved healing')
        self.preset('Tank')
        restarted=Data(self.path)
        self.assertEqual(restarted.wishlist.entries[0].name,'Unsaved applied tank')
        self.assertEqual(restarted.playstyles.plan(restarted.active)['notes'],'Applied tank notes\nSecond line')
        self.assertEqual(w.playstyle_page.form.values()['notes'],'Applied but unsaved notes')
        self.assertIn(('Playstyle plan','first-character','Tank'),w.data.dirty)
        self.assertNotIn(('Gear wishlist','first-character','Tank'),w.data.dirty)

    def test_filters_and_removal_undo_are_isolated_and_persistent(self):
        w=self.w; self.preset('Tank'); p=self.gear('Tank shield')
        p.table.selectRow(0); self.app.processEvents(); p.form.load({'note':'Unfinished gear note'})
        p.remove(); p.save(); p.filter_set('query','Tank'); p.filter_set('status','Obtained')
        self.preset('Healing'); self.gear('Healing shield')
        self.assertFalse(p.undo_button.isEnabled()); self.assertEqual(p.filters.values()['query'],'')
        self.preset('Tank')
        self.assertEqual(p.filters.values()['query'],'Tank'); self.assertEqual(p.filters.values()['status'],'Obtained')
        self.assertEqual(p.form.values()['note'],'Unfinished gear note')
        self.assertIn('Tank shield',p.undo_preview.text())
        self.assertIsNotNone(Data(self.path).playstyles.saved_preset(w.data.active)['undo'])
        p.undo(); p.save()
        self.assertEqual(p.form.values()['note'],'Unfinished gear note')
        self.assertEqual(Data(self.path).wishlist.entries[0].note,'')
        self.assertEqual(w.data.gear[w.data.active].entries[0].name,'Existing shield')

    def test_checklist_actions_preserve_note_and_step_drafts(self):
        self.preset('Solo DPS'); page=self.w.playstyle_page
        page.step.load({'text':'Repair equipment'}); page.apply_step()
        page.table.selectRow(0); self.app.processEvents()
        page.step.load({'text':'Unfinished replacement'}); page.form.load({'notes':'Raw notes'})
        page.toggle(); page.save()
        self.assertTrue(page.plan['checklist'][0]['done'])
        self.assertEqual(page.step.values()['text'],'Unfinished replacement')
        self.assertEqual(Data(self.path).playstyles.plan(self.w.data.active)['notes'],'')
        page.remove(); page.save()
        self.assertEqual(page.plan['checklist'],[])
        self.assertEqual(page.form.values()['notes'],'Raw notes')
        with self.assertRaises(ValueError): page.apply_step()

    def test_bad_and_external_files_preserved(self):
        self.preset('Tank'); self.gear('Tank shield')
        path=self.w.data.playstyles.store.path
        original=path.read_bytes(); path.write_bytes(original+b' ')
        with self.assertRaises(ValueError): self.w.gear_page.save()
        self.assertEqual(path.read_bytes(),original+b' ')
        path.write_text('{broken',encoding='utf-8'); bad=Playstyles(self.path)
        self.assertTrue(bad.store.error)
        with self.assertRaises(ValueError): bad.select('first-character','Healing')
        self.assertEqual(path.read_text(),'{broken')

    def test_class_choices_overrides_and_hidden_plans_preserve_drafts(self):
        w=self.w; self.preset('Healing'); self.gear('Healing gear')
        w.gear_page.form.load({'name':'Raw healing draft'})
        w.playstyle_page.form.load({'notes':'Raw healing notes'})
        w.profile_page.form.load({'character_class':'Warrior'}); w.profile_page.apply_profile()
        self.assertEqual(w.preset.currentText(),'Healing · retained')
        self.preset('Tank')
        self.assertEqual([w.preset.itemText(i) for i in range(w.preset.count())],['General','Tank','Solo DPS'])
        w.switch_preset('Healing'); self.assertEqual(w.data.playstyles.active(w.data.active),'Tank')
        choices=w.playstyle_options
        choices.form.load({'Healing':True}); choices.save()
        self.preset('Healing')
        self.assertEqual(w.gear_page.form.values()['name'],'Raw healing draft')
        self.assertEqual(w.playstyle_page.form.values()['notes'],'Raw healing notes')
        self.assertEqual(w.data.wishlist.entries[0].name,'Healing gear')
        self.assertIn('Healing',Data(self.path).playstyles.available(w.data.active,'Warrior'))
        choices.form.controls['Tank'].setChecked(False)
        w.switch_character('alt'); w.switch_character('first-character')
        self.assertFalse(choices.form.values()['Tank'])
        choices.defaults(); self.preset('Tank')
        self.assertNotIn('Healing',[w.preset.itemText(i) for i in range(w.preset.count())])
        self.assertEqual(w.gear_page.drafts[('first-character','Healing')][1]['name'],'Raw healing draft')

    def test_18_point_layout_and_unsaved_new_character(self):
        w=self.w; w.profile_page.create(False); self.preset('Solo DPS')
        self.gear('Unsaved character item',save=False)
        with self.assertRaises(ValueError): w.gear_page.save()
        w.profile_page.save(); w.gear_page.save()
        self.assertEqual(Data(self.path).playstyles.active(w.data.active),'Solo DPS')
        w.settings['text_size']=18; w.apply_appearance(); w.show_page('Gear wishlist'); w.show_gear_section(True)
        w.resize(1000,800); w.show(); QTest.qWait(40)
        for name in PRESETS: self.preset(name)
        self.assertGreaterEqual(w.preset.width(),w.preset.fontMetrics().horizontalAdvance('Solo DPS'))
        for button in w.playstyle_page.findChildren(type(w.back_button)):
            self.assertGreaterEqual(button.width(),button.fontMetrics().horizontalAdvance(button.text()))


class PlaystyleValidationTests(unittest.TestCase):
    def test_nine_class_planning_defaults(self):
        self.assertEqual(len(CLASS_PLAYSTYLES),9)
        self.assertEqual(CLASS_PLAYSTYLES['Warrior'],('Tank','Solo DPS'))
        self.assertEqual(CLASS_PLAYSTYLES['Paladin'],('Tank','Healing','Solo DPS'))
        for name in ('Mage','Rogue','Hunter','Warlock'): self.assertEqual(CLASS_PLAYSTYLES[name],('Solo DPS',))
        for name in ('Priest','Shaman'): self.assertEqual(CLASS_PLAYSTYLES[name],('Healing','Solo DPS'))

    def test_unknown_schema_fields_and_invalid_plans_rejected(self):
        for payload in ({'version':2,'characters':{}},{'version':True,'characters':{}},
                        {'version':1,'characters':{'x':{'active':'Unknown','presets':{}}}}):
            with self.assertRaises(ValueError): validate(payload)
        for plan in ({'notes':'x'*10001,'checklist':[]},{'notes':'bad\0','checklist':[]},
                     {'notes':'','checklist':[{'id':'1','text':'','done':False}]}):
            with self.assertRaises(ValueError): validate_plan(plan)


if __name__=='__main__': unittest.main()
