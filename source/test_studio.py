"""Regression checks; safe to run without executing shortcuts or hardware writes."""
import copy
import json
import math
from pathlib import Path
import queue
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
import zipfile

from store import Store,validate_control,validate_profile,preset_locator
from midi import RGB,encode,decode,bank_for_note
from controller import Controller,matches,signature,delta
from audio import Audio
import actions
import media

class FakeTransport:
    def __init__(self):
        self.inputs={};self.responses=queue.Queue();self.dropped=0;self.memory=bytearray(28312);self.sent=[];self.reject=False;self.bad_readback=False;self.junk=False;self.header=bytearray(12);self.saves=0
        # Preset 1 mirrors a real MidiSuite export: 128 pad records from offset 211,
        # groups of 16 notes from 4 upward, with the last group repeating notes 52-67.
        for i in range(128):
            note=52+i%16 if i>=112 else 4+i
            rgb=(30,60,90) if 32<=i<64 else (40,70,100) if i>=112 else (150,200,240)
            start=211+i*26;self.memory[start+1:start+9]=bytes([9,note,0,127,*rgb,255])
    def send(self,message):
        cmd,data=decode(message);self.sent.append((cmd,data))
        if cmd==0x23:
            region=data[0];address=int.from_bytes(data[1:5],'little');length=int.from_bytes(data[5:8],'little')
            payload=data+(self.memory[address:address+length] if region==5 else bytes(self.header[address:address+length]) if region==4 else bytes(length))
            if self.junk:
                self.responses.put((99,encode(cmd,payload)));self.responses.put((0,b'\xf0\x7f\xf7'))
                self.responses.put((0,encode(cmd,bytes([0])*len(payload))))
            self.responses.put((0,encode(cmd,payload)))
        elif cmd==0x22:
            address=int.from_bytes(data[1:5],'little');length=int.from_bytes(data[5:8],'little')
            if not length:self.saves+=1
            elif not self.reject and not self.bad_readback:self.memory[address:address+length]=data[8:8+length]
            self.responses.put((0,encode(0,bytes([1 if self.reject else 0]))))
        else:self.responses.put((0,encode(cmd)))
    def close(self):pass

class RegressionTests(unittest.TestCase):
    def test_sysex_roundtrip_rejects_corruption(self):
        for size in [0,1,7,8,1009]:
            data=bytes(i%256 for i in range(size));self.assertEqual(decode(encode(0x23,data)),(0x23,data))
        message=bytearray(encode(0x23,b'hello'));message[-3]^=1
        with self.assertRaises(ValueError):decode(message)
        with self.assertRaises(ValueError):decode(encode(0x23,b'hello')[:-1])

    def test_rgb_addresses_validate_complete_layout(self):
        transport=FakeTransport();rgb=RGB(transport,lambda *a:None);rgb.port=0;rgb.flash=transport.memory;rgb.ready=True
        self.assertEqual(rgb.address(1,0,'A'),0x418)
        self.assertEqual(rgb.address(1,0,'B'),0xc38)
        self.assertEqual(rgb.address(16,0,'B'),0xdbe)
        self.assertEqual(rgb.address(1,0,'G'),211+5);self.assertEqual(rgb.address(1,0,'F'),0xc38)
        # A remapped note or channel no longer blocks color writes.
        transport.memory[211+34*26+2]=99;self.assertEqual(rgb.address(3,0,'A'),211+34*26+5)
        # A damaged record blocks only that pad.
        transport.memory[211+34*26+8]=0
        with self.assertRaises(RuntimeError):rgb.address(3,0,'A')
        self.assertEqual(rgb.address(1,0,'A'),0x418)
        # An unrecognized pad table blocks the whole preset before any write.
        for i in range(128):transport.memory[211+i*26+8]=0
        with self.assertRaises(RuntimeError):rgb.address(1,0,'A')
        with self.assertRaises(RuntimeError):rgb.address(1,1,'A')
        with self.assertRaises(ValueError):rgb.address(1,0,'Z')
        with self.assertRaises(RuntimeError):rgb.apply({'pad1':'#abcdef'},0,'A')
        self.assertEqual([cmd for cmd,data in transport.sent if cmd==0x22],[])

    def test_physical_bank_b_uses_dedicated_records(self):
        transport=FakeTransport();rgb=RGB(transport,lambda *a:None);rgb.port=0
        before=bytes(transport.memory)
        result=rgb.apply({f'pad{i}':'#00ff00' for i in range(1,17)},0,'B')
        self.assertTrue(all(r['ok'] for r in result))
        for i in range(16):
            octave=211+(48+i)*26+5;physical=211+(112+i)*26+5
            self.assertEqual(transport.memory[octave:octave+3],before[octave:octave+3])
            self.assertEqual(transport.memory[physical:physical+3],b'\0\xff\0')
        touched={211+(112+i)*26+j for i in range(16) for j in [5,6,7]}
        self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(before,transport.memory)) if i not in touched))

    def test_rgb_polls_hardware_before_colors_are_read(self):
        transport=FakeTransport();rgb=RGB(transport,lambda *a:None);rgb.port=0;rgb.header=bytes(12)
        transport.header[8]=3;rgb.keep_alive()
        self.assertEqual(rgb.header[8],3)
        self.assertIsNone(rgb.flash)

    def test_unlock_does_not_interleave_background_polls(self):
        transport=FakeTransport();rgb=RGB(transport,lambda *a:None);rgb.port=0;rgb.header=bytes(12)
        entered=threading.Event();resume=threading.Event();send=transport.send
        def slow_send(message):
            cmd,data=decode(message)
            if cmd==0x23 and data[0]==5 and int.from_bytes(data[1:5],'little')==0:
                entered.set();resume.wait(3)
            send(message)
        transport.send=slow_send
        worker=threading.Thread(target=rgb.unlock)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            before=list(transport.sent);rgb.last_activity=0;rgb.keep_alive()
            self.assertEqual(transport.sent,before)
        finally:resume.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertTrue(rgb.ready)

    def test_live_preset_and_bank_override_stale_apply_context(self):
        with tempfile.TemporaryDirectory() as folder:
            transport=FakeTransport()
            transport.memory[2*3539:3*3539]=transport.memory[:3539]
            controller=Controller(folder,transport)
            try:
                controller.rgb.port=0;controller.rgb.unlock()
                # The last UI snapshot said Preset 7. The hardware has since
                # switched to Preset 3 / physical Bank B without sending notes.
                transport.header[10]=2;transport.header[11]=1
                before=bytes(transport.memory)
                requested=controller.request('applyRGB',{'preset':6,'bank':'B'})
                self.assertTrue(requested['ok'])
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if controller.rgb_state.get('preset')==2 and controller.rgb_state.get('results'):break
                    time.sleep(.02)
                self.assertEqual(controller.rgb_state.get('preset'),2)
                self.assertEqual(controller.rgb_state.get('bank'),'B')
                self.assertTrue(all(x['ok'] for x in controller.rgb_state['results']))
                self.assertEqual(controller.store.data['settings']['hardwarePreset'],2)
                self.assertEqual(controller.store.current()['activeBank'],'B')
                for i in range(16):
                    address=2*3539+211+(112+i)*26+5
                    expected=bytes.fromhex(controller.store.controls(bank='B')[f'pad{i+1}']['color'][1:])
                    self.assertEqual(transport.memory[address:address+3],expected)
                touched={2*3539+211+(112+i)*26+j for i in range(16) for j in [5,6,7]}
                self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(before,transport.memory)) if i not in touched))
                transport.header[10]=0;transport.header[11]=0
                controller.rgb.header=bytes(transport.header);controller._detect_preset()
                self.assertEqual(controller.store.data['settings']['hardwarePreset'],0)
                self.assertEqual(controller.store.current()['activeBank'],'A')
                self.assertEqual(controller.request('snapshot')['value']['rgb']['activePreset'],0)
                self.assertTrue(controller.request('snapshot')['value']['rgb']['presetDetection']['located'])
            finally:controller.close()

    def test_identify_never_confirms_rejected_writes(self):
        transport=FakeTransport();events=[];rgb=RGB(transport,lambda k,d:events.append(d));rgb.port=0
        transport.reject=True
        with self.assertRaises(RuntimeError):rgb.identify(0,'B',hold=0)
        self.assertFalse(any('identified' in event for event in events))

    def test_banks_and_preset_detection(self):
        self.assertEqual([bank_for_note(n) for n in [36,51,52,67,68,115,116,4,20,3,128]],['A','A','B','B','C','E','F','G','H',None,None])
        header=lambda value:(bytes(6)+bytes([value])+bytes(5)).hex()
        self.assertIsNone(preset_locator([{'header':header(2),'preset':0}]))
        self.assertEqual(preset_locator([{'header':header(2),'preset':0},{'header':header(5),'preset':3}]),(6,2))
        ambiguous=[{'header':(bytes([p,p])+bytes(10)).hex(),'preset':p} for p in [0,1]]
        self.assertIsNone(preset_locator(ambiguous))
        self.assertIsNone(preset_locator([{'header':'zz','preset':0},{'header':header(1),'preset':9}]))
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);self.assertEqual(set(store.current()['pages'][0]['banks']),{'A','B'})
            store.current()['activeBank']='D';self.assertEqual(store.snapshot()['profiles'][0]['pages'][0]['banks']['D']['pad1']['action'],'none')
            store.controls()['pad1']=validate_control('pad1',{'action':'typeText','value':'bank D'});store.persist()
            reloaded=Store(folder);self.assertEqual(reloaded.controls()['pad1']['value'],'bank D');self.assertNotIn('E',reloaded.current()['pages'][0]['banks'])

    def test_rgb_reply_port_address_ack_and_readback(self):
        transport=FakeTransport();rgb=RGB(transport,lambda *a:None);rgb.port=0;rgb.flash=bytearray(transport.memory);rgb.ready=True;transport.junk=True
        self.assertEqual(rgb.read_region(5,0x418,3),bytes([30,60,90]))
        self.assertTrue(rgb.apply({'pad1':'#000000','pad2':'#ffffff'},0,'A')[1]['ok'])
        transport.reject=True
        results=rgb.apply({'pad1':'#123456','pad2':'#123456'},0,'A')
        self.assertEqual(sum(r['ok'] for r in results),0)
        transport.reject=False;transport.bad_readback=True
        self.assertFalse(rgb.apply({'pad1':'#654321'},0,'A')[0]['ok'])

    def test_rgb_session_refresh_identify_and_hardware_change(self):
        transport=FakeTransport();events=[];rgb=RGB(transport,lambda kind,data:events.append(data));rgb.port=0
        rgb.unlock();transport.sent.clear()
        # Every apply replays the unlock (identity + global read) before writing.
        self.assertTrue(rgb.apply({'pad1':'#102030'},0,'A')[0]['ok'])
        self.assertEqual(transport.sent[0][0],0x11);self.assertIn(0x22,[cmd for cmd,data in transport.sent])
        # Identify paints the bank, then restores the original colors.
        before=bytes(transport.memory);rgb.identify(0,'B',hold=0)
        self.assertEqual(bytes(transport.memory),before)
        self.assertEqual(sum(cmd==0x22 and data[8:]==b'\xff\xff\xff' for cmd,data in transport.sent),16)
        # A hardware preset/bank switch changes the global block and invalidates the cache.
        rgb.last_activity=0;rgb.keep_alive();self.assertTrue(rgb.ready)
        transport.header[6]=3;rgb.last_activity=0;rgb.keep_alive()
        self.assertFalse(rgb.ready);self.assertEqual(events[-1]['state'],'stale')

    def test_controller_preset_confirmation_live_feedback_and_save(self):
        with tempfile.TemporaryDirectory() as folder:
            transport=FakeTransport();controller=Controller(folder,transport)
            try:
                controller.rgb.port=0;controller.rgb.unlock();settings=controller.store.data['settings']
                transport.header[10]=0;controller.rgb.header=bytes(transport.header)
                self.assertTrue(controller.request('confirmPreset',{'preset':0})['value']['detecting'])
                transport.header[10]=2;controller.rgb.header=bytes(transport.header)
                self.assertTrue(controller.request('confirmPreset',{'preset':2})['value']['detecting'])
                transport.header[10]=1;controller.rgb.header=bytes(transport.header);controller._detect_preset()
                self.assertEqual(settings['hardwarePreset'],1);self.assertEqual(controller.detected_preset(),1)
                transport.header[10]=0;controller.rgb.header=bytes(transport.header);controller._detect_preset();self.assertEqual(settings['hardwarePreset'],0)
                # Live feedback lights a playing pad on the active bank, then restores it.
                settings.update(liveFeedback=True,liveColor='#ff0000');players=[{'control':'pad2'}]
                controller.audio.snapshot=lambda:{'players':players}
                address=0x418+26;original=bytes(transport.memory[address:address+3])
                controller._live_feedback();self.assertEqual(bytes(transport.memory[address:address+3]),b'\xff\0\0')
                players.clear();controller._live_feedback();self.assertEqual(bytes(transport.memory[address:address+3]),original)
                self.assertEqual(controller.live_lit,{})
                players.append({'control':'pad2'});controller._live_feedback();controller._live_restore()
                self.assertEqual(bytes(transport.memory[address:address+3]),original)
                controller.rgb.save();self.assertEqual(transport.saves,1)
            finally:controller.close()

    def test_store_migration_recovery_banks_and_bundled_macro_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=Store(root/'one');clip=root/'clip.wav';clip.write_bytes(b'test fixture')
            migrated=validate_profile({'name':'Old profile','controls':{'pad1':{'action':'playAudio','value':str(clip),'audioVolume':0}}})
            self.assertEqual(migrated['pages'][0]['banks']['A']['pad1']['audioVolume'],0)
            self.assertEqual(migrated['pages'][0]['banks']['B']['pad1']['action'],'none')
            store.controls()['pad1']=validate_control('pad1',{'action':'playAudio','value':str(clip),'audioVolume':0})
            store.controls()['pad2']=validate_control('pad2',{'action':'macro','steps':[{'type':'playAudio','value':str(clip)}]})
            store.persist();store.persist();store.path.write_text('broken',encoding='utf8')
            recovered=Store(store.root);self.assertTrue(recovered.recovered);self.assertTrue(list(store.root.glob('studio-corrupt-*')))
            self.assertEqual(recovered.controls()['pad1']['audioVolume'],0)
            bundle=root/'bundle.zip';recovered.export_profile(bundle)
            imported=Store(root/'two');p=imported.import_profile(bundle)
            cfg=p['pages'][0]['banks']['A'];self.assertEqual(Path(cfg['pad1']['value']).read_bytes(),b'test fixture')
            self.assertEqual(Path(cfg['pad2']['steps'][0]['value']).read_bytes(),b'test fixture')
            with zipfile.ZipFile(bundle) as z:self.assertEqual(len([n for n in z.namelist() if n.startswith('audio/')]),1)
            with self.assertRaises(ValueError):validate_control('pad1',{'audioVolume':float('nan')})
            with self.assertRaises(ValueError):validate_control('pad1',{'trimStart':5,'trimEnd':2})

    def test_midi_matching_absolute_and_relative_encoders(self):
        mapping={'kind':'note','channel':9,'data1':36,'port':'Controller A'}
        self.assertTrue(matches(mapping,signature('Controller A',[0x99,36,100]),'Controller A'))
        self.assertFalse(matches(mapping,signature('Controller B',[0x99,36,100]),'Controller A'))
        mapping['port']=''
        self.assertFalse(matches(mapping,signature('Controller B',[0x99,36,100]),'Controller A'))
        self.assertEqual(delta(126,127,'absolute'),1);self.assertEqual(delta(127,0,'absolute'),-8)
        self.assertEqual(delta(None,1,'relative'),1);self.assertEqual(delta(None,127,'relative'),-1)
        self.assertEqual(actions.key_input(37).ki.dwFlags,1);self.assertEqual(actions.key_input(37,True).ki.dwFlags,3)

    def test_controller_queue_macro_cancel_bank_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            controller=Controller(folder,FakeTransport());calls=[]
            controller._perform=lambda req:calls.append(req['value'])
            try:
                controller.primary='Controller A'
                cfg=validate_control('pad1',{'action':'macro','steps':[{'type':'delay','milliseconds':500},{'type':'typeText','value':'must not run'}]})
                controller._trigger('pad1',cfg);time.sleep(.05);controller.cancel_macros();time.sleep(.55);self.assertEqual(calls,[])
                cfg=validate_control('pad1',{'action':'typeText','value':'hello','mapping':{'kind':'note','channel':9,'data1':36,'port':'Controller A'}})
                controller.store.controls()['pad1']=cfg
                controller.on_midi('Controller B',[0x99,36,100]);time.sleep(.02);self.assertEqual(calls,[])
                controller.on_midi('Controller A',[0x99,36,100]);time.sleep(.05);self.assertEqual(calls,['hello'])
                controller.on_midi('Controller A',[0x99,36,0]);time.sleep(.02);self.assertEqual(calls,['hello'])
                controller.on_midi('Controller A',[0x99,52,100]);self.assertEqual(controller.store.current()['activeBank'],'B')
                controller.request('newPage',{'name':'Second'});self.assertEqual(len(controller.store.current()['pages']),2)
                controller.request('undo');self.assertEqual(len(controller.store.current()['pages']),1)
                self.assertFalse(controller.request('switchPage',{'bank':'Z'})['ok']);self.assertEqual(controller.store.current()['activeBank'],'B')
                self.assertTrue(controller.request('switchPage',{'bank':'C'})['ok']);self.assertIn('C',controller.request('snapshot',{})['value']['store']['profiles'][0]['pages'][0]['banks'])
                controller.on_midi('Controller A',[0x99,4,100]);self.assertEqual(controller.store.current()['activeBank'],'G')
            finally:controller.close()

    def test_native_audio_zero_trim_loop_modes_gain_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            clip=Path(folder)/'silence.wav'
            with wave.open(str(clip),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(44100);f.writeframes(bytes(44100*2*2))
            audio=Audio(lambda *args:None)
            def snapshot():time.sleep(.14);return audio.snapshot()['players']
            try:
                duration=audio.command('inspect',{'value':str(clip)},wait=True);self.assertAlmostEqual(duration['duration'],2,places=1)
                req={'value':str(clip),'control':'pad1','volume':0,'trimStart':.2,'trimEnd':.5,'loop':True,'fadeIn':.04,'fadeOut':.04}
                audio.command('play',req,wait=True);players=snapshot();self.assertEqual(players[0]['volume'],0);self.assertEqual(players[0]['start'],.2)
                time.sleep(.7);self.assertEqual(len(snapshot()),1)
                audio.command('play',{**req,'mode':'restart'},wait=True);self.assertEqual(len(snapshot()),1)
                audio.command('play',{**req,'mode':'overlap'},wait=True);self.assertEqual(len(snapshot()),2)
                audio.command('play',{**req,'mode':'toggle'},wait=True);self.assertEqual(len(snapshot()),0)
                audio.command('master',{'volume':0},wait=True);self.assertEqual(audio.snapshot()['masterVolume'],0)
                audio.command('play',req,wait=True);audio.command('stop',wait=True);self.assertEqual(len(snapshot()),0)
            finally:audio.close()

    def test_media_waveform_crop_and_youtube_import(self):
        with tempfile.TemporaryDirectory() as folder:
            clip=Path(folder)/'tone.wav'
            # One second of silence, then one second of a 200 Hz tone at half scale.
            with wave.open(str(clip),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000)
                f.writeframes(bytes(8000*2)+b''.join(struct.pack('<h',int(16384*math.sin(2*math.pi*200*i/8000))) for i in range(8000)))
            shape=media.waveform(clip,100);self.assertAlmostEqual(shape['duration'],2,places=1);self.assertEqual(len(shape['peaks']),100)
            self.assertEqual(max(shape['peaks'][:45]),0);self.assertGreater(min(shape['peaks'][55:]),.4);self.assertLess(max(shape['peaks']),.6)
            cropped=media.crop(clip,Path(folder)/'Audio',.5,1.5);self.assertEqual(cropped['name'],'tone (cropped).wav')
            self.assertAlmostEqual(media.waveform(cropped['path'],50)['duration'],1,places=1)
            with self.assertRaises(ValueError):media.crop(clip,Path(folder)/'Audio',1,1)
            self.assertEqual(media.youtube_url(' youtu.be/abc '),'https://youtu.be/abc')
            for bad in ['','https://example.com/watch?v=abc','https://youtube.com.evil.net/x','file:///C:/Windows/win.ini','ftp://youtube.com/x']:
                with self.assertRaises(ValueError):media.youtube_url(bad)
            self.assertEqual(media.clean_name('a/b:c*?"<>|. '),'abc')
            controller=Controller(Path(folder)/'studio',FakeTransport())
            try:
                self.assertEqual(len(controller.request('waveform',{'path':str(clip),'width':80})['value']['peaks']),80)
                saved=controller.request('cropClip',{'path':str(clip),'start':1,'end':2})['value']
                self.assertTrue(Path(saved['path']).is_relative_to(controller.store.root/'Audio'))
                self.assertFalse(controller.request('cropClip',{'path':str(Path(folder)/'missing.wav'),'start':0,'end':1})['ok'])
                self.assertFalse(controller.request('youtubeImport',{'url':'https://example.com/v'})['ok'])
                self.assertFalse(controller.request('youtubeImport',{'url':'https://youtu.be/abc','assign':{'id':'nope'}})['ok'])
                def fake(url,folder,progress,cancel):
                    progress(state='downloading',percent=50,title='Song');return {**media.crop(clip,folder,0,1,'Song'),'title':'Song','duration':1}
                with patch.object(media,'youtube_mp3',fake):
                    controller.store.controls()['pad1']=validate_control('pad1',{'label':'Kept','trimStart':3,'trimEnd':4})
                    job=controller.request('youtubeImport',{'url':'https://www.youtube.com/watch?v=abc','assign':{'id':'pad1'}})['value']
                    controller.download_thread.join(10)
                download=controller.request('snapshot',{})['value']['download'];pad=controller.store.controls()['pad1']
                self.assertEqual((download['state'],download['job'],download['clip']['name']),('done',job,'Song.wav'))
                self.assertEqual((pad['action'],pad['audioName'],pad['label'],pad['trimStart'],pad['trimEnd']),('playAudio','Song.wav','Kept',0,0))
                self.assertTrue(Path(pad['value']).is_file())
                def cancelled(url,folder,progress,cancel):
                    cancel.wait(5);raise media.Cancelled('Download cancelled')
                with patch.object(media,'youtube_mp3',cancelled):
                    controller.request('youtubeImport',{'url':'https://youtu.be/abc'});controller.request('cancelYoutube');controller.download_thread.join(5)
                self.assertEqual(controller.download['state'],'cancelled')
            finally:controller.close()

if __name__=='__main__':unittest.main(verbosity=2)
