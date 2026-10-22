"""Private application fonts: never registers fonts with Windows or the game."""
from pathlib import Path
from PySide6.QtGui import QFontDatabase
from app import ART_DIRECTORY

FILES={'Friz Quadrata TT':'FRIZQT__.ttf','Arial Narrow':'ARIALN.ttf','Morpheus':'MORPHEUS.ttf','Skurri':'SKURRI.ttf'}


class Fonts:
    def __init__(self):
        self.available={}
        for family,filename in FILES.items():
            path=ART_DIRECTORY/'wow_fonts'/filename
            if path.is_file():
                id=QFontDatabase.addApplicationFont(str(path))
                families=QFontDatabase.applicationFontFamilies(id)
                found=next((f for f in families if f.casefold()==family.casefold()),None)
                if found: self.available[family]=found
                elif id>=0: QFontDatabase.removeApplicationFont(id)

    def family(self,name,fallback): return self.available.get(name,fallback)

    def status(self):
        missing=[f for f in FILES if f not in self.available]
        return ('WoW role fonts: Friz Quadrata UI · Arial Narrow tables · Morpheus titles · Skurri HP. Loaded privately.' if not missing else
                'Unavailable fonts: '+', '.join(missing)+'. Your selected standard font is used as a fallback.')
