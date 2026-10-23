"""Optional first-launch guide. Preferences and an optional addon target are saved only on Finish."""
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWizard, QWizardPage, QVBoxLayout, QLabel, QComboBox, QFormLayout, QLineEdit, QListWidget, QCheckBox, QScrollArea, QWidget
from app import THEMES
from settings_page import TABS


class SetupGuide(QWizard):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.original_settings = deepcopy(host.settings)
        self.original_qt = deepcopy(host.qt_settings)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setPalette(host.palette())
        self.setStyleSheet(host.styleSheet() + f'QWizard, QWizardPage {{ background: {host.colors[1]}; color: {host.colors[3]}; }}')
        self.setWindowTitle('Welcome to WF Companion')
        self.setMinimumSize(580, 420)
        self.resize(640, 620)
        self.setButtonText(QWizard.WizardButton.CancelButton, 'Set up later')
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Save and get started')
        self.add_text_page('Your adventures, in one place',
            'Plan characters, track items and keep wishlists on this PC. WoW does not need to be installed to use the companion.\n\n'
            'Choose your display preferences and optionally select a game folder. You can change everything later in Settings or Addons.')
        page = QWizardPage(); page.setTitle('Make it comfortable')
        page.setAutoFillBackground(True); page.setPalette(host.palette())
        page_layout = QVBoxLayout(page)
        appearance_scroll = QScrollArea(); appearance_scroll.setWidgetResizable(True)
        appearance_body = QWidget(); appearance_body.setObjectName('guideSurface'); form = QFormLayout(appearance_body)
        appearance_scroll.viewport().setObjectName('guideViewport')
        appearance_scroll.setWidget(appearance_body); page_layout.addWidget(appearance_scroll)
        self.mode = QComboBox(); self.mode.addItems(['Easy', 'Advanced'])
        self.mode.setCurrentText(host.qt_settings.get('experience_mode', 'Easy'))
        names=host.theme_choices()
        self.theme = QListWidget(); self.theme.addItems(names); self.theme.setMaximumHeight(150)
        self.theme.setCurrentRow(names.index(host.settings['theme']))
        self.size = QComboBox(); self.size.addItems([str(i) for i in range(9, 19)])
        self.size.setCurrentText(str(host.settings['text_size']))
        form.addRow('Detail level', self.mode); form.addRow('Theme', self.theme); form.addRow('Text size (points)', self.size)
        self.artwork = QCheckBox('Show theme background'); self.artwork.setChecked(host.settings['show_artwork'])
        form.addRow(self.artwork)
        help_text = QLabel('Try Classic Fantasy for gold borders and red buttons, Parchment for a light reading view, or Midnight for a cool dark look. Choices preview behind this window. Cancel restores your previous settings.'); help_text.setWordWrap(True)
        form.addRow(help_text)
        self.sample = QLabel('Preview: Bags · Bank · Gear wishlist'); self.sample.setWordWrap(True)
        form.addRow(self.sample)
        self.size.currentTextChanged.connect(self.preview_size)
        self.theme.currentTextChanged.connect(self.preview_appearance)
        self.artwork.toggled.connect(self.preview_appearance)
        from windows_startup import checkbox
        self.startup=checkbox();form.addRow(self.startup)
        self.addPage(page)
        tabs = QWizardPage(); tabs.setTitle('Choose your tabs')
        tabs_layout = QVBoxLayout(tabs)
        note = QLabel('Keep the pages you use. Hidden tabs keep their saved data. Settings is always available.'); note.setWordWrap(True); tabs_layout.addWidget(note)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); contents = QWidget(); checks = QVBoxLayout(contents)
        contents.setObjectName('guideSurface'); scroll.viewport().setObjectName('guideViewport')
        self.tab_checks = {}
        for name in TABS[:-1]:
            check = QCheckBox(name.replace('&', '&&')); check.setChecked(name not in host.settings['hidden']); checks.addWidget(check); self.tab_checks[name] = check
            check.toggled.connect(self.preview_tabs)
        scroll.setWidget(contents); tabs_layout.addWidget(scroll); self.addPage(tabs)
        from game_folder_picker import GameFolderPicker
        game=QWizardPage();game.setTitle('Choose your game folder (optional)')
        game_layout=QVBoxLayout(game)
        game_scroll=QScrollArea();game_scroll.setWidgetResizable(True)
        body=QWidget();body.setObjectName('guideSurface');body_layout=QVBoxLayout(body)
        game_scroll.viewport().setObjectName('guideViewport')
        current=host.addons_page.client
        self.game_folder=GameFolderPicker(host,roots=host.addons_page.picker.roots,selected=current,auto_select=False)
        body_layout.addWidget(self.game_folder)
        help_text=QLabel('Save and get started remembers your choice only. Then open Addons to install Forever Core, Storage or Professions. No addons are installed by this guide.')
        help_text.setWordWrap(True);body_layout.addWidget(help_text);body_layout.addStretch()
        game_scroll.setWidget(body);game_layout.addWidget(game_scroll);self.addPage(game)
        self.add_text_page('Getting your saved game data',
            'After installing the addons, use /reload or log out normally to save game data. Newly added addons or assets may require a full game restart.\n\n'
            'Connect the saved addon file through Settings. Choosing an addon installation folder does not change that saved-data connection. Inventory & Bank shows the latest saved observations; an unopened bank remains unknown.\n\n'
            'Without a game folder, you can still use manual notes and plans. You can choose a folder later on the Addons page.')
        self.apply_guide_style()

    def apply_guide_style(self):
        # Scroll-area contents auto-fill using the native Windows palette unless
        # explicitly styled. Cover contents and viewport, including before preview.
        self.setPalette(self.host.palette())
        for page_id in self.pageIds(): self.page(page_id).setPalette(self.host.palette())
        self.setStyleSheet(self.host.styleSheet() + f'''
            QWizard, QWizardPage, QWidget#guideSurface, QWidget#guideViewport {{
                background-color: {self.host.colors[1]}; color: {self.host.colors[3]};
            }}
            QWizard QWidget {{ font-size: 11pt; }}
        ''')

    def add_text_page(self, title, text):
        page = QWizardPage(); page.setTitle(title)
        page.setAutoFillBackground(True); page.setPalette(self.host.palette())
        layout = QVBoxLayout(page); label = QLabel(text); label.setWordWrap(True)
        layout.addWidget(label); layout.addStretch(); self.addPage(page)

    def preview_appearance(self, *_):
        item = self.theme.currentItem()
        if item is None: return
        self.host.settings.update(theme=item.text(), text_size=int(self.size.currentText()), show_artwork=self.artwork.isChecked())
        self.host.apply_appearance(); self.host.refresh_settings_status()
        self.apply_guide_style()

    def preview_tabs(self, *_):
        self.host.settings['hidden'] = [name for name, check in self.tab_checks.items() if not check.isChecked()]
        self.host.settings['overview_visible'] = 'Overview' not in self.host.settings['hidden']
        self.host.rebuild_navigation(); self.host.refresh_settings_status()

    def reject(self):
        self.host.settings = deepcopy(self.original_settings); self.host.qt_settings = deepcopy(self.original_qt)
        self.host.apply_appearance(); self.host.sync_controls()
        super().reject()

    def preview_size(self, value):
        font = self.sample.font(); font.setPointSize(int(value)); self.sample.setFont(font)
        self.sample.setStyleSheet(f'font-size: {value}pt;')
        self.preview_appearance()

    def accept(self):
        host = self.host
        if self.game_folder.changed and self.game_folder.client:
            from game_folder_picker import validate_client
            try:validate_client(self.game_folder.client)
            except (OSError,ValueError,RuntimeError) as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self,'Game folder unavailable',str(exc));return
        self.preview_appearance(); self.preview_tabs()
        host.qt_settings['experience_mode'] = self.mode.currentText()
        host.apply_appearance(); host.sync_controls()
        if host.save_session():
            if self.game_folder.changed and not host.addons_page.remember_client(self.game_folder.client):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self,'Folder choice was not saved',host.addons_page.notice.text());return
            from windows_startup import set_enabled
            try:set_enabled(self.startup.isChecked())
            except OSError as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self,'Windows startup',str(exc));return
            host.startup_check.blockSignals(True);host.startup_check.setChecked(self.startup.isChecked());host.startup_check.blockSignals(False)
            host.show_page(next((name for name in TABS if name not in host.settings['hidden']), 'Settings')); super().accept()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Settings were not saved', host.session_status.text())


def show_if_needed(host):
    if not host.testing and not host.settings['setup']:
        host.setup_guide = SetupGuide(host)
        host.setup_guide.open()
