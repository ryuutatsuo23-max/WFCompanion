"""Shared item-label and count validation without storage/UI dependencies."""

from model import text


def count(value, label, minimum=0, maximum=1_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a whole number from {minimum} to {maximum}.")
    return value


def material_name(value):
    return " ".join(text(value, "Material name").split())


def material_key(value):
    return material_name(value).casefold()
