"""Compatibility import for the canonical source addon installer.

Frozen bundles collect tools/distribution/install_addons.py directly as
install_addons.py. Source imports through either entry share one lock registry.
"""
from tools.distribution import install_addons as _engine


def __getattr__(name):
    return getattr(_engine, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_engine)))


__all__ = [name for name in dir(_engine) if not name.startswith('_')]


def install(payload, client, selected, backup_root, *, check_game=True):
    # Preserve this historical source entry's default. The canonical GUI/launcher
    # route retains its own default; neither path creates another lock registry.
    return _engine.install(payload, client, selected, backup_root, check_game=check_game)
