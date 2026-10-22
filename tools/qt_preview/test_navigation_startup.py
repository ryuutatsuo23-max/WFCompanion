import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from companion import Companion
import windows_startup

class NavigationStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_pages_and_child_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            try:
                host.show_page('Inventory & Bank')
                self.assertEqual(host.page_picker.currentText(),'Inventory & Bank')
                host.inventory_scope.setCurrentText('All characters')
                self.assertFalse(host.alt_inventory.isHidden())
                host.settings['hidden']=['Inventory & Bank'];host.rebuild_navigation()
                self.assertEqual(host.page_picker.currentText(),'Settings')
                host.show_page('Inventory & Bank')
                self.assertEqual(host.page_picker.currentText(),'Inventory & Bank')
                self.assertEqual(host.page_layouts[-1].indexOf(host.getting_started),0)
                self.assertEqual(host.page_layouts[0].indexOf(host.getting_started),-1)
                self.assertFalse(host.startup_check.isChecked())
                self.assertFalse(host.startup_check.isEnabled())
            finally:host.close()

    def test_startup_writes_only_own_run_value(self):
        import winreg
        with patch.object(windows_startup,'available',return_value=True), patch.object(winreg,'CreateKeyEx') as create, patch.object(winreg,'SetValueEx') as put, patch.object(winreg,'DeleteValue') as delete:
            windows_startup.set_enabled(True)
            self.assertEqual(put.call_args.args[1], 'WFCompanion')
            self.assertTrue(put.call_args.args[4].startswith('"'))
            windows_startup.set_enabled(False)
            self.assertEqual(delete.call_args.args[1], 'WFCompanion')
            self.assertEqual(create.call_args.args[0],winreg.HKEY_CURRENT_USER)

if __name__=='__main__':unittest.main()
