"""Shared presentation settings schema; no UI is constructed here."""
import re
from appearance_catalogue import FONT_CHOICES, THEMES

DEFAULT = dict(version=5, font_family="Segoe UI", ui_style="WoW", panel_transparency=20, show_artwork=True, artwork_mode="Full background", setup=False, hidden=[], order=[], theme="Dark", background="", image="",
               sound=False, volume=50, text_size=10, support={})


def validate_preferences(data):
    if (not isinstance(data, dict) or data.get("version") not in (1, 2, 3, 4, 5)
            or set(data) != (set(DEFAULT) - ({"show_artwork", "artwork_mode"} if data["version"] < 3 else set())
                             - ({"order"} if data["version"] == 1 else set())
                             - ({"panel_transparency"} if data["version"] < 4 else set())
                             - ({"font_family", "ui_style"} if data["version"] < 5 else set()))):
        raise ValueError("Unsupported display preferences.")
    if type(data.get("show_artwork", True)) is not bool or data.get("artwork_mode", "Header") not in ("Header", "Full background"):
        raise ValueError("Invalid artwork display option.")
    if type(data.get("panel_transparency", 0)) is not int or not 0 <= data.get("panel_transparency", 0) <= 60:
        raise ValueError("Panel transparency must be a whole percentage from 0 to 60.")
    if data.get("font_family", "Segoe UI") not in FONT_CHOICES or data.get("ui_style", "WoW") not in ("Standard", "WoW"):
        raise ValueError("Invalid font or interface style.")
    order = data.get("order", [])
    if (not isinstance(order, list) or any(not isinstance(x, str) or len(x) > 100 for x in order)
            or len(order) != len(set(order)) or len(order) > 100):
        raise ValueError("Invalid tab order.")
    if type(data["setup"]) is not bool or type(data["sound"]) is not bool:
        raise ValueError("Invalid display toggle.")
    if data["theme"] not in THEMES or type(data["text_size"]) is not int or not 9 <= data["text_size"] <= 18:
        raise ValueError("Invalid theme or text size.")
    if type(data["volume"]) is not int or not 0 <= data["volume"] <= 100:
        raise ValueError("Volume must be 0–100.")
    if not isinstance(data["hidden"], list) or any(not isinstance(x, str) for x in data["hidden"]):
        raise ValueError("Invalid hidden tabs.")
    if not isinstance(data["background"], str) or (data["background"] and not re.fullmatch(r"#[0-9a-fA-F]{6}", data["background"])):
        raise ValueError("Use a background colour #RRGGBB.")
    if not isinstance(data["image"], str) or len(data["image"]) > 2000:
        raise ValueError("Invalid image path.")
    if not isinstance(data["support"], dict) or len(data["support"]) > 100:
        raise ValueError("Invalid support plans.")
    for plan in data["support"].values():
        if not isinstance(plan, dict) or set(plan) != {"kind", "key", "note"}:
            raise ValueError("Invalid support plan.")
        if any(not isinstance(v, str) or len(v) > 500 for v in plan.values()):
            raise ValueError("Support labels must be short text.")
