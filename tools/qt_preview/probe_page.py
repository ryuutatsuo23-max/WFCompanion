"""Read-only probe diagnostics, embedded in Activity; no saved settings/store writes."""
from datetime import datetime
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, Qt
from PySide6.QtWidgets import QFileDialog, QPlainTextEdit, QComboBox, QSizePolicy
from app import Panel, label, row
from widgets import Table
from probe_report import ReportReader, summarize


class ProbeTable(Table):
    """Keep short diagnostic names/verdicts readable at larger font sizes."""
    def fit_headers(self):
        super().fit_headers()
        metrics = self.fontMetrics()
        for column, text in ((0,'Cooldowns'),(1,'Working · sample')):
            self.setColumnWidth(column,max(self.columnWidth(column),metrics.horizontalAdvance(text)+30))
        height = self.horizontalHeader().sizeHint().height()+6*max(30,metrics.height()+12)+12
        self.setMinimumHeight(height); self.setMaximumHeight(height+30)


class Result(QObject):
    ready = Signal(int, object, str)


class ReadJob(QRunnable):
    def __init__(self, reader, selected, generation):
        super().__init__()
        self.reader, self.selected, self.generation = reader, selected, generation
        self.result = Result()

    def run(self):
        try: value, error = self.reader.poll(self.selected)
        except Exception: value, error = None, 'Report could not be read; no files were changed.'
        self.result.ready.emit(self.generation, value, error)


class ProbePage(Panel):
    def __init__(self, host, reader=None):
        super().__init__(host, 'Stress test · probe report')
        self.reader = reader or ReportReader()
        self.selected = None; self.generation = 0; self.busy = False; self.loaded = None
        self.notice = label('Open Activity after /reload. The saved probe report is checked automatically every 3 seconds here.')
        self.source = label('Source: latest saved Stress Test report. Report ownership only; no inventory import.')
        for control in (self.notice,self.source):
            control.setTextFormat(Qt.TextFormat.PlainText); self.box.addWidget(control)
        self.box.addWidget(row(host.button('Refresh report',self.refresh),host.button('Choose report file',self.choose),host.button('Use Stress Test folder',self.automatic)))
        def review():
            from capture_review_dialog import CaptureReviewDialog
            dialog=CaptureReviewDialog(host,self.loaded[0] if self.loaded else None)
            dialog.exec()
        self.box.addWidget(host.button('Review captured inventory',review))
        def equipment():
            from equipment_review_dialog import EquipmentReviewDialog
            dialog=EquipmentReviewDialog(host,self.loaded[0] if self.loaded else None)
            dialog.exec()
        self.box.addWidget(host.button('Review equipped items',equipment))
        self.history = QComboBox()
        self.history.setMinimumWidth(0)
        self.history.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.history.setAccessibleName('Saved probe snapshot')
        self.history.addItem('Latest saved snapshot',None)
        self.box.addWidget(self.history)
        self.owner = label('Character: Unknown')
        self.owner.setTextFormat(Qt.TextFormat.PlainText)
        self.owner.setWordWrap(True)
        self.box.addWidget(self.owner)
        self.history.currentIndexChanged.connect(self.show_snapshot)
        self.table = ProbeTable(['Check','Result','Details'],height=260)
        self.box.addWidget(self.table)
        self.table.rows((name,(name,'Not tested','Waiting for a saved snapshot.')) for name in ('HP','Mana','XP','Buffs','Cooldowns','Inventory'))
        self.box.addWidget(label('Saved samples only—not live readings. Working means readable in that sample; restrictions can change in combat. Inventory is partial and never replaces your manual counts.'))
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMinimumHeight(180); self.details.setMaximumHeight(300); self.details.hide()
        self.box.addWidget(host.button('Show / hide raw report',lambda:self.details.setVisible(not self.details.isVisible())))
        self.box.addWidget(self.details)
        self.timer = QTimer(self); self.timer.setInterval(3000); self.timer.timeout.connect(self.refresh)

    def showEvent(self,event):
        super().showEvent(event); self.timer.start(); self.refresh()

    def hideEvent(self,event):
        self.timer.stop(); super().hideEvent(event)

    def choose(self):
        path,_ = QFileDialog.getOpenFileName(self,'Open probe SavedVariables',str(self.reader.client/'WTF'/'Account'),'Probe report (WFStressProbe.lua);;Lua saved data (*.lua)')
        if path: self.set_source(path)

    def automatic(self):
        self.set_source(None)

    def set_source(self,path):
        self.selected = path; self.generation += 1
        # Retained data is explicitly marked until the selected source loads.
        self.notice.setText('Checking selected source. Previous sample remains below until a valid report arrives.')
        self.refresh()

    def refresh(self):
        if self.busy: return
        self.busy = True
        self.job = ReadJob(self.reader,self.selected,self.generation)
        self.job.result.ready.connect(self.accept)
        QThreadPool.globalInstance().start(self.job)

    @Slot(int,object,str)
    def accept(self,generation,value,error):
        self.busy = False
        if generation != self.generation:
            self.refresh(); return
        if error:
            self.notice.setText(('Previous saved sample retained; not current. ' if self.loaded else '')+error)
            return
        if value is None: return
        path,modified,snapshot,count,rows,sources,snapshots = value
        self.notice.setText(f'File saved {datetime.fromtimestamp(modified):%Y-%m-%d %H:%M:%S} (PC local time). Select a snapshot below to inspect its character and results.')
        mode = 'Chosen file' if self.selected else 'Latest Stress Test file'
        self.source.setText(f'{mode} · {sources} report file(s) found · {count} retained snapshots. Source path in tooltip.')
        self.source.setToolTip(str(path))
        if value != self.loaded:
            selected = self.history.currentData() if self.loaded and path == self.loaded[0] else None
            self.history.blockSignals(True)
            self.history.clear(); self.history.addItem('Latest saved snapshot',None)
            selected_index = 0
            for sample in reversed(snapshots):
                self.history.addItem(f'{sample.at} · {sample.character_label} · {sample.reason}',sample)
                if selected is not None and sample == selected: selected_index=self.history.count()-1
            self.history.setCurrentIndex(selected_index)
            self.history.blockSignals(False)
            self.loaded = value
            self.show_snapshot()

    def show_snapshot(self):
        if not self.loaded: return
        snapshot = self.history.currentData() or self.loaded[2]
        self.owner.setText(f'Character: {snapshot.character_label}\nSnapshot: {snapshot.at} · {snapshot.reason}')
        self.history.setToolTip(self.history.currentText())
        self.table.rows((name,(name,state,detail)) for name,state,detail in summarize(snapshot.report))
        self.details.setPlainText(snapshot.report)
