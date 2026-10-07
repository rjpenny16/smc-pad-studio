"""Versioned, atomic local profiles; portable bundles include managed clips."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
import zipfile

COLORS = [
    '#79b8ff',
    '#a78bfa',
    '#f472b6',
    '#fb7185',
    '#f59e0b',
    '#facc15',
    '#84cc16',
    '#34d399',
    '#2dd4bf',
    '#22d3ee',
    '#38bdf8',
    '#818cf8',
    '#c084fc',
    '#e879f9',
    '#fb7185',
    '#f97316',
]
IDS = [f'pad{i}' for i in range(1, 17)] + [f'knob{i}' for i in range(1, 9)] + [f'side{i}' for i in range(1, 11)]
TYPES = {
    'none',
    'nextPage',
    'previousPage',
    'pageKnob',
    'playAudio',
    'stopAudio',
    'launch',
    'url',
    'shortcut',
    'typeText',
    'lockPC',
    'macro',
    'volumeKnob',
    'scrollKnob',
    'hscrollKnob',
    'zoomKnob',
    'tabKnob',
    'windowKnob',
    'desktopKnob',
    'arrowKnob',
    'twoWayShortcutKnob',
    'scrollUp',
    'scrollDown',
    'scrollLeft',
    'scrollRight',
    'volumeUp',
    'volumeDown',
    'volumeMute',
    'mediaPlayPause',
    'mediaNext',
    'mediaPrevious',
    'mediaStop',
    'browserBack',
    'browserForward',
    'showDesktop',
    'taskView',
    'snapLeft',
    'snapRight',
    'maximize',
    'minimize',
    'closeWindow',
    'screenshot',
    'refresh',
    'zoomIn',
    'zoomOut',
    'nextTab',
    'previousTab',
    'nextWindow',
    'previousWindow',
    'desktopRight',
    'desktopLeft',
}
AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.aac', '.wma', '.flac'}
# Hardware pad banks (see midi.BANK_GROUP). A and B always exist; the others are
# created the first time they are used so existing profiles stay small.
BANKS = 'ABCDEFGH'


def number(value, default, low, high):
    try:
        result = float(value)
    except (ValueError, TypeError):
        result = float(default)
    if not __import__('math').isfinite(result):
        raise ValueError('Settings must contain finite numbers')
    return max(low, min(high, result))


def blank_control(cid):
    return {
        'label': cid.replace('pad', 'Pad ').replace('knob', 'Knob ').replace('side', 'Button '),
        'color': COLORS[int(cid[3:]) - 1] if cid.startswith('pad') else '#79b8ff',
        'action': 'none',
        'value': '',
        'trigger': 'press',
        'mapping': None,
        'encoderMode': 'auto',
        'sensitivity': 1,
        'invert': False,
        'acceleration': False,
        'audioMode': 'restart',
        'audioVolume': 100,
        'audioName': '',
        'trimStart': 0,
        'trimEnd': 0,
        'loop': False,
        'fadeIn': 0,
        'fadeOut': 0,
        'steps': [],
    }


def validate_control(cid, value):
    if cid not in IDS or not isinstance(value, dict):
        raise ValueError('Invalid control')
    result = blank_control(cid)
    result.update(copy.deepcopy(value))
    if result['action'] not in TYPES:
        raise ValueError('Unknown action: ' + str(result['action']))
    result['label'] = str(result['label'])[:60]
    result['value'] = str(result['value'])[:12000]
    import re

    if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(result['color'])):
        raise ValueError('Invalid pad color')
    for key, default, low, high in [
        ('audioVolume', 100, 0, 100),
        ('sensitivity', 1, 0.1, 8),
        ('trimStart', 0, 0, 86400),
        ('trimEnd', 0, 0, 86400),
        ('fadeIn', 0, 0, 30),
        ('fadeOut', 0, 0, 30),
    ]:
        result[key] = number(result.get(key), default, low, high)
    if result['trimEnd'] and result['trimEnd'] <= result['trimStart']:
        raise ValueError('Trim end must be after trim start')
    if result['encoderMode'] not in ['auto', 'absolute', 'relative']:
        raise ValueError('Invalid encoder mode')
    if result['audioMode'] not in ['restart', 'overlap', 'toggle']:
        raise ValueError('Invalid playback mode')
    if result['trigger'] not in ['press', 'pressOnly', 'releaseOnly', 'both']:
        raise ValueError('Invalid trigger')
    mapping = result.get('mapping')
    if mapping is not None:
        if not isinstance(mapping, dict) or mapping.get('kind') not in ['note', 'cc', 'pitch', 'aftertouch', 'program']:
            raise ValueError('Invalid MIDI mapping')
        mapping['channel'] = int(number(mapping.get('channel'), 0, 0, 15))
        mapping['data1'] = int(number(mapping.get('data1'), 0, 0, 127))
        mapping['port'] = str(mapping.get('port', ''))[:120]
    if not isinstance(result['steps'], list) or len(result['steps']) > 32:
        raise ValueError('Macros can contain up to 32 steps')
    for step in result['steps']:
        if not isinstance(step, dict):
            raise ValueError('Invalid macro step')
        if step.get('type') == 'delay':
            step['milliseconds'] = int(number(step.get('milliseconds'), 250, 0, 30000))
        elif step.get('type') not in TYPES - {'macro', 'none'} or step.get('type', '').endswith('Knob'):
            raise ValueError('Invalid macro action')
        step['value'] = str(step.get('value', ''))[:12000]
    return result


def blank_bank():
    return {cid: blank_control(cid) for cid in IDS}


def page(name='Page 1'):
    return {'id': uuid.uuid4().hex, 'name': name, 'banks': {bank: blank_bank() for bank in 'AB'}}


def preset_samples(value):
    """Sanitized (global header, confirmed preset) pairs from Identify."""
    result = []
    for item in value if isinstance(value, list) else []:
        try:
            header = bytes.fromhex(str(item['header']))
            preset = int(item['preset'])
            if len(header) == 12 and 0 <= preset <= 7:
                result.append({'header': header.hex(), 'preset': preset})
        except (KeyError, TypeError, ValueError):
            continue
    return result[-8:]


def preset_locator(samples):
    """Find the global-header byte that tracks the active preset.

    Returns (index, offset) such that header[index]-offset is the preset, once
    samples from at least two different presets leave exactly one candidate."""
    samples = preset_samples(samples)
    if len({s['preset'] for s in samples}) < 2:
        return None
    headers = [(bytes.fromhex(s['header']), s['preset']) for s in samples]
    candidates = [
        (i, headers[0][0][i] - headers[0][1]) for i in range(12) if len({h[i] - preset for h, preset in headers}) == 1
    ]
    return candidates[0] if len(candidates) == 1 else None


def settings(value):
    value = dict(value) if isinstance(value, dict) else {}
    value['masterVolume'] = number(value.get('masterVolume'), 100, 0, 100)
    for key in ['autoProfiles', 'reducedMotion', 'liveFeedback']:
        value[key] = bool(value.get(key, False))
    value['autoConnect'] = bool(value.get('autoConnect', True))
    value['hardwarePreset'] = int(number(value.get('hardwarePreset'), 0, 0, 7))
    import re

    if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(value.get('liveColor', ''))):
        value['liveColor'] = '#ffffff'
    value['presetSamples'] = preset_samples(value.get('presetSamples'))
    return value


def profile(name='My SMC-PAD'):
    p = page()
    return {'id': uuid.uuid4().hex, 'name': name, 'apps': [], 'pages': [p], 'activePage': p['id'], 'activeBank': 'A'}


def validate_profile(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid profile')
    if 'controls' in data:  # v0.4/v0.5 migration
        p = profile(str(data.get('name', 'Imported profile')))
        for cid, value in data['controls'].items():
            if cid in IDS:
                p['pages'][0]['banks']['A'][cid] = validate_control(cid, value)
        return p
    p = copy.deepcopy(data)
    p['id'] = str(p.get('id') or uuid.uuid4().hex)
    p['name'] = str(p.get('name', 'My SMC-PAD'))[:80]
    if not isinstance(p.get('pages'), list) or not 1 <= len(p['pages']) <= 32:
        raise ValueError('A profile needs 1–32 pages')
    ids = set()
    for pg in p['pages']:
        pg['id'] = str(pg.get('id') or uuid.uuid4().hex)
        if pg['id'] in ids:
            raise ValueError('Duplicate page identifier')
        ids.add(pg['id'])
        pg['name'] = str(pg.get('name', 'Page'))[:60]
        banks = pg.get('banks') if isinstance(pg.get('banks'), dict) else {}
        pg['banks'] = {
            bank: {cid: validate_control(cid, banks.get(bank, {}).get(cid, {})) for cid in IDS}
            for bank in BANKS
            if bank in 'AB' or bank in banks
        }
    if p.get('activePage') not in ids:
        p['activePage'] = p['pages'][0]['id']
    p['activeBank'] = p.get('activeBank', 'A') if p.get('activeBank') in list(BANKS) else 'A'
    p['apps'] = [str(a).lower()[:200] for a in p.get('apps', [])][:20]
    return p


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'studio.json'
        self.lock = threading.RLock()
        self.undo = []
        self.recovered = False
        p = profile()
        self.data = {
            'schemaVersion': 1,
            'profiles': [p],
            'activeProfile': p['id'],
            'pinned': True,
            'settings': settings({}),
        }
        for candidate in [self.path, self.path.with_suffix('.json.bak')]:
            if candidate.exists():
                try:
                    data = json.loads(candidate.read_text(encoding='utf8'))
                    if data.get('schemaVersion') != 1:
                        raise ValueError('Unsupported profile data version')
                    data['profiles'] = [validate_profile(x) for x in data['profiles']]
                    if not data['profiles']:
                        raise ValueError('No profiles')
                    if data['activeProfile'] not in [p['id'] for p in data['profiles']]:
                        data['activeProfile'] = data['profiles'][0]['id']
                    data['settings'] = settings(data.get('settings'))
                    data['pinned'] = bool(data.get('pinned', True))
                    self.data = data
                    self.recovered = candidate != self.path
                    break
                except (ValueError, KeyError, TypeError):
                    self.recovered = True
        if self.recovered:
            if self.path.exists():
                shutil.copy2(self.path, self.root / ('studio-corrupt-' + uuid.uuid4().hex[:8] + '.json'))
        self.persist(backup=not self.recovered)

    def persist(self, backup=True):
        with self.lock:
            temp = self.path.with_suffix('.tmp')
            with temp.open('w', encoding='utf8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            if backup and self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix('.json.bak'))
            os.replace(temp, self.path)

    def checkpoint(self, label):
        """Remember the state before an edit; `label` names the edit for Undo."""
        self.undo.append((label, copy.deepcopy(self.data)))
        self.undo = self.undo[-30:]

    def restore(self):
        """Undo the most recent edit and return its label (None when there is nothing to undo).

        Only profile content and the active profile go back. Settings and the pin
        state stay as they are now, because Undo is for edits, not preferences or
        state that follows the hardware."""
        if not self.undo:
            return None
        label, data = self.undo.pop()
        data['settings'] = self.data['settings']
        data['pinned'] = self.data['pinned']
        self.data = data
        return label

    def current(self):
        return next(p for p in self.data['profiles'] if p['id'] == self.data['activeProfile'])

    def controls(self, page_id=None, bank=None):
        p = self.current()
        pg = next(pg for pg in p['pages'] if pg['id'] == (page_id or p['activePage']))
        return self.bank(pg, bank or p['activeBank'])

    @staticmethod
    def bank(pg, bank):
        if bank not in BANKS:
            raise ValueError('Invalid bank')
        return pg['banks'].setdefault(bank, blank_bank())

    def snapshot(self):
        with self.lock:
            # The interface reads the active bank of the active page directly.
            for p in self.data['profiles']:
                self.bank(next(pg for pg in p['pages'] if pg['id'] == p['activePage']), p['activeBank'])
            return copy.deepcopy(self.data)

    def import_profile(self, path):
        path = Path(path)
        if path.stat().st_size > 250_000_000:
            raise ValueError('Profile bundle is too large')
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as z:
                if sum(i.file_size for i in z.infolist()) > 500_000_000:
                    raise ValueError('Profile expands beyond the size limit')
                p = validate_profile(json.loads(z.read('profile.json')))
                for pg in p['pages']:
                    for values in pg['banks'].values():
                        for c in values.values():
                            clips = ([c] if c['action'] == 'playAudio' else []) + [
                                step for step in c['steps'] if step['type'] == 'playAudio'
                            ]
                            for clip in clips:
                                value = clip['value']
                                if value.startswith('audio/'):
                                    if value not in z.namelist() or Path(value).suffix.lower() not in AUDIO_EXTS:
                                        raise ValueError('Missing or unsupported bundled audio')
                                    folder = self.root / 'Audio'
                                    folder.mkdir(exist_ok=True)
                                    target = folder / (uuid.uuid4().hex + '-' + Path(value).name)
                                    target.write_bytes(z.read(value))
                                    clip['value'] = str(target)
        else:
            p = validate_profile(json.loads(path.read_text(encoding='utf8')))
        p['id'] = uuid.uuid4().hex
        with self.lock:
            self.checkpoint('Import ' + p['name'])
            self.data['profiles'].append(p)
            self.data['activeProfile'] = p['id']
            self.persist()
        return p

    def export_profile(self, path):
        p = copy.deepcopy(self.current())
        if Path(path).suffix.lower() != '.zip':
            Path(path).write_text(json.dumps(p, indent=2), encoding='utf8')
            return
        # Detect unavailable media before opening (and replacing) a user's bundle.
        for pg in p['pages']:
            for controls in pg['banks'].values():
                for c in controls.values():
                    clips = ([c] if c['action'] == 'playAudio' else []) + [
                        step for step in c['steps'] if step['type'] == 'playAudio'
                    ]
                    for clip in clips:
                        if clip['value'] and not Path(clip['value']).is_file():
                            raise ValueError('Missing audio: ' + Path(clip['value']).name)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            included = {}
            for pg in p['pages']:
                for values in pg['banks'].values():
                    for c in values.values():
                        clips = ([c] if c['action'] == 'playAudio' else []) + [
                            step for step in c['steps'] if step['type'] == 'playAudio'
                        ]
                        for clip in clips:
                            if not clip['value']:
                                continue
                            source = Path(clip['value'])
                            if not source.is_file():
                                raise ValueError('Missing audio: ' + source.name)
                            if str(source) not in included:
                                name = (
                                    'audio/'
                                    + hashlib.sha256(str(source).encode()).hexdigest()[:16]
                                    + source.suffix.lower()
                                )
                                z.write(source, name)
                                included[str(source)] = name
                            clip['value'] = included[str(source)]
            z.writestr('profile.json', json.dumps(p, indent=2))
