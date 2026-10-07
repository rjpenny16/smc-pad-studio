import ctypes as C
from ctypes import wintypes as W
import os
import webbrowser

user = C.WinDLL('user32', use_last_error=True)
user.VkKeyScanW.argtypes = [W.WCHAR]
user.VkKeyScanW.restype = C.c_short
ULONG_PTR = C.c_size_t


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]


class MOUSEINPUT(C.Structure):
    _fields_ = [
        ('dx', W.LONG),
        ('dy', W.LONG),
        ('mouseData', W.DWORD),
        ('dwFlags', W.DWORD),
        ('time', W.DWORD),
        ('dwExtraInfo', ULONG_PTR),
    ]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', W.DWORD), ('wParamL', W.WORD), ('wParamH', W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', W.DWORD), ('u', INPUTUNION)]


user.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
user.SendInput.restype = W.UINT


def send(inputs):
    array = (INPUT * len(inputs))(*inputs)
    if user.SendInput(len(array), array, C.sizeof(INPUT)) != len(array):
        # Release modifiers even when Windows accepts only part of a sequence.
        releases = (INPUT * 4)(*(INPUT(type=1, ki=KEYBDINPUT(k, 0, 2, 0, 0)) for k in [16, 17, 18, 91]))
        user.SendInput(4, releases, C.sizeof(INPUT))
        raise RuntimeError('Windows blocked input. Check the target application permissions.')


KEYS = {
    'ctrl': 17,
    'control': 17,
    'alt': 18,
    'shift': 16,
    'win': 91,
    'windows': 91,
    'enter': 13,
    'return': 13,
    'tab': 9,
    'space': 32,
    'esc': 27,
    'escape': 27,
    'backspace': 8,
    'delete': 46,
    'del': 46,
    'insert': 45,
    'home': 36,
    'end': 35,
    'pageup': 33,
    'pagedown': 34,
    'up': 38,
    'down': 40,
    'left': 37,
    'right': 39,
    'plus': 187,
    'minus': 189,
}
KEYS.update({f'f{i}': 111 + i for i in range(1, 25)})


def key_input(vk, up=False, scan=0, unicode=False):
    return INPUT(
        type=1,
        ki=KEYBDINPUT(
            vk,
            scan,
            (2 if up else 0) | (4 if unicode else (1 if vk in [33, 34, 35, 36, 37, 38, 39, 40, 45, 46, 91, 92] else 0)),
            0,
            0,
        ),
    )


def shortcut(value):
    codes = []
    for part in value.lower().split('+'):
        part = part.strip()
        if part in KEYS:
            codes.append(KEYS[part])
        elif len(part) == 1:
            code = user.VkKeyScanW(part)
            if code == -1:
                raise ValueError('Unsupported shortcut key: ' + part)
            for mask, vk in [(1, 16), (2, 17), (4, 18)]:
                if (code >> 8) & mask and vk not in codes:
                    codes.append(vk)
            codes.append(code & 255)
        else:
            raise ValueError('Unknown shortcut key: ' + part)
    send([key_input(k) for k in codes] + [key_input(k, True) for k in reversed(codes)])


def type_text(value):
    raw = value.encode('utf-16-le')
    for i in range(0, len(raw), 2):
        code = int.from_bytes(raw[i : i + 2], 'little')
        send([key_input(0, scan=code, unicode=True), key_input(0, True, code, True)])


SHORTCUTS = {
    'showDesktop': 'win+d',
    'taskView': 'win+tab',
    'snapLeft': 'win+left',
    'snapRight': 'win+right',
    'maximize': 'win+up',
    'minimize': 'win+down',
    'closeWindow': 'alt+f4',
    'screenshot': 'win+shift+s',
    'refresh': 'f5',
    'zoomIn': 'ctrl+plus',
    'zoomOut': 'ctrl+minus',
    'nextTab': 'ctrl+tab',
    'previousTab': 'ctrl+shift+tab',
    'nextWindow': 'alt+tab',
    'previousWindow': 'alt+shift+tab',
    'desktopRight': 'win+ctrl+right',
    'desktopLeft': 'win+ctrl+left',
}
MEDIA = {
    'volumeUp': 175,
    'volumeDown': 174,
    'volumeMute': 173,
    'mediaPlayPause': 179,
    'mediaNext': 176,
    'mediaPrevious': 177,
    'mediaStop': 178,
    'browserBack': 166,
    'browserForward': 167,
}


def action(req):
    kind = req.get('type', 'none')
    value = str(req.get('value', ''))
    amount = max(1, min(6, int(req.get('amount', 1))))
    if kind == 'none':
        return
    if kind in ('playAudio', 'stopAudio'):
        raise ValueError('Audio is handled by the audio queue')
    if kind == 'launch':
        return os.startfile(value)
    if kind == 'url':
        return webbrowser.open(value)
    if kind == 'typeText':
        return type_text(value)
    if kind == 'lockPC':
        if not user.LockWorkStation():
            raise C.WinError()
        return
    for _ in range(amount):
        if kind == 'shortcut':
            shortcut(value)
        elif kind in SHORTCUTS:
            shortcut(SHORTCUTS[kind])
        elif kind in MEDIA:
            k = MEDIA[kind]
            send([key_input(k), key_input(k, True)])
        elif kind in ['scrollUp', 'scrollDown', 'scrollLeft', 'scrollRight']:
            delta = 120 if kind in ['scrollUp', 'scrollRight'] else -120
            flag = 0x1000 if kind in ['scrollLeft', 'scrollRight'] else 0x800
            send([INPUT(type=0, mi=MOUSEINPUT(0, 0, delta & 0xFFFFFFFF, flag, 0, 0))])
        else:
            raise ValueError('Unknown action: ' + kind)
