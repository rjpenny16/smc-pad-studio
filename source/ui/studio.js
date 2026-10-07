'use strict';
const $ = (id) => document.getElementById(id),
  esc = (s) =>
    String(s ?? '').replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    ),
  icon = (name) => `<svg><use href="#i-${name}"/></svg>`;
const ACTIONS = [
  ['none', 'No action', 'Basics'],
  ['playAudio', 'Play an audio clip', 'Audio'],
  ['stopAudio', 'Stop all audio', 'Audio'],
  ['macro', 'Multi-step macro', 'Automation'],
  ['nextPage', 'Next page', 'Pages'],
  ['previousPage', 'Previous page', 'Pages'],
  ['launch', 'Launch app or file', 'Apps & input'],
  ['url', 'Open a website', 'Apps & input'],
  ['shortcut', 'Keyboard shortcut', 'Apps & input'],
  ['typeText', 'Type a phrase', 'Apps & input'],
  ['volumeKnob', 'System volume', 'Knob controls'],
  ['scrollKnob', 'Vertical scroll', 'Knob controls'],
  ['hscrollKnob', 'Horizontal scroll', 'Knob controls'],
  ['zoomKnob', 'Zoom in / out', 'Knob controls'],
  ['tabKnob', 'Browser tabs', 'Knob controls'],
  ['windowKnob', 'Switch applications', 'Knob controls'],
  ['desktopKnob', 'Virtual desktops', 'Knob controls'],
  ['arrowKnob', 'Left / right arrows', 'Knob controls'],
  ['twoWayShortcutKnob', 'Custom two-way shortcuts', 'Knob controls'],
  ['pageKnob', 'Switch pages', 'Knob controls'],
  ['mediaPlayPause', 'Play / pause media', 'Media'],
  ['mediaNext', 'Next track', 'Media'],
  ['mediaPrevious', 'Previous track', 'Media'],
  ['mediaStop', 'Stop media', 'Media'],
  ['volumeUp', 'Volume up', 'Media'],
  ['volumeDown', 'Volume down', 'Media'],
  ['volumeMute', 'Mute / unmute', 'Media'],
  ['showDesktop', 'Show / hide desktop', 'Windows'],
  ['taskView', 'Task View', 'Windows'],
  ['snapLeft', 'Snap window left', 'Windows'],
  ['snapRight', 'Snap window right', 'Windows'],
  ['maximize', 'Maximize window', 'Windows'],
  ['minimize', 'Minimize window', 'Windows'],
  ['closeWindow', 'Close active window', 'Windows'],
  ['screenshot', 'Screenshot snip', 'Windows'],
  ['lockPC', 'Lock computer', 'Windows'],
  ['browserBack', 'Browser back', 'Navigation'],
  ['browserForward', 'Browser forward', 'Navigation'],
  ['refresh', 'Refresh page', 'Navigation'],
];
const COLORS = [
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
];
const SIDE_NAMES = ['BT', 'Pad bank', 'Knob bank', 'Left', 'Right', 'Play', 'Stop', 'Record', 'Shift', 'Repeat'];
// Actions whose value is typed into #valueInput: field label and placeholder. playAudio keeps its clip path there too.
const VALUE_ACTIONS = {
  launch: ['App or file', 'Browse or paste a path'],
  url: ['Website address', 'https://example.com'],
  typeText: ['Text to type', 'The text Studio types for you'],
};
// Key names actions.shortcut understands besides single characters (test_studio compares the lists).
const SHORTCUT_KEYS = new Set([
  'ctrl',
  'control',
  'alt',
  'shift',
  'win',
  'windows',
  'enter',
  'return',
  'tab',
  'space',
  'esc',
  'escape',
  'backspace',
  'delete',
  'del',
  'insert',
  'home',
  'end',
  'pageup',
  'pagedown',
  'up',
  'down',
  'left',
  'right',
  'plus',
  'minus',
  ...Array.from({ length: 24 }, (_, i) => 'f' + (i + 1)),
]);
// How stored key names read: ctrl+shift+t is shown as Ctrl + Shift + T.
const KEY_LABELS = {
  ctrl: 'Ctrl',
  control: 'Ctrl',
  alt: 'Alt',
  shift: 'Shift',
  win: 'Win',
  windows: 'Win',
  enter: 'Enter',
  return: 'Enter',
  tab: 'Tab',
  space: 'Space',
  esc: 'Esc',
  escape: 'Esc',
  backspace: 'Backspace',
  delete: 'Delete',
  del: 'Delete',
  insert: 'Insert',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pagedown: 'PageDown',
  up: 'Up',
  down: 'Down',
  left: 'Left',
  right: 'Right',
  plus: 'Plus',
  minus: 'Minus',
};
// KeyboardEvent.key values recorded by name. '+' separates keys, so the plus key is "plus".
const KEY_NAMES = {
  Control: 'ctrl',
  Alt: 'alt',
  Shift: 'shift',
  Meta: 'win',
  Enter: 'enter',
  Tab: 'tab',
  ' ': 'space',
  Escape: 'esc',
  Backspace: 'backspace',
  Delete: 'delete',
  Insert: 'insert',
  Home: 'home',
  End: 'end',
  PageUp: 'pageup',
  PageDown: 'pagedown',
  ArrowUp: 'up',
  ArrowDown: 'down',
  ArrowLeft: 'left',
  ArrowRight: 'right',
  '+': 'plus',
  '-': 'minus',
};
const MODIFIER_KEYS = ['ctrl', 'alt', 'shift', 'win'];
const SHORTCUT_HINT = 'Select Record and press the keys. Type Win-key shortcuts such as Win + D by hand.';
// Title and one-line description shown in the top bar for each view.
const VIEWS = {
  studio: ['Studio', 'Choose a pad, knob or button to change what it does.'],
  soundboard: ['Soundboard', 'Your clips, quick previews and the live mixer.'],
  profiles: ['Profiles & pages', 'A profile for each app, with pages of actions inside it.'],
  device: ['Device', 'Connection, pad lighting and troubleshooting.'],
  settings: ['Settings', 'How Studio starts, connects and behaves.'],
};
const waves = new Map(),
  croppers = new Set();
let editorCrop = null,
  handledJob;
let state = null,
  store = null,
  view = 'studio',
  selected = 'pad1',
  multi = new Set(),
  draft = null,
  target = null,
  dirty = false,
  actionValues = {},
  comboOpen = false,
  comboItems = [],
  comboActive = -1,
  recording = null,
  sectionsApplied = false,
  performance = false,
  library = [],
  chosenClip = null,
  polling = null,
  toastTimer,
  modalResolve,
  modalPreviousFocus;
const clone = (x) => JSON.parse(JSON.stringify(x));
const current = () => store.profiles.find((p) => p.id === store.activeProfile),
  page = () => current().pages.find((p) => p.id === current().activePage),
  controls = () => page().banks[current().activeBank];
const context = () => ({ profile: current().id, page: current().activePage, bank: current().activeBank, id: selected });
const label = (type) => ACTIONS.find((a) => a[0] === type)?.[1] || type;
const sameControl = (a, b) => !!a && !!b && ['profile', 'page', 'bank', 'id'].every((key) => a[key] === b[key]);
// The saved controls of one bank ({profile, page, bank}) anywhere in the store.
function bankControls(where) {
  const p = store?.profiles.find((x) => x.id === where.profile);
  return p?.pages.find((x) => x.id === where.page)?.banks[where.bank] || {};
}
const storedControl = (where) => bankControls(where)[where.id];
const describeMapping = (m) => `${m.kind} ${m.data1}, channel ${m.channel + 1}`;
// A readable name for a control id: pad3 -> Pad 3.
function controlTitle(id) {
  const text = String(id ?? '');
  const match = /^(pad|knob|side)(\d+)$/.exec(text);
  if (!match) return text.charAt(0).toUpperCase() + text.slice(1);
  return { pad: 'Pad ', knob: 'Knob ', side: 'Button ' }[match[1]] + match[2];
}
async function call(command, data = {}) {
  const api = window.pywebview?.api;
  if (!api) throw Error('Native runtime is not ready');
  let result = await api.request(command, data);
  if (!result.ok) throw Error(result.error || 'Operation failed');
  return result.value;
}
function toast(message, error = false) {
  $('toast').textContent = message;
  $('toast').className = 'toast' + (error ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.add('hidden'), error ? 7000 : 3200);
}
async function safe(fn) {
  try {
    return await fn();
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}
async function refresh() {
  while (polling) await polling;
  let complete;
  polling = new Promise((resolve) => (complete = resolve));
  try {
    const snap = await call('snapshot', { revision: state?.revision });
    const previous = state;
    state = snap;
    const learned = previous && snap.learned && snap.learned.seq !== previous.learned?.seq ? snap.learned : null;
    if (snap.store) {
      store = snap.store;
      renderStore();
      if (!dirty) loadEditor();
      else if (learned && sameControl(learned, target)) {
        // Keep the unsaved edits, but take the new assignment so Save does not erase it.
        draft.mapping = clone(storedControl(target).mapping);
        renderMapping();
      }
    }
    if (learned) {
      const control = storedControl(learned);
      if (control?.mapping)
        toast(
          control.label +
            ' learned: ' +
            describeMapping(control.mapping) +
            (learned.moved?.length ? ' (moved from ' + learned.moved.join(', ') + ')' : ''),
        );
    }
    renderLive(previous);
    renderHits(previous);
    renderDownload();
    updatePlayheads();
  } catch (e) {
    $('footerStatus').textContent = 'Native runtime unavailable: ' + e.message;
  } finally {
    polling = null;
    complete();
  }
}
async function mutate(command, data = {}) {
  const value = await call(command, data);
  await refresh();
  return value;
}
function setOptions(select, items, selectedValue) {
  select.replaceChildren();
  for (const item of items) {
    let o = document.createElement('option');
    o.value = item.id;
    o.textContent = item.name;
    select.append(o);
  }
  select.value = selectedValue ?? items[0]?.id ?? '';
}
function renderStore() {
  if (!store) return;
  let p = current();
  setOptions($('profileSelect'), store.profiles, store.activeProfile);
  setOptions($('pageSelect'), p.pages, p.activePage);
  for (const b of 'ABCDEFGH') {
    $('bank' + b).classList.toggle('active', p.activeBank === b);
    $('bank' + b).classList.toggle('hidden', !bankVisible(p, b));
  }
  $('extraBanks').checked = !!store.settings.extraBanks;
  if (!sectionsApplied) {
    sectionsApplied = true;
    applySections(store.settings.editorSections);
  }
  $('rgbPreset').value = String(store.settings.hardwarePreset ?? 0);
  $('liveFeedback').checked = !!store.settings.liveFeedback;
  $('liveColor').value = store.settings.liveColor || '#ffffff';
  $('activeProfileLabel').textContent = p.name;
  $('activePageLabel').textContent = page().name + ' · Bank ' + p.activeBank;
  $('pinBtn').innerHTML = icon('pin') + '<span>' + (store.pinned ? 'Pinned' : 'Auto') + '</span>';
  $('profileName').value = p.name;
  $('profileApps').value = (p.apps || []).join(', ');
  $('deletePage').disabled = p.pages.length < 2;
  $('autoProfiles').checked = store.settings.autoProfiles;
  $('autoConnect').checked = store.settings.autoConnect !== false;
  $('reducedMotion').checked = store.settings.reducedMotion;
  document.body.classList.toggle('reduced-motion', store.settings.reducedMotion);
  renderBoard();
  renderProfiles();
}
// Banks C-H are for controllers that send other note ranges, so they show only when wanted or in use.
function bankVisible(p, b) {
  if ('AB'.includes(b) || store.settings.extraBanks || p.activeBank === b) return true;
  const bank = page().banks[b];
  return !!bank && Object.values(bank).some((c) => c.action !== 'none' || c.mapping);
}
function renderBoard() {
  if (!store) return;
  for (const id of ['pads', 'knobs', 'sideBtns']) $(id).replaceChildren();
  let cfgs = controls();
  for (const [cid, cfg] of Object.entries(cfgs)) {
    let button = document.createElement('button');
    button.type = 'button';
    button.dataset.id = cid;
    button.setAttribute('aria-label', cfg.label + ' — ' + label(cfg.action));
    button.setAttribute('aria-pressed', String(selected === cid || multi.has(cid)));
    const isPad = cid.startsWith('pad'),
      isKnob = cid.startsWith('knob');
    button.className = isPad ? 'pad' : isKnob ? 'knob-control' : 'side-control';
    button.classList.toggle('selected', selected === cid || multi.has(cid));
    button.style.setProperty('--color', cfg.color);
    if (isPad) {
      const n = Number(cid.slice(3)) - 1;
      button.style.order = (3 - Math.floor(n / 4)) * 4 + (n % 4);
      button.innerHTML = `<span class="pad-number">${cid.slice(3).padStart(2, '0')}</span><span class="pad-name">${esc(cfg.label)}</span><span class="pad-type">${cfg.action === 'none' ? 'Unassigned' : esc(label(cfg.action))}</span>`;
      $('pads').append(button);
    } else if (isKnob) {
      button.innerHTML = `<span class="dial"><span class="dial-core"></span></span><span>${esc(cfg.label)}</span>`;
      $('knobs').append(button);
    } else {
      button.textContent = cfg.label.startsWith('Button ') ? SIDE_NAMES[Number(cid.slice(4)) - 1] : cfg.label;
      button.title = button.textContent;
      $('sideBtns').append(button);
    }
    button.onclick = (e) => {
      if (performance) {
        safe(() => call('testAction', { ...context(), id: cid }));
        return;
      }
      if (e.ctrlKey || e.metaKey) {
        if (multi.has(cid)) multi.delete(cid);
        else multi.add(cid);
        multi.add(selected);
        renderBoard();
        $('copySelected').classList.toggle('hidden', multi.size < 2);
        return;
      }
      selectControl(cid);
    };
  }
  $('mappingCount').textContent = Object.values(cfgs).filter((c) => c.action !== 'none').length + ' mapped controls';
  renderPlayingPads();
}
async function allowSelection() {
  if (!dirty) return true;
  const answer = await modal(
    'Unsaved control changes',
    '<p class="muted">Save these edits before changing your workspace, or discard them.</p>',
    [
      { label: 'Discard', value: 'discard' },
      { label: 'Save edits', value: 'save' },
    ],
  );
  if (answer === 'save') {
    await saveEditor();
    return true;
  }
  if (answer === 'discard') {
    dirty = false;
    return true;
  }
  return false;
}
async function selectControl(cid) {
  if (cid !== selected && !(await allowSelection())) return;
  selected = cid;
  multi.clear();
  renderBoard();
  loadEditor();
}
// Knob actions are offered only to knobs.
const actionChoices = () => ACTIONS.filter((a) => a[2] !== 'Knob controls' || selected.startsWith('knob'));
// The hidden <select> is the source of truth for the action; the picker below only chooses it.
function actionOptions() {
  const value = $('actionSelect').value || draft?.action || 'none';
  const groups = new Map();
  for (const action of actionChoices()) {
    if (!groups.has(action[2])) groups.set(action[2], []);
    groups.get(action[2]).push(action);
  }
  $('actionSelect').replaceChildren();
  for (const [name, actions] of groups) {
    let group = document.createElement('optgroup');
    group.label = name;
    for (const [id, text] of actions) {
      let o = document.createElement('option');
      o.value = id;
      o.textContent = text;
      group.append(o);
    }
    $('actionSelect').append(group);
  }
  $('actionSelect').value = value;
}
function loadEditor() {
  if (!store) return;
  stopRecording(false);
  target = context();
  draft = clone(controls()[selected]);
  dirty = false;
  $('dirtyBadge').classList.add('hidden');
  $('revertControl').disabled = true;
  $('selectedName').textContent = draft.label;
  $('selectedType').textContent =
    (selected.startsWith('pad') ? 'Pad' : selected.startsWith('knob') ? 'Encoder' : 'Button') +
    ' · Bank ' +
    target.bank;
  $('selectedSwatch').style.setProperty('--color', draft.color);
  for (const [id, key] of [
    ['labelInput', 'label'],
    ['colorInput', 'color'],
    ['colorHex', 'color'],
    ['audioMode', 'audioMode'],
    ['audioVolume', 'audioVolume'],
    ['trimStart', 'trimStart'],
    ['trimEnd', 'trimEnd'],
    ['fadeIn', 'fadeIn'],
    ['fadeOut', 'fadeOut'],
    ['encoderMode', 'encoderMode'],
    ['sensitivity', 'sensitivity'],
    ['triggerSelect', 'trigger'],
  ])
    $(id).value = draft[key] ?? '';
  $('loopAudio').checked = !!draft.loop;
  $('invertKnob').checked = !!draft.invert;
  $('accelerateKnob').checked = !!draft.acceleration;
  actionOptions();
  $('actionSelect').value = draft.action;
  actionValues = { [draft.action]: draft.value };
  writeValueFields(draft.action, draft.value);
  $('assignedAudioName').textContent = draft.audioName || 'Drop a clip or browse';
  $('clipGainValue').textContent = draft.audioVolume + '%';
  $('colorFields').classList.toggle('hidden', !selected.startsWith('pad'));
  $('knobFields').classList.toggle('hidden', !selected.startsWith('knob'));
  $('copySelected').classList.toggle('hidden', multi.size < 2);
  renderFields();
  renderSteps();
  renderMapping();
  renderColorState();
}
function markDirty() {
  dirty = true;
  $('dirtyBadge').classList.remove('hidden');
  $('revertControl').disabled = false;
}
// Put a stored value into its action's fields. Each action keeps its own value while editing.
function writeValueFields(action, value) {
  value = String(value ?? '');
  $('valueInput').value = action in VALUE_ACTIONS || action === 'playAudio' ? value : '';
  $('shortcutInput').value = action === 'shortcut' ? shortcutText(value) : '';
  // Like controller._trigger: without a "|" both directions use the same shortcut.
  const sides = action === 'twoWayShortcutKnob' ? value.split('|') : [''];
  $('ccwInput').value = shortcutText(sides[0].trim());
  $('cwInput').value = shortcutText((sides[1] ?? sides[0]).trim());
}
// The value an action saves, read back from its fields.
function fieldValue(action) {
  if (action === 'shortcut') return shortcutValue($('shortcutInput').value);
  if (action === 'twoWayShortcutKnob') {
    const sides = [$('ccwInput').value, $('cwInput').value].map(shortcutValue);
    return sides.some(Boolean) ? sides.join(' | ') : '';
  }
  return action in VALUE_ACTIONS || action === 'playAudio' ? $('valueInput').value : '';
}
function chooseAction(action) {
  const previous = $('actionSelect').value;
  if (action === previous) return;
  actionValues[previous] = fieldValue(previous);
  $('actionSelect').value = action;
  writeValueFields(action, actionValues[action] ?? '');
  markDirty();
  renderFields();
}
function collect() {
  let cfg = clone(draft);
  for (const [id, key] of [
    ['labelInput', 'label'],
    ['colorInput', 'color'],
    ['audioMode', 'audioMode'],
    ['encoderMode', 'encoderMode'],
    ['triggerSelect', 'trigger'],
  ])
    cfg[key] = $(id).value;
  for (const [id, key] of [
    ['audioVolume', 'audioVolume'],
    ['trimStart', 'trimStart'],
    ['trimEnd', 'trimEnd'],
    ['fadeIn', 'fadeIn'],
    ['fadeOut', 'fadeOut'],
    ['sensitivity', 'sensitivity'],
  ])
    cfg[key] = Number($(id).value);
  cfg.action = $('actionSelect').value;
  cfg.value = fieldValue(cfg.action);
  cfg.loop = $('loopAudio').checked;
  cfg.invert = $('invertKnob').checked;
  cfg.acceleration = $('accelerateKnob').checked;
  return cfg;
}
async function saveEditor() {
  let cfg = collect();
  const recolored = target.id.startsWith('pad') && cfg.color !== storedControl(target)?.color;
  await call('saveControl', { ...target, control: cfg });
  dirty = false;
  draft = cfg;
  await refresh();
  loadEditor();
  toast(cfg.label + ' saved' + (recolored ? '. Apply colors to light it on the controller.' : ''));
}
function renderFields() {
  const action = $('actionSelect').value;
  $('valueField').classList.toggle('hidden', !(action in VALUE_ACTIONS));
  $('shortcutField').classList.toggle('hidden', action !== 'shortcut');
  $('twoWayFields').classList.toggle('hidden', action !== 'twoWayShortcutKnob');
  $('audioFields').classList.toggle('hidden', action !== 'playAudio');
  $('macroFields').classList.toggle('hidden', action !== 'macro');
  $('browseBtn').classList.toggle('hidden', action !== 'launch');
  $('valueLabel').textContent = VALUE_ACTIONS[action]?.[0] || 'Value';
  $('valueInput').placeholder = VALUE_ACTIONS[action]?.[1] || '';
  $('actionMeta').textContent = label(action);
  if (!comboOpen) $('actionPicker').value = label(action);
  renderShortcutHelp();
  renderEditorCrop();
}
// Shortcuts are stored as ctrl+shift+t (see actions.shortcut) and shown as Ctrl + Shift + T.
const shortcutValue = (text) =>
  String(text ?? '')
    .split('+')
    .map((part) => part.trim().toLowerCase())
    .join('+');
function shortcutText(value) {
  if (!value) return '';
  return value
    .split('+')
    .map((part) => {
      part = part.trim().toLowerCase();
      const upper = part.toUpperCase();
      if (Object.hasOwn(KEY_LABELS, part)) return KEY_LABELS[part];
      return /^f\d+$/.test(part) || [...upper].length === 1 ? upper : part;
    })
    .join(' + ');
}
// Why actions.shortcut would reject a stored shortcut, or ''.
function shortcutProblem(value) {
  if (!value) return '';
  for (const part of value.split('+')) {
    if (!part) return 'Finish the shortcut, or write Plus for the + key.';
    if (!SHORTCUT_KEYS.has(part) && [...part].length !== 1) return `Studio doesn't know the key “${part}”.`;
  }
  return '';
}
function renderShortcutHelp() {
  const sides = [$('ccwInput').value, $('cwInput').value].map(shortcutValue);
  for (const [id, problem] of [
    ['shortcutHelp', shortcutProblem(shortcutValue($('shortcutInput').value))],
    [
      'twoWayHelp',
      shortcutProblem(sides[0]) ||
        shortcutProblem(sides[1]) ||
        (sides.filter(Boolean).length === 1 ? 'Set a shortcut for both directions.' : ''),
    ],
  ]) {
    $(id).textContent = problem || SHORTCUT_HINT;
    $(id).classList.toggle('error', !!problem);
  }
}
// Recording: the next key with its modifiers becomes the shortcut. Windows keeps Win-key shortcuts
// for itself, so those are typed by hand.
function keyName(e) {
  if (KEY_NAMES[e.key]) return KEY_NAMES[e.key];
  if (/^F([1-9]|1\d|2[0-4])$/.test(e.key)) return e.key.toLowerCase();
  // Shift+1 is recorded as Shift + 1 rather than Shift + !, because Studio presses Shift itself.
  if (e.shiftKey && /^Digit\d$/.test(e.code)) return e.code.slice(5);
  // Letters typed on a layout without Latin letters, or with AltGr, are recorded by key position.
  if (/^Key[A-Z]$/.test(e.code) && !/^[a-z]$/i.test(e.key)) return e.code.slice(3).toLowerCase();
  return [...e.key].length === 1 ? e.key.toLowerCase() : null;
}
const heldKeys = (e) => MODIFIER_KEYS.filter((_, i) => [e.ctrlKey, e.altKey, e.shiftKey, e.metaKey][i]);
const heldText = (held) => (held.length ? shortcutText(held.join('+')) + ' + …' : '');
function startRecording(input, done) {
  stopRecording(false);
  const box = input.closest('.recorder');
  recording = { input, box, done, previous: input.value, placeholder: input.placeholder };
  box.classList.add('recording');
  box.querySelector('[data-record] span').textContent = 'Cancel';
  input.value = '';
  input.placeholder = 'Press the keys…';
  input.focus();
}
function stopRecording(keep) {
  if (!recording) return;
  const { input, box, done, previous, placeholder } = recording;
  recording = null;
  box.classList.remove('recording');
  box.querySelector('[data-record] span').textContent = 'Record';
  input.placeholder = placeholder;
  if (keep) done(shortcutValue(input.value));
  else input.value = previous;
}
function wireRecorder(input, done) {
  const button = input.closest('.recorder').querySelector('[data-record]');
  // Keep focus in the field, so clicking Cancel does not first end the recording through blur.
  button.onmousedown = (e) => e.preventDefault();
  button.onclick = () => (recording?.input === input ? stopRecording(false) : startRecording(input, done));
  input.addEventListener('blur', () => recording?.input === input && stopRecording(false));
  input.addEventListener('change', () => (input.value = shortcutText(shortcutValue(input.value))));
}
// The factory MIDI input of a pad (see midi.default_mapping), or null.
function factoryMapping(bank, id) {
  const base = state?.factoryNotes?.[bank];
  const note = /^pad\d+$/.test(id) && base != null ? base + Number(id.slice(3)) - 1 : 128;
  return note <= 127 ? { kind: 'note', channel: 9, data1: note, port: '' } : null;
}
const sameInput = (a, b) => a.kind === b.kind && a.channel === b.channel && a.data1 === b.data1;
function renderMapping() {
  if (!draft) return;
  let m = draft.mapping;
  const fallback = factoryMapping(target.bank, target.id);
  $('clearLearn').textContent = fallback ? 'Use default' : 'Clear';
  $('clearLearn').disabled = !m;
  if (m) {
    $('mappingInfo').textContent =
      `${m.kind} · channel ${m.channel + 1} · number ${m.data1}\n${m.port || 'Primary performance input'}`;
    $('physicalMeta').textContent = 'Learned';
    return;
  }
  if (!fallback) {
    $('mappingInfo').textContent = 'No physical control assigned';
    $('physicalMeta').textContent = 'Not assigned';
    return;
  }
  // Mirrors controller.effective_mappings: a learned control elsewhere in the bank takes the factory input.
  const owner = Object.entries(bankControls(target)).find(
    ([cid, cfg]) => cid !== target.id && cfg.mapping && sameInput(cfg.mapping, fallback),
  );
  $('mappingInfo').textContent = owner
    ? `Not assigned: note ${fallback.data1} is learned by ${owner[1].label}`
    : `Factory default\nnote ${fallback.data1} · channel 10\nLearn to use a different control`;
  $('physicalMeta').textContent = owner ? 'Not assigned' : 'Factory default';
}
const STEP_TYPES = [
  ['delay', 'Wait'],
  ...ACTIONS.filter((a) => !['none', 'macro'].includes(a[0]) && a[2] !== 'Knob controls').map((a) => a.slice(0, 2)),
];
// The field for a macro step's value; actions without a value have none.
function stepField(step, n) {
  const value = esc(step.value || '');
  switch (step.type) {
    case 'delay':
      return `<label class="step-wait"><input type="number" min="0" max="30000" step="50" value="${esc(step.milliseconds ?? 250)}" data-ms aria-label="Step ${n}: milliseconds to wait"><span>ms</span></label>`;
    case 'shortcut':
      return `<div class="recorder"><input value="${esc(shortcutText(step.value || ''))}" placeholder="Ctrl + C" data-keys aria-label="Step ${n}: keys to press" autocomplete="off" spellcheck="false"><button type="button" class="btn tiny" data-record title="Record keys">${icon('record')}<span class="sr-only">Record</span></button></div>`;
    case 'launch':
      return `<div class="row"><input class="grow" value="${value}" placeholder="Browse or paste a path" data-text aria-label="Step ${n}: app or file"><button type="button" class="btn tiny" data-browse>Browse</button></div>`;
    case 'url':
      return `<input inputmode="url" value="${value}" placeholder="https://example.com" data-text aria-label="Step ${n}: website address">`;
    case 'typeText':
      return `<input value="${value}" placeholder="The text to type" data-text aria-label="Step ${n}: text to type">`;
    case 'playAudio':
      return `<div class="row"><span class="step-clip grow" title="${value}">${esc(step.value ? clipName(step.value.split(/[\\/]/).pop()) : 'No clip chosen')}</span><button type="button" class="btn tiny" data-clip>Choose clip</button></div>`;
    default:
      return '';
  }
}
// Each step remembers its value per type while editing, so trying another type loses nothing.
const stepValues = new WeakMap();
// focus: [step index, selectors to try in order] for the element to focus after rebuilding.
function renderSteps(focus = null) {
  if (!draft) return;
  const list = $('steps');
  list.replaceChildren();
  if (!draft.steps.length)
    list.innerHTML = '<p class="helper">No steps yet. Add a step to build a sequence of actions.</p>';
  const count = draft.steps.length;
  for (const [index, step] of draft.steps.entries()) {
    const n = index + 1;
    const el = document.createElement('div');
    el.className = 'step';
    el.innerHTML =
      `<div class="step-main"><select aria-label="Step ${n} action">${STEP_TYPES.map(([id, name]) => `<option value="${id}">${esc(name)}</option>`).join('')}</select>${stepField(step, n)}</div>` +
      `<div class="step-tools"><button type="button" class="icon-btn" data-move="-1" title="Move up" aria-label="Move step ${n} up"${index ? '' : ' disabled'}>${icon('up')}</button>` +
      `<button type="button" class="icon-btn" data-move="1" title="Move down" aria-label="Move step ${n} down"${n < count ? '' : ' disabled'}>${icon('down')}</button>` +
      `<button type="button" class="icon-btn" data-duplicate title="Duplicate" aria-label="Duplicate step ${n}">${icon('copy')}</button>` +
      `<button type="button" class="icon-btn" data-remove title="Remove" aria-label="Remove step ${n}">${icon('close')}</button></div>`;
    const select = el.querySelector('select');
    select.value = step.type;
    select.onchange = () => {
      const memory = stepValues.get(step) || {};
      memory[step.type] = step.value;
      stepValues.set(step, memory);
      step.type = select.value;
      step.value = memory[step.type] ?? '';
      if (step.type === 'delay') step.milliseconds = step.milliseconds ?? 250;
      markDirty();
      renderSteps([index, 'select']);
    };
    el.querySelector('[data-ms]')?.addEventListener('input', (e) => (step.milliseconds = Number(e.target.value)));
    el.querySelector('[data-text]')?.addEventListener('input', (e) => (step.value = e.target.value));
    const keys = el.querySelector('[data-keys]');
    if (keys) {
      keys.addEventListener('input', () => (step.value = shortcutValue(keys.value)));
      wireRecorder(keys, (value) => {
        step.value = value;
        markDirty();
      });
    }
    el.querySelector('[data-browse]')?.addEventListener('click', () =>
      safe(async () => {
        const path = await call('browse');
        if (!path) return;
        step.value = path;
        markDirty();
        renderSteps([index, '[data-text]']);
      }),
    );
    el.querySelector('[data-clip]')?.addEventListener('click', () =>
      safe(async () => {
        const clips = await call('chooseAudio');
        if (!clips?.length) return;
        step.value = clips[0].path;
        markDirty();
        renderSteps([index, '[data-clip]']);
      }),
    );
    for (const button of el.querySelectorAll('[data-move]'))
      button.onclick = () => {
        const to = index + Number(button.dataset.move);
        [draft.steps[index], draft.steps[to]] = [draft.steps[to], draft.steps[index]];
        markDirty();
        // Keep focus on the moved step, so the keyboard can move it again.
        renderSteps([to, `[data-move="${button.dataset.move}"]:not(:disabled)`, '[data-move]:not(:disabled)']);
      };
    el.querySelector('[data-duplicate]').onclick = () => {
      if (draft.steps.length >= 32) return toast('Maximum 32 steps', true);
      draft.steps.splice(index + 1, 0, clone(step));
      markDirty();
      renderSteps([index + 1, 'select']);
    };
    el.querySelector('[data-remove]').onclick = () => {
      draft.steps.splice(index, 1);
      markDirty();
      renderSteps([Math.min(index, draft.steps.length - 1), '[data-remove]']);
    };
    list.append(el);
  }
  if (focus) {
    const [at, ...selectors] = focus;
    const row = list.children[at];
    (selectors.map((selector) => row?.querySelector(selector)).find(Boolean) || $('addStep')).focus();
  }
}
function renderColorState() {
  if (!draft || !state) return;
  let sameContext = state.rgb.bank === target.bank && Number(state.rgb.preset) === Number($('rgbPreset').value);
  let actual = sameContext ? state.rgb.colors?.[selected] : null;
  $('colorState').textContent =
    actual === draft.color
      ? 'Stored on the device for Preset ' +
        (Number($('rgbPreset').value) + 1) +
        ', Bank ' +
        target.bank +
        '.' +
        (state.rgb.activeBank && state.rgb.activeBank !== target.bank
          ? ' Switch PAD BANK ' + (target.bank === 'B' ? 'on' : 'off') + ' to display these colors.'
          : '')
      : actual
        ? 'Unsynced: physical pad is ' + actual + '. Apply to update it.'
        : 'Local color. Read the device before applying changes.';
  const status = actual === draft.color ? 'On the controller' : actual ? 'Not synced' : '';
  renderOnChange(
    $('lightMeta'),
    [draft.color, status],
    ([color, text]) => `<i class="meta-swatch" style="--color:${esc(color)}"></i>${esc(text)}`,
  );
}
function renderLive(previous) {
  if (!state) return;
  let connected = state.connection.state === 'connected';
  $('appVersion').textContent = 'v' + state.version;
  $('aboutVersion').textContent = 'SMC-PAD Studio ' + state.version;
  $('undoBtn').disabled = !state.canUndo;
  renderAutostart();
  $('connectionDot').classList.toggle('on', connected);
  $('railStatus').textContent = connected
    ? 'Background MIDI active'
    : state.connection.state === 'error'
      ? 'Connection needs attention'
      : 'Not connected';
  $('connectBtn').querySelector('span').textContent = connected ? 'Reconnect' : 'Connect device';
  // The only primary button in the top bar, and only while there is something to do.
  $('connectBtn').classList.toggle('primary', !connected);
  $('canvasStatus').textContent = connected ? 'Live' : 'Offline';
  // Which bank the PAD BANK switch has selected, so the app and the controller are visibly in step.
  const hardwareBank = connected ? state.rgb.activeBank : null;
  $('hardwareBank').classList.toggle('hidden', !hardwareBank);
  if (hardwareBank) $('hardwareBank').textContent = 'Controller: Bank ' + hardwareBank;
  for (const b of 'AB') $('bank' + b).classList.toggle('on-controller', hardwareBank === b);
  $('canvasStatus').className = 'tag' + (connected ? ' good' : '');
  $('deviceStatusTag').textContent = state.connection.state[0].toUpperCase() + state.connection.state.slice(1);
  $('deviceStatusTag').className = 'tag' + (connected ? ' good' : ' warn');
  $('deviceMessage').textContent = state.connection.message;
  $('pauseBtn').querySelector('span').textContent = state.paused ? 'Resume mappings' : 'Pause mappings';
  $('pauseBtn').classList.toggle('danger', state.paused);
  $('footerStatus').textContent = state.paused ? 'Mappings paused — audio remains available' : state.connection.message;
  $('audioCount').textContent = state.audio.players.length + ' clip' + (state.audio.players.length === 1 ? '' : 's');
  $('playingCount').textContent = state.audio.players.length + ' playing';
  if (state.midi) {
    $('lastMidiValue').textContent = state.midi.kind.toUpperCase() + ' ' + state.midi.value;
    $('lastMidiPort').textContent = state.midi.port + ' · Ch ' + state.midi.channel;
  }
  let rgb = state.rgb;
  $('rgbStatus').textContent =
    rgb.state === 'reading'
      ? 'Reading ' + (rgb.progress || 0) + '%'
      : rgb.state === 'writing'
        ? 'Applying ' + (rgb.progress || 0) + '%'
        : {
            notRead: 'Not read',
            synced: 'Stored on device',
            partial: 'Partial / failed',
            available: 'Ready to read',
            unavailable: 'Unavailable',
            error: 'Needs attention',
            discovering: 'Finding port',
            stale: 'Changed on device',
            saved: 'Saved to device',
          }[rgb.state] || rgb.state;
  // Confirming a preset by eye is only needed when the device does not report it.
  let asked = rgb.activePreset == null ? rgb.identified : null;
  $('identifyConfirm').classList.toggle('hidden', !asked);
  $('confirmPresetBar').classList.toggle('hidden', !asked);
  if (asked) $('identifyQuestion').textContent = 'Did all 16 pads flash white for Preset ' + (asked.preset + 1) + '?';
  $('rgbPreset').disabled = rgb.activePreset != null;
  if (rgb.activePreset != null) $('rgbPreset').value = String(rgb.activePreset);
  $('presetDetect').textContent = rgb.presetDetection?.located
    ? 'Auto-detect is on' +
      (rgb.activePreset != null ? ': the hardware is on Preset ' + (rgb.activePreset + 1) + '.' : '.')
    : 'Connect the device to detect its active preset.';
  $('deviceSave').disabled = !connected || ['discovering', 'reading', 'writing'].includes(rgb.state);
  $('rgbStatus').className =
    'tag' +
    (['synced', 'saved'].includes(rgb.state)
      ? ' good'
      : ['error', 'partial', 'unavailable', 'stale'].includes(rgb.state)
        ? ' warn'
        : '');
  for (const id of ['identifyRGB', 'deviceIdentify'])
    $(id).disabled = !connected || ['discovering', 'reading', 'writing'].includes(rgb.state);
  $('applyRGB').disabled = !connected || ['discovering', 'reading', 'writing'].includes(rgb.state);
  $('readRGB').disabled = !connected || ['discovering', 'reading', 'writing'].includes(rgb.state);
  renderOnChange($('rgbResults'), rgb.results || [], (results) =>
    results
      .map(
        (r) =>
          `<p class="helper" style="color:${r.ok ? 'var(--accent)' : 'var(--danger)'}">${esc(controlTitle(r.pad))} · ${r.ok ? 'Stored ' + esc(r.color) : esc(r.error)}</p>`,
      )
      .join(''),
  );
  $('healthInfo').textContent =
    `MIDI: ${state.connection.state}. Pad colors: ${$('rgbStatus').textContent.toLowerCase()}. Dropped MIDI messages: ${state.droppedMidi}. Audio: ${state.audio.error || 'ready'}.`;
  renderPlayingPads();
  renderMixer();
  renderColorState();
  if (draft) {
    let cal = state.calibration[selected];
    if (cal) $('calibration').textContent = `Raw ${cal.raw} · delta ${cal.delta}\n${cal.port} · ${cal.mode}`;
    let waiting = sameControl(state.learning, target);
    renderOnChange($('learnBtn'), waiting, (on) => icon('link') + (on ? 'Cancel learning' : 'Learn'));
    $('learnHint').textContent = waiting
      ? 'Waiting for your SMC-PAD: press or turn the control. Esc cancels.'
      : 'Press Learn, then press or turn a control on your SMC-PAD.';
    for (let el of document.querySelectorAll('[data-id]'))
      el.classList.toggle('learning', waiting && el.dataset.id === selected);
  }
  let portsKey = JSON.stringify(state.ports);
  if (portsKey !== window.lastPortsKey) {
    window.lastPortsKey = portsKey;
    renderPorts();
  }
  renderOnChange($('logs'), state.logs.at(-1)?.seq ?? 0, () =>
    state.logs
      .slice()
      .reverse()
      .map(
        (log) =>
          `<div class="log-item ${log.kind === 'error' ? 'error' : ''}"><time>${esc(log.time)}</time><span class="kind">${esc(log.kind)}</span><span>${esc(log.message)}</span></div>`,
      )
      .join(''),
  );
  $('diagnosticCount').textContent = state.logs.length + (state.logs.length === 1 ? ' event' : ' events');
  if (previous?.rgb?.state !== rgb.state && rgb.state === 'partial')
    toast('Some pad colors were not applied. See Device for individual results.', true);
}
// Rebuild an element only when its data changed, so clicks and hover survive the 350 ms refresh.
function renderOnChange(element, data, html) {
  const key = JSON.stringify(data);
  if (element.dataset.renderKey === key) return false;
  element.dataset.renderKey = key;
  element.innerHTML = html(data);
  return true;
}
// Library files are stored as <32 hex characters>-<original name>.
const clipName = (name) => String(name).replace(/^[0-9a-f]{32}-/, '');
// Briefly highlight controls the hardware just pressed or turned (state.hits, newest last).
let lastHit = 0;
function renderHits(previous) {
  const hits = state.hits || [];
  const newest = hits.at(-1)?.seq ?? lastHit;
  if (!previous || !store) {
    lastHit = newest;
    return;
  }
  for (const hit of hits) {
    if (hit.seq <= lastHit || hit.bank !== current().activeBank || hit.page !== current().activePage) continue;
    const el = document.querySelector(`[data-id="${hit.id}"]`);
    if (!el) continue;
    el.classList.remove('hit');
    void el.offsetWidth; // restart the animation for repeated presses
    el.classList.add('hit');
    clearTimeout(el.hitTimer);
    el.hitTimer = setTimeout(() => el.classList.remove('hit'), 450);
  }
  lastHit = Math.max(lastHit, newest);
}
function renderAutostart() {
  const autostart = state?.autostart || { available: false, enabled: false };
  $('startWithWindows').checked = autostart.enabled;
  $('startWithWindows').disabled = !autostart.available;
  $('startWithWindowsHelp').textContent = autostart.available
    ? 'Opens quietly in the tray, so your pads work as soon as the controller is plugged in.'
    : 'Available in the SMC-PAD Studio EXE. When running from source, start it yourself.';
}
function renderPlayingPads() {
  if (!state) return;
  let playing = new Set(state.audio.players.map((p) => p.control));
  for (const el of document.querySelectorAll('.pad')) {
    el.classList.toggle('playing', playing.has(el.dataset.id));
    let cfg = store ? controls()[el.dataset.id] : null;
    if (cfg)
      el.querySelector('.pad-type').textContent = playing.has(el.dataset.id)
        ? cfg.loop
          ? 'Looping'
          : 'Playing'
        : cfg.action === 'none'
          ? 'Unassigned'
          : label(cfg.action);
  }
}
function renderMixer() {
  if (!state) return;
  if (document.activeElement !== $('masterVolume')) $('masterVolume').value = state.audio.masterVolume;
  $('masterValue').textContent = Math.round(state.audio.masterVolume) + '%';
  const list = $('playingList');
  const players = state.audio.players;
  const position = (p) => Math.max(0, Math.min(100, ((p.position - p.start) / (p.end - p.start)) * 100)) || 0;
  // Rebuild only when clips start or stop; otherwise update rows in place so Stop and gain stay clickable.
  const rebuilt = renderOnChange(
    list,
    players.map((p) => p.id),
    () =>
      players
        .map(
          (p) =>
            `<div class="playing-row" data-player="${esc(p.id)}"><div class="row"><span class="clip-name grow">${esc(controlTitle(p.control))} · ${esc(clipName(p.name))}</span><span class="tag" data-loop></span><button class="btn ghost tiny" data-stop="${esc(p.control)}" aria-label="Stop ${esc(controlTitle(p.control))}">${icon('stop')}</button></div><div class="progress"><i data-progress></i></div><div class="row" style="margin-top:7px"><span class="helper grow" data-time></span><input type="range" data-gain="${esc(p.control)}" aria-label="Gain for ${esc(controlTitle(p.control))}" min="0" max="100" value="${p.volume}" style="width:110px;height:18px;padding:0;accent-color:var(--accent)"></div></div>`,
        )
        .join('') || '<p class="muted">Nothing playing. Preview a clip or press an assigned pad.</p>',
  );
  if (rebuilt) {
    for (let b of list.querySelectorAll('[data-stop]'))
      b.onclick = () => safe(() => call('stopClip', { control: b.dataset.stop }));
    for (let gain of list.querySelectorAll('[data-gain]'))
      gain.onchange = () => safe(() => call('clipGain', { control: gain.dataset.gain, volume: Number(gain.value) }));
  }
  for (const p of players) {
    const row = list.querySelector(`[data-player="${CSS.escape(p.id)}"]`);
    if (!row) continue;
    row.querySelector('[data-loop]').textContent = p.loop ? 'Loop' : 'Playing';
    row.querySelector('[data-progress]').style.width = position(p) + '%';
    row.querySelector('[data-time]').textContent = `${p.position.toFixed(1)} / ${p.end.toFixed(1)} seconds`;
    const gain = row.querySelector('[data-gain]');
    if (document.activeElement !== gain) gain.value = p.volume;
  }
}
function renderPorts() {
  for (const [id, key] of [
    ['performanceInput', 'inputs'],
    ['rgbInputPort', 'inputs'],
    ['rgbOutputPort', 'outputs'],
  ]) {
    let value = $(id).value;
    setOptions(
      $(id),
      [{ id: '', name: id === 'performanceInput' ? 'Auto discover SMC-PAD' : 'Auto discover' }, ...state.ports[key]],
      value,
    );
  }
  $('portList').innerHTML =
    '<h3>Inputs</h3>' +
    state.ports.inputs.map((p) => esc(p.id + ' · ' + p.name)).join('<br>') +
    '<hr class="section-rule"><h3>Outputs</h3>' +
    state.ports.outputs.map((p) => esc(p.id + ' · ' + p.name)).join('<br>');
}
async function showView(next) {
  if (next !== view && !(await allowSelection())) return;
  view = next;
  for (const name of ['studio', 'soundboard', 'profiles', 'device', 'settings'])
    $('view-' + name).classList.toggle('hidden', name !== view);
  for (let button of document.querySelectorAll('[data-view]'))
    button.classList.toggle('active', button.dataset.view === view);
  $('viewTitle').textContent = VIEWS[view][0];
  $('viewDescription').textContent = VIEWS[view][1];
  if (view === 'soundboard') await loadLibrary();
}
async function loadLibrary() {
  library = await call('library');
  renderLibrary();
}
function renderLibrary() {
  let query = $('librarySearch').value.toLowerCase();
  let list = library.filter((c) => c.name.toLowerCase().includes(query));
  $('libraryCount').textContent = library.length + (library.length === 1 ? ' clip' : ' clips');
  $('libraryList').innerHTML = list.length
    ? list
        .map(
          (c) =>
            `<article class="clip${chosenClip?.path === c.path ? ' selected' : ''}" data-clip="${esc(c.path)}"><div class="clip-icon">${icon('audio')}</div><div class="grow" style="flex:1;min-width:0"><div class="clip-name">${esc(c.name)}</div><div class="clip-details">${(c.size / 1048576).toFixed(1)} MB · ${c.duration ? c.duration.toFixed(1) + ' seconds' : 'Ready to preview'}</div></div><button class="btn ghost tiny" data-preview aria-label="Preview ${esc(c.name)}">${icon('play')}</button><button class="btn tiny" data-select>Details</button></article>`,
        )
        .join('')
    : `<div class="panel empty">${icon('audio')}<p>${query ? 'No clips match your search.' : 'No clips yet. Import audio files, or paste a YouTube link above.'}</p>${query ? '' : `<button class="btn" data-empty-import>${icon('plus')}Import clips</button>`}</div>`;
  $('libraryList')
    .querySelector('[data-empty-import]')
    ?.addEventListener('click', () => $('importClips').click());
  for (let el of $('libraryList').querySelectorAll('[data-clip]')) {
    let clip = list.find((c) => c.path === el.dataset.clip);
    el.querySelector('[data-preview]').onclick = () => safe(() => call('previewAudio', { path: clip.path }));
    el.querySelector('[data-select]').onclick = () => {
      chosenClip = clip;
      renderLibrary();
      renderClipDetail();
    };
  }
}
function renderClipDetail() {
  if (!chosenClip) return;
  let c = chosenClip;
  $('clipDetail').innerHTML =
    `<div class="clip-icon" style="width:52px;height:52px;margin-bottom:16px">${icon('audio')}</div><h2 style="overflow-wrap:anywhere">${esc(c.name)}</h2><p class="muted">${(c.size / 1048576).toFixed(1)} MB · Windows default output</p><div class="row" style="margin-top:16px"><button class="btn primary" id="detailPreview">${icon('play')}Preview</button><button class="btn" id="detailInspect">Details</button></div><hr class="section-rule"><div class="field"><label id="detailCropLabel">Crop · drag the handles or the highlighted part</label><div id="detailCrop" role="group" aria-labelledby="detailCropLabel"></div></div><div class="row" style="flex-wrap:wrap"><button class="btn tiny" id="previewSelection">${icon('play')}Preview selection</button><button class="btn tiny" id="saveCrop">Save as new clip</button></div><p class="helper">Assign uses only the selected part. Save as new clip writes a separate cropped file to your library.</p><hr class="section-rule"><div class="field"><label for="assignPad">Assign to a pad in this bank</label><select id="assignPad">${Array.from({ length: 16 }, (_, i) => `<option value="pad${i + 1}"${selected === 'pad' + (i + 1) ? ' selected' : ''}>Pad ${i + 1} · ${esc(controls()['pad' + (i + 1)].label)}</option>`).join('')}</select></div><button class="btn" id="assignClip">Assign clip</button><p class="helper" id="clipMetadata"></p>`;
  const crop = cropper($('detailCrop'), c.path, 0, 0);
  $('detailPreview').onclick = () => safe(() => call('previewAudio', { path: c.path }));
  $('previewSelection').onclick = () =>
    safe(() => call('previewAudio', { path: c.path, control: { trimStart: crop.start, trimEnd: crop.trimEnd } }));
  $('saveCrop').onclick = () =>
    safe(async () => {
      let clip = await call('cropClip', { path: c.path, start: crop.start, end: crop.end });
      await loadLibrary();
      chosenClip = library.find((x) => x.path === clip.path) || chosenClip;
      renderLibrary();
      renderClipDetail();
      toast('Saved ' + clip.name);
    });
  $('detailInspect').onclick = () =>
    safe(async () => {
      let info = await call('inspectAudio', { path: c.path });
      $('clipMetadata').textContent = info.duration.toFixed(2) + ' seconds';
    });
  $('assignClip').onclick = () =>
    safe(async () => {
      let id = $('assignPad').value;
      let cfg = clone(controls()[id]);
      cfg.action = 'playAudio';
      cfg.value = c.path;
      cfg.audioName = c.name;
      cfg.trimStart = crop.start;
      cfg.trimEnd = crop.trimEnd;
      await mutate('saveControl', { ...context(), id, control: cfg });
      toast(c.name + ' assigned to ' + cfg.label);
    });
}
function renderProfiles() {
  if (!store) return;
  let query = $('profileSearch').value.toLowerCase();
  const shown = store.profiles.filter((p) => p.name.toLowerCase().includes(query));
  if (!shown.length) {
    $('profilesGrid').innerHTML =
      `<div class="panel empty">${icon('search')}<p>No profiles match your search.</p></div>`;
    return;
  }
  $('profilesGrid').innerHTML = shown
    .map(
      (p) =>
        `<article class="profile-card${p.id === store.activeProfile ? ' active' : ''}"><div class="row"><svg style="color:var(--accent)"><use href="#i-layers"/></svg><div class="spacer"></div><span class="tag${p.id === store.activeProfile ? ' good' : ''}">${p.id === store.activeProfile ? 'Active' : 'Profile'}</span></div><h2>${esc(p.name)}</h2><p class="muted">${p.pages.length} page${p.pages.length === 1 ? '' : 's'}</p><div class="profile-colors">${Object.values(
          p.pages[0].banks.A,
        )
          .slice(0, 8)
          .map((c) => `<i style="background:${esc(c.color)}"></i>`)
          .join('')}</div><button class="btn tiny" data-profile="${esc(p.id)}">Open workspace</button></article>`,
    )
    .join('');
  for (let b of $('profilesGrid').querySelectorAll('[data-profile]'))
    b.onclick = () =>
      safe(async () => {
        await mutate('switchProfile', { id: b.dataset.profile });
        await showView('studio');
      });
}
function modal(title, body, choices = null) {
  modalPreviousFocus = document.activeElement;
  $('modalTitle').textContent = title;
  $('modalBody').innerHTML = body;
  $('modal').classList.remove('hidden');
  $('modalCancel').textContent = choices?.[0]?.label || 'Cancel';
  $('modalAccept').textContent = choices?.[1]?.label || 'Save';
  setTimeout(() => ($('modalBody').querySelector('input') || $('modalAccept')).focus(), 20);
  return new Promise((resolve) => {
    modalResolve = resolve;
    const close = (value) => {
      $('modal').classList.add('hidden');
      modalResolve = null;
      modalPreviousFocus?.focus();
      resolve(value);
    };
    $('modalCancel').onclick = () => close(choices?.[0]?.value ?? null);
    $('modalAccept').onclick = () =>
      close(choices?.[1]?.value ?? ($('modalBody').querySelector('input')?.value || true));
    window.closeStudioModal = () => close(null);
  });
}
async function nameDialog(title, initial = '') {
  return modal(
    title,
    `<div class="field"><label for="modalName">Name</label><input id="modalName" maxlength="80" value="${esc(initial)}"></div>`,
  );
}
function connect() {
  let data = {};
  for (const [id, key] of [
    ['performanceInput', 'performanceInput'],
    ['rgbInputPort', 'rgbInput'],
    ['rgbOutputPort', 'rgbOutput'],
  ])
    if ($(id).value !== '') data[key] = Number($(id).value);
  return call('connect', data);
}
function rgbContext() {
  return { ...context(), preset: state?.rgb?.activePreset ?? Number($('rgbPreset').value) };
}
async function importForEditor(paths = null) {
  const captured = clone(target);
  const capturedControl = collect();
  const values = await call(paths ? 'importAudio' : 'chooseAudio', paths ? { paths } : {});
  if (!values?.length) return;
  const value = values[0];
  let cfg = capturedControl;
  cfg.action = 'playAudio';
  cfg.value = value.path;
  cfg.audioName = value.name;
  cfg.trimStart = 0;
  cfg.trimEnd = 0;
  await call('saveControl', { ...captured, control: cfg });
  if (JSON.stringify(target) === JSON.stringify(captured)) {
    dirty = false;
    await refresh();
    loadEditor();
  } else await refresh();
  toast('Clip assigned to ' + capturedControl.label);
}
async function dropFiles(event) {
  event.preventDefault();
  $('audioDrop').classList.remove('drag');
  let files = [...event.dataTransfer.files];
  if (!files.length) return;
  window.pendingDrop = { target: clone(target), control: collect() };
  if (window.nativeDropEnabled) return;
  let paths = files.map((f) => f.pywebviewFullPath || f.path).filter(Boolean);
  if (paths.length) return importForEditor(paths);
  toast('Use Browse to select this clip; Windows did not expose a path for this drop.', true);
}
const fmtTime = (t) => {
  t = Math.max(0, Number(t) || 0);
  return Math.floor(t / 60) + ':' + (t % 60).toFixed(2).padStart(5, '0');
};
function loadWave(path) {
  if (!waves.has(path))
    waves.set(
      path,
      call('waveform', { path, width: 800 }).catch((e) => {
        waves.delete(path);
        throw e;
      }),
    );
  return waves.get(path);
}
function cropper(host, path, start, end, onChange) {
  host.innerHTML = `<div class="crop"><div class="crop-track"><canvas aria-hidden="true"></canvas><div class="crop-shade left"></div><div class="crop-shade right"></div><div class="crop-region" title="Drag to move the selection"></div><div class="crop-playhead hidden"></div><button type="button" class="crop-handle" role="slider" aria-label="Crop start" disabled></button><button type="button" class="crop-handle" role="slider" aria-label="Crop end" disabled></button><div class="crop-loading">Reading waveform…</div></div></div><div class="row crop-times"><span class="helper grow" data-times style="margin:0"></span><button type="button" class="btn ghost tiny" data-reset disabled>Full clip</button></div>`;
  const box = host.querySelector('.crop'),
    canvas = box.querySelector('canvas'),
    [hs, he] = box.querySelectorAll('.crop-handle'),
    region = box.querySelector('.crop-region'),
    MIN = 0.05;
  let wave = null,
    s = Number(start) || 0,
    e = Number(end) || 0,
    drag = null;
  const D = () => (wave ? wave.duration : 0);
  const clamp = () => {
    let d = D();
    s = Math.max(0, Math.min(s, d - MIN));
    if (!(e > 0) || e > d) e = d;
    e = Math.max(s + MIN, Math.min(e, d));
  };
  const round = (v) => Math.round(v * 100) / 100;
  const api = {
    path,
    box,
    get start() {
      return round(s);
    },
    get end() {
      return round(e);
    },
    get trimEnd() {
      return !wave || e >= D() - 0.005 ? 0 : round(e);
    },
    set(a, b) {
      s = Number(a) || 0;
      e = Number(b) || 0;
      if (wave) {
        clamp();
        paint();
      }
    },
    playhead(position) {
      let ph = box.querySelector('.crop-playhead');
      ph.classList.toggle('hidden', position == null || !wave);
      if (position != null && wave) ph.style.left = Math.max(0, Math.min(100, (position / D()) * 100)) + '%';
    },
  };
  const emit = () => onChange?.(api.start, api.trimEnd);
  function draw() {
    if (!wave) return;
    let w = canvas.clientWidth,
      h = canvas.clientHeight,
      r = devicePixelRatio || 1;
    if (!w || !h) return;
    canvas.width = Math.round(w * r);
    canvas.height = Math.round(h * r);
    let c = canvas.getContext('2d');
    c.scale(r, r);
    c.clearRect(0, 0, w, h);
    let p = wave.peaks,
      n = p.length,
      d = D(),
      cols = Math.max(1, Math.floor(w));
    for (let x = 0; x < cols; x++) {
      let a = Math.floor((x / cols) * n),
        b = Math.max(a + 1, Math.floor(((x + 1) / cols) * n)),
        m = 0;
      for (let i = a; i < b && i < n; i++) m = Math.max(m, p[i]);
      let t = ((x + 0.5) / cols) * d,
        amp = Math.max(0.5, m * (h / 2 - 6));
      c.fillStyle = t >= s && t <= e ? '#72d4d4' : '#3b4656';
      c.fillRect((x * w) / cols, h / 2 - amp, Math.max(1, w / cols - 0.35), amp * 2);
    }
  }
  function paint() {
    let d = D() || 1,
      ps = (s / d) * 100,
      pe = (e / d) * 100;
    box.querySelector('.crop-shade.left').style.width = ps + '%';
    box.querySelector('.crop-shade.right').style.width = 100 - pe + '%';
    region.style.left = ps + '%';
    region.style.width = pe - ps + '%';
    hs.style.left = ps + '%';
    he.style.left = pe + '%';
    for (const [el, v] of [
      [hs, s],
      [he, e],
    ]) {
      el.setAttribute('aria-valuemin', '0');
      el.setAttribute('aria-valuemax', D().toFixed(2));
      el.setAttribute('aria-valuenow', v.toFixed(2));
      el.setAttribute('aria-valuetext', fmtTime(v));
    }
    host.querySelector('[data-times]').textContent =
      `Start ${fmtTime(s)} · End ${fmtTime(e)} · Length ${fmtTime(e - s)}`;
    draw();
  }
  const at = (x) => {
    let b = box.firstElementChild.getBoundingClientRect();
    return Math.max(0, Math.min(1, (x - b.left) / b.width)) * D();
  };
  function move(ev) {
    let t = at(ev.clientX);
    if (drag.move) {
      s = Math.max(0, Math.min(t - drag.offset, D() - drag.length));
      e = s + drag.length;
    } else if (drag.edge === 's') s = Math.max(0, Math.min(t, e - MIN));
    else e = Math.min(D(), Math.max(t, s + MIN));
    paint();
  }
  box.addEventListener('pointerdown', (ev) => {
    if (!wave || ev.button) return;
    let t = at(ev.clientX),
      handle = ev.target.closest('.crop-handle');
    if (handle) drag = { edge: handle === hs ? 's' : 'e' };
    else if (ev.target === region) drag = { move: true, offset: t - s, length: e - s };
    else drag = { edge: Math.abs(t - s) < Math.abs(t - e) ? 's' : 'e' };
    drag.from = [s, e];
    box.classList.toggle('moving', !!drag.move);
    box.setPointerCapture(ev.pointerId);
    ev.preventDefault();
    (handle || (drag.edge === 's' ? hs : he)).focus({ preventScroll: true });
    if (!drag.move && !handle) move(ev);
  });
  box.addEventListener('pointermove', (ev) => {
    if (drag) move(ev);
  });
  for (const type of ['pointerup', 'pointercancel'])
    box.addEventListener(type, () => {
      if (!drag) return;
      let changed = drag.from[0] !== s || drag.from[1] !== e;
      drag = null;
      box.classList.remove('moving');
      if (changed) emit();
    });
  for (const [el, edge] of [
    [hs, 's'],
    [he, 'e'],
  ])
    el.addEventListener('keydown', (ev) => {
      let step = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -10, PageUp: 10 }[ev.key];
      if (step == null && !['Home', 'End'].includes(ev.key)) return;
      ev.preventDefault();
      step = (step || 0) * (ev.shiftKey ? 1 : 0.1);
      if (edge === 's')
        s = ev.key === 'Home' ? 0 : ev.key === 'End' ? e - MIN : Math.max(0, Math.min(s + step, e - MIN));
      else e = ev.key === 'Home' ? s + MIN : ev.key === 'End' ? D() : Math.min(D(), Math.max(e + step, s + MIN));
      paint();
      emit();
    });
  host.querySelector('[data-reset]').onclick = () => {
    s = 0;
    e = D();
    paint();
    emit();
  };
  new ResizeObserver(draw).observe(box);
  croppers.add(api);
  loadWave(path)
    .then((w) => {
      wave = w;
      clamp();
      box.querySelector('.crop-loading')?.remove();
      for (const el of [hs, he, host.querySelector('[data-reset]')]) el.disabled = false;
      paint();
    })
    .catch((err) => {
      let el = box.querySelector('.crop-loading');
      if (el) el.textContent = 'Waveform unavailable: ' + err.message;
    });
  return api;
}
function renderEditorCrop() {
  let path = $('actionSelect').value === 'playAudio' ? $('valueInput').value : '';
  if (!path) {
    editorCrop = null;
    $('editorCrop').innerHTML = '<p class="helper" style="margin:0">Assign a clip to crop it.</p>';
    return;
  }
  if (editorCrop?.path === path && editorCrop.box.isConnected) {
    editorCrop.set($('trimStart').value, $('trimEnd').value);
    return;
  }
  editorCrop = cropper($('editorCrop'), path, $('trimStart').value, $('trimEnd').value, (a, b) => {
    $('trimStart').value = a;
    $('trimEnd').value = b;
    markDirty();
  });
}
function updatePlayheads() {
  if (!state) return;
  for (const c of croppers) {
    if (!c.box.isConnected) {
      croppers.delete(c);
      continue;
    }
    let p = state.audio.players.find((p) => p.path.toLowerCase() === c.path.toLowerCase());
    c.playhead(p ? p.position : null);
  }
}
function renderDownload() {
  let d = state?.download || { state: 'idle' },
    running = ['fetching', 'downloading', 'converting'].includes(d.state);
  if (handledJob === undefined) handledJob = running ? null : d.job || null;
  let text =
    {
      fetching: 'Looking up the video…',
      downloading:
        'Downloading' + (d.title ? ' “' + d.title + '”' : '') + (d.percent != null ? ' · ' + d.percent + '%' : ''),
      converting: 'Converting to MP3…',
      done: 'Saved ' + (d.clip?.name || '') + (d.assign ? ' and assigned to ' + d.assign.id : ''),
      error: d.message || 'Download failed',
      cancelled: 'Download cancelled',
    }[d.state] || '';
  for (const el of document.querySelectorAll('[data-yt-status]')) {
    el.classList.toggle('hidden', d.state === 'idle');
    el.classList.toggle('error', d.state === 'error');
    el.querySelector('[data-yt-text]').textContent = text;
    el.querySelector('[data-yt-bar]').style.width =
      (['converting', 'done'].includes(d.state) ? 100 : d.percent || 0) + '%';
    el.querySelector('[data-yt-cancel]').classList.toggle('hidden', !running);
  }
  for (const id of ['ytGo', 'ytEditorGo']) $(id).disabled = running;
  if (!d.job || d.job === handledJob || running) return;
  handledJob = d.job;
  if (d.state !== 'done') return;
  toast('YouTube audio saved: ' + d.clip.name);
  if (view === 'soundboard') safe(loadLibrary);
  if (d.assign && target && dirty && JSON.stringify(d.assign) === JSON.stringify(target)) {
    draft.value = d.clip.path;
    draft.audioName = d.clip.name;
    chooseAction('playAudio');
    $('valueInput').value = d.clip.path;
    $('assignedAudioName').textContent = d.clip.name;
    $('trimStart').value = 0;
    $('trimEnd').value = 0;
    renderFields();
  }
}
async function youtubeImport(input, assign) {
  await call('youtubeImport', { url: $(input).value, assign });
  $(input).value = '';
  await refresh();
}
document.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => safe(() => showView(b.dataset.view))));
$('editorForm').onsubmit = (e) => {
  e.preventDefault();
  safe(saveEditor);
};
$('editorForm').addEventListener('input', (e) => {
  if (['actionPicker', 'ytEditorUrl'].includes(e.target.id)) return;
  markDirty();
});
$('editorForm').addEventListener('change', (e) => {
  if (!['actionPicker', 'ytEditorUrl'].includes(e.target.id)) markDirty();
});
// Action picker: a combobox that filters as you type; arrows move, Enter chooses, Escape closes.
function renderCombo(query = '') {
  const q = query.trim().toLowerCase();
  const chosen = $('actionSelect').value;
  const groups = new Map();
  for (const item of actionChoices())
    if (!q || item[1].toLowerCase().includes(q) || item[2].toLowerCase().includes(q)) {
      if (!groups.has(item[2])) groups.set(item[2], []);
      groups.get(item[2]).push(item);
    }
  comboItems = [...groups.values()].flat();
  let index = 0;
  $('actionList').innerHTML = comboItems.length
    ? [...groups]
        .map(
          ([group, items], g) =>
            `<div role="group" aria-labelledby="actionGroup${g}"><div class="combo-group" id="actionGroup${g}" role="presentation">${esc(group)}</div>${items
              .map(
                ([id, text]) =>
                  `<div class="combo-option" role="option" id="actionOption${index}" data-index="${index++}" aria-selected="${id === chosen}"><span>${esc(text)}</span>${id === chosen ? icon('check') : ''}</div>`,
              )
              .join('')}</div>`,
        )
        .join('')
    : '<div class="combo-empty">No actions match. Try another word.</div>';
  setComboActive(q ? (comboItems.length ? 0 : -1) : comboItems.findIndex((a) => a[0] === chosen));
}
function setComboActive(index) {
  comboActive = index;
  let active = null;
  for (const option of $('actionList').querySelectorAll('[role="option"]')) {
    option.classList.toggle('active', Number(option.dataset.index) === index);
    if (Number(option.dataset.index) === index) active = option;
  }
  if (!active) return $('actionPicker').removeAttribute('aria-activedescendant');
  $('actionPicker').setAttribute('aria-activedescendant', active.id);
  // Scroll the list only (not the page); the first option of a group brings its heading along.
  const list = $('actionList');
  const heading = active.previousElementSibling?.classList.contains('combo-group')
    ? active.previousElementSibling
    : null;
  const top = (heading || active).offsetTop,
    bottom = active.offsetTop + active.offsetHeight;
  if (top < list.scrollTop) list.scrollTop = top;
  else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
}
function openCombo(query = '') {
  comboOpen = true;
  $('actionList').classList.remove('hidden');
  $('actionPicker').setAttribute('aria-expanded', 'true');
  renderCombo(query);
}
function closeCombo() {
  if (!comboOpen) return;
  comboOpen = false;
  $('actionList').classList.add('hidden');
  $('actionPicker').setAttribute('aria-expanded', 'false');
  $('actionPicker').removeAttribute('aria-activedescendant');
  $('actionPicker').value = label($('actionSelect').value);
}
function pickAction(index) {
  const item = comboItems[index];
  closeCombo();
  if (item) chooseAction(item[0]);
}
$('actionPicker').onclick = () => {
  if (comboOpen) return closeCombo();
  openCombo();
  $('actionPicker').select();
};
$('actionPicker').oninput = () => openCombo($('actionPicker').value);
$('actionPicker').onblur = closeCombo;
$('actionPicker').onkeydown = (e) => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (!comboOpen) return openCombo();
    const count = comboItems.length,
      step = e.key === 'ArrowDown' ? 1 : -1;
    if (count) setComboActive(((comboActive < 0 ? (step > 0 ? -1 : count) : comboActive) + step + count) % count);
  } else if (e.key === 'Enter') {
    // Enter chooses an action here; it does not submit (save) the form.
    e.preventDefault();
    if (!comboOpen) openCombo();
    else if (comboActive >= 0) pickAction(comboActive);
  } else if (e.key === 'Escape' && comboOpen) {
    e.preventDefault();
    e.stopPropagation();
    closeCombo();
    $('actionPicker').select();
  }
};
// Clicks in the list keep focus in the picker, so blur does not close it first.
$('actionList').onmousedown = (e) => e.preventDefault();
$('actionList').onclick = (e) => {
  const option = e.target.closest('[role="option"]');
  if (option) pickAction(Number(option.dataset.index));
};
$('actionList').onmousemove = (e) => {
  const option = e.target.closest('[role="option"]');
  if (option && Number(option.dataset.index) !== comboActive) setComboActive(Number(option.dataset.index));
};
// Shortcut fields: Record captures the next key press; typing by hand works too.
for (const id of ['shortcutInput', 'ccwInput', 'cwInput']) {
  wireRecorder($(id), () => {
    markDirty();
    renderShortcutHelp();
  });
  $(id).addEventListener('input', renderShortcutHelp);
}
window.addEventListener(
  'keydown',
  (e) => {
    if (!recording) return;
    // While recording, keys go to the recorder only: Ctrl+S records Ctrl + S instead of saving.
    e.preventDefault();
    e.stopPropagation();
    const held = heldKeys(e),
      key = keyName(e);
    if (e.key === 'Escape' && !held.length) return stopRecording(false);
    if (key && !MODIFIER_KEYS.includes(key)) {
      recording.input.value = shortcutText([...held, key].join('+'));
      return stopRecording(true);
    }
    recording.input.value = heldText(held);
  },
  true,
);
window.addEventListener(
  'keyup',
  (e) => {
    if (!recording) return;
    e.preventDefault();
    e.stopPropagation();
    recording.input.value = heldText(heldKeys(e));
  },
  true,
);
$('revertControl').onclick = () => {
  loadEditor();
  toast('Changes discarded');
};
// Which editor sections are open is kept in settings: pages loaded into WebView2 have no browser storage.
const editorSections = () => [...document.querySelectorAll('#editorForm [data-section]')];
function applySections(saved) {
  for (const section of editorSections()) section.open = saved?.[section.dataset.section] !== false;
}
for (const section of editorSections())
  section.addEventListener('toggle', () => {
    if (!store) return;
    const open = Object.fromEntries(editorSections().map((s) => [s.dataset.section, s.open]));
    if (JSON.stringify(open) === JSON.stringify(store.settings.editorSections)) return;
    store.settings.editorSections = open;
    call('editorSections', open).catch(() => {});
  });
$('audioVolume').oninput = () => ($('clipGainValue').textContent = $('audioVolume').value + '%');
$('colorInput').oninput = () => {
  $('colorHex').value = $('colorInput').value;
  draft.color = $('colorInput').value;
  $('selectedSwatch').style.setProperty('--color', draft.color);
  renderColorState();
};
$('colorHex').oninput = () => {
  if (/^#[0-9a-f]{6}$/i.test($('colorHex').value)) {
    $('colorInput').value = $('colorHex').value;
    draft.color = $('colorHex').value;
    renderColorState();
  }
};
$('palette').innerHTML = COLORS.map(
  (c) =>
    `<button type="button" title="${c}" aria-label="Choose ${c}" style="--swatch:${c}" data-color="${c}"></button>`,
).join('');
$('palette')
  .querySelectorAll('button')
  .forEach(
    (b) =>
      (b.onclick = () => {
        $('colorInput').value = b.dataset.color;
        $('colorHex').value = b.dataset.color;
        draft.color = b.dataset.color;
        markDirty();
        renderColorState();
      }),
  );
$('browseBtn').onclick = () =>
  safe(async () => {
    let value = await call('browse');
    if (value) {
      $('valueInput').value = value;
      markDirty();
    }
  });
$('learnBtn').onclick = () => safe(() => call(sameControl(state?.learning, target) ? 'cancelLearn' : 'learn', target));
$('clearLearn').onclick = () => {
  draft.mapping = null;
  markDirty();
  renderMapping();
};
$('testAction').onclick = () => safe(() => call('testAction', { ...target, control: collect() }));
$('copySelected').onclick = () =>
  safe(async () => {
    await saveEditor();
    await mutate('copyControls', { ...target, source: selected, ids: [...multi].filter((id) => id !== selected) });
    toast('Configuration copied; MIDI assignments preserved');
  });
$('audioDrop').onclick = () => safe(() => importForEditor());
for (const ev of ['dragenter', 'dragover'])
  $('audioDrop').addEventListener(ev, (e) => {
    e.preventDefault();
    $('audioDrop').classList.add('drag');
  });
$('audioDrop').addEventListener('dragleave', () => $('audioDrop').classList.remove('drag'));
$('audioDrop').addEventListener('drop', (e) => safe(() => dropFiles(e)));
$('previewClip').onclick = () => safe(() => call('previewAudio', { control: collect() }));
$('selectFromLibrary').onclick = () => safe(() => showView('soundboard'));
$('addStep').onclick = () => {
  if (draft.steps.length >= 32) return toast('Maximum 32 steps', true);
  draft.steps.push({ type: 'delay', milliseconds: 250, value: '' });
  markDirty();
  renderSteps();
};
$('macroPreview').onclick = () =>
  safe(async () => {
    let steps = await call('macroPreview', { ...target, control: collect() });
    await modal(
      'Macro dry-run',
      steps.length
        ? steps.map((s, i) => `<p class="helper">${i + 1}. ${esc(s.description)}</p>`).join('')
        : '<p class="muted">No steps yet. Nothing will execute.</p>',
      [
        { label: 'Close', value: null },
        { label: 'Done', value: true },
      ],
    );
  });
$('cancelMacros').onclick = () => safe(() => call('cancelActions'));
for (const id of ['connectBtn', 'deviceConnect']) $(id).onclick = () => safe(connect);
$('deviceDisconnect').onclick = () => safe(() => call('disconnect'));
$('refreshPorts').onclick = () =>
  safe(async () => {
    await call('refresh');
    await refresh();
  });
for (const id of ['readRGB', 'deviceRead']) $(id).onclick = () => safe(() => call('readRGB', rgbContext()));
for (const id of ['applyRGB', 'deviceApply'])
  $(id).onclick = () =>
    safe(async () => {
      if (dirty) await saveEditor();
      await call('applyRGB', {
        ...rgbContext(),
        ids: multi.size ? [...multi].filter((id) => id.startsWith('pad')) : null,
      });
    });
$('cancelRGB').onclick = () => safe(() => call('cancelRGB'));
for (const id of ['identifyRGB', 'deviceIdentify']) $(id).onclick = () => safe(() => call('identifyRGB', rgbContext()));
for (const id of ['confirmPreset', 'confirmPresetBar'])
  $(id).onclick = () =>
    safe(async () => {
      let r = await mutate('confirmPreset', { preset: state.rgb.identified.preset });
      toast(
        r.detecting
          ? 'Preset confirmed. Studio now follows the hardware preset automatically.'
          : 'Preset confirmed. Confirm one more preset to turn on auto-detect.',
      );
    });
$('deviceSave').onclick = () => safe(() => call('saveRGB'));
$('adoptRGB').onclick = () => safe(() => mutate('adoptRGB', rgbContext()));
$('pauseBtn').onclick = () =>
  safe(async () => {
    await call('pause');
    await refresh();
  });
$('stopAudioBtn').onclick = () => safe(() => call('stopAudio'));
$('undoBtn').onclick = () =>
  safe(async () => {
    dirty = false;
    const undone = await mutate('undo');
    loadEditor();
    toast(undone ? 'Undone: ' + undone : 'Nothing to undo');
  });
$('performanceBtn').onclick = () =>
  safe(async () => {
    if (!(await allowSelection())) return;
    performance = !performance;
    $('view-studio').classList.toggle('performance', performance);
    $('performanceBtn').innerHTML = icon('play') + (performance ? 'Back to editing' : 'Performance');
    $('canvasHint').textContent = performance
      ? 'Click a pad to execute its action'
      : 'Select to edit · Ctrl-click to select several';
  });
$('profileSelect').onchange = () =>
  safe(async () => {
    if (await allowSelection()) {
      await mutate('switchProfile', { id: $('profileSelect').value });
      loadEditor();
    } else renderStore();
  });
$('pageSelect').onchange = () =>
  safe(async () => {
    if (await allowSelection()) {
      await mutate('switchPage', { id: $('pageSelect').value });
      loadEditor();
    } else renderStore();
  });
for (const bank of 'ABCDEFGH')
  $('bank' + bank).onclick = () =>
    safe(async () => {
      if (await allowSelection()) {
        await mutate('switchPage', { bank });
        loadEditor();
      }
    });
$('pinBtn').onclick = () => safe(() => mutate('updateProfile', { pinned: !store.pinned }));
$('newPageBtn').onclick = () =>
  safe(async () => {
    if (!(await allowSelection())) return;
    let name = await nameDialog('New application page');
    if (name) await mutate('newPage', { name });
  });
$('renamePage').onclick = () =>
  safe(async () => {
    let name = await nameDialog('Rename page', page().name);
    if (name) await mutate('renamePage', { name });
  });
$('deletePage').onclick = () =>
  safe(async () => {
    if (!(await allowSelection())) return;
    const name = page().name;
    const confirmed = await modal(
      'Delete page?',
      `<p class="muted">Delete ${esc(name)} and all of its banks? You can restore it with Undo.</p>`,
      [
        { label: 'Keep page', value: null },
        { label: 'Delete page', value: true },
      ],
    );
    if (!confirmed) return;
    await mutate('deletePage');
    loadEditor();
    toast(name + ' deleted');
  });
$('newProfile').onclick = () =>
  safe(async () => {
    let name = await nameDialog('New profile');
    if (name) await mutate('newProfile', { name });
  });
$('duplicateProfile').onclick = () => safe(() => mutate('duplicateProfile'));
$('deleteProfile').onclick = () =>
  safe(async () => {
    let result = await modal(
      'Delete profile?',
      `<p class="muted">Delete ${esc(current().name)}? You can restore it with Undo.</p>`,
      [
        { label: 'Keep profile', value: null },
        { label: 'Delete profile', value: true },
      ],
    );
    if (result) await mutate('deleteProfile');
  });
$('saveProfile').onclick = () =>
  safe(async () => {
    await mutate('updateProfile', { name: $('profileName').value, apps: $('profileApps').value });
    toast('Profile settings saved');
  });
$('profileSearch').oninput = renderProfiles;
$('importProfile').onclick = () =>
  safe(async () => {
    if (await mutate('importProfile')) toast('Profile imported');
  });
$('exportProfile').onclick = () =>
  safe(async () => {
    if (await call('exportProfile')) toast('Profile bundle exported with audio');
  });
$('ytGo').onclick = () => safe(() => youtubeImport('ytUrl', null));
$('ytEditorGo').onclick = () => safe(() => youtubeImport('ytEditorUrl', clone(target)));
for (const [input, button] of [
  ['ytUrl', 'ytGo'],
  ['ytEditorUrl', 'ytEditorGo'],
])
  $(input).addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      $(button).click();
    }
  });
document.querySelectorAll('[data-yt-cancel]').forEach((b) => (b.onclick = () => safe(() => call('cancelYoutube'))));
for (const id of ['trimStart', 'trimEnd'])
  $(id).addEventListener('input', () => editorCrop?.set($('trimStart').value, $('trimEnd').value));
$('importClips').onclick = () =>
  safe(async () => {
    let clips = await call('chooseAudio');
    if (clips?.length) {
      await loadLibrary();
      toast(clips.length + ' clip(s) imported');
    }
  });
$('librarySearch').oninput = renderLibrary;
$('masterVolume').oninput = () => ($('masterValue').textContent = $('masterVolume').value + '%');
$('masterVolume').onchange = () => safe(() => mutate('masterVolume', { volume: Number($('masterVolume').value) }));
$('liveColor').onchange = () => safe(() => mutate('settings', { liveColor: $('liveColor').value }));
for (const id of ['autoConnect', 'autoProfiles', 'reducedMotion', 'liveFeedback', 'extraBanks'])
  $(id).onchange = () => safe(() => mutate('settings', { [id]: $(id).checked }));
$('quitApp').onclick = () => safe(() => call('quit'));
$('startWithWindows').onchange = () =>
  safe(async () => {
    try {
      const on = await mutate('autostart', { enabled: $('startWithWindows').checked });
      toast(on ? 'Studio will start in the tray when you sign in' : 'Studio will no longer start at sign-in');
    } finally {
      renderAutostart();
    }
  });
function diagnostics() {
  $('diagnostics').classList.toggle('hidden');
}
for (const id of ['diagnosticsBtn', 'footerDiagnostics']) $(id).onclick = diagnostics;
$('closeDiagnostics').onclick = () => $('diagnostics').classList.add('hidden');
$('exportDiagnostics').onclick = () =>
  safe(async () => {
    if (await call('diagnostics')) toast('Troubleshooting report exported');
  });
document.addEventListener('keydown', (e) => {
  if (!$('modal').classList.contains('hidden')) {
    if (e.key === 'Escape') {
      e.preventDefault();
      window.closeStudioModal?.();
    }
    if (e.key === 'Tab') {
      let items = [...$('modal').querySelectorAll('button,input,select,textarea')].filter((el) => !el.disabled);
      let first = items[0],
        last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    return;
  }
  if (e.ctrlKey && e.key.toLowerCase() === 's') {
    e.preventDefault();
    if (view === 'studio') safe(saveEditor);
  }
  if (e.key === 'Escape') {
    call('cancelLearn').catch(() => {});
    $('diagnostics').classList.add('hidden');
  }
});
setOptions(
  $('rgbPreset'),
  Array.from({ length: 8 }, (_, i) => ({ id: String(i), name: 'Preset ' + (i + 1) })),
  '0',
);
$('rgbPreset').onchange = () => {
  renderColorState();
  safe(() => mutate('settings', { hardwarePreset: Number($('rgbPreset').value) }));
};
window.receiveNativeDrop = async (paths) =>
  safe(async () => {
    let captured = window.pendingDrop || { target: clone(target), control: collect() };
    let values = await call('importAudio', { paths });
    if (!values.length) return;
    let cfg = {
      ...captured.control,
      action: 'playAudio',
      value: values[0].path,
      audioName: values[0].name,
      trimStart: 0,
      trimEnd: 0,
    };
    await call('saveControl', { ...captured.target, control: cfg });
    if (JSON.stringify(target) === JSON.stringify(captured.target)) dirty = false;
    await refresh();
    toast('Clip assigned to ' + cfg.label);
  });
window.studioReady = false;
let pollTimer = null;
const startPolling = () => (pollTimer ??= setInterval(refresh, 350));
window.addEventListener('pywebviewready', async () => {
  await refresh();
  window.studioReady = true;
  startPolling();
});
// Pause the 350 ms refresh while the window is hidden in the tray; mappings and audio keep running.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearInterval(pollTimer);
    pollTimer = null;
  } else if (window.studioReady) {
    refresh();
    startPolling();
  }
});
