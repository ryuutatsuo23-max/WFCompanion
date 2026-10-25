import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QPoint
from companion import Companion, PagePicker
import windows_startup

class NavigationStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_pages_and_child_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Companion(Path(tmp));host.testing=True;host.updates_panel.timer.stop()
            try:
                host.show_page('Inventory & Bank')
                self.assertEqual(host.page_picker.currentText(),'Storage')
                host.show_inventory_section(True)
                self.assertFalse(host.alt_inventory.isHidden())
                host.settings['hidden']=['Inventory & Bank'];host.rebuild_navigation()
                self.assertEqual(host.page_picker.currentText(),'Settings')
                host.show_page('Inventory & Bank')
                self.assertEqual(host.page_picker.currentText(),'Storage')
                self.assertIn(host.getting_started,host.settings_groups['Connections'])
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

    def test_page_popup_stays_below_control_for_each_selection(self):
        host=QWidget();host.setGeometry(50,50,500,500)
        picker=PagePicker(host);picker.setGeometry(230,50,220,30)
        picker.addItems(['Page '+str(i) for i in range(11)])
        host.show();self.app.processEvents()
        try:
            for index in (0,5,10):
                picker.setCurrentIndex(index);picker.showPopup();self.app.processEvents()
                popup=picker.view().window()
                self.assertEqual(popup.y(),picker.mapToGlobal(QPoint(0,picker.height())).y())
                self.assertTrue(picker.screen().availableGeometry().contains(popup.geometry()))
                picker.hidePopup()
        finally:host.close()

if __name__=='__main__':unittest.main()
