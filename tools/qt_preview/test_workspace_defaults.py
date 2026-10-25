"""Fresh/upgrade navigation defaults using disposable companion preferences."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from companion import Companion,QApplication
from data import validate_qt
from display_settings import DEFAULT
from settings_page import DEFAULT_HIDDEN_TABS
from first_run import SetupGuide


class WorkspaceDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def open(self,root):
        host=Companion(root);host.testing=True
        host.updates_panel.timer.stop();host.saved_character_connection.timer.stop()
        host.character_overview.game_data_monitor.set_enabled(False)
        self.addCleanup(host.deleteLater)
        return host

    def test_fresh_setup_and_restore_defaults_hide_only_requested_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=self.open(Path(tmp))
            self.assertEqual(set(host.settings['hidden']),set(DEFAULT_HIDDEN_TABS))
            visible={host.page_picker.itemText(i) for i in range(host.page_picker.count())}
            self.assertTrue({'Overview','Crafting','Storage','Activity','Addons','Settings'}<=visible)
            self.assertTrue(set(DEFAULT_HIDDEN_TABS).isdisjoint(visible))
            guide=SetupGuide(host)
            self.assertTrue(all(not guide.tab_checks[name].isChecked() for name in DEFAULT_HIDDEN_TABS))
            guide.reject()
            host.toggle_tab('Gathering',True);host.defaults()
            self.assertEqual(set(host.settings['hidden']),set(DEFAULT_HIDDEN_TABS))
            host.close()

    def test_upgrade_keeps_other_preferences_and_saved_opt_in_survives_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);display=deepcopy(DEFAULT)
            display.update(setup=True,hidden=['Activity'],order=['Settings','Crafting'],text_size=14)
            (root/'display_settings.json').write_text(json.dumps(display))
            (root/'qt_fonts.json').write_text(json.dumps(dict(version=1,classic_fonts=False,font_override='',experience_mode='Advanced',workspace_defaults=1)))
            sentinel=root/'WFCore.lua';sentinel.write_bytes(b'unchanged snapshot')
            original={p.name:p.read_bytes() for p in root.iterdir()}
            host=self.open(root)
            self.assertEqual(set(host.settings['hidden']),{'Gathering','Gear wishlist','Auction Journal','Activity'})
            self.assertEqual(host.settings['order'],display['order'])
            self.assertEqual(host.settings['text_size'],14)
            self.assertEqual(host.qt_settings['experience_mode'],'Advanced')
            self.assertTrue(all((root/name).read_bytes()==raw for name,raw in original.items()))
            host.profile_page.form.load({'name':'Unfinished character edit'})
            host.toggle_tab('Gathering',True);self.assertTrue(host.save_session())
            self.assertEqual(host.profile_page.form.values()['name'],'Unfinished character edit')
            host.close()
            reopened=self.open(root)
            self.assertNotIn('Gathering',reopened.settings['hidden'])
            self.assertIn('Activity',reopened.settings['hidden'])
            self.assertTrue({'Gear wishlist','Auction Journal'}<=set(reopened.settings['hidden']))
            self.assertNotIn('Profiles & Rules',reopened.settings['hidden'])
            self.assertEqual(sentinel.read_bytes(),b'unchanged snapshot')
            self.assertEqual(reopened.qt_settings['workspace_defaults'],2)
            reopened.close()

    def test_legacy_qt_preferences_and_marker_validation(self):
        old=dict(version=1,classic_fonts=True,font_override='')
        validate_qt(old);validate_qt(dict(old,workspace_defaults=1));validate_qt(dict(old,workspace_defaults=2))
        for value in (True,0,3,'1'):
            with self.assertRaises(ValueError):validate_qt(dict(old,workspace_defaults=value))
