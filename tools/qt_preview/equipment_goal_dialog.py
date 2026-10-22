"""Review destination and identity before creating one saved planning goal."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QComboBox, QMessageBox
from app import label
from equipment_goal import proposed_goal, save_goal


class EquipmentGoalDialog(QDialog):
    def __init__(self, host, slot, parent=None):
        super().__init__(parent or host)
        self.host, self.slot, self.character = host, slot, host.data.active
        self.goal, self.record = proposed_goal(host.data, slot)
        self.setWindowTitle('Create wishlist goal from equipped item'); self.resize(620, 420)
        box = QVBoxLayout(self)
        self.target = QComboBox()
        self.target.addItems(host.data.playstyles.available(self.character, host.data.profile.character_class)[1:])
        active = host.data.playstyles.active(self.character)
        if self.target.findText(active) >= 0: self.target.setCurrentText(active)
        box.addWidget(label('Destination playstyle')); box.addWidget(self.target)
        self.preview = label(''); self.preview.setTextFormat(Qt.TextFormat.PlainText); box.addWidget(self.preview)
        self.target.currentTextChanged.connect(self.review); self.review()
        box.addWidget(label('Creates a Wanted goal with Normal priority. This is the same captured item, not a suggested upgrade. Other goals, unfinished edits, bags and bank stay unchanged.'))
        self.notice = label(''); self.notice.setTextFormat(Qt.TextFormat.PlainText); box.addWidget(self.notice)
        box.addWidget(host.button('Save reviewed goal', self.save))
        box.addWidget(host.button('Cancel', self.reject))

    def review(self):
        self.preview.setText(f'{self.host.data.profile.name} · {self.target.currentText()}\n'
                             f'{self.goal.name}\nSlot: {self.goal.slot} · Item ID: {self.goal.catalogue_ref.item_id}\n'
                             f'Captured: {self.record["captured_at"]} (client local)')

    def save(self):
        answer = QMessageBox.question(self, 'Confirm wishlist goal', self.preview.text()+'\n\nSave this Wanted goal?',
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Save: return
        try:
            save_goal(self.host.data, self.character, self.target.currentText(), self.slot, self.record, self.goal)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.notice.setText(str(exc)); return
        self.accept()
