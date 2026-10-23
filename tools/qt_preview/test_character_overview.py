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
    def test_card_order_and_collapse_persist_without_changing_profiles(self):
        from character_overview import validate_card_preferences
        from local_journal import LocalStore
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True
            try:
                page=w.character_overview;before=files(root);original=page.card_order()
                self.assertTrue(page.move_card(original[0],original[1]))
                self.assertEqual(page.card_order()[:2],[original[1],original[0]])
                page.toggle_collapsed();self.assertTrue(page.cards.isHidden())
                page.refresh();self.assertTrue(page.cards.isHidden())
                self.assertEqual(page.card_order()[:2],[original[1],original[0]])
                saved=LocalStore(root,'character_cards.json',{},validate_card_preferences)
                self.assertTrue(saved.data['collapsed']);self.assertEqual(saved.data['order'],page.card_order())
                page.toggle_collapsed();self.assertFalse(page.cards.isHidden())
                for name,value in before.items():self.assertEqual(files(root)[name],value)
                # An external preference edit must not overwrite the file or move cards.
                order=page.card_order();page.card_preferences.path.write_text('external change')
                self.assertFalse(page.move_card(order[0],order[1]));self.assertEqual(page.card_order(),order)
            finally:
                QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()

    def test_drag_target_feedback_clears_on_leave_and_drop(self):
        from unittest.mock import Mock
        from character_overview import CardHandle
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True
            try:
                page=w.character_overview
                source=page.cards_box.itemAt(0).widget().findChild(CardHandle)
                target=page.cards_box.itemAt(1).widget()
                event=Mock();event.source.return_value=source
                target.dragEnterEvent(event);self.assertTrue(target.drop_target)
                event.acceptProposedAction.assert_called_once()
                target.dragLeaveEvent(event);self.assertFalse(target.drop_target)
                target.dragEnterEvent(event);target.dropEvent(event)
                self.assertFalse(target.drop_target)
                self.assertEqual(page.card_order()[1],source.key)
                foreign=Mock();foreign.source.return_value=None
                target.dragEnterEvent(foreign);foreign.ignore.assert_called_once()
                self.assertFalse(target.drop_target)
            finally:
                QThreadPool.globalInstance().waitForDone();app.processEvents();w.close();w.deleteLater();app.processEvents()

    def test_character_cards_reflow_without_losing_buttons(self):
        from character_overview import CharacterCards
        from PySide6.QtWidgets import QGroupBox,QPushButton,QVBoxLayout
        app=QApplication.instance() or QApplication([])
        cards=CharacterCards()
        buttons=[]
        try:
            for i in range(4):
                card=QGroupBox();box=QVBoxLayout(card);button=QPushButton(str(i));box.addWidget(button)
                cards.grid.addWidget(card,i,0);buttons.append(button)
            cards.resize(1150,400);cards.show();app.processEvents();cards.reflow()
            self.assertGreater(cards.columns,1)
            self.assertEqual(cards.grid.getItemPosition(1)[0],0)
            cards.resize(450,800);app.processEvents();cards.reflow()
            self.assertEqual(cards.columns,1)
            self.assertEqual(cards.grid.count(),4)
            self.assertTrue(all(button.parent() is not None for button in buttons))
        finally:cards.close();cards.deleteLater();app.processEvents()

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

    def test_direct_snapshots_override_planning_ledger_without_writes(self):
        from data import Data
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);data=Data(root)
            now=datetime(2026,10,23,12,tzinfo=timezone.utc)
            saved=dict(finished=int(now.timestamp()),rows=((159,16),),coverage='complete',unknown=0,interrupted=False)
            direct={'bags':saved,'bank':dict(saved,rows=())}
            before=files(root)
            with patch('character_overview.linked_snapshots',side_effect=lambda directory,profile:direct if profile=='first-character' else {}):
                records=dict(summaries(data,now))
                self.assertIn('addon snapshot',records['first-character'][3])
                self.assertIn('saved empty',records['first-character'][4])
                self.assertEqual(records['alt'][3:5],('Not captured','Not captured'))
                direct['bank']=dict(saved,rows=(),coverage='partial')
                self.assertIn('incomplete',dict(summaries(data,now))['first-character'][4])
                self.assertNotIn('saved empty',dict(summaries(data,now))['first-character'][4])
            with patch('character_overview.linked_snapshots',side_effect=ValueError('invalid source')):
                self.assertTrue(all('Unavailable' in value for value in dict(summaries(data,now))['first-character'][3:5]))
            self.assertEqual(files(root),before)

    def test_card_opens_saved_selected_character_from_manual_view(self):
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed(root);w=Companion(root);w.testing=True
            try:
                w.updates_panel.timer.stop();w.saved_character_connection.timer.stop()
                w.inventory_page.form.load({'name':'Unfinished manual item'})
                w.set_inventory_view(1)
                w.saved_inventory.character_scope.setCurrentIndex(1)
                w.saved_inventory.search.setText('water')
                before=files(root)
                w.character_overview.card_buttons['alt'][0].click()
                self.assertEqual(w.data.active,'alt')
                self.assertEqual(w.inventory_scope.currentIndex(),0)
                self.assertEqual(w.saved_inventory.character_scope.currentIndex(),0)
                self.assertEqual(w.saved_inventory.search.text(),'water')
                self.assertEqual(w.pages.currentWidget(),w.scrollers['Inventory & Bank'])
                w.switch_character('first-character')
                self.assertEqual(w.inventory_page.form.values()['name'],'Unfinished manual item')
                after=files(root)
                for name,value in before.items():
                    if not name.startswith('profiles'):self.assertEqual(after[name],value,name)
            finally:
                QThreadPool.globalInstance().waitForDone();w.close();w.deleteLater();app.processEvents()

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
