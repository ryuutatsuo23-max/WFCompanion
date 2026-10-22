"""Read-only appearance catalogue shared by the Tk and Qt previews."""

from pathlib import Path
from character_themes import CHARACTER_THEMES, CHARACTER_ART

FONT_CHOICES = ("Segoe UI", "Arial", "Calibri", "Georgia", "Times New Roman", "Verdana")

THEMES = {
    "Stormwind · Alliance": ("#101c32", "#1b3151", "#14263e", "#f6edd6", "#bdcce0", "#edc66d"),
    "Orgrimmar · Horde": ("#271713", "#40221c", "#2f1b16", "#fff0d7", "#dcc1ac", "#ed997b"),
    "Dark": ("#101722", "#1b2635", "#111c2a", "#edf3fa", "#a8b8cb", "#75ddcb"),
    "Normal": ("#eef1f5", "#ffffff", "#ffffff", "#172334", "#46566b", "#277a70"),
    "Azeroth blue": ("#101e30", "#20364b", "#14283d", "#f3e7c4", "#b8cbdc", "#e8c579"),
    "Forest": ("#12231e", "#203a30", "#142d24", "#edf5e6", "#b4ccbd", "#91dba7"),
    "Forever · Ashenvale": ("#191624", "#292438", "#211c30", "#f3ebfa", "#c8b8d6", "#bfacd9"),
    "Forever · Darkshore": ("#111d24", "#20333e", "#162831", "#eaf3f5", "#afc5cd", "#8bc7d1"),
    "Forever · Barrens": ("#261b14", "#3a2a1d", "#2d2017", "#fff0d5", "#d8bea1", "#e7b56e"),
}
THEME_ART = {"Stormwind · Alliance": "stormwind.png", "Orgrimmar · Horde": "orgrimmar.png",
             "Forever · Ashenvale": "ashenvale.png", "Forever · Darkshore": "darkshore.png",
             "Forever · Barrens": "barrens.png"}
THEMES.update(CHARACTER_THEMES)
THEME_ART.update(CHARACTER_ART)
ART_DIRECTORY = Path(__file__).resolve().parent / "theme_art"
