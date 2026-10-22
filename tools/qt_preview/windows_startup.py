"""Opt-in per-user Windows sign-in launch; never enabled by installation."""
from pathlib import Path
import sys
from PySide6.QtWidgets import QCheckBox

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'WFCompanion'


def available():
    return sys.platform == 'win32' and bool(getattr(sys, 'frozen', False)) and Path(sys.executable).name.lower() == 'wfcompanion.exe'


def enabled():
    if not available(): return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, kind = winreg.QueryValueEx(key, NAME)
        return kind == winreg.REG_SZ and value == '"' + str(Path(sys.executable).resolve()) + '"'
    except FileNotFoundError: return False


def set_enabled(value):
    if not available():
        if value: raise OSError('Available in the installed Windows companion.')
        return
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        if value: winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, '"' + str(Path(sys.executable).resolve()) + '"')
        else:
            try: winreg.DeleteValue(key, NAME)
            except FileNotFoundError: pass


def checkbox():
    check = QCheckBox('Start WF Companion when I sign in to Windows')
    check.setEnabled(available())
    try: check.setChecked(enabled())
    except OSError: check.setToolTip('Windows startup settings could not be read.')
    if not available(): check.setToolTip('Available in the installed Windows companion. Off by default.')
    return check
