from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from PySide6.QtWidgets import QLabel
from companion import Companion,QApplication
from professions import CraftGoal,Ingredient
from inventory import InventoryEntry,utc_now
from test_copy_and_alts import seed,files


class CraftRecordPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);seed(self.root)
        self.host=Companion(self.root);self.host.testing=True
        self.host.updates_panel.timer.stop();self.host.saved_character_connection.timer.stop()
        self.host.character_overview.game_data_monitor.set_enabled(False)
        self.page=self.host.queue;self.data=self.host.data
        self.data.plan.goals=[CraftGoal('demo','Thread example',3,[Ingredient('Thread',2),Ingredient('Water',1)],completed=2)]
        self.data.inventory.entries=[InventoryEntry('b','Thread',3,'Bags',utc_now()),InventoryEntry('k','Thread',1,'Bank',utc_now())]
        (self.root/'WFCore.lua').write_text('saved snapshot sentinel')
        self.page.refresh();self.page.table.selectRow(0)
        self.page.form.load({'name':'Unfinished draft','quantity':'99','ingredients':'Different material = 7'})
        self.draft=self.page.form.values();self.before=files(self.root)
        self.stock=deepcopy(self.data.inventories);self.plans=deepcopy(self.data.plans)

    def tearDown(self):
        if hasattr(self.page,'record_dialog'):self.page.record_dialog.reject()
        if hasattr(self.page,'progress_dialog'):self.page.progress_dialog.reject()
        self.host.close();self.host.deleteLater();self.app.processEvents();self.tmp.cleanup()

    def test_cancel_preserves_plan_drafts_inventory_and_files(self):
        self.page.record();self.page.record_dialog.reject()
        self.assertEqual(self.data.plans,self.plans)
        self.assertEqual(self.data.inventories,self.stock)
        self.assertEqual(self.page.form.values(),self.draft)
        self.assertEqual(files(self.root),self.before)

    def test_final_craft_rechecks_manual_counts_preserves_snapshots_and_drafts(self):
        self.page.record()
        text=' '.join(w.text() for w in self.page.record_dialog.findChildren(QLabel))
        self.assertIn('2 / 3 to 3 / 3',text);self.assertIn('completes',text)
        self.page.record_confirm.click()
        self.assertEqual(self.data.plan.goals[0].completed,3)
        self.assertEqual(set(self.data.plan.recheck_after),{'thread','water'})
        self.assertEqual(self.data.inventories,self.stock)
        self.assertEqual(self.page.form.values(),self.draft)
        self.assertEqual(files(self.root),self.before)
        with self.assertRaises(ValueError):self.page.record()
        self.assertEqual(self.data.plan.goals[0].completed,3)

    def test_confirmation_notes_fit_below_table(self):
        from PySide6.QtWidgets import QTableWidget
        self.page.record();self.app.processEvents()
        dialog=self.page.record_dialog
        notes=next(w for w in dialog.findChildren(QLabel) if w.text().startswith('Unknown counts'))
        table=dialog.findChild(QTableWidget)
        self.assertGreater(notes.geometry().top(),table.geometry().bottom())
        self.assertGreaterEqual(notes.height(),notes.heightForWidth(notes.width()))

    def test_partial_craft_updates_remaining_need_but_does_not_guess_stock(self):
        self.data.plan.goals[0].quantity=5
        self.page.record();self.page.record_confirm.click()
        rows={r.name:r for r in self.data.plan.requirements(self.data.inventory)}
        self.assertEqual(rows['Thread'].needed,4)
        self.assertIsNone(rows['Thread'].owned);self.assertIsNone(rows['Thread'].remaining)
        self.assertIsNone(rows['Water'].owned)
        self.assertEqual(files(self.root),self.before)

    def test_changed_plan_cannot_apply_stale_confirmation(self):
        self.page.record();self.data.plan.goals[0].quantity=4
        self.page.record_confirm.click()
        self.assertFalse(self.page.record_confirm.isEnabled())
        self.assertEqual(self.data.plan.goals[0].completed,2)
        self.assertFalse(self.data.plan.recheck_after)

    def test_undo_restores_previous_rechecks_and_keeps_drafts_and_snapshots(self):
        self.data.plan.recheck_after['water']='2026-10-01T00:00:00+00:00'
        before=deepcopy(self.data.plan)
        self.page.record();self.page.record_confirm.click()
        self.assertIn('3/3 complete',self.page.craft_status.text())
        self.assertIn('Unsaved plan changes',self.page.plan_status.text())
        self.page.undo_craft_button.click()
        self.assertEqual(self.data.plan,before)
        self.assertFalse(self.page.undo_craft_button.isEnabled())
        self.assertEqual(self.page.form.values(),self.draft)
        self.assertEqual(self.data.inventories,self.stock)
        self.assertEqual(files(self.root),self.before)

    def test_save_and_reopen_recording_then_save_and_reopen_undo(self):
        from data import Data
        self.data.save_records('Inventory & Bank')
        snapshot=(self.root/'WFCore.lua').read_bytes()
        self.page.record();self.page.record_confirm.click();self.page.save()
        self.assertEqual(self.page.plan_status.text(),'No unsaved plan changes.')
        reopened=Data(self.root)
        self.assertEqual(reopened.plan,self.data.plan)
        self.assertEqual(reopened.plan.goals[0].completed,3)
        self.page.undo_craft();self.page.save()
        reopened=Data(self.root)
        self.assertEqual(reopened.plan,self.plans[self.data.active])
        self.assertEqual(reopened.inventory,self.data.inventory)
        self.assertEqual(self.page.form.values(),self.draft)
        self.assertEqual((self.root/'WFCore.lua').read_bytes(),snapshot)

    def test_newer_inventory_or_plan_changes_disable_undo(self):
        self.page.record();self.page.record_confirm.click()
        self.data.inventory.entries[0].quantity=10
        self.page.refresh()
        self.assertFalse(self.page.undo_craft_button.isEnabled())
        with self.assertRaises(ValueError):self.page.undo_craft()
        self.assertEqual(self.data.inventory.entries[0].quantity,10)
        self.assertEqual(self.data.plan.goals[0].completed,3)

    def test_other_character_cannot_undo_recording(self):
        self.page.record();self.page.record_confirm.click()
        original=self.data.active;self.data.active='alt';self.page.refresh()
        self.assertFalse(self.page.undo_craft_button.isEnabled())
        self.data.active=original;self.page.refresh()
        self.assertTrue(self.page.undo_craft_button.isEnabled())

    def test_lower_progress_cancel_retains_final_craft_draft_and_undo(self):
        self.page.record();self.page.record_confirm.click()
        recorded=deepcopy(self.data.plan);history=deepcopy(self.page.craft_history)
        self.page.apply();self.app.processEvents()
        text=' '.join(w.text() for w in self.page.progress_dialog.findChildren(QLabel))
        self.assertIn('3 / 3',text);self.assertIn('2 / 99',text)
        self.assertEqual(self.data.plan,recorded);self.assertEqual(files(self.root),self.before)
        self.page.progress_dialog.reject()
        self.assertEqual(self.data.plan,recorded);self.assertEqual(self.page.craft_history,history)
        self.assertEqual(self.page.form.values(),self.draft)
        self.page.undo_craft();self.assertEqual(self.data.plans,self.plans)
        self.assertEqual(self.data.inventories,self.stock);self.assertEqual(files(self.root),self.before)

    def test_confirm_lower_progress_save_reopen_retains_rechecks_and_snapshots(self):
        from data import Data
        self.page.record();self.page.record_confirm.click();rechecks=deepcopy(self.data.plan.recheck_after)
        self.page.apply();self.page.progress_confirm.click()
        self.assertEqual(self.data.plan.goals[0].completed,2)
        self.assertEqual(self.data.plan.goals[0].name,'Unfinished draft')
        self.assertEqual(self.data.plan.recheck_after,rechecks)
        self.assertFalse(self.page.undo_craft_button.isEnabled())
        self.assertEqual(files(self.root),self.before)
        self.assertEqual(self.page.form.values(),self.draft);self.assertEqual(self.data.inventories,self.stock)
        self.page.save();reopened=Data(self.root)
        self.assertEqual(reopened.plan,self.data.plan);self.assertEqual(reopened.plan.goals[0].completed,2)
        self.assertEqual((self.root/'WFCore.lua').read_bytes(),self.before['WFCore.lua'])

    def test_save_final_progress_does_not_apply_older_form(self):
        from data import Data
        self.page.record();self.page.record_confirm.click();self.page.apply();self.page.progress_dialog.reject()
        self.page.save();self.assertEqual(Data(self.root).plan.goals[0].completed,3)
        self.assertEqual(self.page.form.values(),self.draft)
        self.assertTrue(self.page.undo_craft_button.isEnabled())
        self.page.undo_craft();self.page.save();self.assertEqual(Data(self.root).plan.goals[0].completed,2)
        self.assertEqual((self.root/'WFCore.lua').read_bytes(),self.before['WFCore.lua'])

    def test_unchanged_or_increased_progress_applies_without_confirmation(self):
        self.page.apply();self.assertFalse(hasattr(self.page,'progress_dialog'))
        self.page.form.load({'completed':'3'});self.page.apply()
        self.assertEqual(self.data.plan.goals[0].completed,3);self.assertFalse(hasattr(self.page,'progress_dialog'))

    def test_stale_lower_progress_confirmation_rejects_changed_state(self):
        self.page.record();self.page.record_confirm.click()
        original=deepcopy(self.data.plan);owner=self.data.active
        for change in ('plan','draft','character'):
            self.data.active=owner;self.data.plans[owner]=deepcopy(original);self.page.form.load(self.draft)
            self.page.apply()
            if change=='plan':self.data.plan.goals[0].quantity=4
            elif change=='draft':self.page.form.load({'name':'Newer draft'})
            else:self.data.active='alt'
            before=deepcopy(self.data.plans)
            self.page.progress_confirm.click();self.assertFalse(self.page.progress_confirm.isEnabled())
            self.assertEqual(self.data.plans,before);self.page.progress_dialog.reject()
        self.data.active=owner;self.assertEqual(files(self.root),self.before)

    def test_invalid_lower_progress_is_rejected_before_dialog(self):
        self.page.record();self.page.record_confirm.click();before=deepcopy(self.data.plan)
        self.page.form.load({'quantity':'1','completed':'2'})
        with self.assertRaises(ValueError):self.page.apply()
        self.assertFalse(hasattr(self.page,'progress_dialog'));self.assertEqual(self.data.plan,before)

    def test_lower_progress_cancel_is_default_and_escape_keeps_recording(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialogButtonBox
        self.page.record();self.page.record_confirm.click();before=deepcopy(self.data.plan)
        for key in (Qt.Key.Key_Return,Qt.Key.Key_Escape):
            self.page.apply();self.app.processEvents()
            buttons=self.page.progress_dialog.findChild(QDialogButtonBox)
            self.assertTrue(buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
            QTest.keyClick(self.page.progress_dialog,key);self.app.processEvents()
            self.assertFalse(self.page.progress_dialog.isVisible());self.assertEqual(self.data.plan,before)
            self.assertTrue(self.page.undo_craft_button.isEnabled())


if __name__=='__main__':unittest.main()
