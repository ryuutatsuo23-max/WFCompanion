"""Optional first-launch guide. Only confirmed display preferences are saved."""
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
        self.setWindowTitle('Welcome to WFCompanion')
        self.setMinimumSize(580, 420)
        self.resize(640, 620)
        self.setButtonText(QWizard.WizardButton.CancelButton, 'Set up later')
        self.setButtonText(QWizard.WizardButton.FinishButton, 'Save and get started')
        self.add_text_page('Your adventures, in one place',
            'Plan characters, track items and keep wishlists on this PC. WoW does not need to be installed to use the companion.\n\n'
            'This short guide chooses how much detail you see and makes the text comfortable to read. You can change everything later in Settings.')
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
        self.add_text_page('Getting your game data',
            'Start with a character in Overview, then browse Inventory & Bank or make a gear wishlist.\n\n'
            'When WoW Forever is available, install Forever Storage with Core using the installer. The addons collect data while you play, even when this companion is closed.\n\n'
            'Use /reload or log out normally to save addon data. In the companion, connect the saved addon file through Overview. An unopened bank remains unknown.\n\n'
            'No game installation is needed today. Your manual notes and plans stay on this PC.')
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
        self.preview_appearance(); self.preview_tabs()
        host.qt_settings['experience_mode'] = self.mode.currentText()
        host.apply_appearance(); host.sync_controls()
        if host.save_session():
            host.show_page(next((name for name in TABS if name not in host.settings['hidden']), 'Settings')); super().accept()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Settings were not saved', host.session_status.text())


def show_if_needed(host):
    if not host.testing and not host.settings['setup']:
        host.setup_guide = SetupGuide(host)
        host.setup_guide.open()
