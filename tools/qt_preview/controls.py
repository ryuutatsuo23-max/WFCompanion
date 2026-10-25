"""Consistent dropdown placement and scroll-safe choices across pages/dialogs."""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QComboBox, QScrollArea


class ComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMaxVisibleItems(12)

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        anchor = self.mapToGlobal(QPoint(0, self.height()))
        area = self.screen().availableGeometry()
        below = area.bottom() - anchor.y() + 1
        # Prefer below even for a selected item near the end of the list. At
        # the screen bottom use above only when no useful list fits below.
        minimum = min(popup.height(), self.fontMetrics().height() * 3 + 12)
        above = self.mapToGlobal(QPoint(0, 0)).y() - area.top()
        use_below = below >= minimum or below >= above
        height = max(1, min(popup.height(), below if use_below else above))
        width = min(max(self.width(), popup.width()), area.width())
        x = max(area.left(), min(anchor.x(), area.right() - width + 1))
        y = anchor.y() if use_below else anchor.y() - self.height() - height
        popup.setGeometry(x, max(area.top(), y), width, height)

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            movement = event.pixelDelta().y() or round(event.angleDelta().y() / 120 * max(20, self.fontMetrics().height()) * 3)
            bar = parent.verticalScrollBar()
            bar.setValue(bar.value() - movement)
            event.accept()
        else:
            event.ignore()
