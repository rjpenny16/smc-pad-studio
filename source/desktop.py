"""Desktop window helpers: a window size that fits the screen, and the tray tooltip."""

import ctypes as C
from ctypes import wintypes as W
import logging

DEFAULT_SIZE = (1440, 960)
MIN_SIZE = (800, 650)


def fit_window(saved, area):
    """(width, height, maximized) in logical pixels for opening the window.

    Uses the remembered size when there is one, never larger than the work area
    (a 1440x960 window does not fit a 1366x768 laptop, or 1920x1080 at 150%), and
    opens maximized when even the minimum size does not fit."""
    width, height = DEFAULT_SIZE
    maximized = False
    if isinstance(saved, dict):
        width, height = saved.get('width', width), saved.get('height', height)
        maximized = bool(saved.get('maximized', False))
    if area:
        if area[0] < MIN_SIZE[0] or area[1] < MIN_SIZE[1]:
            return MIN_SIZE[0], MIN_SIZE[1], True
        # Leave a margin so the title bar and edges stay on screen.
        width, height = min(width, int(area[0] * 0.94)), min(height, int(area[1] * 0.94))
    return max(MIN_SIZE[0], int(width)), max(MIN_SIZE[1], int(height)), maximized


def work_area():
    """The primary monitor's work area (screen minus taskbar) in logical pixels, or None."""
    try:
        user = C.WinDLL('user32')
        rect = W.RECT()
        if not user.SystemParametersInfoW(0x0030, 0, C.byref(rect), 0):  # SPI_GETWORKAREA
            return None
        try:
            # Physical pixels for a DPI-aware process; GetDpiForSystem is 96 when it is not.
            scale = user.GetDpiForSystem() / 96 or 1
        except AttributeError:
            scale = 1
        return round((rect.right - rect.left) / scale), round((rect.bottom - rect.top) / scale)
    except Exception:
        logging.exception('Could not read the screen work area')
        return None


class SHFILEOPSTRUCTW(C.Structure):
    _fields_ = [
        ('hwnd', W.HWND),
        ('wFunc', W.UINT),
        ('pFrom', W.LPCWSTR),
        ('pTo', W.LPCWSTR),
        ('fFlags', W.WORD),
        ('fAnyOperationsAborted', W.BOOL),
        ('hNameMappings', C.c_void_p),
        ('lpszProgressTitle', W.LPCWSTR),
    ]


def recycle(path):
    """Move a file to the Recycle Bin, where it can be restored. Never a permanent delete."""
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    # pFrom is a list of paths ending with an extra null character.
    operation = SHFILEOPSTRUCTW(
        None, FO_DELETE, str(path) + '\0', None, FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    )
    result = C.WinDLL('shell32').SHFileOperationW(C.byref(operation))
    if result or operation.fAnyOperationsAborted:
        raise RuntimeError(f'Windows could not move the clip to the Recycle Bin (code {result})')


def tray_text(connection_state, paused):
    """Tooltip for the tray icon; Windows limits it to 63 characters."""
    if paused:
        status = 'mappings paused'
    else:
        status = {'connected': 'connected', 'error': 'connection needs attention'}.get(
            connection_state, 'not connected'
        )
    return ('SMC-PAD Studio: ' + status)[:63]
