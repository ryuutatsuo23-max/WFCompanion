"""Small Qt forms with explicit drafts and tables that never load editors on refresh."""
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLineEdit, QPlainTextEdit, QCheckBox,
    QComboBox, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QPushButton)
from controls import ComboBox as QComboBox
from app import row, field, label, Panel


def shown(value):
    return 'Unknown' if value is None else str(value)


class Form(QWidget):
    """Fields are raw drafts; parsing/validation happens only at explicit Apply."""
    def __init__(self, host, specs):
        super().__init__()
        self.controls = {}
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        cells = []
        for key, caption, kind, default in specs:
            if kind == bool:
                control = QCheckBox(caption)
                control.setChecked(bool(default))
                cells.append(control)
            elif kind == 'multiline':
                control = QPlainTextEdit()
                control.setPlainText(str(default))
                control.setMinimumHeight(120)
                control.setMaximumHeight(220)
                if cells:
                    box.addWidget(row(*cells)); cells = []
                box.addWidget(label(caption)); box.addWidget(control)
            else:
                if isinstance(kind, (tuple, list)):
                    control = host.combo(kind, lambda _: None)
                    control.setCurrentText(str(default))
                else:
                    control = QLineEdit(str(default))
                    control.setMaximumWidth(470)
                    control.setMinimumWidth(210)
                cells.append(field(caption, control))
            self.controls[key] = control
        if cells:
            box.addWidget(row(*cells))
        self.defaults = self.values()

    def values(self):
        values = {}
        for key, c in self.controls.items():
            values[key] = (c.isChecked() if isinstance(c, QCheckBox) else (c.currentData() if c.property('usesData') else c.currentText()) if isinstance(c, QComboBox)
                           else c.toPlainText() if isinstance(c, QPlainTextEdit) else c.text())
        return values

    def load(self, values):
        for key, value in values.items():
            if key not in self.controls: continue
            c = self.controls[key]
            c.blockSignals(True)
            if isinstance(c, QCheckBox): c.setChecked(bool(value))
            elif isinstance(c, QComboBox):
                if c.property('usesData'): c.setCurrentIndex(c.findData(value))
                else: c.setCurrentText(str(value))
            elif isinstance(c, QPlainTextEdit): c.setPlainText('' if value is None else str(value))
            else: c.setText('' if value is None else str(value))
            c.blockSignals(False)

    def changed(self, callback):
        for control in self.controls.values():
            signal = (control.toggled if isinstance(control,QCheckBox) else control.currentTextChanged
                      if isinstance(control,QComboBox) else control.textChanged)
            signal.connect(callback)


class TableHeader(QHeaderView):
    """Resize adjacent columns together, keeping the table's right edge fixed."""
    def __init__(self, table):
        super().__init__(Qt.Orientation.Horizontal, table)
        self.table = table
        self._divider_drag = None

    def divider(self, x):
        visible=[self.logicalIndex(i) for i in range(self.count()) if not self.isSectionHidden(self.logicalIndex(i))]
        for position,index in enumerate(visible[:-1]):
            if abs(x-(self.sectionViewportPosition(index)+self.sectionSize(index)))<=5:
                return index,visible[position+1]
        return None

    def minimum_width(self,index):
        return max(self.minimumSectionSize(),self.fontMetrics().horizontalAdvance(self.table.horizontalHeaderItem(index).text())+28)

    def mousePressEvent(self, event):
        self.table._header_gesture = True
        pair=self.divider(event.position().x())
        if event.button()==Qt.MouseButton.LeftButton and pair:
            left,right=pair
            self._divider_drag=(left,right,event.position().x(),self.sectionSize(left),self.sectionSize(right))
            self.setStretchLastSection(False)
            event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._divider_drag:
            left,right,x,a,b=self._divider_drag
            low=min(a,self.minimum_width(left));high=a+b-min(b,self.minimum_width(right))
            width=max(low,min(high,round(a+event.position().x()-x)))
            self.resizeSection(left,width);self.resizeSection(right,a+b-width)
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._divider_drag:
            self._divider_drag=None;self.table._header_gesture=False
            self.setStretchLastSection(True);event.accept();return
        super().mouseReleaseEvent(event)
        self.table._header_gesture = False

    def mouseDoubleClickEvent(self,event):
        # Native auto-size can also push the final column outside the viewport.
        if self.divider(event.position().x()):event.accept();return
        super().mouseDoubleClickEvent(event)


class Table(QTableWidget):
    def __init__(self, headers, selected=None, height=240):
        super().__init__(0, len(headers))
        self._header_gesture=False;self._manual_columns=False
        self.setHorizontalHeader(TableHeader(self))
        self.setHorizontalHeaderLabels(headers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Full values remain in tooltips and editors. Elide cleanly rather than
        # starting a wrapped second line beneath a fixed-height row.
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self._fitting_columns=False
        # Give spare space to meaningful content, not a usually empty trailing
        # binding/ID field. Narrow windows retain horizontal table scrolling.
        self.content_column=next((headers.index(name) for name in ('Why','Details','Material','Item','Recipe','Rule','Name') if name in headers),len(headers)-1)
        self.setMinimumHeight(height)
        self.setMaximumHeight(height + 100)
        self.keys = []
        self._rows = None
        for i, title in enumerate(headers):
            self.setColumnWidth(i, max(170 if title in ('Rule','Name','Reminder','Note','Source','Price date','Entered (UTC)') else 100, self.fontMetrics().horizontalAdvance(title)+28))
        self._default_widths=[self.columnWidth(i) for i in range(self.columnCount())]
        self.horizontalHeader().sectionResized.connect(self.column_resized)
        if selected:
            self.itemSelectionChanged.connect(lambda: selected(self.key()) if self.key() is not None else None)

    def fit_headers(self):
        self.ensurePolished(); self.horizontalHeader().ensurePolished()
        metrics=self.horizontalHeader().fontMetrics()
        self._fitting_columns=True
        try:
            for column in range(self.columnCount()):
                width=metrics.horizontalAdvance(self.horizontalHeaderItem(column).text())+28
                self.setColumnWidth(column,max(self.columnWidth(column),width))
        finally:self._fitting_columns=False
        self.fit_content_column()

    def fit_content_column(self):
        if not hasattr(self,'content_column') or self._fitting_columns or self._manual_columns:return
        column=self.content_column
        minimum=max(180,self.horizontalHeader().fontMetrics().horizontalAdvance(self.horizontalHeaderItem(column).text())+28)
        self._fitting_columns=True
        header=self.horizontalHeader()
        try:
            # Initial/window fitting gives the descriptive column spare space.
            # Temporarily suspend native stretching so its already-expanded
            # trailing width does not absorb that space before this calculation.
            header.setStretchLastSection(False)
            visible=[header.logicalIndex(i) for i in range(header.count()) if not self.isColumnHidden(header.logicalIndex(i))]
            if visible and visible[-1]!=column:
                last=visible[-1]
                self.setColumnWidth(last,max(self._default_widths[last],header.fontMetrics().horizontalAdvance(self.horizontalHeaderItem(last).text())+28))
            available=self.viewport().width()-sum(self.columnWidth(i) for i in visible if i!=column)
            width=max(minimum,available)
            if self.columnWidth(column)!=width:self.setColumnWidth(column,width)
        finally:
            header.setStretchLastSection(True)
            self._fitting_columns=False

    def column_resized(self,index,*_):
        if self._fitting_columns:return
        if self._header_gesture:self._manual_columns=True

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.fit_content_column()

    def key(self):
        index = self.currentRow()
        return self.keys[index] if 0 <= index < len(self.keys) else None

    def rows(self, entries):
        entries = list(entries)
        if entries == self._rows: return
        self._rows = deepcopy(entries)
        key = self.key()
        self.blockSignals(True)
        self.setUpdatesEnabled(False)
        self.setRowCount(len(entries))
        self.keys = [k for k, _ in entries]
        for r, (_, values) in enumerate(entries):
            for c, value in enumerate(values):
                item = QTableWidgetItem(shown(value))
                item.setToolTip(shown(value))
                self.setItem(r, c, item)
        self.verticalHeader().setDefaultSectionSize(max(30, self.fontMetrics().height()+12))
        if key in self.keys: self.selectRow(self.keys.index(key))
        else: self.clearSelection(); self.setCurrentCell(-1, -1)
        self.setUpdatesEnabled(True)
        self.blockSignals(False)


class Page(Panel):
    def __init__(self, host, title):
        super().__init__(host, title)
        self.host = host
        self.data = host.data
        self.notice = label('')
        self.notice.hide()
        self.box.addWidget(self.notice)
        self.drafts = {}
        self.edit_id = None
        self.reference = None
        self.references = {}

    def message(self, text):
        self.notice.setText(str(text))
        self.notice.setVisible(bool(text))

    def action(self, caption, callback):
        return self.host.button(caption, lambda: self.run(callback))

    def run(self, callback):
        try:
            return callback()
        except (ValueError, OSError, TypeError) as error:
            self.message(error)
            return False

    def remember(self, character):
        if hasattr(self, 'form'):
            self.drafts[character] = (self.edit_id, self.form.values(), self.reference, deepcopy(self.references))

    def restore(self, character):
        if hasattr(self, 'form'):
            self.edit_id, values, self.reference, self.references = deepcopy(self.drafts.get(character, (None,self.form.defaults,None,{})))
            self.form.load(values)
        self.refresh()

    def new(self):
        self.edit_id = self.reference = None
        self.references = {}
        self.form.load(self.form.defaults)
        self.link_label()

    def link_label(self):
        if hasattr(self, 'link'):
            self.link.setText(f'Linked item ID {self.reference.item_id} · {self.reference.name}' if self.reference else 'Manual item · no catalogue link')

    def lookup_controls(self, scope='All', name_key='name'):
        self.link = label('Manual item · no catalogue link')
        self.box.addWidget(row(self.action('Find local item', lambda: self.host.lookup(scope, lambda item: self.use_item(item,name_key))),
                               self.action('Clear item link', self.clear_link)))
        self.box.addWidget(self.link)

    def clear_link(self):
        self.reference = None
        self.link_label()

    def use_item(self, item, key='name'):
        self.reference = item.reference
        self.form.load({key: item.reference.name})
        self.link_label()

    def refresh(self):
        self.link_label()

    def dirty(self, kind):
        self.data.dirty.add(kind)
        self.host.stock_changed()
        self.message('Applied in this session. Use Save to keep these records.')


def integer(value, optional=False):
    value = str(value).strip()
    if optional and not value: return None
    if not value.isascii() or not value.isdecimal():
        raise ValueError('Enter a whole non-negative number, or leave optional values blank for Unknown.')
    return int(value)
