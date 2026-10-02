"""One supervised Windows MediaPlayer worker with responsive stop and fades."""
import copy
import logging
from pathlib import Path
import os
import queue
import threading
import time
import uuid

class Audio:
    def __init__(self,event):
        self.event=event;self.queue=queue.PriorityQueue(128);self.sequence=0;self.lock=threading.RLock();self.thread=None;self.ready=threading.Event();self.error=None;self.players={};self.status=[];self.master=100;self.generation=0;self.duration={};self.stopping=False

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            self.ready.clear();self.error=None;self.stopping=False
            self.thread=threading.Thread(target=self._worker,name='Windows audio',daemon=True);self.thread.start()
        if not self.ready.wait(10):raise RuntimeError('Windows audio did not start')
        if self.error:raise RuntimeError(self.error)

    def command(self,operation,req=None,wait=False):
        self.start();req=copy.deepcopy(req or {})
        if operation in ['stop','quit']:
            with self.lock:self.generation+=1
        with self.lock:self.sequence+=1;sequence=self.sequence;generation=self.generation
        done=threading.Event();result=[]
        item=(0 if operation in ['stop','quit'] else 5,sequence,operation,req,generation,result,done)
        try:self.queue.put_nowait(item)
        except queue.Full:
            if operation not in ['stop','quit']:raise RuntimeError('Audio queue is full; stop playback and retry')
            # Emergency stop remains available even during a burst of pad presses.
            pending=self.queue.get_nowait();pending[-2].append(RuntimeError('Audio request cancelled'));pending[-1].set()
            self.queue.put_nowait(item)
        if wait:
            if not done.wait(12):raise RuntimeError('Windows audio did not respond')
            if result and isinstance(result[0],Exception):raise result[0]
            return result[0] if result else None
        return sequence

    def snapshot(self):
        with self.lock:return {'players':copy.deepcopy(self.status),'masterVolume':self.master,'error':self.error,'durations':dict(self.duration)}

    def close(self):
        if self.thread and self.thread.is_alive():
            self.command('quit',wait=True);self.thread.join(3)

    def _worker(self):
        try:
            import clr
            base=Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'WPF'
            clr.AddReference(str(base/'PresentationCore.dll'));clr.AddReference(str(base/'WindowsBase.dll'))
            from System import Uri,Action,TimeSpan
            from System.Windows.Media import MediaPlayer
            from System.Windows.Threading import Dispatcher,DispatcherPriority
            dispatcher=Dispatcher.CurrentDispatcher
            def pump():dispatcher.Invoke(Action(lambda:None),DispatcherPriority.Background)
            self.ready.set();last_status=0
            while not self.stopping:
                pump();now=time.monotonic()
                for key,p in list(self.players.items()):
                    player=p['player'];position=player.Position.TotalSeconds
                    if p['errors']:
                        self.event('error',{'message':'Audio playback failed: '+p['errors'][0]});player.Close();self.players.pop(key);continue
                    if position>=p['end']-.015:
                        if p['loop']:
                            player.Position=TimeSpan.FromSeconds(p['start']);player.Play();position=p['start']
                        else:player.Close();self.players.pop(key);continue
                    elapsed=max(0,position-p['start']);remaining=max(0,p['end']-position)
                    fade=min(1,elapsed/p['fadeIn']) if p['fadeIn'] else 1
                    if p['fadeOut']:fade=min(fade,remaining/p['fadeOut'])
                    player.Volume=p['gain']*self.master/100*fade
                if now-last_status>.1:
                    with self.lock:self.status=[{'id':key,'control':p['control'],'path':p['path'],'name':Path(p['path']).name,'position':round(p['player'].Position.TotalSeconds,2),'duration':p['duration'],'start':p['start'],'end':p['end'],'loop':p['loop'],'volume':round(p['gain']*100)} for key,p in self.players.items()]
                    last_status=now
                try:item=self.queue.get(timeout=.02)
                except queue.Empty:continue
                priority,sequence,operation,req,generation,result,done=item
                try:
                    owner=str(req.get('control','preview'))
                    if operation in ['stop','quit']:
                        for key,p in list(self.players.items()):
                            if req.get('control') is None or p['control']==owner:p['player'].Stop();p['player'].Close();self.players.pop(key)
                        if operation=='quit':self.stopping=True
                        result.append(True)
                    elif operation=='master':self.master=max(0,min(100,float(req.get('volume',100))));result.append(self.master)
                    elif operation=='gain':
                        for p in self.players.values():
                            if p['control']==owner:p['gain']=max(0,min(100,float(req.get('volume',100))))/100
                        result.append(True)
                    elif operation in ['play','inspect']:
                        if generation!=self.generation:raise RuntimeError('Audio request cancelled')
                        path=Path(req['value']).resolve(strict=True)
                        if path.suffix.lower() not in ['.wav','.mp3','.m4a','.aac','.wma','.flac']:raise ValueError('Unsupported audio format')
                        mode=req.get('mode',req.get('audioMode','restart'))
                        active=any(p['control']==owner for p in self.players.values())
                        if operation=='play' and mode!='overlap':
                            for key,p in list(self.players.items()):
                                if p['control']==owner:p['player'].Close();self.players.pop(key)
                        if operation=='play' and mode=='toggle' and active:result.append(True);continue
                        if len(self.players)>=48:raise RuntimeError('Maximum 48 simultaneous clips reached')
                        player=MediaPlayer();errors=[]
                        player.MediaFailed+=lambda sender,event,errors=errors:errors.append(str(event.ErrorException))
                        player.Volume=0;player.Open(Uri(str(path)));deadline=time.monotonic()+5
                        while not player.NaturalDuration.HasTimeSpan and time.monotonic()<deadline:
                            pump();time.sleep(.01)
                            if errors:player.Close();raise RuntimeError(errors[0])
                            if generation!=self.generation:player.Close();raise RuntimeError('Audio request cancelled')
                        if not player.NaturalDuration.HasTimeSpan:player.Close();raise RuntimeError('Windows could not decode '+path.name)
                        duration=player.NaturalDuration.TimeSpan.TotalSeconds
                        with self.lock:self.duration[str(path)]=duration
                        if operation=='inspect':player.Close();result.append({'duration':duration});continue
                        start=max(0,float(req.get('trimStart',0)));end=float(req.get('trimEnd',0)) or duration;end=min(duration,end)
                        if not start<end:player.Close();raise ValueError('Trim range is outside this clip')
                        gain=max(0,min(100,float(req.get('volume',req.get('audioVolume',100)))))/100
                        fade_in=max(0,float(req.get('fadeIn',0)));fade_out=max(0,float(req.get('fadeOut',0)))
                        player.Position=TimeSpan.FromSeconds(start);player.Volume=0 if fade_in else gain*self.master/100;player.Play()
                        self.players[uuid.uuid4().hex]={'player':player,'control':owner,'path':str(path),'duration':duration,'start':start,'end':end,'loop':bool(req.get('loop',False)),'gain':gain,'fadeIn':fade_in,'fadeOut':fade_out,'errors':errors}
                        result.append({'duration':duration,'control':owner})
                    else:raise ValueError('Unknown audio operation')
                except Exception as exc:
                    logging.exception('Audio operation failed');result.append(exc);self.event('error',{'message':str(exc)})
                finally:done.set()
        except BaseException as exc:
            logging.exception('Audio worker failed');self.error=str(exc);self.event('error',{'message':'Audio worker stopped: '+str(exc)})
        finally:
            self.ready.set()
            for p in self.players.values():
                try:p['player'].Close()
                except Exception:pass
            self.players.clear()
            with self.lock:self.status=[]
            while True:
                try:item=self.queue.get_nowait();item[-2].append(RuntimeError(self.error or 'Audio stopped'));item[-1].set()
                except queue.Empty:break
