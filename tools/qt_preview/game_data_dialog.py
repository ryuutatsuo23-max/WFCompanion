"""One explicit file read per request; discovery and parsing run off the UI thread."""
from PySide6.QtCore import QObject,QRunnable,QThreadPool,Signal,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QFileDialog,QScrollArea,QWidget,QSizePolicy
from app import label,row
from widgets import Table
from game_data_review import discover,read,locations,observed_time,sync_status


class Result(QObject):
    ready=Signal(object,str)


class ReadJob(QRunnable):
    def __init__(self,path):
        super().__init__();self.path=path;self.result=Result()

    def run(self):
        try:
            value=read(self.path) if self.path else discover()
            self.result.ready.emit(value,'')
        except Exception as exc:self.result.ready.emit(None,str(exc))


class GameDataDialog(QDialog):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.records=[];self.busy=False
        self.setWindowTitle('Check for new game data');self.resize(1050,740)
        outer=QVBoxLayout(self);scroll=QScrollArea();scroll.setWidgetResizable(True)
        content=QWidget();box=QVBoxLayout(content);scroll.setWidget(content);outer.addWidget(scroll)
        box.addWidget(label('Review saved bags and bank from our addon. After playing, /reload or normal logout lets the game save its records. Reviewing does not import counts. Character links and new profiles are saved only after their separate confirmations.'))
        self.files=QComboBox();self.files.setAccessibleName('Addon saved-data file');box.addWidget(self.files)
        self.scan=host.button('Find saved files',lambda:self.start(None))
        self.choose=host.button('Choose WFCore file',self.choose_file)
        self.check=host.button('Check selected file',self.check_file)
        box.addWidget(row(self.scan,self.choose,self.check))
        self.notice=label('');box.addWidget(self.notice)
        self.table=Table(['Character','Location','Saved records','Captured (local time)'],self.select,height=220);box.addWidget(self.table)
        self.details=label('Select a location to review its items.');box.addWidget(self.details)
        box.addWidget(host.button('Link selected character…',self.link_character))
        self.items=Table(['Item ID','Observed quantity'],height=240);box.addWidget(self.items)
        box.addWidget(label('Observed quantities are subtotals, not guaranteed full ownership. An unopened bank or an absent item never clears existing records. Safe import needs complete count evidence and an explicitly reviewed character mapping; neither is assumed here.'))
        for text in (self.notice,self.details):
            text.setTextFormat(Qt.TextFormat.PlainText);text.setMinimumWidth(0)
            text.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.files.setMinimumWidth(0);self.files.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        outer.addWidget(host.button('Close review',self.accept))
        host.style_table(self.table);host.style_table(self.items);host.wire_nested_scrolling(self)
        self.start(None)

    def start(self,path):
        if self.busy:return
        self.busy=True;self.loading=path
        for button in (self.scan,self.choose,self.check):button.setEnabled(False)
        self.records=[];self.table.rows([]);self.items.rows([]);self.details.setText('')
        self.notice.setText('Checking saved data…')
        self.job=ReadJob(path);self.job.result.ready.connect(self.receive_result)
        QThreadPool.globalInstance().start(self.job)

    def receive_result(self,value,error):
        self.busy=False
        for button in (self.scan,self.choose,self.check):button.setEnabled(True)
        if error:self.notice.setText('Could not check saved data: '+error);return
        if self.loading is None:
            self.files.clear()
            for path in value:self.files.addItem(str(path),str(path))
            self.notice.setText('Select a saved file, then Check selected file. Each client/account stays separate.' if value else 'No WFCore save found in the known game folders. Choose a saved file, or /reload after enabling the addon.')
            if len(value)==1:self.start(str(value[0]))
            return
        self.records=locations(value)
        self.table.rows((i,(name,scope.title(),
            sync_status(obs)[0],
            observed_time(obs.finished_at or obs.started_at) if obs else 'Not recorded'))
            for i,(_,name,scope,obs) in enumerate(self.records))
        self.notice.setText(f'Read {len(value)} saved observations. No changes imported.\n{self.loading}' if value else 'No readable location observations in this save. Existing records are unchanged.')

    def check_file(self):
        path=self.files.currentData()
        if path:self.start(path)

    def link_character(self):
        key=self.table.key()
        if self.busy or key is None:
            self.details.setText('Select a saved character/location first.');return
        from character_link_dialog import CharacterLinkDialog
        dialog=CharacterLinkDialog(self.host,self.loading,self.records[key][0])
        try:
            if dialog.exec():self.details.setText('Character link saved. Item counts and unfinished edits are unchanged.')
        finally:dialog.deleteLater()

    def choose_file(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose WFCore saved data','','Lua saved data (*.lua)')
        if path:
            self.files.addItem(path,path);self.files.setCurrentIndex(self.files.count()-1);self.start(path)

    def select(self,key):
        owner,name,scope,obs=self.records[key]
        self.items.rows([(item,(item,count)) for item,count in obs.rows] if obs else [])
        self.details.setText(f'{name} · {scope.title()}\nIdentity: {owner}\n'+
            (f'Build: {obs.build} · Schema: {obs.schema} · Coverage: {obs.coverage} · Unknown slots: {obs.unknown_slots}\n'+
             (f'Occupied slots: {obs.observed_slots} · Confirmed empty slots: {obs.empty_slots}\n' if obs.schema==2 else '')+
             'Saved observation, not live inventory. Reviewing never clears missing items.' if obs else
             'No saved observation for this location. Keep previous records; the bank is not confirmed empty.')+
             '\nSync status: '+sync_status(obs)[1])
