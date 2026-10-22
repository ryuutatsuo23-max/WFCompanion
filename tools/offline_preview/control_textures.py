"""Local Blizzard control textures with reversible native layouts and bindings."""
from copy import deepcopy
import tkinter as tk

class ControlTextures:
    names = ('TEntry', 'TCombobox', 'TSpinbox', 'Vertical.TScrollbar',
             'Horizontal.TScrollbar', 'Horizontal.TScale', 'TCheckbutton',
             'Treeview', 'Treeview.Heading', 'TNotebook.Tab')

    def __init__(self, style, textures):
        self.style = style
        self.original = {name: deepcopy(style.layout(name)) for name in self.names}
        self.padding = {name: style.lookup(name, 'padding') for name in self.names}
        self.layouts = {}
        try:
            ring = tk.PhotoImage(master=style.master, width=256, height=256)
            textures.draw_border(ring, 256, 256)
            ring = ring.subsample(2)
            textures.images.append(ring)
            style.element_create('WoWInput', 'image', ring, border=8, width=0, height=0, sticky='nswe')
            up = textures.crop(textures.load('UI-ScrollBar-ScrollUpButton-Up.PNG'), 5, 5, 22, 22)
            down = textures.crop(textures.load('UI-ScrollBar-ScrollDownButton-Up.PNG'), 5, 5, 22, 22)
            knob = textures.crop(textures.load('UI-ScrollBar-Knob.PNG'), 4, 5, 23, 21)
            slider = textures.crop(textures.load('UI-SliderBar-Button-Horizontal.PNG'), 7, 4, 16, 23)
            check = textures.load('UI-CheckBox-Up.PNG')
            checked = tk.PhotoImage(master=style.master, width=32, height=32)
            checked.tk.call(str(checked), 'copy', str(check))
            checked.tk.call(str(checked), 'copy', str(textures.load('UI-CheckBox-Check.PNG')))
            textures.images.append(checked)
            elements = {'Combobox.downarrow': down, 'Spinbox.uparrow': up,
                        'Spinbox.downarrow': down, 'Vertical.Scrollbar.uparrow': up,
                        'Vertical.Scrollbar.downarrow': down,
                        'Vertical.Scrollbar.thumb': textures.expand(knob, 23, 256, (6, 8, 6, 8)),
                        'Horizontal.Scrollbar.thumb': textures.expand(knob, 256, 21, (8, 6, 8, 6)), 'Horizontal.Scale.slider': slider}
            # Transpose arrows for the horizontal scrollbar without external imaging dependencies.
            for original, source in (('Horizontal.Scrollbar.leftarrow', up), ('Horizontal.Scrollbar.rightarrow', down)):
                turned = tk.PhotoImage(master=style.master, width=source.height(), height=source.width())
                for x in range(source.width()):
                    for y in range(source.height()):
                        turned.tk.call(str(turned), 'copy', str(source), '-from', x, y, x+1, y+1, '-to', y, x)
                elements[original] = turned
            trough = textures.expand(textures.load('UI-SliderBar-Background.PNG'), 256, 12, (2, 2, 2, 2))
            style.element_create('WoW.Horizontal.Scale.trough', 'image', trough, border=2, width=0, height=12, sticky='we')
            mapping = {'Horizontal.Scale.trough': 'WoW.Horizontal.Scale.trough'}
            for name, image in elements.items():
                textures.images.append(image)
                target = 'WoW.' + name
                style.element_create(target, 'image', image, border=4 if name.endswith('thumb') else 0,
                                     width=23 if name.endswith('thumb') else image.width(),
                                     height=21 if name.endswith('thumb') else image.height(),
                                     sticky='nswe' if name.endswith('thumb') else '')
                mapping[name] = target
            style.element_create('WoW.Checkbutton.indicator', 'image', check, ('selected', checked), sticky='')
            mapping['Checkbutton.indicator'] = 'WoW.Checkbutton.indicator'
            mapping['Treeheading.border'] = 'WoWButton'
            mapping['Notebook.tab'] = 'WoWButton'
            def transform(layout):
                result = []
                for element, options in layout:
                    options = deepcopy(options)
                    if 'children' in options:
                        options['children'] = transform(options['children'])
                    if element in ('Entry.field', 'Combobox.field', 'Spinbox.field', 'Treeview.field'):
                        children = options.get('children', [])
                        options['children'] = [('WoWInput', {'sticky': 'nswe', 'children': children})]
                    result.append((mapping.get(element, element), options))
                return result
            self.layouts = {name: transform(layout) for name, layout in self.original.items()}
        except (OSError, tk.TclError):
            # Partial or absent optional assets never leave a half-applied skin.
            self.layouts = {}

    def apply(self, mode):
        wow = mode == 'WoW' and bool(self.layouts)
        for name in self.names:
            self.style.layout(name, self.layouts[name] if wow else self.original[name])
            if name in ('TEntry', 'TCombobox', 'TSpinbox', 'TNotebook.Tab', 'Treeview.Heading'):
                self.style.configure(name, padding=(8, 5) if wow else self.padding[name])
