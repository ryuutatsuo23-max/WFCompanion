"""Count links intercept pointer selection so opening details preserves drafts."""
from PySide6.QtCore import Qt
from widgets import Table


class WishlistTable(Table):
    LINK_COLUMNS=(4,5)

    def __init__(self,headers,selected,open_stock):
        super().__init__(headers,selected)
        self.open_stock=open_stock; self.pressed_link=None
        self.setMouseTracking(True)

    def link_at(self,pos):
        index=self.indexAt(pos)
        if index.isValid() and index.column() in self.LINK_COLUMNS and index.row()<len(self.keys):
            return self.keys[index.row()],index.column()
        return None

    def mousePressEvent(self,event):
        self.pressed_link=None
        if event.button()==Qt.MouseButton.LeftButton:
            self.pressed_link=self.link_at(event.position().toPoint())
            if self.pressed_link is not None:
                event.accept(); return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self,event):
        pressed=self.pressed_link; self.pressed_link=None
        if event.button()==Qt.MouseButton.LeftButton and pressed is not None:
            event.accept()
            if self.link_at(event.position().toPoint())==pressed: self.open_stock(pressed[0])
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.link_at(event.position().toPoint()) is not None:
            self.pressed_link=None; event.accept(); return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self,event):
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if self.link_at(event.position().toPoint()) else Qt.CursorShape.ArrowCursor)
        if self.pressed_link is not None:
            event.accept(); return
        super().mouseMoveEvent(event)
