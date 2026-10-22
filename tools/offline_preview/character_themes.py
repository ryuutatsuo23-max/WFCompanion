"""Desktop palettes, independent of character data or playable combinations.

Roster: Blizzard's Create the Hero You Want to Be (news/24304075), checked
2026-10-20. Colours are our design, not game data. Backdrops are sourced per class/race.
Artwork files are optional local Blizzard wallpapers; see THEME_ARTWORK.md.
"""

CLASS_PRESETS = {
    "Druid": ("#ffae68", "class-druid.png"),
    "Hunter": ("#b2d98b", "class-hunter.png"),
    "Mage": ("#83d9ef", "class-mage.png"),
    "Paladin": ("#f4a9cd", "class-paladin.png"),
    "Priest": ("#f2eee3", "class-priest.png"),
    "Rogue": ("#f4df7b", "class-rogue.png"),
    "Shaman": ("#82b3ff", "class-shaman.png"),
    "Warlock": ("#c6a0f0", "class-warlock.png"),
    "Warrior": ("#d8b28b", "class-warrior.png"),
}
RACE_PRESETS = {
    "Human": ("#91baff", "race-human.png"),
    "Dwarf": ("#e3ad70", "race-dwarf.png"),
    "Gnome": ("#edacf0", "race-gnome.png"),
    "Night Elf": ("#c2a2f2", "race-night-elf.png"),
    "Orc": ("#b6cd79", "race-orc.png"),
    "Tauren": ("#dcb581", "race-tauren.png"),
    "Troll": ("#82d6c4", "race-troll.png"),
    "Undead": ("#b3c48e", "race-undead.png"),
    "Skyborne High Order": ("#aeb9ff", "race-skyborne.png"),
    "Skyborne Windshaper": ("#8de0dc", "race-skyborne.png"),
}


def palette(accent):
    """Tint dark surfaces without sacrificing light-text contrast."""
    rgb = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
    def surface(amount):
        return "#" + "".join(f"{round(base + channel * amount):02x}"
                            for base, channel in zip((9, 10, 14), rgb))
    return (surface(.08), surface(.17), surface(.11), "#f2f2f5", "#bec5d3", accent)


CHARACTER_THEMES = {}
CHARACTER_ART = {}
for category, presets in (("Class", CLASS_PRESETS), ("Race", RACE_PRESETS)):
    for name, (accent, artwork) in presets.items():
        label = f"{category} · {name}"
        CHARACTER_THEMES[label] = palette(accent)
        CHARACTER_ART[label] = artwork
