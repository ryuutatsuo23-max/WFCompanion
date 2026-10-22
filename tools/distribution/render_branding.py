"""Render installer layout and convert the original SVG to Windows icon formats."""
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QFont, QPixmap
from PySide6.QtCore import Qt, QRectF
from PySide6.QtSvg import QSvgRenderer
from PIL import Image


def render():
    app = QApplication.instance() or QApplication([])
    folder = Path(__file__).resolve().parent / 'assets'
    svg = QSvgRenderer(str(folder / 'forever.svg'))
    if not svg.isValid(): raise ValueError('Invalid Forever icon SVG')
    icon = QImage(256,256,QImage.Format.Format_ARGB32); icon.fill(Qt.GlobalColor.transparent)
    painter = QPainter(icon); svg.render(painter,QRectF(0,0,256,256)); painter.end()
    icon.save(str(folder/'forever.png'))
    with Image.open(folder/'forever.png') as image:
        image.save(folder/'forever.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    canvas = QImage(994,720,QImage.Format.Format_RGB32); canvas.fill(QColor('#171817'))
    painter = QPainter(canvas); painter.drawTiledPixmap(canvas.rect(),QPixmap(str(folder/'stone.png')))
    painter.fillRect(18,18,958,684,QColor(18,20,20,215))
    for inset,colour,width in ((3,'#332a1c',6),(8,'#a08b57',2),(13,'#514735',2)):
        painter.setPen(QPen(QColor(colour),width)); painter.drawRect(inset,inset,993-2*inset,719-2*inset)
    painter.end(); canvas.save(str(folder/'wizard-background.png'))
    panel = QImage(328,720,QImage.Format.Format_RGB32); panel.fill(QColor('#151a1b'))
    painter = QPainter(panel); painter.drawTiledPixmap(panel.rect(),QPixmap(str(folder/'stone.png')))
    painter.fillRect(panel.rect(),QColor(8,20,22,150)); svg.render(painter,QRectF(44,90,240,240))
    painter.setPen(QColor('#d8be7b')); painter.setFont(QFont('Georgia',23,QFont.Weight.Bold))
    painter.drawText(QRectF(10,355,308,70),Qt.AlignmentFlag.AlignCenter,'WFCompanion')
    painter.setFont(QFont('Segoe UI',12)); painter.setPen(QColor('#eadfca'))
    painter.drawText(QRectF(20,430,288,120),Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,'Your characters.\nYour adventures.\nAlways within reach.')
    painter.end(); panel.save(str(folder/'wizard-sidebar.png'))


if __name__ == '__main__': render()
