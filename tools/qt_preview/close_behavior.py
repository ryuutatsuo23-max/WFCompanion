"""Remembered close action; tray hiding never discards the current session."""
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QMessageBox, QCheckBox, QStyle
from PySide6.QtCore import Qt
from local_journal import LocalStore

CHOICES = {'Ask every time': 'ask', 'Minimize to tray': 'tray', 'Quit': 'quit'}


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('action') not in CHOICES.values():
        raise ValueError('Invalid close-window preference.')


class CloseBehavior:
    def __init__(self, host):
        self.host = host
        self.force_quit = False
        self.store = LocalStore(host.data.directory, 'close_behavior.json', dict(version=1, action='ask'), validate)
        self.tray = QSystemTrayIcon(host)
        icon = host.windowIcon()
        if icon.isNull(): icon = host.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray.setIcon(icon)
        self.tray.setToolTip('WF Companion')
        self.menu = QMenu(host)
        self.menu.addAction('Open WF Companion', self.restore)
        self.menu.addSeparator()
        self.menu.addAction('Quit', self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.activate)

    def activate(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore()

    def restore(self):
        self.host.show(); self.host.setWindowState(self.host.windowState() & ~Qt.WindowState.WindowMinimized)
        self.host.raise_(); self.host.activateWindow(); self.tray.hide()

    def quit(self):
        self.force_quit = True
        try: return self.host.close()
        finally: self.force_quit = False

    def save(self, text):
        try:
            self.store.save(dict(version=1, action=CHOICES[text]))
            self.host.close_status.setText('Choice saved. Changes apply immediately.')
            self.host.close_choice.blockSignals(True)
            self.host.close_choice.setCurrentText(text)
            self.host.close_choice.blockSignals(False)
            return True
        except (ValueError, OSError) as exc:
            self.host.close_status.setText('Could not save close preference: '+str(exc))
            self.host.close_choice.blockSignals(True)
            self.host.close_choice.setCurrentText(next(k for k,v in CHOICES.items() if v == self.store.data['action']))
            self.host.close_choice.blockSignals(False)
            return False

    def allow_close(self):
        if self.force_quit: return True
        available = QSystemTrayIcon.isSystemTrayAvailable()
        action = self.store.data['action']
        remember = False
        if action == 'ask' or (action == 'tray' and not available):
            box = QMessageBox(self.host)
            box.setWindowTitle('Close WF Companion')
            box.setText('Keep WF Companion running in the notification area, or quit completely?' if available else 'The notification area is unavailable. You can quit or keep the window open.')
            tray_button = box.addButton('Minimize to tray', QMessageBox.ButtonRole.ActionRole)
            tray_button.setEnabled(available)
            quit_button = box.addButton('Quit', QMessageBox.ButtonRole.DestructiveRole)
            cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(cancel_button)
            check = QCheckBox('Remember my choice'); box.setCheckBox(check)
            box.exec()
            clicked = box.clickedButton()
            if clicked == tray_button: action = 'tray'
            elif clicked == quit_button: action = 'quit'
            else: return False
            remember = check.isChecked()
        if remember:
            self.save(next(k for k,v in CHOICES.items() if v == action))
        if action == 'tray':
            self.tray.show(); self.host.hide()
            return False
        return True
