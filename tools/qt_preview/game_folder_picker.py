"""Bounded client discovery and explicit folder choice; never writes game files."""
import os
import sys
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QFileDialog
from app import label, row

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'distribution'))
from install_addons import validate_client


def standard_roots():
    return list(dict.fromkeys(Path(os.environ.get(key, fallback)) / 'World of Warcraft'
        for key, fallback in (('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                              ('ProgramFiles', r'C:\Program Files'))))


def find_clients(roots):
    found = {}
    for root in roots:
        root = Path(root)
        for candidate in (root, root / '_forever_', root / '_classic_beta_'):
            try:
                client = validate_client(candidate)
                found[str(client).casefold()] = client
            except (OSError, ValueError, RuntimeError):
                pass
    return sorted(found.values(), key=lambda p: str(p).casefold())


def client_title(client):
    return 'Forever' if client.name == '_forever_' else 'Beta'


class GameFolderPicker(QWidget):
    selectionChanged = Signal(object)

    def __init__(self, host, *, roots=None, selected=None, auto_select=True, unavailable=''):
        super().__init__(host)
        self.roots = list(standard_roots() if roots is None else roots)
        self.client = selected
        self.changed = False
        box = QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0)
        self.choices = QComboBox(); self.choices.setMinimumContentsLength(25)
        self.choices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        box.addWidget(self.choices)
        box.addWidget(row(host.button('Choose game folder', self.choose), host.button('Find game folders', self.scan)))
        self.target = label(''); self.target.setWordWrap(True); self.target.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.target)
        self.notice = label(''); self.notice.setWordWrap(True); self.notice.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.notice)
        hint = label('Choose the client folder or its World of Warcraft parent folder. Custom locations can be browsed. Folder selection does not install addons or connect saved character data.')
        hint.setWordWrap(True); box.addWidget(hint)
        self.populate(find_clients(self.roots + ([selected] if selected else [])), auto_select and not unavailable)
        if unavailable: self.notice.setText('Saved game folder is unavailable: ' + unavailable + '\nChoose a folder to continue; another client will not be selected automatically.')
        self.choices.currentIndexChanged.connect(self.select)

    def populate(self, clients, auto_select=False):
        self.choices.blockSignals(True); self.choices.clear()
        self.choices.addItem('Choose a game folder / set up later', None)
        for client in clients:
            self.choices.addItem(client_title(client) + ' — ' + str(client), str(client))
            self.choices.setItemData(self.choices.count()-1, str(client), Qt.ItemDataRole.ToolTipRole)
        if self.client not in clients: self.client = None
        if self.client is None and auto_select and len(clients) == 1: self.client = clients[0]
        self.choices.setCurrentIndex(self.choices.findData(str(self.client)) if self.client else 0)
        self.choices.blockSignals(False)
        self.notice.setText('Multiple clients found. Choose the one you want to use.' if len(clients)>1 and not self.client else
                            'No game folder found here. Browse to a custom location, or continue offline.' if not clients else '')
        self.describe()

    def describe(self):
        self.target.setText((client_title(self.client) + ' selected\nClient: ' + str(self.client) +
                            '\nAddons will go to: ' + str(self.client / 'Interface' / 'AddOns')) if self.client else 'No game folder selected. Offline planning is available.')
        self.choices.setToolTip(str(self.client or 'Choose a client; installations are never merged.'))

    def select(self, index):
        value = self.choices.itemData(index)
        try: self.client = validate_client(value) if value else None
        except (OSError, ValueError, RuntimeError):
            self.client = None; self.notice.setText('That folder is unavailable. Choose it again or browse to its new location.')
        else: self.notice.setText('')
        self.changed = True; self.describe(); self.selectionChanged.emit(self.client)

    def scan(self):
        previous = self.client
        self.populate(find_clients(self.roots + ([previous] if previous else [])))
        if previous != self.client:
            self.notice.setText('The selected folder is unavailable. Choose a folder to continue.')
            self.selectionChanged.emit(self.client)

    def choose(self):
        selected = QFileDialog.getExistingDirectory(self, 'Choose client or World of Warcraft folder', str(self.client or ''))
        if not selected: return
        clients = find_clients([selected])
        if not clients:
            self.notice.setText('No supported client found. Choose _forever_ or _classic_beta_ containing Wow.exe or WowB.exe, or their parent folder.'); return
        self.roots.append(Path(selected)); self.client = clients[0] if len(clients)==1 else None
        self.populate(clients); self.changed = True; self.selectionChanged.emit(self.client)
