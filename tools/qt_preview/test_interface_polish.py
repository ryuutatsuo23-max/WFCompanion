"""Pointer navigation and layout regressions, using disposable state only."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import Qt, QPoint, QPointF, QThreadPool
from PySide6.QtGui import QWheelEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox as NativeComboBox
from companion import Companion, QApplication
from controls import ComboBox
from addon_art import logo_pixmap
from test_copy_and_alts import seed, files


class InterfacePolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);seed(self.root)
        self.w=Companion(self.root);self.w.testing=True;self.w.timer.stop()
        self.w.updates_panel.timer.stop();self.w.saved_character_connection.timer.stop()
        self.w.character_overview.game_data_monitor.set_enabled(False)
        self.w.probe_page.reader=Mock(poll=Mock(return_value=(None,None)))
        self.w.resize(1200,900);self.w.show();self.flush()

    def flush(self):
        for _ in range(4):self.app.processEvents()

    def tearDown(self):
        self.w.close();QThreadPool.globalInstance().waitForDone(3000)
        self.w.deleteLater();self.flush();self.tmp.cleanup()

    def test_header_drag_shares_space_without_losing_right_edge(self):
        for page,table in (('Storage',self.w.saved_inventory.items),('Crafting',self.w.saved_crafting.recipes)):
            self.w.show_page(page);self.flush();header=table.horizontalHeader()
            before=[table.columnWidth(i) for i in range(table.columnCount())]
            x=header.sectionViewportPosition(0)+header.sectionSize(0)-1
            start=QPoint(x,header.height()//2);end=start-QPoint(70,0)
            QTest.mousePress(header.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(header.viewport(),end,30)
            QTest.mouseRelease(header.viewport(),Qt.MouseButton.LeftButton,pos=end);self.flush()
            self.assertTrue(table._manual_columns)
            self.assertAlmostEqual(table.columnWidth(0),before[0]-70,delta=3)
            self.assertAlmostEqual(table.columnWidth(1),before[1]+70,delta=3)
            self.assertEqual([table.columnWidth(i) for i in range(2,table.columnCount()-1)],before[2:-1])
            self.assertGreaterEqual(header.length(),table.viewport().width())
            self.assertLessEqual(header.length(),table.viewport().width()+1)
            content=table.columnWidth(0)
            x=header.sectionViewportPosition(1)+header.sectionSize(1)-1
            start=QPoint(x,header.height()//2);end=start+QPoint(35,0)
            QTest.mousePress(header.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(header.viewport(),end,30)
            QTest.mouseRelease(header.viewport(),Qt.MouseButton.LeftButton,pos=end);self.flush()
            self.assertEqual(table.columnWidth(0),content)
            self.assertLessEqual(header.length(),table.viewport().width()+1)
            self.w.resize(1100,900);self.flush();self.assertEqual(table.columnWidth(0),content)
            self.w.resize(1200,900);self.flush()

    def test_every_choice_uses_dropdown_and_closed_wheel_scrolls_page(self):
        self.assertTrue(all(isinstance(c,ComboBox) for c in self.w.findChildren(NativeComboBox)))
        character=self.w.character
        for index in range(character.count()):
            character.blockSignals(True);character.setCurrentIndex(index);character.blockSignals(False)
            character.showPopup();self.flush()
            self.assertEqual(character.view().window().y(),character.mapToGlobal(QPoint(0,character.height())).y())
            character.hidePopup()
        self.w.show_page('Activity');self.w.toggle_diagnostics();self.flush()
        combo=self.w.probe_page.history;combo.addItems(['Another snapshot','Third snapshot'])
        bar=self.w.scrollers['Activity'].verticalScrollBar();bar.setValue(0);self.flush()
        original=combo.currentIndex();point=QPointF(combo.rect().center())
        event=QWheelEvent(point,QPointF(combo.mapToGlobal(point.toPoint())),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        self.app.sendEvent(combo,event);self.flush()
        self.assertEqual(combo.currentIndex(),original);self.assertGreater(bar.value(),0)

    def test_back_keeps_drafts_and_returns_without_history_loop(self):
        w=self.w;w.show_page('Overview');w.page_history.clear()
        w.show_planning('Queue');w.queue.form.load({'name':'Unfinished craft'})
        before=files(self.root)
        w.show_page('Storage');w.show_page('Settings');self.flush()
        w.go_back();self.assertEqual(w.page_picker.currentText(),'Storage')
        w.go_back();self.assertEqual(w.page_picker.currentText(),'Planning')
        self.assertEqual(w.queue.form.values()['name'],'Unfinished craft')
        w.go_back();self.assertEqual(w.page_picker.currentText(),'Overview')
        self.assertFalse(w.back_button.isEnabled());self.assertEqual(files(self.root),before)

    def test_settings_actions_are_separate_and_planning_controls_stay_near_title(self):
        w=self.w;w.show_page('Settings');w.select_settings_category('Workspace');self.flush()
        panel=w.planning_settings;title=panel.box.itemAt(0).widget();field=panel.section_content
        self.assertLessEqual(field.y()-title.geometry().bottom(),30)
        self.assertGreater(w.settings_actions.y(),panel.geometry().bottom())
        self.assertFalse(hasattr(w,'pause_button'))

    def test_addon_logos_and_activity_start_simple(self):
        page=self.w.addons_page
        self.assertEqual(set(page.cards),{'WFCore','WFStorage','WFProfessions'})
        self.assertTrue(all(icon.pixmap() is not None and not icon.pixmap().isNull() for icon in page.icons.values()))
        self.w.show_page('Activity');self.flush()
        self.assertTrue(self.w.probe_page.isHidden());self.assertFalse(self.w.probe_page.timer.isActive())
        self.w.toggle_diagnostics();self.flush();self.assertFalse(self.w.probe_page.isHidden())
        self.w.toggle_diagnostics();self.assertFalse(self.w.probe_page.timer.isActive())

    def test_frozen_core_card_loads_icon_from_payload_branding(self):
        import sys
        bundle=self.root/'frozen-bundle';path=bundle/'payload/branding/forever.ico'
        path.parent.mkdir(parents=True)
        pixmap=QPixmap(32,32);pixmap.fill(Qt.GlobalColor.cyan)
        self.assertTrue(pixmap.save(str(path),'PNG'))
        page=self.w.addons_page
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(bundle),create=True):
            page.add_card('WFCore','Forever Core','Test icon',page.core_status,page.core_action)
        actual=page.icons['WFCore'].pixmap()
        self.assertIsNotNone(actual);self.assertFalse(actual.isNull())
        self.assertEqual(actual.toImage().pixelColor(10,10),Qt.GlobalColor.cyan)

    def test_large_divider_drag_cannot_push_last_column_out(self):
        w=self.w;w.show_page('Storage');self.flush();table=w.saved_inventory.items;header=table.horizontalHeader()
        before=files(self.root)
        for left in range(table.columnCount()-1):
            x=header.sectionViewportPosition(left)+header.sectionSize(left)-1
            start=QPoint(x,header.height()//2)
            QTest.mousePress(header.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(header.viewport(),start+QPoint(1500,0),30)
            QTest.mouseRelease(header.viewport(),Qt.MouseButton.LeftButton,pos=start+QPoint(1500,0));self.flush()
            self.assertLessEqual(header.length(),table.viewport().width()+1)
            self.assertEqual(table.horizontalScrollBar().maximum(),0)
            self.assertGreaterEqual(header.sectionSize(left+1),header.minimum_width(left+1))
        self.assertEqual(files(self.root),before)

    def test_settings_collapse_save_revert_and_reopen_keep_edits(self):
        w=self.w;w.show_page('Settings');w.select_settings_category('Workspace');self.flush()
        w.queue.form.load({'name':'Keep unfinished queue'})
        key='Planning settings';panel,body,button=w.settings_sections[key]
        self.assertEqual(w.preset.parentWidget().parentWidget(),body)
        w.toggle_settings_section(key);self.flush()
        self.assertTrue(body.isHidden());self.assertEqual(button.text(),'Show')
        self.assertFalse(panel.isHidden());self.assertTrue(w.save_session())
        w.toggle_settings_section(key);self.assertFalse(body.isHidden())
        w.revert();self.assertTrue(body.isHidden())
        w.select_settings_category('Connections');w.select_settings_category('Workspace')
        self.assertTrue(body.isHidden());self.assertEqual(w.queue.form.values()['name'],'Keep unfinished queue')
        self.w.close();self.w.deleteLater();self.flush()
        self.w=Companion(self.root);self.w.testing=True;self.w.timer.stop()
        self.w.updates_panel.timer.stop();self.w.saved_character_connection.timer.stop()
        self.w.character_overview.game_data_monitor.set_enabled(False)
        self.assertTrue(self.w.settings_sections[key][1].isHidden())
        self.w.toggle_settings_section(key);self.assertFalse(self.w.settings_sections[key][1].isHidden())

    def test_saved_page_logos_have_transparent_corners(self):
        for addon in ('WFStorage','WFProfessions'):
            image=logo_pixmap(addon).toImage()
            self.assertFalse(image.isNull());self.assertTrue(image.hasAlphaChannel())
            for x,y in ((0,0),(image.width()-1,0),(0,image.height()-1)):
                self.assertEqual(image.pixelColor(x,y).alpha(),0)
            self.assertGreater(image.pixelColor(image.width()//2,image.height()//2).alpha(),0)
        self.assertFalse(self.w.saved_inventory.heading.logo.pixmap().isNull())
        self.assertFalse(self.w.saved_crafting.heading.logo.pixmap().isNull())


if __name__=='__main__':unittest.main()
