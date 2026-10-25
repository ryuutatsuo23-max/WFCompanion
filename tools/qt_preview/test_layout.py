"""All-tab font/geometry checks with long labels and private disposable state."""
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QFontMetrics, QPalette, QColor
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QWidget, QLabel
from app import FlowLayout, Title, WrappedButton, SOURCE
from companion import Companion, QApplication, TABS
from catalogue_dialog import ItemPicker
from data import STATE
from test_companion import fingerprint
from inventory import InventoryEntry, utc_now
from inventory_undo import RemovedEntry
from unittest.mock import Mock
from gear import GearItem
from gear_undo import RemovedGoal


class FontLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.originals={str(path):fingerprint(path) for path in (SOURCE/'state',STATE)}

    @classmethod
    def tearDownClass(cls):
        for directory,original in cls.originals.items():
            assert fingerprint(Path(directory))==original, 'Personal state changed during layout tests'

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wow-qt-font-layout-')
        self.w=Companion(Path(self.temp.name)); self.w.testing=True; self.w.timer.stop()
        # Geometry must not race a real saved-report read changing wrapped text.
        self.w.probe_page.reader = Mock(poll=Mock(return_value=(None, None)))
        self.w.change('theme','Stormwind · Alliance'); self.w.change('panel_transparency',60)
        name='Ancient ceremonial armor of the northern mountains and forgotten guardians'
        self.w.data.inventory_undo.records[self.w.data.active]=RemovedEntry(0,InventoryEntry('removed',name,1,'Bank',utc_now()))
        self.w.data.gear_undo.records[self.w.data.active]=RemovedGoal(0,GearItem('removed-gear',name,'Shoulders'))
        self.w.data.profile.name='A long profile name for our travelling gathering and crafting adventurer'
        self.w.profiles_changed(); self.w.inventory_page.refresh(); self.w.gear_page.refresh()
        self.w.show()

    def tearDown(self):
        self.w.close(); self.w.deleteLater(); self.app.processEvents(); self.temp.cleanup()

    def flush(self):
        for _ in range(3): self.app.processEvents()

    def check_layout(self,root):
        for widget in root.findChildren(QWidget):
            if not widget.isVisible(): continue
            if isinstance(widget.layout(),FlowLayout):
                for index in range(widget.layout().count()):
                    child=widget.layout().itemAt(index).widget()
                    if child.isVisible():
                        self.assertLessEqual(child.geometry().right(),widget.contentsRect().right()+1,child.accessibleName())
                        self.assertLessEqual(child.geometry().bottom(),widget.contentsRect().bottom()+1)
            if isinstance(widget,QLabel) and widget.text():
                needed=widget.heightForWidth(widget.width()) if widget.wordWrap() else widget.sizeHint().height()
                self.assertGreaterEqual(widget.height()+2,needed,widget.text())
            if isinstance(widget,WrappedButton):
                self.assertGreaterEqual(widget.height(),widget.heightForWidth(widget.width()))
                self.assertLessEqual(widget.width(),560)
            if isinstance(widget,Title):
                metrics=QFontMetrics(QFont(widget.font().family(),widget.font().pointSize(),QFont.Weight.Bold))
                self.assertLessEqual(metrics.horizontalAdvance(widget.text),widget.width()-50,widget.text)
                self.assertGreaterEqual(widget.height(),metrics.height()+30,widget.text)

    def test_all_tabs_large_fonts_narrow_windows_and_long_recovery_labels(self):
        w=self.w
        modes=[(True,'',12,'WoW'),(True,'',18,'WoW'),(True,'',18,'Standard')]
        modes.extend((False,family,18,'WoW') for family in ('Friz Quadrata TT','Arial Narrow','Morpheus','Skurri'))
        pages=[(name,None) for name in TABS]+[('Planning',part) for part in ('Recipe book','Shopping list','Gathering goals','Price journal')]+[('Settings',part) for part in ('Appearance','Workspace','Behaviour','Backup & updates')]+[('Activity','Diagnostics')]
        for roles,family,size,skin in modes:
            w.qt_settings.update(classic_fonts=roles,font_override=family)
            w.settings.update(text_size=size,ui_style=skin); w.apply_appearance(); w.sync_controls()
            for width in (680,1000,1440):
                w.resize(width,900)
                for name,part in pages:
                    with self.subTest(font=family or 'Role fonts',size=size,skin=skin,width=width,tab=name,part=part):
                        w.show_page(name)
                        if name=='Planning': w.show_planning(part or 'Queue')
                        if name=='Settings': w.select_settings_category(part or 'Connections')
                        if name=='Activity' and w.probe_page.isHidden()==bool(part):w.toggle_diagnostics()
                        self.flush()
                        scroll=w.scrollers[name]
                        self.assertEqual(w.width(),width)
                        self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
                        self.check_layout(w)
                        # The final controls are reachable with the outer scrollbar.
                        bar=scroll.verticalScrollBar(); bar.setValue(bar.maximum()); self.flush()
                        self.assertEqual(bar.value(),bar.maximum())
                        bar.setValue(0)
        self.assertFalse(any('Local artwork available' in item.text() for item in w.findChildren(QLabel)))

    def test_search_headers_receive_role_font_after_dialog_creation(self):
        w=self.w; w.change('text_size',18)
        for scope in ('All','Gear','Material'):
            dialog=ItemPicker(w,scope,lambda _:None); dialog.resize(900,800); dialog.show(); self.flush()
            try:
                table=dialog.table
                self.assertEqual(dialog.palette().color(QPalette.ColorRole.Window),QColor(w.colors[1]))
                self.assertEqual(dialog.grab().toImage().pixelColor(2,2),QColor(w.colors[1]))
                self.assertEqual(dialog.grab().toImage().pixelColor(15,15),QColor(w.colors[1]))
                self.assertEqual(table.font().family(),w.fonts.family('Arial Narrow',w.settings['font_family']))
                self.assertFalse(table.wordWrap())
                metrics=table.horizontalHeader().fontMetrics()
                for column in range(table.columnCount()):
                    self.assertGreaterEqual(table.columnWidth(column),metrics.horizontalAdvance(table.horizontalHeaderItem(column).text())+28)
                self.assertGreaterEqual(table.columnWidth(table.content_column),180)
                self.check_layout(dialog)
                for row in range(table.rowCount()):
                    for column in range(table.columnCount()):
                        item=table.item(row,column)
                        self.assertEqual(item.toolTip(),item.text())
            finally: dialog.done(0); dialog.deleteLater(); self.flush()

    def test_wrapped_field_captions_share_a_control_baseline(self):
        w=self.w; w.change('text_size',18)
        for width in (680,1000,1440):
            w.resize(width,900)
            for name in TABS:
                w.show_page(name); self.flush()
                for container in w.findChildren(QWidget):
                    layout=container.layout()
                    if not container.isVisible() or not isinstance(layout,FlowLayout): continue
                    rows={}
                    for item in layout.items:
                        box=item.widget()
                        if box.isVisible() and box.property('formField'):
                            control=box.field_control
                            bottom=control.mapTo(container,QPoint(0,control.height())).y()
                            rows.setdefault(box.y(),[]).append(bottom)
                    for bottoms in rows.values():
                        self.assertLessEqual(max(bottoms)-min(bottoms),2,name)
        self.assertFalse(hasattr(w,'custom'))

    def test_wrapped_buttons_keep_pointer_and_keyboard_actions(self):
        button=WrappedButton('Will restore: '+('LongItemNameWithoutSpaces'*4)+' · Bank')
        button.setFont(QFont(self.w.fonts.family('Friz Quadrata TT','Segoe UI'),18))
        button.resize(260,button.heightForWidth(260)); button.show(); self.flush()
        try:
            self.assertGreater(button.heightForWidth(260),button.heightForWidth(560))
            spy=QSignalSpy(button.clicked)
            QTest.mouseClick(button,Qt.MouseButton.LeftButton,pos=button.rect().center())
            button.setFocus(); QTest.keyClick(button,Qt.Key.Key_Space)
            self.assertEqual(spy.count(),2)
            self.assertLessEqual(button.text_layout(button.width()).boundingRect().height()+18,button.height())
        finally: button.close(); button.deleteLater(); self.flush()


if __name__=='__main__': unittest.main()
