"""Optional launch at Windows sign-in through the per-user Run registry key."""

import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE = 'SMC-PAD Studio'


def command():
    """What Windows runs at sign-in, or None when Studio runs from source rather than the EXE."""
    if not getattr(sys, 'frozen', False):
        return None
    return f'"{sys.executable}" --background'


def _registered(key):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            return winreg.QueryValueEx(handle, VALUE)[0]
    except FileNotFoundError:
        return None


def enabled(key=RUN_KEY):
    return _registered(key) is not None


def set_enabled(on, key=RUN_KEY, value=None):
    import winreg

    if on:
        value = value or command()
        if not value:
            raise RuntimeError('Start with Windows works in the packaged SMC-PAD Studio EXE')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, VALUE, 0, winreg.REG_SZ, value)
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.DeleteValue(handle, VALUE)
    except FileNotFoundError:
        pass


def refresh(key=RUN_KEY):
    """Point an existing entry at this EXE. Release file names include the version, so
    the entry would otherwise keep starting an old download."""
    current = command()
    if current and _registered(key) not in (None, current):
        set_enabled(True, key, current)
