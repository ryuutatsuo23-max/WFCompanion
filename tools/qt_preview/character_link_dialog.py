"""One-time explicit character linking; no item counts are imported."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QComboBox,QMessageBox
from app import label
from character_links import LinkStore,identity,create_profile


class CharacterLinkDialog(QDialog):
    def __init__(self,host,path,guid):
        super().__init__(host);self.host=host;self.path=path;self.guid=guid;self.value=None
        self.setWindowTitle('Link addon character');self.resize(720,480)
        box=QVBoxLayout(self)
        box.addWidget(label('Choose the source environment and destination once. Names alone never establish a match. Linking does not import inventory.'))
        self.environment=QComboBox();self.environment.addItems(['Choose environment…','Test','Live']);box.addWidget(self.environment)
        self.detail=label('Choose Test for beta/stress-test characters, including any source backed up from those clients.')
        self.detail.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(self.detail)
        self.destination=QComboBox();box.addWidget(self.destination);self.fill_profiles()
        box.addWidget(host.button('Create separate profile…',self.create))
        box.addWidget(host.button('Review and save link…',self.save))
        box.addWidget(host.button('Close',self.reject))
        self.environment.currentTextChanged.connect(self.inspect)

    def fill_profiles(self,selected=None):
        self.destination.clear();self.destination.addItem('Choose companion profile…',None)
        for p in self.host.data.saved_profiles:self.destination.addItem(f'{p.name} · {p.character_class} · {p.id}',p.id)
        if selected:self.destination.setCurrentIndex(self.destination.findData(selected))

    def inspect(self):
        self.value=None
        try:
            value=identity(self.path,self.guid,self.environment.currentText());store=LinkStore(self.host.data.directory)
            self.value=value
            self.detail.setText(f'{value["name"]}\nRealm: {value["realm"]}\nEnvironment: {value["environment"]}\nClient: {value["version"]} · build {value["build"]}\nGUID: {value["guid"]}\nSource: {value["source"]}\n'+('Already linked: '+store.linked(value) if store.linked(value) else 'No saved link yet.'))
        except (OSError,ValueError,KeyError) as exc:self.detail.setText(str(exc))

    def current_identity(self):
        if self.value is None:raise ValueError('Choose a valid source environment first.')
        fresh=identity(self.path,self.guid,self.environment.currentText())
        if fresh!=self.value:raise ValueError('Source identity changed. Choose the environment again to refresh.')
        return fresh

    def create(self):
        try:
            value=self.current_identity()
            if LinkStore(self.host.data.directory).linked(value):raise ValueError('This source already has a saved link.')
            if QMessageBox.question(self,'Create companion profile',f'Create a separate profile named {value["name"]}?\nClass will be unspecified. Existing profiles and item counts stay unchanged.\nYou will still review its link afterward.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            profile=create_profile(self.host.data,self.current_identity());self.host.profiles_changed();self.fill_profiles(profile)
            self.detail.setText('Separate profile created. Review and save its link next.')
        except (OSError,ValueError,KeyError) as exc:self.detail.setText(str(exc))

    def save(self):
        try:
            value=self.current_identity();destination=self.destination.currentData()
            if destination is None:raise ValueError('Choose a companion profile first.')
            store=LinkStore(self.host.data.directory)
            text=f'Link {value["name"]} ({value["realm"]}, {value["environment"]})\nGUID: {value["guid"]}\nTo: {self.destination.currentText()}?\nNo inventory will be imported.'
            if QMessageBox.question(self,'Confirm character link',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
            store.save(self.host.data,self.current_identity(),destination);self.accept()
        except (OSError,ValueError,KeyError) as exc:self.detail.setText(str(exc))
