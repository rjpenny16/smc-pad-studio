"""Regression checks; safe to run without executing shortcuts or hardware writes."""
import copy
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
import zipfile

from store import Store,validate_control,validate_profile
from midi import RGB,encode,decode
from controller import Controller,matches,signature,delta
from audio import Audio
import actions

class FakeTransport:
    def __init__(self):
        self.inputs={};self.responses=queue.Queue();self.dropped=0;self.memory=bytearray(28312);self.sent=[];self.reject=False;self.bad_readback=False;self.junk=False;self.header=bytearray(12)
        for i in range(32):
            start=0x414+i*26;self.memory[start:start+8]=bytes([9,36+i,0,127,30,60,90,255])
        for i in range(16):
            start=0xc34+i*26;self.memory[start:start+8]=bytes([9,52+i,0,127,40,70,100,255])
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
            if not self.reject and not self.bad_readback:
                address=int.from_bytes(data[1:5],'little');self.memory[address:address+3]=data[8:]
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
        self.assertEqual(rgb.address(1,0,'B'),0x5b8)
        self.assertEqual(rgb.address(16,0,'B'),0x73e)
        transport.memory[0x414+2*26+1]=99
        with self.assertRaises(RuntimeError):rgb.address(1,0,'A')
        with self.assertRaises(RuntimeError):rgb.apply({'pad1':'#abcdef'},0,'A')
        self.assertEqual([cmd for cmd,data in transport.sent if cmd==0x22],[])

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
                self.assertFalse(controller.request('switchPage',{'bank':'C'})['ok']);self.assertEqual(controller.store.current()['activeBank'],'B')
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

if __name__=='__main__':unittest.main(verbosity=2)
