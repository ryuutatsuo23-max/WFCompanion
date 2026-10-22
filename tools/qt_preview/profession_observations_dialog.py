"""Read-only profession journal with an explicit saved-character connection action."""
from datetime import datetime, timezone
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFileDialog, QPlainTextEdit,
    QComboBox, QLineEdit, QScrollArea, QWidget, QGroupBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView)
from app import label, row


class RecipeCell(QTableWidgetItem):
    """Sort recipe identifiers numerically instead of sorting their captions."""
    def __lt__(self, other):
        return self.data(Qt.ItemDataRole.UserRole) < other.data(Qt.ItemDataRole.UserRole)


class TextCell(QTableWidgetItem):
    def __lt__(self, other):
        return self.text().casefold() < other.text().casefold()


def describe(snapshot):
    if snapshot is None:
        return 'No observations read. Choose the Beta account SavedVariables folder.'
    lines = ['Cached DataStore observation · Coverage unknown',
             'Recipe names unknown · Ingredients unknown · Output items unknown',
             'Learned means flagged learned in this saved cache, not current game state.',
             'Empty or missing recipes do not establish unlearning.',
             'Session-only cache; manual plans and inventory are untouched.', '',
             snapshot['directory'], snapshot['provenance'],
             'Read at: ' + datetime.fromtimestamp(snapshot['read_time'], timezone.utc).isoformat()]
    for name, info in snapshot['files'].items():
        lines.append(f"{name}: file mtime {datetime.fromtimestamp(info['mtime_ns']/1e9, timezone.utc).isoformat()}")
        lines.append('SHA-256: ' + info['sha256'])
    if not snapshot['characters']:
        lines.append('\nNo character observations · Coverage unknown')
    for char in snapshot['characters']:
        lines.extend(['', f"Source character #{char['source_id']} · " +
                      (char['guid'] or 'Character mapping unavailable'),
                      'Character source update: ' + char['freshness'],
                      'Source update is not a per-recipe timestamp.'])
        if not char['professions']:
            lines.append('No profession observations · Coverage unknown')
        for prof in char['professions']:
            rank = 'Unknown' if prof['rank'] is None else f"{prof['rank']}/{prof['max']}"
            learned = [r for r in prof['recipes'] if r['fields'][0]]
            lines.append(f"\n{prof['name']} · Recorded skill {rank} · Coverage unknown")
            lines.append(f"{len(learned)} flagged learned / {len(prof['recipes'])} cached recipe records")
            if not learned:
                lines.append('No learned recipe IDs recorded here; current knowledge unknown.')
            for recipe in learned:
                _, difficulty, rank, maximum = recipe['fields']
                categories = '; '.join(f'{k}: {v}' for k, v in recipe['categories'].items())
                lines.append(f"Recipe #{recipe['id']} — name unknown | recorded rank {rank}/{maximum} | "
                             f"difficulty code {difficulty} | {categories}")
    return '\n'.join(lines)


class ProfessionObservationsDialog(QDialog):
    def __init__(self, host, cache):
        super().__init__(host)
        self.cache = cache
        self.host = host
        self.directory = cache.accepted['directory'] if cache.accepted else None
        self.setWindowTitle('Cached professions · WF Companion')
        self.resize(980, 750); self.setPalette(host.palette())
        box = QVBoxLayout(self)
        self.status = label(''); self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText); box.addWidget(self.status)
        self.character = QComboBox()
        box.addWidget(row(label('Character'), self.character))
        self.saved = label(''); self.saved.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.saved)
        self.cards_scroll = QScrollArea(); self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setPalette(host.palette()); self.cards_scroll.viewport().setPalette(host.palette())
        self.cards_scroll.setMaximumHeight(210)
        self.cards = QWidget(); self.cards_layout = QVBoxLayout(self.cards)
        self.cards.setPalette(host.palette())
        self.cards_scroll.setWidget(self.cards); box.addWidget(self.cards_scroll)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search recipe ID, profession or category…')
        self.search.setMinimumWidth(320)
        self.profession = QComboBox(); self.category = QComboBox()
        box.addWidget(row(self.search, self.profession, self.category))
        self.recipes = QTableWidget(0, 3)
        self.recipes.setHorizontalHeaderLabels(['Category', 'Profession', 'Saved recipe'])
        self.recipes.setSortingEnabled(True)
        self.recipes.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.recipes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recipes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recipes.verticalHeader().hide(); self.recipes.setCornerButtonEnabled(False)
        self.recipes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.recipes, 1)
        self.summary = label(''); box.addWidget(self.summary)
        box.addWidget(label('Recipe names and ingredients are not available yet.'))
        self.details_button = host.button('Details', self.toggle_details)
        self.details_button.setCheckable(True)
        self.forget_button = host.button('Forget saved connection', self.forget_connection)
        self.forget_button.hide(); box.addWidget(row(self.details_button, self.forget_button))
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        self.output.setMaximumHeight(180); self.output.hide(); box.addWidget(self.output)
        self.refresh_button = host.button('Refresh', self.refresh)
        self.connect_button = host.button('Connect & remember characters', self.connect_characters)
        box.addWidget(row(host.button('Choose saved data', self.choose),
                          self.refresh_button, self.connect_button, host.button('Close', self.accept)))
        self.character.currentIndexChanged.connect(self.select_character)
        self.search.textChanged.connect(self.filter_recipes)
        self.profession.currentIndexChanged.connect(self.filter_recipes)
        self.category.currentIndexChanged.connect(self.filter_recipes)
        self.recipe_rows = []
        self.render()

    def toggle_details(self):
        self.output.setVisible(self.details_button.isChecked())
        self.forget_button.setVisible(self.details_button.isChecked())

    def forget_connection(self):
        try:
            self.host.saved_character_connection.forget()
            self.status.setText('Connection forgotten. Existing characters and plans are kept.')
        except (ValueError, OSError) as exc:
            self.status.setText('Could not forget connection: '+str(exc))

    def select_character(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        snapshot = self.cache.accepted
        index = self.character.currentIndex()
        char = snapshot['characters'][index] if snapshot and index >= 0 else None
        self.recipe_rows = []
        self.profession.blockSignals(True); self.category.blockSignals(True)
        self.profession.clear(); self.profession.addItem('All professions', None)
        self.category.clear(); self.category.addItem('All categories', None)
        categories = {}
        self.saved.setText('No observations read. Choose a Beta account folder.' if char is None else
            'Saved: ' + (datetime.fromtimestamp(char['source_time'], timezone.utc).astimezone().strftime('%d %b %Y, %H:%M')
                if char['freshness'] not in ('Unknown age',) and not char['freshness'].startswith('Clock mismatch')
                else char['freshness']) +
            ('' if char['guid'] else ' · Character mapping unavailable'))
        for prof in char['professions'] if char else []:
            self.profession.addItem(prof['name'], prof['index'])
            learned = [r for r in prof['recipes'] if r['fields'][0]]
            card = QGroupBox(); card.setPalette(self.palette()); layout = QVBoxLayout(card)
            title = label(prof['name']); title.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(title)
            rank = 'Unknown' if prof['rank'] is None else f"{prof['rank']}/{prof['max']}"
            layout.addWidget(label(f'Skill {rank} · {len(learned)} saved recipes'))
            if prof['rank'] is not None and prof['max'] > 0:
                progress = QProgressBar(); progress.setRange(0, prof['max'])
                progress.setValue(prof['rank']); progress.setTextVisible(False); layout.addWidget(progress)
            self.cards_layout.addWidget(card)
            for recipe in learned:
                categories.update(recipe['categories'])
                self.recipe_rows.append((prof, recipe))
        if not char or not char['professions']:
            self.cards_layout.addWidget(label('No profession observations saved for this character.'))
        for key, name in sorted(categories.items()): self.category.addItem(name, key)
        self.profession.blockSignals(False); self.category.blockSignals(False)
        self.filter_recipes()

    def filter_recipes(self):
        query = self.search.text().strip().casefold()
        rows = []
        for prof, recipe in self.recipe_rows:
            category = '; '.join(dict.fromkeys(recipe['categories'].values()))
            cells = (category, prof['name'], f"Recipe #{recipe['id']}")
            if self.profession.currentData() not in (None, prof['index']): continue
            if self.category.currentData() is not None and self.category.currentData() not in recipe['categories']: continue
            if query and query not in ' '.join(cells).casefold(): continue
            rows.append((cells, recipe['id']))
        self.recipes.setSortingEnabled(False)
        self.recipes.setRowCount(len(rows))
        for i, (cells, recipe_id) in enumerate(rows):
            for j, value in enumerate(cells):
                item = RecipeCell(value) if j == 2 else TextCell(value)
                item.setData(Qt.ItemDataRole.UserRole, recipe_id)
                item.setToolTip(value); self.recipes.setItem(i, j, item)
        self.recipes.setSortingEnabled(True)
        self.summary.setText(f'{len(rows)} of {len(self.recipe_rows)} saved recipes'
                             if self.recipe_rows else 'No learned recipes recorded in this save.')

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Beta account SavedVariables folder')
        if folder:
            self.directory = folder
            self.refresh()

    def refresh(self):
        if self.directory:
            self.cache.refresh(self.directory)
        self.render()

    def connect_characters(self):
        if not self.directory:return
        try:
            self.cache=self.host.saved_character_connection.connect(self.directory)
            self.render()
            self.status.setText('Connected. This folder and its saved characters will load when the companion starts.')
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self.status.setText('Could not connect saved characters: '+str(exc))

    def render(self):
        self.refresh_button.setEnabled(bool(self.directory))
        self.connect_button.setEnabled(bool(self.directory) and self.cache.accepted is not None and not self.cache.error)
        retained = ('Previous accepted observation remains below.' if self.cache.accepted
                    else 'No observation has been accepted yet.')
        self.status.setText(('Read failed: ' + self.cache.error + '\n' + retained
                             if self.cache.error else 'Saved professions · Read-only'))
        self.output.setPlainText(describe(self.cache.accepted))
        old = self.character.currentData()
        self.character.blockSignals(True); self.character.clear()
        snapshot = self.cache.accepted
        for char in snapshot['characters'] if snapshot else []:
            identity = char.get('label')
            caption = (f"{identity['name']} · {identity['realm']}" if identity else
                       f"Saved character #{char['source_id']}")
            self.character.addItem(caption +
                                   ('' if char['guid'] else ' · Unmapped'),
                                   (snapshot['directory'], char['guid'], char['source_id']))
        selected = next((i for i in range(self.character.count())
                         if tuple(self.character.itemData(i)) == tuple(old or ())), -1)
        if selected >= 0: self.character.setCurrentIndex(selected)
        self.character.blockSignals(False)
        self.select_character()
