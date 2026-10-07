"""WinMM transport and serialized SMC-PAD configuration operations."""

import ctypes as C
from ctypes import wintypes as W
import queue
import threading
import time

UINT_PTR = C.c_size_t
# Substrings that identify SMC-PAD MIDI endpoints in Windows port names.
DEVICE_NAMES = ('smc', 'sinco')


class InCaps(C.Structure):
    _fields_ = [('mid', W.WORD), ('pid', W.WORD), ('version', W.DWORD), ('name', W.WCHAR * 32), ('support', W.DWORD)]


class OutCaps(C.Structure):
    _fields_ = [
        ('mid', W.WORD),
        ('pid', W.WORD),
        ('version', W.DWORD),
        ('name', W.WCHAR * 32),
        ('tech', W.WORD),
        ('voices', W.WORD),
        ('notes', W.WORD),
        ('mask', W.WORD),
        ('support', W.DWORD),
    ]


class MIDIHDR(C.Structure):
    _fields_ = [
        ('lpData', C.c_void_p),
        ('dwBufferLength', W.DWORD),
        ('dwBytesRecorded', W.DWORD),
        ('dwUser', UINT_PTR),
        ('dwFlags', W.DWORD),
        ('lpNext', C.c_void_p),
        ('reserved', UINT_PTR),
        ('dwOffset', W.DWORD),
        ('dwReserved', UINT_PTR * 8),
    ]


CALLBACK = C.WINFUNCTYPE(None, W.HANDLE, W.UINT, UINT_PTR, UINT_PTR, UINT_PTR)
mm = C.WinDLL('winmm')
mm.midiInOpen.argtypes = [C.POINTER(W.HANDLE), W.UINT, C.c_void_p, UINT_PTR, W.DWORD]
mm.midiOutOpen.argtypes = [C.POINTER(W.HANDLE), W.UINT, C.c_void_p, UINT_PTR, W.DWORD]
for name in [
    'midiInPrepareHeader',
    'midiInUnprepareHeader',
    'midiInAddBuffer',
    'midiOutPrepareHeader',
    'midiOutUnprepareHeader',
    'midiOutLongMsg',
]:
    getattr(mm, name).argtypes = [W.HANDLE, C.POINTER(MIDIHDR), W.UINT]
for name in ['midiInStart', 'midiInStop', 'midiInReset', 'midiInClose', 'midiOutReset', 'midiOutClose']:
    getattr(mm, name).argtypes = [W.HANDLE]
for name in ['midiInGetDevCapsW', 'midiOutGetDevCapsW']:
    getattr(mm, name).argtypes = [UINT_PTR, C.c_void_p, W.UINT]


def check(code):
    if code:
        buf = C.create_unicode_buffer(256)
        mm.midiInGetErrorTextW(code, buf, len(buf))
        raise RuntimeError(buf.value or f'Windows MIDI error {code}')


def ports():
    result = {'inputs': [], 'outputs': []}
    for direction, cls, key in [('In', InCaps, 'inputs'), ('Out', OutCaps, 'outputs')]:
        for i in range(getattr(mm, 'midi' + direction + 'GetNumDevs')()):
            caps = cls()
            check(getattr(mm, 'midi' + direction + 'GetDevCapsW')(i, C.byref(caps), C.sizeof(caps)))
            result[key].append({'id': i, 'name': caps.name, 'manufacturer': caps.mid, 'product': caps.pid})
    return result


class Transport:
    def __init__(self, event):
        self.event = event
        self.inputs = {}
        self.output = None
        self.output_id = None
        self.responses = queue.Queue(256)
        self.messages = queue.Queue(4096)
        self.dropped = 0
        self.closed = False
        self.callback = CALLBACK(self._callback)
        self.thread = threading.Thread(target=self._dispatch, name='MIDI events', daemon=True)
        self.thread.start()

    def _callback(self, handle, message, instance, param1, param2):
        try:
            if message == 0x3C3:  # MIM_DATA
                status = param1 & 255
                size = 2 if status & 0xF0 in (0xC0, 0xD0) else 3
                self.messages.put_nowait((int(instance), bytes((param1 >> (8 * i)) & 255 for i in range(size))))
            elif message == 0x3C4:  # MIM_LONGDATA
                hdr = C.cast(param1, C.POINTER(MIDIHDR)).contents
                if hdr.dwBytesRecorded:
                    self.responses.put_nowait((int(instance), C.string_at(hdr.lpData, hdr.dwBytesRecorded)))
                if not self.closed and int(instance) in self.inputs:
                    mm.midiInAddBuffer(handle, C.cast(param1, C.POINTER(MIDIHDR)), C.sizeof(MIDIHDR))
            elif message == 0x3C6:
                self.messages.put_nowait((int(instance), b''))
        except queue.Full:
            self.dropped += 1
        except Exception:
            pass  # callbacks must never propagate through the driver boundary

    def _dispatch(self):
        while not self.closed:
            try:
                port, data = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            entry = self.inputs.get(port)
            if entry:
                try:
                    self.event(entry['name'], list(data))
                except Exception:
                    __import__('logging').exception('MIDI event failed')

    def open_input(self, port):
        if port['id'] in self.inputs:
            return
        handle = W.HANDLE()
        check(mm.midiInOpen(C.byref(handle), port['id'], C.cast(self.callback, C.c_void_p), port['id'], 0x30000))
        buffers = []
        entry = {'handle': handle, 'name': port['name'], 'buffers': buffers}
        self.inputs[port['id']] = entry
        try:
            for _ in range(4):
                buf = C.create_string_buffer(65536)
                hdr = MIDIHDR(lpData=C.cast(buf, C.c_void_p), dwBufferLength=len(buf))
                check(mm.midiInPrepareHeader(handle, C.byref(hdr), C.sizeof(hdr)))
                buffers.append((buf, hdr))
                check(mm.midiInAddBuffer(handle, C.byref(hdr), C.sizeof(hdr)))
            check(mm.midiInStart(handle))
        except Exception:
            self.close_input(port['id'])
            raise

    def close_input(self, port_id):
        entry = self.inputs.pop(port_id, None)
        if not entry:
            return
        handle = entry['handle']
        mm.midiInStop(handle)
        mm.midiInReset(handle)
        for _buf, hdr in entry['buffers']:
            mm.midiInUnprepareHeader(handle, C.byref(hdr), C.sizeof(hdr))
        mm.midiInClose(handle)

    def open_output(self, port):
        if self.output_id == port['id']:
            return
        self.close_output()
        handle = W.HANDLE()
        check(mm.midiOutOpen(C.byref(handle), port['id'], None, 0, 0))
        self.output = handle
        self.output_id = port['id']

    def close_output(self):
        if self.output:
            mm.midiOutReset(self.output)
            mm.midiOutClose(self.output)
        self.output = None
        self.output_id = None

    def send(self, data):
        if self.output is None:
            raise RuntimeError('The controller is not connected')
        buf = C.create_string_buffer(bytes(data))
        hdr = MIDIHDR(lpData=C.cast(buf, C.c_void_p), dwBufferLength=len(data))
        check(mm.midiOutPrepareHeader(self.output, C.byref(hdr), C.sizeof(hdr)))
        try:
            check(mm.midiOutLongMsg(self.output, C.byref(hdr), C.sizeof(hdr)))
            deadline = time.monotonic() + 3
            while not hdr.dwFlags & 1:
                if time.monotonic() > deadline:
                    mm.midiOutReset(self.output)
                    raise TimeoutError('Windows MIDI output timed out')
                time.sleep(0.002)
        finally:
            mm.midiOutUnprepareHeader(self.output, C.byref(hdr), C.sizeof(hdr))

    def close(self):
        self.closed = True
        for port in list(self.inputs):
            self.close_input(port)
        self.close_output()
        self.thread.join(1)


def logical(cmd, data):
    data = bytes(data)
    return bytes([0, 0x59, cmd]) + len(data).to_bytes(3, 'little') + data + bytes([(~sum(data)) & 255])


def encode(cmd, data=b''):
    output = [0xF0]
    acc = bits = 0
    for value in logical(cmd, data):
        acc |= value << bits
        bits += 8
        while bits >= 7:
            output.append(acc & 127)
            acc >>= 7
            bits -= 7
    if bits:
        output.append(acc & 127)
    output.append(0xF7)
    return bytes(output)


def decode(message):
    if not message or message[0] != 0xF0 or message[-1] != 0xF7:
        raise ValueError('Incomplete SysEx reply')
    output = []
    acc = bits = 0
    for value in message[1:-1]:
        if value >= 128:
            raise ValueError('Invalid SysEx byte')
        acc |= value << bits
        bits += 7
        while bits >= 8:
            output.append(acc & 255)
            acc >>= 8
            bits -= 8
    raw = bytes(output)
    if len(raw) < 7 or raw[:2] != b'\0\x59':
        raise ValueError('Unexpected device reply')
    length = int.from_bytes(raw[3:6], 'little')
    data = raw[6:-1]
    if len(raw) != length + 7 or raw[-1] != (~sum(data)) & 255:
        raise ValueError('Reply length or checksum is invalid')
    return raw[2], data


# Device memory layout, from the decompiled MidiSuite structures: eight presets
# of 3539 bytes, each holding 128 pad records of 26 bytes from offset 211. A
# record is `?? ch note min max R G B FF ...`, so RGB starts 5 bytes in.
PRESET_SIZE = 3539
PAD_TABLE = 211
PAD_RECORD = 26
PAD_RGB = 5
# The physical PAD BANK button selects the dedicated final 16 records. Those
# records repeat notes 52-67, but are distinct from the octave group at index
# 48. Confirmed on hardware: writing group 48 changes memory only; writing
# group 112 changes all 16 LEDs with PAD BANK on.
BANKS = 'ABCDEFGH'
BANK_GROUP = {'A': 2, 'B': 7, 'C': 4, 'D': 5, 'E': 6, 'F': 7, 'G': 0, 'H': 1}
NOTE_GROUP = {'A': 2, 'B': 3, 'C': 4, 'D': 5, 'E': 6, 'F': 7, 'G': 0, 'H': 1}


def bank_for_note(note):
    """The bank whose default note range contains this pad note, if any."""
    group = (int(note) - 4) // 16
    return next((b for b, g in NOTE_GROUP.items() if g == group), None) if 4 <= int(note) <= 127 else None


def default_mapping(bank, cid):
    """The factory MIDI input of a pad in a bank: a note on channel 10 from the bank's
    16-note group (the same ranges bank_for_note recognises), or None."""
    if not cid.startswith('pad') or bank not in NOTE_GROUP:
        return None
    note = 4 + NOTE_GROUP[bank] * 16 + int(cid[3:]) - 1
    return {'kind': 'note', 'channel': 9, 'data1': note, 'port': ''} if note <= 127 else None


class RGB:
    def __init__(self, transport, event):
        self.transport = transport
        self.event = event
        self.lock = threading.RLock()
        self.port = None
        self.flash = None
        self.header = None
        self.ready = False
        self.cancel = threading.Event()
        self.last_activity = 0

    def active_preset(self):
        # Region 4, byte 10 is the zero-based preset selector. Captured on this
        # device: SHIFT+PAD1 reports 0, SHIFT+PAD3 reports 2. Byte 11 is PAD BANK.
        return (
            self.header[10]
            if self.port is not None and self.header is not None and len(self.header) == 12 and self.header[10] < 8
            else None
        )

    def active_bank(self):
        return (
            ('A', 'B')[self.header[11]]
            if self.port is not None and self.header is not None and len(self.header) == 12 and self.header[11] < 2
            else None
        )

    def request(self, cmd, data=b'', timeout=5, predicate=None):
        with self.lock:
            if self.port is None:
                raise RuntimeError('Connect the controller first')
            while True:
                try:
                    self.transport.responses.get_nowait()
                except queue.Empty:
                    break
            self.transport.send(encode(cmd, data))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.cancel.is_set():
                    raise RuntimeError('RGB operation cancelled')
                try:
                    port, message = self.transport.responses.get(timeout=0.05)
                except queue.Empty:
                    continue
                if port != self.port:
                    continue
                try:
                    reply, payload = decode(message)
                except ValueError:
                    continue
                if predicate and not predicate(reply, payload):
                    continue
                self.last_activity = time.monotonic()
                return reply, payload
            self.ready = False
            raise TimeoutError(
                'The controller did not answer. Close MidiSuite if it is open, then unplug and reconnect the controller.'
            )

    def read_region(self, region, address, length, timeout=5):
        request = bytes([region]) + address.to_bytes(4, 'little') + length.to_bytes(3, 'little')
        cmd, data = self.request(
            0x23, request, timeout, lambda cmd, data: cmd == 0x23 and data[:8] == request and len(data) == length + 8
        )
        return data[8:]

    def discover(self, available, input_id=None, output_id=None):
        with self.lock:
            self.cancel.clear()
            self.ready = False
            self.flash = None
            self.header = None
            ins = [p for p in available['inputs'] if any(x in p['name'].lower() for x in DEVICE_NAMES)]
            outs = [p for p in available['outputs'] if any(x in p['name'].lower() for x in DEVICE_NAMES)]
            if input_id is not None and output_id is not None:
                pairs = [
                    (
                        next(p for p in available['inputs'] if p['id'] == int(input_id)),
                        next(p for p in available['outputs'] if p['id'] == int(output_id)),
                    )
                ]
            else:
                pairs = [(i, o) for i in ins for o in outs if i['name'].replace('MIDIIN', 'MIDIOUT') == o['name']]
                pairs.sort(
                    key=lambda pair: (
                        'private' not in pair[0]['name'].lower(),
                        not pair[0]['name'].startswith('MIDIIN'),
                    )
                )
            errors = []
            for inp, out in pairs:
                opened = inp['id'] not in self.transport.inputs
                try:
                    self.event('rgb', {'state': 'discovering', 'message': 'Checking ' + inp['name']})
                    self.transport.open_input(inp)
                    self.transport.open_output(out)
                    self.port = inp['id']
                    self.request(0x11, timeout=1.5)
                    self.header = self.read_region(4, 0, 12, 1.5)
                    self.event('rgb', {'state': 'available', 'input': inp['name'], 'output': out['name']})
                    return
                except Exception as exc:
                    errors.append(inp['name'] + ': ' + str(exc))
                    self.port = None
                    if opened:
                        self.transport.close_input(inp['id'])
                    self.transport.close_output()
            raise RuntimeError('No configuration port replied. ' + ' | '.join(errors or ['No SMC-PAD port is present']))

    def unlock(self, report=True):
        """Open a configuration session and read the device memory. Background work
        (live pad feedback) passes report=False so the interface does not show a read."""
        with self.lock:
            if self.port is None:
                raise RuntimeError('Connect the controller first')
            self.request(0x11)
            self.header = self.read_region(4, 0, 12)
            flash = bytearray(28312)
            for address in range(0, len(flash), 1009):
                length = min(1009, len(flash) - address)
                flash[address : address + length] = self.read_region(5, address, length)
                if report:
                    self.event('rgb', {'state': 'reading', 'progress': round((address + length) * 100 / len(flash))})
            self.flash = flash
            self.ready = True

    def address(self, pad, preset, bank):
        if not self.ready or self.flash is None:
            raise RuntimeError('Read the pad colors from the controller first')
        preset = int(preset)
        pad = int(pad)
        if not 0 <= preset <= 7 or not 1 <= pad <= 16 or bank not in BANK_GROUP:
            raise ValueError('Invalid pad, preset or bank')
        table = preset * PRESET_SIZE + PAD_TABLE
        # Each pad's slot is fixed by the firmware structure, so a pad whose MIDI
        # note or channel was remapped can still be colored. Writes stay blocked
        # when the table does not look like pad records at all (unknown firmware).
        terminators = sum(self.flash[table + i * PAD_RECORD + 8] == 255 for i in range(128))
        if terminators < 112:
            raise RuntimeError(f'Preset {preset + 1} has an unrecognized pad layout; color writes are disabled.')
        record = table + (BANK_GROUP[bank] * 16 + pad - 1) * PAD_RECORD
        if self.flash[record + 8] != 255:
            raise RuntimeError(f'Pad {pad} in Bank {bank} has an unrecognized record; its color writes are disabled.')
        return record + PAD_RGB

    def read_colors(self, preset, bank):
        with self.lock:
            self.cancel.clear()
            self.unlock()
            colors = {}
            for pad in range(1, 17):
                address = self.address(pad, preset, bank)
                colors['pad' + str(pad)] = '#' + self.flash[address : address + 3].hex()
            self.event('rgb', {'state': 'synced', 'colors': colors, 'preset': preset, 'bank': bank})
            return colors

    def apply(self, colors, preset, bank, refresh=True, report=True, only_changed=False):
        """Write pad colors and check each against the device. With only_changed, pads
        that already show their color (in the memory just read by unlock) are reported
        as stored without a write."""
        with self.lock:
            self.cancel.clear()
            # The pad ignores writes once its session lapses, even though memory
            # readback can still match. Replay the full unlock immediately before
            # writing, exactly as the verified read-then-write sequence does.
            if refresh or not self.ready:
                self.unlock(report)
            # Validate all intended addresses and colors before the first hardware write.
            writes = []
            results = []
            for cid, color in colors.items():
                if not cid.startswith('pad'):
                    raise ValueError('Only pad colors can be applied')
                rgb = bytes.fromhex(color.removeprefix('#'))
                if len(rgb) != 3:
                    raise ValueError('Invalid RGB color')
                address = self.address(int(cid[3:]), preset, bank)
                if only_changed and self.flash[address : address + 3] == rgb:
                    results.append({'pad': cid, 'ok': True, 'color': '#' + rgb.hex()})
                else:
                    writes.append((cid, address, rgb))
            for cid, address, rgb in writes:
                if self.cancel.is_set():
                    break
                try:
                    data = b'\x05' + address.to_bytes(4, 'little') + b'\x03\0\0' + rgb
                    reply, ack = self.request(0x22, data, predicate=lambda cmd, data: cmd == 0 and len(data) >= 1)
                    if ack[0] != 0:
                        raise RuntimeError('Device rejected the RGB write (status ' + str(ack[0]) + ')')
                    # Readback is the authority even when firmware acknowledgements differ.
                    actual = self.read_region(5, address, 3)
                    if actual != rgb:
                        raise RuntimeError('Device color readback did not match')
                    self.flash[address : address + 3] = actual
                    results.append({'pad': cid, 'ok': True, 'color': '#' + actual.hex()})
                except Exception as exc:
                    results.append({'pad': cid, 'ok': False, 'error': str(exc)})
                    # A timed-out session must be re-established before another write.
                    if isinstance(exc, TimeoutError):
                        break
                if report:
                    self.event(
                        'rgb',
                        {
                            'state': 'writing',
                            'results': list(results),
                            'progress': round(len(results) * 100 / len(colors)),
                        },
                    )
            completed = {r['pad'] for r in results}
            for cid, _address, _rgb in writes:
                if cid not in completed:
                    results.append({'pad': cid, 'ok': False, 'error': 'Cancelled or session interrupted'})
            order = {cid: i for i, cid in enumerate(colors)}
            results.sort(key=lambda r: order[r['pad']])
            if report:
                self.event(
                    'rgb',
                    {
                        'state': 'synced' if all(r['ok'] for r in results) else 'partial',
                        'results': results,
                        'preset': preset,
                        'bank': bank,
                    },
                )
            return results

    def save(self):
        """Ask the device to persist its configuration, as MidiSuite's Save does
        (a zero-length region-5 write). Color writes alone may not survive a
        power cycle."""
        with self.lock:
            self.cancel.clear()
            if not self.ready:
                self.unlock()
            reply, ack = self.request(0x22, b'\x05' + bytes(7), predicate=lambda cmd, data: cmd == 0 and len(data) >= 1)
            if ack[0] != 0:
                raise RuntimeError('Device rejected the save (status ' + str(ack[0]) + ')')
            self.event('rgb', {'state': 'saved', 'message': 'Colors saved to device memory'})

    def identify(self, preset, bank, color='#ffffff', hold=1.5):
        """Briefly paint all 16 pads of a preset/bank, then restore them, so the
        user can see which stored preset the hardware is actually displaying."""
        with self.lock:
            self.cancel.clear()
            self.unlock()
            originals = {
                f'pad{i}': '#' + self.flash[a : a + 3].hex()
                for i in range(1, 17)
                for a in [self.address(i, preset, bank)]
            }
            try:
                changed = self.apply({cid: color for cid in originals}, preset, bank, refresh=False)
                if not all(r['ok'] for r in changed):
                    raise RuntimeError('Identify could not paint every pad. Check the individual write results.')
                self.cancel.wait(hold)
            finally:
                self.cancel.clear()
                restored = self.apply(originals, preset, bank, refresh=False)
            if not all(r['ok'] for r in restored):
                raise RuntimeError(
                    'Identify could not restore every pad. Read colors, then Sync colors to restore them.'
                )
            self.event(
                'rgb',
                {
                    'state': 'synced',
                    'colors': originals,
                    'preset': preset,
                    'bank': bank,
                    'identified': {'preset': int(preset), 'bank': bank},
                    'message': f'Identify finished for Preset {int(preset) + 1}, Bank {bank}',
                },
            )
            return originals

    def keep_alive(self):
        # Mirror the official app: poll the 12-byte global block about twice a
        # second. It changes when the preset/bank is switched on the hardware.
        if self.port is None or self.header is None or time.monotonic() - self.last_activity < 0.4:
            return
        if not self.lock.acquire(blocking=False):
            return
        try:
            try:
                header = self.read_region(4, 0, 12, 1)
            except Exception as exc:
                self.header = None
                self.ready = False
                self.event('rgb', {'state': 'error', 'message': 'Configuration session lost: ' + str(exc)})
                return
            if header != self.header:
                previous = self.header
                changed = {i for i in range(len(header)) if i >= len(previous) or header[i] != previous[i]}
                self.header = header
                self.ready = False
                if len(header) == len(previous) and changed <= {10, 11}:
                    # The person pressed PAD BANK or picked another preset: normal use,
                    # not a warning. Controller._detect_preset reports preset changes.
                    bank = self.active_bank()
                    update = {'state': 'available'}
                    if 11 in changed and bank:
                        update['message'] = 'PAD BANK switched to Bank ' + bank
                    self.event('rgb', update)
                else:
                    self.event(
                        'rgb',
                        {
                            'state': 'stale',
                            'message': 'Device state changed on the hardware ('
                            + previous.hex(' ')
                            + ' -> '
                            + header.hex(' ')
                            + '). Colors will be re-read before the next write.',
                        },
                    )
        finally:
            self.lock.release()
