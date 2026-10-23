from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QThreadPool
from companion import Companion,QApplication
from data import Data
from core_observations import CoreData,decode
from character_links import identity,LinkStore
from observed_inventory import ObservationStore,prepare,apply_prepared
from observed_inventory_dialog import ObservedInventoryDialog
from test_copy_and_alts import seed,files
from test_core_inventory_v2 import lua


class ObservedTests(unittest.TestCase):
    def test_direct_view_keeps_complete_snapshot_over_attempt_and_checks_identity(self):
        from saved_inventory_view import linked_snapshots
        from dataclasses import replace
        from unittest.mock import patch
        original=decode(self.source.read_bytes())[0]
        completed=replace(original,scope='bags',interrupted=False)
        attempt=replace(completed,interrupted=True,coverage='partial',rows=())
        with patch('saved_inventory_view.read',return_value=[attempt,completed]):
            records=linked_snapshots(self.root,self.data.active)
            self.assertFalse(records['bags']['interrupted']);self.assertNotIn('bank',records)
        with patch('saved_inventory_view.read',return_value=[attempt]):
            self.assertEqual(linked_snapshots(self.root,self.data.active)['bags']['coverage'],'partial')
        with patch('saved_inventory_view.read',return_value=[replace(completed,realm='Different realm')]):
            with self.assertRaises(ValueError):linked_snapshots(self.root,self.data.active)

    def test_direct_split_view_without_planning_cache(self):
        from saved_inventory_view import linked_snapshots
        for location in self.db['characters']['Player-1-ABC']['locations'].values():
            location['latest']['addonVersion']='0.7.0'
        self.write_source();before=files(self.root)
        records=linked_snapshots(self.root,self.data.active)
        self.assertEqual(records['bags']['rows'],((100,10),))
        self.assertEqual(records['bags']['names'][100],'Test Item')
        self.assertEqual(records['bank']['rows'],())
        self.assertEqual(files(self.root),before)
        self.assertFalse((self.root/'addon_inventory.json').exists())
        self.source.write_bytes(self.source.read_bytes()+b' print("no")')
        with self.assertRaises(ValueError):linked_snapshots(self.root,self.data.active)

    def test_removed_source_retains_snapshots_and_reports_offline(self):
        from game_data_monitor import retained_notice
        apply_prepared(self.data,self.prepared(),self.data.profile_bytes)
        before=files(self.root);self.source.unlink()
        pending=prepare(self.root,{}, {p.id for p in self.data.saved_profiles})
        changed,decisions=apply_prepared(self.data,pending,self.data.profile_bytes)
        self.assertFalse(changed);self.assertEqual(decisions,())
        self.assertIn('2 saved location(s) retained',retained_notice(pending))
        self.assertEqual(files(self.root),{k:v for k,v in before.items() if k!='WFCore.lua'})

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);seed(self.root)
        self.source=self.root/'WFCore.lua'
        fixture=Path(__file__).resolve().parents[2]/'tests/fixtures/WFCore_schema2_example.lua'
        self.db=CoreData(fixture.read_text()).decode()
        del self.db['characters']['Player-1-ABC']['locations']['bags']['attempt']
        self.db['characters']['Player-1-ABC']['client']['build']='70532'
        for location in self.db['characters']['Player-1-ABC']['locations'].values():
            location['latest']['client']['build']='70532'
        self.write_source();self.data=Data(self.root)
        LinkStore(self.root).save(self.data,identity(self.source,'Player-1-ABC','Test'),self.data.active)

    def write_source(self):self.source.write_text('WFCoreDB='+lua(self.db),encoding='utf-8')

    def prepared(self):
        stat=self.source.stat();cache={str(self.source):((stat.st_mtime_ns,stat.st_size),decode(self.source.read_bytes()))}
        return prepare(self.root,cache,{p.id for p in self.data.saved_profiles})

    def tearDown(self):self.tmp.cleanup()

    def test_persist_restart_deduplicate_and_backup(self):
        original=files(self.root);before=deepcopy(self.data.inventories)
        changed,_=apply_prepared(self.data,self.prepared(),self.data.profile_bytes);self.assertTrue(changed)
        ledger=ObservationStore(self.root).ledger;self.assertEqual(len(ledger),2)
        stored=(self.root/'addon_inventory.json').read_bytes()
        changed,_=apply_prepared(self.data,self.prepared(),self.data.profile_bytes);self.assertFalse(changed)
        self.assertEqual((self.root/'addon_inventory.json').read_bytes(),stored)
        self.assertFalse((self.root/'addon_inventory.previous.json').exists())
        for snap in self.db['characters']['Player-1-ABC']['locations'].values():
            snap['latest']['startedAt']+=1;snap['latest']['finishedAt']+=1
        self.write_source();changed,_=apply_prepared(self.data,self.prepared(),self.data.profile_bytes)
        self.assertTrue(changed);self.assertEqual((self.root/'addon_inventory.previous.json').read_bytes(),stored)
        self.assertEqual(self.data.inventories,before)
        self.assertEqual([p for p in original if p!='WFCore.lua' and files(self.root)[p]!=original[p]],[])

    def test_changed_sources_links_dirty_and_invalid_store_preserved(self):
        pending=self.prepared();self.source.write_bytes(self.source.read_bytes()+b'\n')
        with self.assertRaises(ValueError):apply_prepared(self.data,pending,self.data.profile_bytes)
        self.assertFalse((self.root/'addon_inventory.json').exists())
        pending=self.prepared();self.data.dirty.add('Inventory & Bank')
        with self.assertRaises(ValueError):apply_prepared(self.data,pending,self.data.profile_bytes)
        self.data.dirty.clear()
        links=self.root/'character_links.json';links.write_bytes(links.read_bytes()+b'\n')
        with self.assertRaises(ValueError):apply_prepared(self.data,pending,self.data.profile_bytes)
        store=self.root/'addon_inventory.json';store.write_bytes(b'invalid')
        with self.assertRaises(ValueError):self.prepared()
        self.assertEqual(store.read_bytes(),b'invalid')

    def test_unverified_build_does_not_persist(self):
        self.db['characters']['Player-1-ABC']['locations']['bags']['latest']['client']['build']='99999'
        self.db['characters']['Player-1-ABC']['locations']['bank']['latest']['client']['build']='99999'
        self.write_source();changed,decisions=apply_prepared(self.data,self.prepared(),self.data.profile_bytes)
        self.assertFalse(changed);self.assertTrue(all(d.status=='blocked' for d in decisions))
        self.assertFalse((self.root/'addon_inventory.json').exists())

    def test_split_review_preserves_earlier_counts_until_live_validation(self):
        apply_prepared(self.data,self.prepared(),self.data.profile_bytes)
        original=(self.root/'addon_inventory.json').read_bytes()
        for location in self.db['characters']['Player-1-ABC']['locations'].values():
            location['latest']['addonVersion']='0.7.0'
            location['latest']['startedAt']+=10;location['latest']['finishedAt']+=10
        self.write_source();source=self.source.read_bytes()
        changed,decisions=apply_prepared(self.data,self.prepared(),self.data.profile_bytes)
        self.assertFalse(changed)
        self.assertTrue(all(d.status=='blocked' and 'live split validation' in d.reason for d in decisions))
        self.assertEqual((self.root/'addon_inventory.json').read_bytes(),original)
        self.assertEqual(self.source.read_bytes(),source)

    def test_viewer_preserves_active_character_and_drafts(self):
        apply_prepared(self.data,self.prepared(),self.data.profile_bytes)
        app=QApplication.instance() or QApplication([]);w=Companion(self.root);w.testing=True;w.timer.stop();w.probe_page.timer.stop()
        w.inventory_page.form.load({'name':'Unfinished manual edit','quantity':'???'})
        before=deepcopy((w.data.active,w.data.inventories,w.data.dirty,w.inventory_page.form.values()));disk=files(self.root)
        dialog=ObservedInventoryDialog(w)
        try:
            dialog.locations.selectRow(0);self.assertGreater(dialog.items.rowCount(),0)
            dialog.locations.selectRow(1);self.assertEqual(dialog.items.rowCount(),0);self.assertIn('contains no items',dialog.notice.text())
            dialog.character.setCurrentIndex(dialog.character.findData('alt'));dialog.locations.selectRow(1)
            self.assertIn('No saved addon observation',dialog.notice.text())
            self.assertEqual(before,(w.data.active,w.data.inventories,w.data.dirty,w.inventory_page.form.values()))
            self.assertEqual(files(self.root),disk)
        finally:
            dialog.close();dialog.deleteLater();QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()

    def test_inventory_page_defaults_to_saved_and_follows_character_without_editing_plans(self):
        app=QApplication.instance() or QApplication([]);w=Companion(self.root);w.testing=True
        w.updates_panel.timer.stop()
        try:
            w.inventory_page.form.load({'name':'Unfinished manual edit','quantity':'???'})
            before=deepcopy((w.data.inventories,w.inventory_page.form.values()));disk=files(self.root)
            w.show_page('Inventory & Bank')
            view=w.saved_inventory
            self.assertEqual(w.inventory_scope.currentIndex(),0)
            self.assertFalse(view.isWindow());self.assertTrue(w.inventory_page.isHidden())
            self.assertGreater(view.items.rowCount(),0)
            w.inventory_scope.setCurrentIndex(1)
            self.assertTrue(view.isHidden());self.assertFalse(w.inventory_page.isHidden())
            w.show_observed_inventory()
            self.assertEqual(before,(w.data.inventories,w.inventory_page.form.values()))
            self.assertEqual(files(self.root),disk)
            w.switch_character('alt')
            self.assertEqual(view.character.currentData(),'alt')
            self.assertEqual(view.items.rowCount(),0)
            self.assertIn('Unknown',view.notice.text())
            w.switch_character(self.data.active)
            self.assertGreater(view.items.rowCount(),0)
        finally:
            w.close();w.deleteLater();QThreadPool.globalInstance().waitForDone();app.processEvents()


if __name__=='__main__':unittest.main()
