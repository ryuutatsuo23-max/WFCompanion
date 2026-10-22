"""Offscreen UI checks use only disposable companion state and invented saves."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Qt
from companion import Companion
from profession_observations import ObservationCache
from profession_observations_dialog import ProfessionObservationsDialog
from test_profession_observations import fixture, inputs


class ViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cached_unknown_unmapped_zero_and_failed_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root/'_classic_beta_'/'WTF'/'Account'/'Example'/'SavedVariables'
            folder.mkdir(parents=True)
            host = Companion(root/'state'); host.testing = True
            host.updates_panel.timer.stop(); host.timer.stop()
            cache = ObservationCache()
            dialog = ProfessionObservationsDialog(host, cache)
            try:
                self.assertIn('No observations read', dialog.output.toPlainText())
                self.assertFalse(dialog.refresh_button.isEnabled())
                host.show_page('Crafting')
                self.assertTrue(any(b.text() == 'Cached professions' for b in host.findChildren(QPushButton)))
                for ranks, expected, guids in (({}, 'Unknown', {}), ({1: 0}, '0/0', {}),
                                               ({1: 4915212}, '12/75', {1: 'Player-999-ABC1'})):
                    chars = fixture(); chars[1]['Ranks'] = ranks
                    a, b = inputs(chars, guids)
                    (folder/'DataStore_Crafts.lua').write_bytes(a)
                    (folder/'DataStore.lua').write_bytes(b)
                    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    with patch('profession_observations_dialog.QFileDialog.getExistingDirectory', return_value=str(folder)):
                        dialog.choose()
                    output = dialog.output.toPlainText()
                    self.assertIn('Recorded skill '+expected, output)
                    self.assertIn('Recipe #900001 — name unknown', output)
                    self.assertIn('Ingredients unknown', output)
                    self.assertIn('Coverage unknown', output)
                    if not guids: self.assertIn('Character mapping unavailable', output)
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
                previous = dialog.output.toPlainText()
                (folder/'DataStore_Crafts.lua').write_bytes(b'unsupported()')
                dialog.refresh()
                self.assertIn('Read failed', dialog.status.text())
                self.assertEqual(dialog.output.toPlainText(), previous)
                dialog.show(); self.app.processEvents()
                self.assertTrue(dialog.output.isReadOnly())
                self.assertFalse(dialog.output.isVisible())
                self.assertEqual(dialog.character.count(), 2)
                self.assertEqual(dialog.recipes.rowCount(), 1)
                dialog.search.setText('900001'); self.assertEqual(dialog.recipes.rowCount(), 1)
                dialog.search.setText('not a recipe'); self.assertEqual(dialog.recipes.rowCount(), 0)
                dialog.search.clear()
                dialog.profession.setCurrentIndex(1); self.assertEqual(dialog.recipes.rowCount(), 1)
                dialog.category.setCurrentIndex(1); self.assertEqual(dialog.recipes.rowCount(), 1)
                dialog.character.setCurrentIndex(1); self.assertEqual(dialog.recipes.rowCount(), 0)
                self.assertIn('No learned recipes', dialog.summary.text())
                dialog.character.setCurrentIndex(0); self.assertEqual(dialog.recipes.rowCount(), 1)
                self.assertEqual([dialog.recipes.horizontalHeaderItem(i).text() for i in range(3)],
                                 ['Category', 'Profession', 'Saved recipe'])
                prof = cache.accepted['characters'][0]['professions'][0]
                prof['recipes'] = [{'id': n, 'fields': (True, 0, 1, 1),
                                    'categories': {7: category}}
                                   for n, category in ((100, 'alpha'), (9, 'Zulu'), (20, 'Beta'))]
                dialog.select_character()
                dialog.recipes.sortItems(2, Qt.SortOrder.AscendingOrder)
                self.assertEqual([dialog.recipes.item(i, 2).text() for i in range(3)],
                                 ['Recipe #9', 'Recipe #20', 'Recipe #100'])
                dialog.recipes.sortItems(0, Qt.SortOrder.AscendingOrder)
                self.assertEqual([dialog.recipes.item(i, 0).text() for i in range(3)], ['alpha', 'Beta', 'Zulu'])
                dialog.recipes.sortItems(2, Qt.SortOrder.DescendingOrder)
                dialog.search.setText('Recipe'); dialog.search.clear()
                self.assertEqual(dialog.recipes.item(0, 2).text(), 'Recipe #100')
                dialog.details_button.click(); self.assertTrue(dialog.output.isVisible())
                dialog.details_button.click(); self.assertFalse(dialog.output.isVisible())
                self.assertGreater(dialog.recipes.height(), 100)
                self.assertTrue(dialog.rect().contains(dialog.refresh_button.mapTo(dialog, dialog.refresh_button.rect().center())))
            finally:
                dialog.close(); host.close()


if __name__ == '__main__':
    unittest.main()
