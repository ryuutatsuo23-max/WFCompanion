from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import QThreadPool
from companion import Companion, QApplication
from character_overview import observation_status, summaries
from test_copy_and_alts import seed, files
from game_data_review import installation_status
from presentation import simple_observation
from observed_inventory import ObservationStore


class OverviewTests(unittest.TestCase):
    def test_cards_use_explicit_source_identity_and_keep_data_unchanged(self):
        from profession_observations import ObservationCache,decode
        from test_profession_observations import inputs
        from storage import write_json
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True
            w.timer.stop();w.updates_panel.timer.stop()
            try:
                cache=ObservationCache();cache.accepted=decode(*inputs())
                directory=root/'_classic_beta_'/'WTF'/'Account'/'Example'/'SavedVariables'
                cache.accepted.update(directory=str(directory),files={},provenance='Synthetic only')
                char=cache.accepted['characters'][0];char['label']={'name':'Example Hero','realm':'Example Realm'}
                w.profession_observations=cache
                page=w.character_overview;before=files(root);page.refresh()
                self.assertIn(('saved',1),page.card_buttons)
                self.assertFalse(page.card_buttons[('saved',1)][0].isEnabled())
                self.assertFalse(page.card_buttons['first-character'][1].isEnabled())
                target=(str(directory),char['guid'],1)
                with patch.object(w,'show_profession_observations') as opened:
                    page.card_buttons[('saved',1)][1].click();opened.assert_called_once_with(target)
                selected=[]
                with patch('profession_observations_dialog.ProfessionObservationsDialog.exec',
                           lambda dialog:selected.append(dialog.character.currentData())):
                    w.show_profession_observations(target)
                self.assertEqual([tuple(value) for value in selected],[target])
                self.assertEqual(files(root),before)
                ident=dict(source=str(directory/'WFCore.lua'),environment='Test',realm='Example Realm',
                           guid=char['guid'],version='1.60.1',interface=16001,build='70532',name='Example Hero')
                write_json(root/'character_links.json',dict(version=1,links=[dict(profile='first-character',identity=ident)]))
                before=files(root);page.refresh()
                self.assertNotIn(('saved',1),page.card_buttons)
                self.assertTrue(page.card_buttons['first-character'][1].isEnabled())
                with patch.object(w,'show_profession_observations') as opened:
                    page.card_buttons['first-character'][1].click();opened.assert_called_once_with(target)
                self.assertEqual(files(root),before)
                page.card_buttons['alt'][0].click();self.assertEqual(w.data.active,'alt')
                self.assertEqual(w.pages.currentWidget(),w.scrollers['Inventory & Bank'])
                page.show_details.setChecked(True);self.assertFalse(page.table.isHidden())
                page.show_details.setChecked(False);self.assertTrue(page.table.isHidden())
                ident['source']=str(root/'OtherAccount'/'WFCore.lua')
                write_json(root/'character_links.json',dict(version=1,links=[dict(profile='first-character',identity=ident)]))
                page.refresh();self.assertFalse(page.card_buttons['first-character'][1].isEnabled())
                self.assertIn(('saved',1),page.card_buttons)
            finally:w.close();w.deleteLater();app.processEvents()

    def test_folder_status_is_read_only_and_distinguishes_core_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'_forever_'
            self.assertIn('No game found',installation_status([root]))
            root.mkdir();(root/'Wow.exe').write_bytes(b'test marker')
            core=root/'Interface/AddOns/WFCore';core.mkdir(parents=True)
            (core/'WFCore.toc').write_text('fixture')
            before=files(root)
            self.assertIn('Storage missing',installation_status([root]))
            self.assertEqual(files(root),before)
            storage=core.parent/'WFStorage';storage.mkdir()
            (storage/'WFStorage.toc').write_text('fixture')
            self.assertIn('Core + Storage files found',installation_status([root]))

    def test_addon_snapshot_empty_is_not_an_unknown_bank(self):
        from data import Data
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);data=Data(root)
            now=datetime(2026,10,22,12,tzinfo=timezone.utc);stamp=int(now.timestamp())
            identity=dict(source=str(root/'WFCore.lua'),environment='Test',realm='Test',guid='Player-1-ABC',version='1.60.1',build='70532',name='Example',interface=16001)
            store=ObservationStore(root)
            store.save({('first-character','bags'):dict(identity=identity,started=stamp-10,finished=stamp,rows=(),build='70532')})
            before=files(root)
            result=dict(summaries(data,now))['first-character']
            self.assertEqual(simple_observation(result[3]),'Empty in saved scan')
            self.assertNotEqual(simple_observation(result[4]),'Empty in saved scan')
            self.assertEqual(files(root),before)
            (root/'addon_inventory.json').write_text('broken')
            self.assertTrue(all('Unavailable' in value for value in dict(summaries(data,now))['first-character'][3:5]))

    def test_dates_and_unknown_are_explicit(self):
        now=datetime(2026,10,22,12,tzinfo=timezone.utc)
        self.assertEqual(observation_status([],now),'Not captured')
        self.assertIn('Outdated',observation_status(['2026-10-20T12:00:00+00:00'],now))
        self.assertIn('Recorded',observation_status(['2026-10-22T11:00:00+00:00'],now))
        self.assertIn('mixed dates',observation_status(['2026-10-20T12:00:00+00:00','2026-10-22T11:00:00+00:00'],now))
        self.assertIn('date unknown',observation_status([None],now))
        self.assertIn('check clock',observation_status(['2027-01-01T12:00:00+00:00'],now))

    def test_read_only_refresh_and_navigation_preserve_drafts(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True
            w.timer.stop();w.probe_page.timer.stop()
            try:
                page=w.character_overview
                w.inventory_page.form.load({'name':'Inventory unfinished','quantity':'???'})
                w.gear_page.form.load({'name':'Wishlist unfinished','note':'Keep me'})
                drafts=deepcopy((w.inventory_page.form.values(),w.gear_page.form.values(),w.inventory_page.filters.values(),w.gear_page.filters.values()))
                before=files(root);books=deepcopy(w.data.inventories)
                page.refresh();self.assertEqual(len(page.records),2)
                self.assertEqual(files(root),before);self.assertEqual(w.data.inventories,books)
                page.table.selectRow(page.table.keys.index('alt'));page.open_page('Inventory & Bank')
                self.assertEqual(w.data.active,'alt');self.assertEqual(w.pages.currentWidget(),w.scrollers['Inventory & Bank'])
                page.table.selectRow(page.table.keys.index('first-character'));page.open_page('Gear wishlist')
                self.assertEqual(drafts,(w.inventory_page.form.values(),w.gear_page.form.values(),w.inventory_page.filters.values(),w.gear_page.filters.values()))
                with patch.object(w.gear_page,'show_equipment_comparison') as opened:
                    page.open_equipment();opened.assert_called_once()
                (root/'equipment.json').write_text('invalid',encoding='utf-8')
                self.assertTrue(all('Unavailable' in values[-1] for _,values in summaries(w.data)))
                w.settings['text_size']=18;w.apply_appearance();w.resize(720,700);w.show_page('Overview');w.show();app.processEvents()
                self.assertEqual(w.scrollers['Overview'].horizontalScrollBar().maximum(),0)
            finally:
                QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
