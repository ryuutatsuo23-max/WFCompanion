"""Companion display artwork, separate from the pinned installable addon files."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


def logo_pixmap(addon, size=88):
    slug={'WFStorage':'forever-storage','WFProfessions':'forever-professions'}[addon]
    base=Path(sys._MEIPASS)/'payload/tools/qt_preview' if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    pixmap=QPixmap(str(base/'artwork'/(slug+'-transparent.png')))
    return pixmap.scaled(size,size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation) if not pixmap.isNull() else pixmap


def saved_heading(addon,caption):
    container=QWidget();box=QHBoxLayout(container);box.setContentsMargins(0,0,0,0);box.setSpacing(12)
    icon=QLabel();icon.setFixedSize(88,88);icon.setAccessibleName(('Forever Storage' if addon=='WFStorage' else 'Forever Professions')+' logo')
    pixmap=logo_pixmap(addon)
    if not pixmap.isNull():icon.setPixmap(pixmap);box.addWidget(icon)
    else:icon.hide()
    text=QLabel(caption);text.setWordWrap(True);box.addWidget(text,1)
    container.logo=icon
    return container
