"""Isolated Qt rendering preview. No personal stores, network or game access.

One backing-store background is propagated through transparent scrolling widgets.
Changing opacity schedules paint only; it never rebuilds styles or layouts.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import math
import sys

from PySide6.QtCore import Qt, QRect, QSize, QTimer, QPoint, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QPalette, QPen, QTextLayout, QTextOption, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLayout, QSizePolicy,
    QLabel, QPushButton, QComboBox, QCheckBox, QSlider, QSpinBox,
    QScrollArea, QStackedWidget, QProgressBar, QProxyStyle, QStyle,
    QStyleFactory, QStyleOptionButton, QStylePainter,
)

SOURCE = Path(__file__).resolve().parents[1] / 'offline_preview'
sys.path.insert(0, str(SOURCE))
from appearance_catalogue import THEMES, THEME_ART, FONT_CHOICES, ART_DIRECTORY

DEFAULT = dict(theme='Stormwind · Alliance', ui_style='WoW', text_size=12,
               font_family='Segoe UI', show_artwork=True,
               artwork_mode='Full background', panel_transparency=20,
               overview_visible=True)


class FlowLayout(QLayout):
    """Content-sized controls that wrap instead of stretching across the window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(12)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), True)

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)

    def arrange(self, rect, measure):
        x, y, height = rect.x(), rect.y(), 0
        line = []
        def place_line():
            if measure: return
            controls = [item.widget().field_control for item,_,_ in line
                        if item.widget() and item.widget().property('formField')]
            baseline_height = max((control.sizeHint().height() for control in controls),default=height)
            for item, left, size in line:
                # Field boxes share a bottom baseline even when a caption wraps.
                # Other controls are vertically centred within the flow row.
                is_field = bool(item.widget() and item.widget().property('formField'))
                offset = max(0, height-(baseline_height+size.height())//2) if controls else (height-size.height())//2
                offset = min(offset, height-size.height())
                item.setGeometry(QRect(left, y if is_field else y + offset,
                                       size.width(), height if is_field else size.height()))
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            width = min(size.width(), max(1, rect.width()))
            height_for_width = item.heightForWidth(width) if item.hasHeightForWidth() else -1
            size = QSize(width, height_for_width if height_for_width >= 0 else size.height())
            if x > rect.x() and x + size.width() > rect.right() + 1:
                place_line()
                line = []
                x, y, height = rect.x(), y + height + self.spacing(), 0
            line.append((item, x, size))
            x += size.width() + self.spacing()
            height = max(height, size.height())
        place_line()
        return y + height - rect.y()


def nine_slice(painter, target, image, caps):
    """Nine cached pixmap blits, independent of the destination pixel count."""
    if image.isNull():
        return
    left, top, right, bottom = caps
    xs = (0, left, image.width() - right, image.width())
    ys = (0, top, image.height() - bottom, image.height())
    dx = (target.x(), target.x() + left, target.right() + 1 - right, target.right() + 1)
    dy = (target.y(), target.y() + top, target.bottom() + 1 - bottom, target.bottom() + 1)
    for i in range(3):
        for j in range(3):
            painter.drawPixmap(QRect(dx[i], dy[j], dx[i+1]-dx[i], dy[j+1]-dy[j]),
                               image, QRect(xs[i], ys[j], xs[i+1]-xs[i], ys[j+1]-ys[j]))


class TiledFrame:
    """Cache native-size corner/edge pieces; never magnify their texture detail."""
    def __init__(self, image, caps):
        self.caps = caps
        left, top, right, bottom = caps
        xs = (0, left, image.width()-right, image.width())
        ys = (0, top, image.height()-bottom, image.height())
        self.pieces = {(i,j): image.copy(xs[i],ys[j],xs[i+1]-xs[i],ys[j+1]-ys[j])
                       for i in range(3) for j in range(3)} if not image.isNull() else {}

    def paint(self, painter, target):
        left, top, right, bottom = self.caps
        xs = (target.x(),target.x()+left,target.right()+1-right,target.right()+1)
        ys = (target.y(),target.y()+top,target.bottom()+1-bottom,target.bottom()+1)
        for (i,j), pixmap in self.pieces.items():
            area = QRect(xs[i],ys[j],xs[i+1]-xs[i],ys[j+1]-ys[j])
            if area.width()>0 and area.height()>0:
                painter.drawTiledPixmap(area,pixmap)


class Textures:
    def __init__(self):
        directory = ART_DIRECTORY / 'wow_ui'
        def load(name, crop=None):
            pix = QPixmap(str(directory / name))
            return pix.copy(*crop) if crop and not pix.isNull() else pix
        self.up = load('UI-Panel-Button-Up.PNG', (0, 0, 80, 22))
        self.down = load('UI-Panel-Button-Down.PNG', (0, 0, 80, 22))
        self.header = load('UI-DialogBox-Header.PNG', (58, 0, 139, 40))
        self.slider = load('UI-SliderBar-Button-Horizontal.PNG', (7, 4, 16, 23))
        self.check = load('UI-CheckBox-Up.PNG')
        self.checked = load('UI-CheckBox-Check.PNG')
        atlas = load('UI-DialogBox-Border.PNG')
        self.border = QPixmap(96, 96)
        self.border.fill(Qt.GlobalColor.transparent)
        self.ready = not atlas.isNull() and not self.header.isNull() and not self.up.isNull()
        if self.ready:
            edges = [atlas.copy(i * 32, 0, 32, 32) for i in range(8)]
            # Top/bottom strips in Blizzard's atlas run vertically.
            for i in (2, 3):
                old = edges[i].toImage()
                new = old.copy()
                for x in range(32):
                    for y in range(32):
                        new.setPixelColor(y, x, old.pixelColor(x, y))
                edges[i] = QPixmap.fromImage(new)
            painter = QPainter(self.border)
            for image, x, y in zip(edges, (0,64,32,32,0,64,0,64), (32,32,0,64,0,0,64,64)):
                painter.drawPixmap(x, y, image)
            painter.end()
        self.panel_frame = TiledFrame(self.border, (32,32,32,32))
        self.panel_frame.pieces.pop((1,1), None)  # Panel already paints its fill.
        # Only repeat the grain inside the bevel, never its dark top/bottom lip.
        self.title_frame = TiledFrame(self.header, (24,19,24,14))
        # The header's seven-pixel interior is too small to repeat without
        # visible bands. Use Blizzard's seamless dialog grain for the centre.
        grain = load('UI-DialogBox-Background.PNG')
        if not grain.isNull():
            painter = QPainter(grain)
            painter.fillRect(grain.rect(), QColor(48,40,28,140))
            painter.end()
            self.title_frame.pieces[1,1] = grain


class TextureStyle(QProxyStyle):
    """Keep Qt's native interaction/focus semantics while painting WoW details."""
    def __init__(self, textures):
        super().__init__(QStyleFactory.create('Fusion'))
        self.textures = textures
        self.wow = True

    def pixelMetric(self, metric, option=None, widget=None):
        if self.wow and metric in (QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight):
            return max(24, widget.fontMetrics().height() if widget else 24)
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        t = self.textures
        if self.wow and t.ready:
            if element == QStyle.PrimitiveElement.PE_PanelButtonCommand:
                image = t.down if option.state & QStyle.StateFlag.State_Sunken else t.up
                nine_slice(painter, option.rect, image, (8, 10, 8, 11))
                if option.state & QStyle.StateFlag.State_MouseOver:
                    painter.fillRect(option.rect.adjusted(5, 5, -5, -5), QColor(255, 210, 110, 25))
                return
            if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox and not t.check.isNull():
                painter.drawPixmap(option.rect, t.check)
                if option.state & QStyle.StateFlag.State_On:
                    painter.drawPixmap(option.rect, t.checked)
                return
        super().drawPrimitive(element, option, painter, widget)

    def drawComplexControl(self, control, option, painter, widget=None):
        super().drawComplexControl(control, option, painter, widget)
        if self.wow and control == QStyle.ComplexControl.CC_Slider and not self.textures.slider.isNull():
            rect = self.subControlRect(control, option, QStyle.SubControl.SC_SliderHandle, widget)
            painter.drawPixmap(rect.adjusted(-1, -3, 1, 3), self.textures.slider)


class Panel(QWidget):
    def __init__(self, host, title):
        super().__init__()
        self.host = host
        host.panels.append(self)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(20, 16, 20, 20)
        self.box.setSpacing(14)
        self.box.addWidget(Title(host, title))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        color = QColor(self.host.colors[1])
        color.setAlpha(round(255 * (1 - self.host.settings['panel_transparency'] / 100)))
        inset = 9 if self.host.wow else 5
        painter.fillRect(self.rect().adjusted(inset, inset, -inset, -inset), color)
        if self.host.original_theme:
            paint_original_frame(painter, self.rect(), self.host.colors)
        elif self.host.wow:
            self.host.textures.panel_frame.paint(painter, self.rect())
        else:
            painter.setPen(QColor(self.host.colors[4]))
            painter.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 6, 6)


class WrappedButton(QPushButton):
    """Keep native button behavior, with readable long recovery/action captions."""
    def __init__(self, text):
        super().__init__(text)
        policy = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._text_layout = None
        self._text_key = None

    def text_layout(self, width):
        # Captions are escaped for QPushButton's mnemonic syntax by the factory.
        text = self.text().replace('&&', '&')
        key = (text, self.font().toString(), max(1, width - 32))
        if key != self._text_key:
            layout = QTextLayout(text, self.font())
            option = QTextOption(Qt.AlignmentFlag.AlignHCenter)
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            layout.beginLayout()
            height = 0
            while True:
                line = layout.createLine()
                if not line.isValid(): break
                line.setLineWidth(key[2]); line.setPosition(QPointF(0, height))
                height += line.height()
            layout.endLayout()
            self._text_layout, self._text_key = layout, key
        return self._text_layout

    def heightForWidth(self, width):
        return max(super().sizeHint().height(), math.ceil(self.text_layout(width).boundingRect().height()) + 18)

    def sizeHint(self):
        width = min(560, super().sizeHint().width())
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        hint = self.sizeHint()
        return QSize(min(220, hint.width()), super().sizeHint().height())

    def paintEvent(self, event):
        option = QStyleOptionButton(); self.initStyleOption(option); option.text = ''
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        painter.setPen(self.palette().color(group, QPalette.ColorRole.ButtonText))
        layout = self.text_layout(self.width())
        offset = 1 if self.isDown() else 0
        layout.draw(painter, QPointF(16 + offset, (self.height() - layout.boundingRect().height()) / 2 + offset))


class Title(QWidget):
    def __init__(self, host, text):
        super().__init__()
        self.host, self.text = host, text
        self.setAccessibleName(text)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        from PySide6.QtGui import QFontMetrics
        metrics = QFontMetrics(QFont(self.font().family(), self.font().pointSize(), QFont.Weight.Bold))
        return QSize(metrics.horizontalAdvance(self.text) + 56,
                     self.fontMetrics().height() + 40)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.host.original_theme:
            gradient=QLinearGradient(0,0,0,self.height())
            gradient.setColorAt(0,QColor(self.host.colors[1]));gradient.setColorAt(1,QColor(self.host.colors[2]))
            painter.fillRect(self.rect().adjusted(3,3,-3,-3),gradient)
            paint_original_frame(painter,self.rect(),self.host.colors)
        elif self.host.wow:
            self.host.textures.title_frame.paint(painter, self.rect())
        painter.setFont(QFont(self.font().family(), self.font().pointSize(), QFont.Weight.Bold))
        painter.setPen(QColor('#ffdd70' if self.host.wow else self.host.colors[3]))
        painter.drawText(self.rect().adjusted(25, 0, -25, 0), Qt.AlignmentFlag.AlignCenter, self.text)


def label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    return widget


def paint_original_frame(painter, rect, colors):
    """Original scalable double-rule frame, with small diamond corner details."""
    painter.setPen(QPen(QColor(colors[5]),1))
    painter.drawRect(rect.adjusted(3,3,-4,-4))
    painter.setPen(QPen(QColor(colors[4]),1))
    painter.drawRect(rect.adjusted(6,6,-7,-7))
    for x,y in ((7,7),(rect.width()-8,7),(7,rect.height()-8),(rect.width()-8,rect.height()-8)):
        painter.setPen(QPen(QColor(colors[5]),2))
        painter.drawLine(x-3,y,x,y-3);painter.drawLine(x,y-3,x+3,y)
        painter.drawLine(x+3,y,x,y+3);painter.drawLine(x,y+3,x-3,y)


def row(*widgets):
    container = QWidget()
    layout = FlowLayout(container)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def field(caption, control):
    box = QWidget()
    box.setProperty('formField', True)
    box.field_control = control
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label(caption), 1, Qt.AlignmentFlag.AlignBottom)
    layout.addWidget(control, 0, Qt.AlignmentFlag.AlignLeft)
    box.setMaximumWidth(max(470, control.minimumWidth()))
    return box


class Preview(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WoW Forever · Qt Preview · Session only')
        self.settings = deepcopy(DEFAULT)
        self.saved = deepcopy(DEFAULT)
        self.panels = []
        self.colors = THEMES[self.settings['theme']]
        self.textures = Textures()
        self.style_engine = TextureStyle(self.textures)
        QApplication.instance().setStyle(self.style_engine)
        self.art = QPixmap()
        self.art_key = None
        self.art_loads = 0
        self.style_updates = 0
        self.simulation_time = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.demo_tick)
        self.build()
        self.apply_appearance()
        self.sync_controls()
        self.resize(1200, 900)
        self.setMinimumSize(620, 480)

    @property
    def wow(self):
        return not self.original_theme and self.settings['ui_style'] == 'WoW' and self.textures.ready

    @property
    def original_theme(self):
        return self.settings['theme'] in ('Classic Fantasy','Parchment','Midnight')

    def button(self, text, callback):
        button = WrappedButton(text.replace('&', '&&'))
        # QPushButton.clicked supplies a checked bool. Do not let it overwrite
        # a callback's captured default (for example, a tab name).
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def combo(self, values, callback):
        control = QComboBox()
        control.addItems(values)
        control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        control.setMaximumWidth(440)
        control.setToolTip(control.currentText())
        control.currentTextChanged.connect(control.setToolTip)
        control.currentTextChanged.connect(callback)
        # Wheel scrolling over a closed choice box scrolls the page, not its value.
        control.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        control.installEventFilter(self)
        return control

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.ToolTip and isinstance(watched, QComboBox):
            # Character/tracker lists are populated with signals blocked.
            watched.setToolTip(watched.currentText())
        if event.type() == QEvent.Type.Wheel and isinstance(watched, (QComboBox, QSpinBox, QSlider)):
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def slider(self, low, high, value, callback):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        slider.setFixedWidth(280)
        slider.setMinimumHeight(32)
        slider.valueChanged.connect(callback)
        slider.installEventFilter(self)
        return slider

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.addWidget(Title(self, 'WoW Forever'))
        layout.addWidget(label('Qt rendering preview · Simulated data · Settings last for this session only'))
        self.overview_button = self.button('Overview', lambda: self.pages.setCurrentIndex(0))
        self.settings_button = self.button('Settings', lambda: self.pages.setCurrentIndex(1))
        layout.addWidget(row(self.overview_button, self.settings_button))
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.scrolls = []
        self.page_layouts = []
        for name in ('Overview', 'Settings'):
            scroll = QScrollArea()
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.viewport().setAutoFillBackground(False)
            content = QWidget()
            box = QVBoxLayout(content)
            box.setContentsMargins(0, 0, 12, 0)
            box.setSpacing(14)
            box.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(content)
            content.setAutoFillBackground(False)
            self.pages.addWidget(scroll)
            self.scrolls.append(scroll)
            self.page_layouts.append(box)
        self.build_overview(self.page_layouts[0])
        self.build_settings(self.page_layouts[1])
        layout.addWidget(label('Offline preview · No game connection or input backend · Your existing tool remains separate'))

    def build_overview(self, layout):
        panel = Panel(self, 'Overview')
        layout.addWidget(panel)
        panel.box.addWidget(label('Try a class-neutral example, or move the sliders to test your own reminder thresholds.'))
        self.hp_bars = []
        self.hp_values = []
        cards = []
        for name in ('Your HP', 'Party member HP'):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedWidth(280)
            bar.setMinimumHeight(34)
            bar.setTextVisible(False)
            self.hp_bars.append(bar)
            value = QLabel()
            self.hp_values.append(value)
            card = field(name, value)
            card.layout().addWidget(bar)
            cards.append(card)
        panel.box.addWidget(row(*cards))
        self.buff_text, self.cooldown_text = label(''), label('')
        panel.box.addWidget(self.buff_text)
        panel.box.addWidget(self.cooldown_text)
        self.reminder = label('')
        self.reminder.setMinimumHeight(70)
        panel.box.addWidget(self.reminder)
        self.demo_button = self.button('Play demo', self.toggle_demo)
        panel.box.addWidget(row(self.demo_button, self.button('Reset simulation', self.reset_demo)))
        inputs = Panel(self, 'Simulation controls')
        layout.addWidget(inputs)
        self.hp = self.slider(0, 100, 100, self.refresh_simulation)
        self.party = self.slider(0, 100, 82, self.refresh_simulation)
        self.cooldown = self.slider(0, 60, 15, self.refresh_simulation)
        inputs.box.addWidget(row(field('Your HP %', self.hp), field('Party HP %', self.party)))
        inputs.box.addWidget(field('Cooldown · seconds', self.cooldown))
        self.buff = QCheckBox('Tracked buff present')
        self.buff.setChecked(True)
        self.buff.toggled.connect(self.refresh_simulation)
        inputs.box.addWidget(self.buff)
        rules = Panel(self, 'Reminder preview')
        layout.addWidget(rules)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 99)
        self.threshold.setValue(40)
        self.threshold.setSuffix('%')
        self.threshold.valueChanged.connect(self.refresh_simulation)
        self.threshold.installEventFilter(self)
        self.missing_buff = QCheckBox('Remind me when the tracked buff is missing')
        self.missing_buff.setChecked(True)
        self.missing_buff.toggled.connect(self.refresh_simulation)
        rules.box.addWidget(field('Low HP threshold · applies to both HP sources', self.threshold))
        rules.box.addWidget(self.missing_buff)
        rules.box.addWidget(label('These examples exercise the display. They do not replace your existing character profiles or reminder rules. Cooldown ready does not establish castability.'))
        self.refresh_simulation()

    def build_settings(self, layout):
        self.dirty_button = self.button('No unsaved settings', self.save_session)
        layout.addWidget(self.dirty_button, 0, Qt.AlignmentFlag.AlignLeft)
        workspace = Panel(self, 'Workspace')
        layout.addWidget(workspace)
        workspace.box.addWidget(label('This separate preview contains Overview and Settings. Your other tabs and all their data stay in the existing tool.'))
        self.visible = QCheckBox('Show Overview tab')
        self.visible.toggled.connect(lambda value: self.change('overview_visible', value))
        workspace.box.addWidget(self.visible)
        appearance = Panel(self, 'Appearance')
        layout.addWidget(appearance)
        self.category = self.combo(['General', 'Places', 'Classes', 'Races'], self.choose_category)
        self.theme = self.combo(list(THEMES), lambda value: self.change('theme', value) if value else None)
        self.skin = self.combo(['WoW', 'Standard'], lambda value: self.change('ui_style', value))
        appearance.box.addWidget(row(field('Theme category', self.category), field('Theme', self.theme), field('Interface style', self.skin)))
        self.font_choice = self.combo(FONT_CHOICES, lambda value: self.change('font_family', value))
        self.text_size = self.combo([str(i) for i in range(9, 19)], lambda value: self.change('text_size', int(value)))
        appearance.box.addWidget(row(field('Font style', self.font_choice), field('Text size · points', self.text_size)))
        self.show_art = QCheckBox('Show theme artwork')
        self.show_art.toggled.connect(lambda value: self.change('show_artwork', value))
        self.art_mode = self.combo(['Full background', 'Header'], lambda value: self.change('artwork_mode', value))
        appearance.box.addWidget(row(self.show_art, self.art_mode))
        self.art_status = label('')
        appearance.box.addWidget(self.art_status)
        self.opacity = self.slider(0, 60, 20, lambda value: self.change('panel_transparency', value))
        self.opacity.setObjectName('transparencySlider')
        self.percent = QLabel('20%')
        self.percent.setMinimumWidth(60)
        appearance.box.addWidget(label('Panel transparency · 0% solid, 60% most artwork'))
        appearance.box.addWidget(row(self.opacity, self.percent))
        appearance.box.addWidget(label('The background stays anchored to the window as the page scrolls. Text draws directly on the translucent panels; input fields keep a solid surface for readability.'))
        saving = Panel(self, 'Session settings')
        layout.addWidget(saving)
        saving.box.addWidget(label('Save keeps this preview’s appearance in memory until you close it. Nothing is written to your personal settings, profiles, inventory or other files. Revert returns to this session’s saved appearance.'))
        saving.box.addWidget(row(self.button('Save for this session', self.save_session),
                                self.button('Revert unsaved settings', self.revert),
                                self.button('Restore defaults', self.defaults)))
        self.session_status = label('No files will be saved.')
        saving.box.addWidget(self.session_status)

    @staticmethod
    def category_for(theme):
        if theme.startswith('Class ·'): return 'Classes'
        if theme.startswith('Race ·'): return 'Races'
        return 'Places' if theme in THEME_ART else 'General'

    def choose_category(self, category):
        names = [name for name in THEMES if self.category_for(name) == category]
        self.theme.blockSignals(True)
        self.theme.clear()
        self.theme.addItems(names)
        self.theme.blockSignals(False)
        if names:
            self.theme.setCurrentText(names[0])
            self.change('theme', names[0])

    def sync_controls(self):
        settings = self.settings
        if hasattr(self,'category'):
            self.category.blockSignals(True)
            self.category.setCurrentText(self.category_for(settings['theme']))
            self.category.blockSignals(False)
        self.theme.blockSignals(True)
        self.theme.clear()
        self.theme.addItems(self.theme_choices() if hasattr(self,'theme_choices') else [name for name in THEMES if self.category_for(name) == self.category_for(settings['theme'])])
        self.theme.blockSignals(False)
        if hasattr(self,'skin'):
            self.skin.blockSignals(True);self.skin.setCurrentText(settings['ui_style']);self.skin.blockSignals(False)
        for widget, key in ((self.theme,'theme'), (self.font_choice,'font_family'),
                            (self.text_size,'text_size'), (self.art_mode,'artwork_mode')):
            widget.blockSignals(True)
            widget.setCurrentText(str(settings[key]))
            widget.blockSignals(False)
        for widget, key in ((self.visible,'overview_visible'), (self.show_art,'show_artwork')):
            widget.blockSignals(True)
            widget.setChecked(settings[key])
            widget.blockSignals(False)
        self.opacity.blockSignals(True)
        self.opacity.setValue(settings['panel_transparency'])
        self.opacity.blockSignals(False)
        self.refresh_settings_status()

    def change(self, key, value):
        if self.settings[key] == value:
            return
        self.settings[key] = value
        if key == 'panel_transparency':
            for panel in self.panels:
                panel.update()
        elif key in ('show_artwork', 'artwork_mode'):
            self.update()
        elif key == 'overview_visible':
            self.overview_button.setVisible(value)
            if not value:
                self.pages.setCurrentIndex(1)
        else:
            self.apply_appearance()
        self.refresh_settings_status()

    def refresh_settings_status(self):
        self.percent.setText(f"{self.settings['panel_transparency']}%")
        self.dirty_button.setText('Unsaved settings · click to save for this session' if self.settings != self.saved else 'No unsaved settings')
        self.art_status.setText('Local theme artwork available.' if not self.art.isNull() else 'This theme uses colours only; artwork is unavailable or not assigned.')

    def save_session(self):
        self.saved = deepcopy(self.settings)
        self.session_status.setText('Appearance saved for this session only. Simulation edits are unchanged.')
        self.refresh_settings_status()

    def revert(self):
        self.settings = deepcopy(self.saved)
        self.apply_appearance()
        self.sync_controls()

    def defaults(self):
        self.settings = deepcopy(DEFAULT)
        self.apply_appearance()
        self.sync_controls()

    def apply_appearance(self):
        self.colors = THEMES[self.settings['theme']]
        if self.settings.get('background'):
            self.colors = (self.settings['background'], *self.colors[1:])
        self.style_engine.wow = self.wow
        bg, panel, surface, ink, muted, accent = self.colors
        family = getattr(self, 'appearance_font_family', self.settings['font_family'])
        font = QFont(family, self.settings['text_size'])
        self.setFont(font)
        palette = QPalette()
        for role, color in ((QPalette.ColorRole.Window,bg), (QPalette.ColorRole.WindowText,ink),
                            (QPalette.ColorRole.Base,surface), (QPalette.ColorRole.Text,ink),
                            (QPalette.ColorRole.Button,panel), (QPalette.ColorRole.ButtonText,'#ffdd70' if self.wow else ink),
                            (QPalette.ColorRole.Highlight,accent), (QPalette.ColorRole.HighlightedText,bg)):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.style_updates += 1
        # Native Windows themes may ignore Button palette colours. When texture
        # assets are unavailable, explicitly paint both sides of the contrast pair.
        button_style = '' if self.wow and self.textures.ready else f'''
            QPushButton {{ background: {panel}; border: 1px solid {muted}; border-radius: 3px; }}
            QPushButton:hover {{ background: {surface}; border-color: {accent}; }}
            QPushButton:pressed, QPushButton:checked {{ background: {bg}; border-color: {accent}; }}
            QPushButton:focus {{ border: 2px solid {accent}; }}
            QPushButton:disabled {{ background: {panel}; color: {muted}; border-color: {muted}; }}
        '''
        if self.original_theme:
            top,bottom=('#762f29','#361615') if self.settings['theme']=='Classic Fantasy' else (panel,surface)
            button_style += f'''
                QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {top},stop:1 {bottom}); border: 1px solid {accent}; border-radius: 2px; }}
                QPushButton:hover {{ background: {surface}; border: 2px solid {accent}; }}
                QPushButton:pressed, QPushButton:checked {{ background: {bg}; border: 2px solid {accent}; }}
                QPushButton:disabled {{ background: {panel}; color: {muted}; border-color: {muted}; }}
            '''
        # Style changes happen only for theme/font/skin changes, never slider ticks.
        self.setStyleSheet(f'''
            QWidget {{ font-family: "{family}"; font-size: {self.settings['text_size']}pt; }}
            QDialog, QMessageBox {{ background-color: {panel}; color: {ink}; }}
            QMessageBox QLabel {{ background-color: {panel}; color: {ink}; }}
            QScrollArea, QStackedWidget {{ background: transparent; border: none; }}
            QLabel, QCheckBox {{ background: transparent; color: {ink}; }}
            QCheckBox {{ spacing: 8px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; }}
            QCheckBox::indicator:unchecked {{ background-color: {surface}; border: 2px solid {muted}; border-radius: 2px; }}
            QCheckBox::indicator:unchecked:hover {{ border-color: {accent}; }}
            QCheckBox::indicator:unchecked:disabled {{ border: 1px solid {muted}; }}
            QPushButton {{ padding: 9px 16px; color: {'#ffdd70' if self.wow else ink}; }}
            {button_style}
            QComboBox, QSpinBox {{ padding: 5px 9px; background: {surface}; color: {ink};
                border: 1px solid {accent if self.wow else muted}; border-radius: 3px; }}
            QComboBox QAbstractItemView {{ background: {surface}; color: {ink}; }}
            QLineEdit, QPlainTextEdit, QListWidget, QTableWidget {{ background: {surface}; color: {ink}; border: 1px solid {muted}; selection-background-color: {accent}; selection-color: {bg}; }}
            QLineEdit {{ padding: 5px 8px; }}
            QHeaderView::section {{ background: {panel}; color: {ink}; padding: 6px; border: 1px solid {muted}; }}
            QProgressBar {{ border: 1px solid {muted}; background: {surface}; text-align: center; color: {ink}; }}
            QProgressBar::chunk {{ background: {accent}; }}
            QScrollBar:vertical {{ background: {surface}; width: 17px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {accent}; border: 2px solid {panel}; min-height: 32px; border-radius: 5px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        ''')
        art_key = self.settings.get('image') or THEME_ART.get(self.settings['theme'])
        if art_key != self.art_key:
            self.art_key = art_key
            self.art = QPixmap(str(ART_DIRECTORY / art_key)) if art_key else QPixmap()
            self.art_loads += 1
        self.overview_button.setVisible(self.settings['overview_visible'])
        for title in self.findChildren(Title):
            title.updateGeometry()
        for panel in self.panels:
            panel.update()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.colors[0]))
        if self.original_theme and self.settings['show_artwork']:
            # Original geometric ornament; clipped for the Header preference.
            painter.save()
            if self.settings['artwork_mode']=='Header': painter.setClipRect(0,0,self.width(),145)
            line=QColor(self.colors[5]);line.setAlpha(18)
            painter.setPen(QPen(line,1))
            for x in range(-self.height(),self.width(),80):
                painter.drawLine(x,0,x+self.height(),self.height())
                painter.drawLine(x+self.height(),0,x,self.height())
            painter.restore()
        if self.settings['show_artwork'] and not self.art.isNull():
            rect = self.rect() if self.settings['artwork_mode'] == 'Full background' else QRect(0, 0, self.width(), 145)
            scale = max(rect.width() / self.art.width(), rect.height() / self.art.height())
            width, height = rect.width() / scale, rect.height() / scale
            source = QRect(round((self.art.width()-width)/2), round((self.art.height()-height)/2), round(width), round(height))
            painter.drawPixmap(rect, self.art, source)
            # A single gentle veil keeps unframed text readable without label boxes.
            painter.fillRect(rect, QColor(0, 0, 0, 85))
        painter.end()

    def refresh_simulation(self, *_):
        if not hasattr(self, 'missing_buff'):
            return
        values = (self.hp.value(), self.party.value())
        for bar, readout, value in zip(self.hp_bars, self.hp_values, values):
            bar.setValue(value)
            readout.setText(f'{value}%')
        self.buff_text.setText('Tracked buff: ' + ('Present' if self.buff.isChecked() else 'Missing'))
        self.cooldown_text.setText(f'Tracked ability: {self.cooldown.value()} seconds remaining' if self.cooldown.value() else 'Tracked ability: Ready · castability unknown')
        if min(values) < self.threshold.value():
            who = 'Your HP' if values[0] <= values[1] else 'Party HP'
            message = f'{who} is low. Consider your configured heal, defensive or consumable.'
        elif not self.buff.isChecked() and self.missing_buff.isChecked():
            message = 'Tracked buff is missing. Consider refreshing it.'
        else:
            message = 'No reminder right now.'
        self.reminder.setText(message)

    def toggle_demo(self):
        if self.timer.isActive():
            self.timer.stop()
            self.demo_button.setText('Play demo')
        else:
            self.timer.start()
            self.demo_button.setText('Pause demo')

    def demo_tick(self):
        self.simulation_time += .1
        t = self.simulation_time
        self.hp.setValue(round(60 + 39 * math.cos(t / 3)))
        self.party.setValue(round(55 + 40 * math.cos(t / 4 + 1)))
        self.cooldown.setValue(max(0, 15 - int(t) % 20))
        self.buff.setChecked(int(t) % 18 < 13)

    def reset_demo(self):
        self.timer.stop()
        self.demo_button.setText('Play demo')
        self.simulation_time = 0
        self.hp.setValue(100)
        self.party.setValue(82)
        self.cooldown.setValue(15)
        self.buff.setChecked(True)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


def main():
    application = QApplication(sys.argv)
    preview = Preview()
    preview.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
