"""Native state, action queue, profile switching, and the narrow UI bridge."""
from collections import deque
import copy
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import logging
from pathlib import Path
import queue
import shutil
import threading
import time
import uuid

import actions
from audio import Audio
import media
from midi import Transport,RGB,ports,bank_for_note
from store import Store,profile,page,validate_control,number,preset_locator,AUDIO_EXTS,TYPES,BANKS

VERSION='0.8.0'
KNOBS={'volumeKnob':('volumeDown','volumeUp'),'scrollKnob':('scrollDown','scrollUp'),'hscrollKnob':('scrollLeft','scrollRight'),'zoomKnob':('zoomOut','zoomIn'),'tabKnob':('previousTab','nextTab'),'windowKnob':('previousWindow','nextWindow'),'desktopKnob':('desktopLeft','desktopRight')}

def signature(port,data):
    high=data[0]&0xF0;kind={0x80:'note',0x90:'note',0xB0:'cc',0xE0:'pitch',0xD0:'aftertouch',0xC0:'program'}.get(high)
    return {'kind':kind,'channel':data[0]&15,'data1':data[1] if kind not in ['pitch','aftertouch'] else 0,'port':port}

def matches(mapping,sig,primary):
    return mapping and all(mapping.get(k)==sig.get(k) for k in ['kind','channel','data1']) and (mapping.get('port')==sig['port'] if mapping.get('port') else sig['port']==primary)

def delta(previous,value,mode):
    if mode=='relative' or mode=='auto' and value in [1,127,65,63]:
        if value in [1,65]:return 1
        if value in [127,63]:return -1
        return -(128-value) if value>64 else value
    if previous is None:return 0
    # Absolute encoders do not wrap from maximum back to minimum.
    return max(-8,min(8,value-previous))

def foreground_executable():
    user=C.WinDLL('user32');kernel=C.WinDLL('kernel32')
    user.GetForegroundWindow.restype=W.HWND
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)];kernel.CloseHandle.argtypes=[W.HANDLE]
    user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    process=W.DWORD();user.GetWindowThreadProcessId(user.GetForegroundWindow(),C.byref(process))
    handle=kernel.OpenProcess(0x1000,False,process.value)
    if not handle:return ''
    try:
        buf=C.create_unicode_buffer(32768);length=W.DWORD(len(buf))
        return Path(buf.value).name.lower() if kernel.QueryFullProcessImageNameW(handle,0,buf,C.byref(length)) else ''
    finally:kernel.CloseHandle(handle)

class Controller:
    def __init__(self,root,transport=None):
        self.lock=threading.RLock();self.logs=deque(maxlen=300);self.store=Store(root);self.revision=1;self.window=None;self.quitting=False;self.paused=False;self.learning=None;self.previous={};self.primary='';self.connection={'state':'disconnected','message':'Connect your SMC-PAD to begin'};self.rgb_state={'state':'notRead','colors':{},'results':[]};self.last_midi=None;self.available=ports();self.action_queue=queue.Queue(256);self.device_queue=queue.Queue(8);self.cancel_actions=threading.Event();self.stop=threading.Event();self.last_monitor=0;self.calibration={};self._reconnect=None
        self.performance_auto=False;self.performance_candidates=set();self.rgb_epoch=0;self.device_busy=False
        self.hardware_bank_marker=None
        self.live_lit={};self.live_retry=0
        self.download={'state':'idle'};self.download_cancel=threading.Event();self.download_thread=None;self.waveforms={}
        self.audio=Audio(self.event);self.transport=transport or Transport(self.on_midi);self.rgb=RGB(self.transport,self.event)
        self.audio.master=number(self.store.data.get('settings',{}).get('masterVolume'),100,0,100)
        self.action_thread=threading.Thread(target=self._actions,name='Actions',daemon=True);self.action_thread.start()
        self.device_thread=threading.Thread(target=self._devices,name='Device operations',daemon=True);self.device_thread.start()
        self.poll_thread=threading.Thread(target=self._poll,name='Device supervision',daemon=True);self.poll_thread.start()
        if self.store.recovered:self.event('error',{'message':'Profile data was recovered; the original file was preserved.'})

    def event(self,kind,data):
        with self.lock:
            if kind=='rgb':
                if data.get('state') in ['discovering','unavailable','available']:
                    self.rgb_state={'colors':{},'results':[]}
                if 'results' in data:
                    if (data.get('bank'),data.get('preset'))!=(self.rgb_state.get('bank'),self.rgb_state.get('preset')) and 'bank' in data:
                        self.rgb_state['colors']={}
                    for result in data['results']:
                        if result['ok']:self.rgb_state.setdefault('colors',{})[result['pad']]=result['color']
                self.rgb_state.update(copy.deepcopy(data))
            message=data.get('message')
            if message or kind=='error':
                item={'time':time.strftime('%H:%M:%S'),'kind':kind,'message':message or str(data)};self.logs.append(item);logging.info('%s %s',kind,item['message'])

    def _changed(self):self.revision+=1

    def on_midi(self,port,data):
        if not data:
            self.event('error',{'message':'MIDI device reported an input error'});return
        if data[0]>=0xF0:return
        sig=signature(port,data)
        if not sig['kind']:return
        with self.lock,self.store.lock:
            self.last_midi={'port':port,'data':data,'kind':sig['kind'],'channel':sig['channel']+1,'value':data[-1]}
            if self.performance_auto and port in self.performance_candidates and ((sig['kind']=='note' and sig['channel']==9 and bank_for_note(sig['data1'])) or (sig['kind']=='cc' and sig['channel']==0 and 30<=sig['data1']<=37)) and port!=self.primary:
                self.primary=port;self.connection['input']=port
                self.event('device',{'message':'Performance input identified from controller activity: '+port})
            if self.learning:
                target=self.learning;self.learning=None
                p=next(p for p in self.store.data['profiles'] if p['id']==target['profile'])
                pg=next(pg for pg in p['pages'] if pg['id']==target['page'])
                self.store.checkpoint();Store.bank(pg,target['bank'])[target['id']]['mapping']=sig;self.store.persist();self._changed();self.event('learn',{'message':'MIDI learned for '+target['id']+' from '+port});return
            current=self.store.current();bank=current['activeBank']
            if sig['kind']=='note' and sig['channel']==9 and port==self.primary:
                detected=bank_for_note(sig['data1']) or bank
                if detected!=bank:current['activeBank']=detected;bank=detected;self.previous.clear();self._changed()
            controls=copy.deepcopy(self.store.controls(bank=bank))
        for cid,cfg in controls.items():
            if not matches(cfg['mapping'],sig,self.primary):continue
            key=(current['id'],current['activePage'],bank,cid);value=data[2] if len(data)>2 else data[1]
            if cid.startswith('knob'):
                change=delta(self.previous.get(key),value,cfg['encoderMode']);self.previous[key]=value
                self.calibration[cid]={'raw':value,'delta':change,'port':port,'mode':cfg['encoderMode']}
            else:change=None
            if self.paused:continue
            self._trigger(cid,cfg,data,change,key)

    def _trigger(self,cid,cfg,data=None,change=None,key=None):
        if cfg['action']=='none':return
        if data is not None:
            high=data[0]&0xF0;press=not(high==0x80 or high in [0x90,0xB0] and (data[2] if len(data)>2 else 0)==0)
            if cfg['trigger'] in ['press','pressOnly'] and not press and not cid.startswith('knob'):return
            if cfg['trigger']=='releaseOnly' and press:return
        req=copy.deepcopy(cfg);req.update(type=cfg['action'],control=cid,amount=1,mode=cfg['audioMode'],volume=cfg['audioVolume'])
        if cfg['action'].endswith('Knob'):
            change=1 if change is None else change
            if not change:return
            if cfg['invert']:change=-change
            req['amount']=max(1,min(6,round(abs(change)*cfg['sensitivity']*(2 if cfg['acceleration'] and abs(change)>1 else 1))))
            if cfg['action'] in KNOBS:req['type']=KNOBS[cfg['action']][change>0]
            elif cfg['action']=='arrowKnob':req.update(type='shortcut',value='right' if change>0 else 'left')
            elif cfg['action']=='twoWayShortcutKnob':
                parts=cfg['value'].split('|');req.update(type='shortcut',value=(parts[min(1,len(parts)-1)] if change>0 else parts[0]).strip())
        if req['type']=='stopAudio':self.audio.command('stop');return
        try:self.action_queue.put_nowait((req,self.cancel_actions))
        except queue.Full:self.event('error',{'message':'Action queue is full. Pause mappings and try again.'})

    def _perform(self,req):
        if req['type']=='playAudio':return self.audio.command('play',req)
        if req['type']=='stopAudio':return self.audio.command('stop')
        if req['type']=='url' and not str(req['value']).lower().startswith(('https://','http://')):raise ValueError('Websites must use http or https')
        return actions.action(req)

    def _actions(self):
        while not self.stop.is_set():
            try:req,cancel=self.action_queue.get(timeout=.2)
            except queue.Empty:continue
            if cancel.is_set():continue
            try:
                if req['type']=='macro':
                    for step in req.get('steps',[]):
                        if cancel.is_set():break
                        if step['type']=='delay':cancel.wait(step.get('milliseconds',250)/1000)
                        else:self._perform({**req,**step,'amount':1})
                else:self._perform(req)
            except Exception as exc:self.event('error',{'message':'Action failed: '+str(exc)})

    def cancel_macros(self):
        self.cancel_actions.set();self.cancel_actions=threading.Event()

    def _devices(self):
        while not self.stop.is_set():
            try:command,data=self.device_queue.get(timeout=.2)
            except queue.Empty:
                # Keep-alive runs here, between queued operations, so it never
                # occupies the queue and blocks a user's read/apply request.
                try:self.rgb.keep_alive();self._detect_preset();self._live_feedback()
                except Exception as exc:self.event('rgb',{'state':'error','message':str(exc)})
                continue
            if command in ['read','apply','identify','save'] and data.get('epoch')!=self.rgb_epoch:continue
            self.device_busy=True
            try:
                if command in ['read','apply','identify']:
                    # Resolve the live preset when the queued operation actually
                    # runs, rather than trusting a stale dropdown or snapshot.
                    self.rgb.header=self.rgb.read_region(4,0,12)
                    self._detect_preset()
                    active=self.detected_preset()
                    if active is not None:data['preset']=active
                if command=='connect':
                    self.available=ports();requested=data.get('performanceInput')
                    for port_id in list(self.transport.inputs):self.transport.close_input(port_id)
                    self.transport.close_output();self.rgb.port=None;self.rgb.ready=False;self.primary=''
                    self.hardware_bank_marker=None
                    try:self.rgb.discover(self.available,data.get('rgbInput'),data.get('rgbOutput'))
                    except Exception as exc:self.event('rgb',{'state':'unavailable','message':str(exc)})
                    candidates=[p for p in self.available['inputs'] if any(name in p['name'].lower() for name in ['smc','sinco']) and 'private' not in p['name'].lower()]
                    candidates.sort(key=lambda p:(p['id']==self.rgb.port,'midiin3' in p['name'].lower(),p['name'].startswith('MIDIIN')))
                    inp=next((p for p in self.available['inputs'] if p['id']==int(requested)),None) if requested is not None else next(iter(candidates),None)
                    if not inp:raise RuntimeError('No SMC-PAD performance input found. Connect USB and refresh ports.')
                    self.transport.open_input(inp);self.primary=inp['name'];self.connection={'state':'connected','input':inp['name'],'message':'MIDI is active in the background'};self._reconnect=copy.deepcopy(data)
                    self.performance_auto=requested is None;self.performance_candidates={inp['name']}
                    if self.performance_auto:
                        for candidate in candidates:
                            if candidate['name'].lower().startswith('midiin3'):continue
                            try:self.transport.open_input(candidate);self.performance_candidates.add(candidate['name'])
                            except Exception as exc:self.event('device',{'message':'Additional input unavailable: '+str(exc)})
                    self.event('device',{'message':'Connected performance input '+inp['name']})
                elif command=='read':
                    self._live_restore();colors=self.rgb.read_colors(data['preset'],data['bank']);self.rgb_state['colors']=colors
                elif command=='apply':self._live_restore();self.rgb.apply(data['colors'],data['preset'],data['bank'])
                elif command=='identify':self._live_restore();self.rgb.identify(data['preset'],data['bank'])
                elif command=='save':self._live_restore();self.rgb.save()
            except Exception as exc:
                if command=='connect':self.connection={'state':'error','message':str(exc)}
                self.event('rgb' if command in ['read','apply','identify','save'] else 'error',{'state':'error','message':str(exc)})
            finally:self.device_busy=False
        try:self._live_restore()
        except Exception:logging.exception('Live feedback restore failed')

    def _detect_preset(self):
        """Follow the live preset and physical PAD BANK switch."""
        settings=self.store.data['settings'];preset=self.detected_preset()
        if preset is not None and preset!=settings['hardwarePreset']:
            with self.lock,self.store.lock:settings['hardwarePreset']=preset;self.store.persist();self._changed()
            self.event('device',{'message':f'Hardware switched to Preset {preset+1}'})
        bank=self.rgb.active_bank();marker=(preset,bank)
        if bank is not None and marker!=self.hardware_bank_marker:
            self.hardware_bank_marker=marker
            with self.lock,self.store.lock:
                current=self.store.current()
                if current['activeBank']!=bank:
                    current['activeBank']=bank;self.previous.clear();self.store.persist();self._changed()

    def detected_preset(self):
        active=self.rgb.active_preset()
        if active is not None:return active
        located=preset_locator(self.store.data['settings'].get('presetSamples'))
        if self.rgb.port is None or not self.rgb.header or not located:return None
        preset=self.rgb.header[located[0]]-located[1]
        return preset if 0<=preset<=7 else None

    def _live_feedback(self):
        """Light pads while their clips play, then restore the device's own color."""
        settings=self.store.data['settings'];want=set()
        if settings.get('liveFeedback') and self.rgb.port is not None and self.rgb.flash is not None and time.monotonic()>=self.live_retry:
            with self.lock,self.store.lock:bank=self.store.current()['activeBank']
            playing={str(x['control']) for x in self.audio.snapshot()['players']}
            want={(settings['hardwarePreset'],bank,cid) for cid in playing if cid.startswith('pad') and cid[3:].isdigit()}
        elif self.live_lit and time.monotonic()<self.live_retry:return
        if want==set(self.live_lit):return
        try:
            for key in [k for k in self.live_lit if k not in want]:
                preset,bank,cid=key
                if self.rgb.apply({cid:self.live_lit[key]},preset,bank,refresh=False,report=False)[0]['ok']:self.live_lit.pop(key)
                else:raise RuntimeError('Could not restore '+cid)
            for key in sorted(want-set(self.live_lit)):
                preset,bank,cid=key
                if not self.rgb.ready:self.rgb.unlock()
                address=self.rgb.address(int(cid[3:]),preset,bank);original='#'+self.rgb.flash[address:address+3].hex()
                result=self.rgb.apply({cid:settings['liveColor']},preset,bank,refresh=False,report=False)[0]
                if not result['ok']:raise RuntimeError(result['error'])
                self.live_lit[key]=original
        except Exception as exc:
            self.live_retry=time.monotonic()+5;self.event('error',{'message':'Live pad feedback paused for 5 s: '+str(exc)})

    def _live_restore(self):
        for key,color in list(self.live_lit.items()):
            preset,bank,cid=key
            if self.rgb.port is None:break
            if self.rgb.apply({cid:color},preset,bank,refresh=False,report=False)[0]['ok']:self.live_lit.pop(key)

    def _poll(self):
        tick=0
        while not self.stop.wait(.5):
            tick+=1
            try:
                if tick%4==0:
                    self.available=ports()
                    if self.primary and self.primary not in [p['name'] for p in self.available['inputs']]:
                        self.rgb.cancel.set();self.rgb.ready=False;self.connection={'state':'disconnected','message':'USB disconnected — waiting to reconnect'};self.primary='';self.event('device',{'message':'USB disconnected'})
                    elif not self.primary and self._reconnect and any('smc' in p['name'].lower() for p in self.available['inputs']) and self.device_queue.empty():self.device_queue.put_nowait(('connect',self._reconnect))
                if self.store.data['settings'].get('autoProfiles') and not self.store.data.get('pinned',True):
                    app=foreground_executable()
                    if 'smc-pad' in app:continue
                    target=next((p for p in self.store.data['profiles'] if app in p.get('apps',[])),None)
                    if target and target['id']!=self.store.data['activeProfile']:
                        with self.lock,self.store.lock:self.store.data['activeProfile']=target['id'];self.previous.clear();self._changed()
                        self.event('profile',{'message':'Profile switched for '+app})
            except Exception as exc:self.event('error',{'message':'Background check: '+str(exc)})

    def _target(self,data):
        p=next(p for p in self.store.data['profiles'] if p['id']==data.get('profile',self.store.data['activeProfile']))
        pg=next(pg for pg in p['pages'] if pg['id']==data.get('page',p['activePage']))
        return Store.bank(pg,data.get('bank',p['activeBank']))

    def request(self,command,data=None):
        """Only this explicit command allowlist is exposed to the local UI."""
        data=data or {}
        try:return {'ok':True,'value':self._request(command,data)}
        except Exception as exc:
            logging.exception('UI command %s failed',command);self.event('error',{'message':str(exc)});return {'ok':False,'error':str(exc)}

    def _request(self,command,data):
        if command=='snapshot':
            with self.lock,self.store.lock:
                located=preset_locator(self.store.data['settings'].get('presetSamples'))
                active=self.detected_preset()
                rgb={**copy.deepcopy(self.rgb_state),'activePreset':active,'activeBank':self.rgb.active_bank(),'presetDetection':{'located':active is not None,'presets':len({x['preset'] for x in self.store.data['settings'].get('presetSamples',[])})}}
                result={'version':VERSION,'revision':self.revision,'connection':copy.deepcopy(self.connection),'rgb':rgb,'ports':copy.deepcopy(self.available),'audio':self.audio.snapshot(),'paused':self.paused,'learning':self.learning,'midi':self.last_midi,'calibration':copy.deepcopy(self.calibration),'logs':list(self.logs)[-70:],'droppedMidi':self.transport.dropped,'download':copy.deepcopy(self.download)}
                if data.get('revision')!=self.revision:result['store']=self.store.snapshot()
                return result
        if command=='refresh':self.available=ports();return self.available
        if command=='connect':self.device_queue.put_nowait(('connect',copy.deepcopy(data)));return True
        if command=='cancelRGB':self.rgb_epoch+=1;self.rgb.cancel.set();return True
        if command=='disconnect':
            self.rgb.cancel.set()
            with self.rgb.lock:
                for port in list(self.transport.inputs):self.transport.close_input(port)
                self.transport.close_output();self.rgb.port=None;self.rgb.ready=False;self.primary='';self._reconnect=None;self.connection={'state':'disconnected','message':'Device disconnected'}
            return True
        if command=='saveRGB':
            if self.rgb.port is None:raise RuntimeError('Connect the device configuration port first')
            if self.device_busy or not self.device_queue.empty():raise RuntimeError('Wait for the current device operation, or cancel it first')
            self.device_queue.put_nowait(('save',{'epoch':self.rgb_epoch}));return True
        if command=='confirmPreset':
            if not self.rgb.header:raise RuntimeError('Connect and read the device first')
            preset=int(number(data.get('preset'),0,0,7))
            with self.lock,self.store.lock:
                settings=self.store.data['settings']
                samples=[x for x in settings['presetSamples'] if x['preset']!=preset]+[{'header':self.rgb.header.hex(),'preset':preset}]
                settings['presetSamples']=samples[-8:];settings['hardwarePreset']=preset
                self.rgb_state.pop('identified',None);self.store.persist();self._changed()
            return {'detecting':self.detected_preset() is not None,'presets':len({x['preset'] for x in settings['presetSamples']})}
        if command in ['readRGB','applyRGB','identifyRGB']:
            if self.rgb.port is None:raise RuntimeError('Connect the device configuration port first')
            if self.device_busy or not self.device_queue.empty():raise RuntimeError('Wait for the current device operation, or cancel it first')
            payload={'preset':int(number(data.get('preset'),0,0,7)),'bank':data.get('bank','A'),'epoch':self.rgb_epoch}
            if payload['bank'] not in BANKS:raise ValueError('Invalid bank')
            if command=='applyRGB':
                payload['colors']={cid:c['color'] for cid,c in self._target(data).items() if cid.startswith('pad') and (data.get('ids') is None or cid in data['ids'])}
                if not payload['colors']:raise ValueError('Select at least one pad to apply hardware colors')
            self.rgb_state.pop('identified',None)
            self.device_queue.put_nowait(({'readRGB':'read','applyRGB':'apply','identifyRGB':'identify'}[command],payload));return True
        if command=='adoptRGB':
            with self.lock,self.store.lock:
                if self.rgb_state.get('bank')!=data.get('bank',self.store.current()['activeBank']):raise ValueError('Read colors from this bank first')
                target=self._target(data);self.store.checkpoint()
                for cid,color in self.rgb_state.get('colors',{}).items():target[cid]['color']=color
                self.store.persist();self._changed();return True
        if command=='pause':self.paused=bool(data.get('paused',not self.paused));self.cancel_macros();return self.paused
        if command=='cancelActions':self.cancel_macros();return True
        if command=='stopAudio':self.audio.command('stop');return True
        if command=='stopClip':self.audio.command('stop',data);return True
        if command=='masterVolume':
            volume=number(data.get('volume'),100,0,100);self.audio.command('master',{'volume':volume})
            with self.lock,self.store.lock:self.store.data['settings']['masterVolume']=volume;self.store.persist();self._changed()
            return volume
        if command=='clipGain':self.audio.command('gain',data);return True
        if command=='learn':
            if not self.primary:raise ValueError('Connect MIDI before learning a control')
            if data['id'] not in self._target(data):raise ValueError('Unknown control')
            self.learning={'id':data['id'],'profile':data.get('profile',self.store.current()['id']),'page':data.get('page',self.store.current()['activePage']),'bank':data.get('bank',self.store.current()['activeBank'])};return True
        if command=='cancelLearn':self.learning=None;return True
        if command in ['saveControl','copyControls','undo','newProfile','duplicateProfile','deleteProfile','switchProfile','updateProfile','newPage','switchPage','renamePage','settings']:
            with self.lock,self.store.lock:
                p=self.store.current()
                if command=='undo':
                    if self.store.undo:self.store.data=self.store.undo.pop()
                else:
                    self.store.checkpoint()
                    if command=='saveControl':self._target(data)[data['id']]=validate_control(data['id'],data['control'])
                    elif command=='copyControls':
                        target=self._target(data);source=copy.deepcopy(target[data['source']])
                        for cid in data['ids']:target[cid]=validate_control(cid,{**source,'mapping':target[cid]['mapping']})
                    elif command=='newProfile':
                        new=profile(str(data.get('name','New profile')));self.store.data['profiles'].append(new);self.store.data['activeProfile']=new['id']
                    elif command=='duplicateProfile':
                        new=copy.deepcopy(p);new['id']=uuid.uuid4().hex;new['name']=p['name']+' copy';self.store.data['profiles'].append(new);self.store.data['activeProfile']=new['id']
                    elif command=='deleteProfile':
                        if len(self.store.data['profiles'])==1:raise ValueError('Keep at least one profile')
                        self.store.data['profiles'].remove(p);self.store.data['activeProfile']=self.store.data['profiles'][0]['id']
                    elif command=='switchProfile':
                        if data['id'] not in [p['id'] for p in self.store.data['profiles']]:raise ValueError('Unknown profile')
                        self.store.data['activeProfile']=data['id'];self.store.data['pinned']=bool(data.get('pinned',True))
                    elif command=='updateProfile':p['name']=str(data.get('name',p['name']))[:80];p['apps']=[a.strip().lower() for a in str(data.get('apps','')).split(',') if a.strip()];self.store.data['pinned']=bool(data.get('pinned',self.store.data['pinned']))
                    elif command=='newPage':
                        if len(p['pages'])>=32:raise ValueError('Maximum 32 pages reached')
                        pg=page(str(data.get('name','Page '+str(len(p['pages'])+1))));p['pages'].append(pg);p['activePage']=pg['id']
                    elif command=='switchPage':
                        if data.get('id',p['activePage']) not in [pg['id'] for pg in p['pages']]:raise ValueError('Unknown page')
                        if data.get('bank',p['activeBank']) not in BANKS:raise ValueError('Unknown bank')
                        p['activePage']=data.get('id',p['activePage']);p['activeBank']=data.get('bank',p['activeBank'])
                    elif command=='renamePage':next(pg for pg in p['pages'] if pg['id']==p['activePage'])['name']=str(data['name'])[:60]
                    elif command=='settings':
                        settings=self.store.data['settings'];settings.update({k:bool(v) for k,v in data.items() if k in ['autoProfiles','reducedMotion','liveFeedback']})
                        if 'hardwarePreset' in data:settings['hardwarePreset']=int(number(data['hardwarePreset'],0,0,7))
                        if 'liveColor' in data:
                            if not __import__('re').fullmatch(r'#[0-9a-fA-F]{6}',str(data['liveColor'])):raise ValueError('Invalid live color')
                            settings['liveColor']=str(data['liveColor'])
                self.store.persist();self.previous.clear();self.learning=None;self._changed();return True
        if command in ['testAction','macroPreview']:
            cfg=validate_control(data['id'],data.get('control',self._target(data)[data['id']]))
            if command=='macroPreview':return [{**step,'description':f"Wait {step.get('milliseconds',250)} ms" if step['type']=='delay' else step['type']+': '+str(step.get('value',''))} for step in cfg['steps']]
            self._trigger(data['id'],cfg);return True
        if command=='library':
            folder=self.store.root/'Audio';folder.mkdir(exist_ok=True)
            return [{'path':str(p),'name':p.name.split('-',1)[-1] if len(p.name.split('-',1)[0])==32 else p.name,'size':p.stat().st_size,'duration':self.audio.duration.get(str(p))} for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
        if command in ['chooseAudio','importAudio']:
            paths=data.get('paths')
            if command=='chooseAudio':paths=self._dialog('audio')
            if not paths:return []
            values=[];folder=self.store.root/'Audio';folder.mkdir(exist_ok=True)
            for value in paths:
                source=Path(value).resolve(strict=True)
                if source.suffix.lower() not in AUDIO_EXTS or source.stat().st_size>200_000_000:raise ValueError('Unsupported audio or file exceeds 200 MB')
                target=folder/(uuid.uuid4().hex+'-'+source.name);shutil.copy2(source,target);values.append({'path':str(target),'name':source.name})
            return values
        if command=='previewAudio':
            cfg=data.get('control',{});path=data.get('path',cfg.get('value',''));self.audio.command('play',{**cfg,'value':path,'control':'preview','mode':'restart'});return True
        if command=='youtubeImport':
            url=media.youtube_url(data.get('url'));assign=data.get('assign')
            if self.download_thread and self.download_thread.is_alive():raise RuntimeError('A YouTube download is already running')
            if assign is not None:
                assign={k:assign[k] for k in ['profile','page','bank','id'] if k in assign}
                if assign.get('id') not in self._target(assign):raise ValueError('Unknown control')
            self.download_cancel=threading.Event();self.download={'state':'fetching','job':uuid.uuid4().hex,'url':url,'percent':None,'assign':assign}
            self.download_thread=threading.Thread(target=self._youtube,args=(url,assign,self.download_cancel),name='YouTube import',daemon=True);self.download_thread.start()
            return self.download['job']
        if command=='cancelYoutube':self.download_cancel.set();return True
        if command in ['waveform','cropClip']:
            path=Path(str(data.get('path',''))).resolve(strict=True)
            if path.suffix.lower() not in AUDIO_EXTS:raise ValueError('Unsupported audio format')
            if command=='cropClip':
                clip=media.crop(path,self.store.root/'Audio',number(data.get('start'),0,0,86400),number(data.get('end'),0,0,86400),data.get('name'))
                self.event('audio',{'message':'Cropped clip saved: '+clip['name']});return clip
            key=(str(path),path.stat().st_mtime_ns,int(number(data.get('width'),1000,50,4000)))
            if key not in self.waveforms:
                if len(self.waveforms)>=24:self.waveforms.pop(next(iter(self.waveforms)))
                self.waveforms[key]=media.waveform(path,key[2]);self.audio.duration.setdefault(str(path),self.waveforms[key]['duration'])
            return self.waveforms[key]
        if command=='inspectAudio':return self.audio.command('inspect',{'value':data['path']},wait=True)
        if command=='browse':
            paths=self._dialog('file');return paths[0] if paths else ''
        if command=='importProfile':
            paths=self._dialog('profile')
            if paths:self.store.import_profile(paths[0]);self._changed()
            return bool(paths)
        if command=='exportProfile':
            paths=self._dialog('export')
            if paths:self.store.export_profile(paths[0] if isinstance(paths,(tuple,list)) else paths)
            return bool(paths)
        if command=='diagnostics':
            paths=self._dialog('diagnostics')
            if not paths:return False
            path=paths[0] if isinstance(paths,(tuple,list)) else paths
            report={'version':VERSION,'connection':self.connection,'ports':self.available,'rgb':self.rgb_state,'logs':list(self.logs),'audioError':self.audio.error,'droppedMidi':self.transport.dropped}
            Path(path).write_text(json.dumps(report,indent=2),encoding='utf8');return True
        if command=='quit':self.quitting=True;self.window.destroy() if self.window else None;return True
        raise ValueError('Unknown UI command')

    def _youtube(self,url,assign,cancel):
        def progress(**update):
            with self.lock:
                if self.download_cancel is cancel:self.download.update(update)
        try:
            clip=media.youtube_mp3(url,self.store.root/'Audio',progress,cancel)
            if assign is not None:
                with self.lock,self.store.lock:
                    self.store.checkpoint();control=self._target(assign)[assign['id']]
                    control.update(action='playAudio',value=clip['path'],audioName=clip['name'],trimStart=0,trimEnd=0)
                    self.store.persist();self._changed()
            with self.lock:self.download.update(state='done',percent=100,clip=clip,title=clip['title'])
            self.event('audio',{'message':'YouTube audio saved: '+clip['name']+(' and assigned to '+assign['id'] if assign else '')})
        except media.Cancelled:
            with self.lock:self.download.update(state='cancelled',message='Download cancelled')
        except Exception as exc:
            logging.exception('YouTube import failed')
            with self.lock:self.download.update(state='error',message=str(exc))
            self.event('error',{'message':str(exc)})

    def _dialog(self,kind):
        if self.window is None:raise RuntimeError('File dialogs require the desktop window')
        import webview
        if kind in ['export','diagnostics']:
            return self.window.create_file_dialog(webview.FileDialog.SAVE,save_filename='SMC-PAD-profile.zip' if kind=='export' else 'SMC-PAD-diagnostics.json',file_types=('Profile bundle (*.zip)',) if kind=='export' else ('JSON (*.json)',))
        return self.window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=kind=='audio',file_types={'audio':('Audio (*.wav;*.mp3;*.m4a;*.aac;*.wma;*.flac)',),'profile':('SMC-PAD profile (*.json;*.zip)',),'file':('All files (*.*)',)}[kind])

    def close(self):
        self.stop.set();self.cancel_macros();self.rgb.cancel.set();self.download_cancel.set()
        self.device_thread.join(6);self.transport.close();self.audio.close();self.store.persist()
        self.action_thread.join(1);self.poll_thread.join(1)
