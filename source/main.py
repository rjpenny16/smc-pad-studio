"""SMC-PAD Studio desktop entry point. No browser or production HTTP server."""

import ctypes as C
from ctypes import wintypes as W
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time

ROOT = Path(
    os.environ.get('SMC_STUDIO_DATA', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'SMC-PAD Control Center'))
)
if '--ui-check' in sys.argv and 'SMC_STUDIO_DATA' not in os.environ:
    ROOT = ROOT / 'Verification' / str(os.getpid())
kernel = C.WinDLL('kernel32', use_last_error=True)
kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
kernel.CreateMutexW.restype = W.HANDLE
kernel.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
kernel.CreateEventW.restype = W.HANDLE
kernel.SetEvent.argtypes = [W.HANDLE]
kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
kernel.CloseHandle.argtypes = [W.HANDLE]


class Bridge:
    def __init__(self, controller):
        self._controller = controller

    def request(self, command, data=None):
        return self._controller.request(command, data)


def visible_error(message):
    logging.error(message)
    user = C.WinDLL('user32')
    user.MessageBoxW.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT]
    if '--no-dialog' not in sys.argv:
        user.MessageBoxW(None, message + '\n\nStartup log: ' + str(ROOT / 'startup.log'), 'SMC-PAD Studio', 0x10)


def main():
    controller = None
    tray = None
    tray_items = {}
    mutex = None
    show_event = None
    window = None
    startup_failed = False
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            handlers=[RotatingFileHandler(ROOT / 'startup.log', maxBytes=2_000_000, backupCount=3, encoding='utf8')],
            format='%(asctime)s %(levelname)s %(message)s',
            force=True,
        )
        logging.info('Starting SMC-PAD Studio pid=%s', os.getpid())
        instance_suffix = '.test.' + str(os.getpid()) if '--ui-check' in sys.argv else ''
        mutex = kernel.CreateMutexW(None, False, 'Local\\SMCPADStudio' + instance_suffix)
        if not mutex:
            raise C.WinError(C.get_last_error())
        existing = C.get_last_error() == 183
        show_event = kernel.CreateEventW(None, False, False, 'Local\\SMCPADStudio.Show' + instance_suffix)
        # --background is the sign-in launch: start in the tray and never pop up a running window.
        background = '--background' in sys.argv
        if existing:
            if not background:
                kernel.SetEvent(show_event)
                logging.info('Existing instance restored')
            return 0
        import webview
        import autostart
        from controller import Controller, VERSION
        import desktop
        import ui_bundle
        import clr  # noqa: F401  (loads the CLR so the System import below works)
        from System import Action

        logging.info('SMC-PAD Studio %s', VERSION)
        # UI checks stay deterministic: they connect only when a hardware flag asks for it.
        controller = Controller(ROOT, auto_connect='--ui-check' not in sys.argv)
        try:
            autostart.refresh()
        except Exception:
            logging.exception('Could not update the sign-in launch entry')
        base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        html = ui_bundle.load(base / 'ui')
        width, height, maximized = desktop.fit_window(
            controller.store.data['settings'].get('window'), desktop.work_area()
        )
        window = webview.create_window(
            'SMC-PAD Studio',
            html=html,
            js_api=Bridge(controller),
            width=width,
            height=height,
            maximized=maximized,
            hidden=background,
            min_size=desktop.MIN_SIZE,
            background_color='#0c0e12',
            text_select=False,
        )
        controller.window = window

        def dark_title_bar(renderer):
            # The interface is always dark. pywebview themes the title bar from the Windows
            # app theme; runs after its WinForms backend loads and before the form exists.
            try:
                from webview.platforms import winforms

                winforms.BrowserView.BrowserForm.is_dark_theme = lambda self: True
            except Exception:
                logging.exception('Dark title bar unavailable')

        window.events.initialized += dark_title_bar
        # The normal (not maximized) size and the maximized state, saved for the next launch.
        remembered = {'width': width, 'height': height, 'maximized': maximized}

        def resized(width, height):
            try:
                state = int(window.native.WindowState)  # FormWindowState: 0 normal, 1 minimized, 2 maximized
            except Exception:
                state = 2 if remembered['maximized'] else 0
            if state == 0:
                remembered.update(width=width, height=height, maximized=False)
            elif state == 2:
                remembered['maximized'] = True

        window.events.resized += resized
        window.events.maximized += lambda: remembered.update(maximized=True)
        window.events.restored += lambda: remembered.update(maximized=False)

        def closing():
            if not controller.quitting:
                window.hide()
                logging.info('Window hidden; background mappings remain active')
                return False
            return True

        window.events.closing += closing

        def show():
            window.show()
            try:
                window.native.BeginInvoke(Action(lambda: window.native.Activate()))
            except Exception:
                logging.exception('Window activation failed')

        def initialize():
            nonlocal tray, startup_failed
            if not window.events.loaded.wait(30):
                startup_failed = True
                visible_error('The desktop interface did not load. Check the WebView2 Runtime.')
                controller.quitting = True
                window.destroy()
                return
            logging.info('Native window loaded')
            try:
                import clr

                clr.AddReference('System.Windows.Forms')
                clr.AddReference('System.Drawing')
                from System.Windows.Forms import NotifyIcon, ContextMenuStrip, ToolStripMenuItem
                from System.Drawing import Icon, SystemIcons

                def setup_native():
                    nonlocal tray
                    tray = NotifyIcon()
                    tray.Icon = (
                        Icon(str(base / 'studio.ico')) if (base / 'studio.ico').exists() else SystemIcons.Application
                    )
                    tray.Text = desktop.tray_text(controller.connection.get('state'), controller.paused)
                    menu = ContextMenuStrip()
                    for title, handler in [
                        ('Open Studio', lambda: show()),
                        ('Pause mappings', lambda: controller.request('pause')),
                        ('Stop all audio', lambda: controller.request('stopAudio')),
                        ('Quit Studio', lambda: controller.request('quit')),
                    ]:
                        item = ToolStripMenuItem(title)
                        item.Click += lambda sender, event, handler=handler: handler()
                        menu.Items.Add(item)
                        if title == 'Pause mappings':
                            tray_items['pause'] = item
                    tray.ContextMenuStrip = menu
                    tray.DoubleClick += lambda sender, event: show()
                    tray.Visible = True
                    # Only our bundled document has access to the native bridge.
                    browser = window.native.browser.webview

                    def navigation(sender, args):
                        if not str(args.Uri).startswith('about:blank'):
                            args.Cancel = True

                    browser.NavigationStarting += navigation
                    logging.info('Tray installed and external navigation blocked')

                window.native.Invoke(Action(setup_native))

                def update_tray():
                    paused = controller.paused
                    tray.Text = desktop.tray_text(controller.connection.get('state'), paused)
                    tray_items['pause'].Text = 'Resume mappings' if paused else 'Pause mappings'
                    tray_items['pause'].Checked = paused

                def dropped(event):
                    files = event.get('dataTransfer', {}).get('files', [])
                    paths = [f['pywebviewFullPath'] for f in files if f.get('pywebviewFullPath')]
                    if paths:
                        window.run_js('window.receiveNativeDrop(' + json.dumps(paths) + ')')
                    else:
                        controller.event(
                            'error', {'message': 'Windows did not provide a dropped file path. Use Browse instead.'}
                        )

                element = window.dom.get_element('#audioDrop')
                if element:
                    element.events.drop += dropped
                window.run_js('window.nativeDropEnabled=true')
                if '--ui-check' in sys.argv:
                    check_ui(window, controller, ROOT)
            except Exception:
                startup_failed = True
                logging.exception('Desktop setup failed')
                visible_error('The desktop interface loaded, but native setup failed. See startup.log.')
                controller.quitting = True
                window.destroy()
            saved_size = dict(remembered)
            tray_status = None
            while not controller.stop.is_set() and not controller.quitting:
                if kernel.WaitForSingleObject(show_event, 500) == 0:
                    show()
                if remembered != saved_size:
                    saved_size = dict(remembered)
                    try:
                        controller.remember_window(saved_size)
                    except Exception:
                        logging.exception('Could not remember the window size')
                status = (controller.connection.get('state'), controller.paused)
                if tray is not None and 'pause' in tray_items and status != tray_status:
                    tray_status = status
                    try:
                        window.native.BeginInvoke(Action(update_tray))
                    except Exception:
                        logging.exception('Tray update failed')

        webview.start(
            initialize,
            gui='edgechromium',
            debug='--debug' in sys.argv,
            private_mode=False,
            storage_path=str(ROOT / 'WebView'),
            icon=str(base / 'studio.ico') if (base / 'studio.ico').exists() else None,
        )
        logging.info('Desktop window closed')
        return 1 if startup_failed else 0
    except BaseException as exc:
        logging.exception('Desktop startup failed')
        visible_error('Could not start SMC-PAD Studio: ' + str(exc))
        return 1
    finally:
        if tray:
            try:
                tray.Visible = False
                tray.Dispose()
            except Exception:
                pass
        if controller:
            try:
                controller.close()
            except Exception:
                logging.exception('Shutdown failed')
        if show_event:
            kernel.CloseHandle(show_event)
        if mutex:
            kernel.CloseHandle(mutex)


def check_ui(window, controller, root):
    """Exercise the real packaged native bridge without executing desktop shortcuts."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if window.evaluate_js('window.studioReady'):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('UI never became ready')
    results = []
    import wave

    fixture = root / 'verification-silence.wav'
    with wave.open(str(fixture), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(bytes(44100 * 2))
    window.run_js('window.checkClip=' + json.dumps(str(fixture)))
    script = """(async()=>{
      const assert=(v,m)=>{if(!v)throw Error(m)};
      assert(document.getElementById('pads').children.length===16,'Pad canvas missing');
      assert(document.getElementById('knobs').children.length===8,'Encoder canvas missing');
      const before=await window.pywebview.api.request('snapshot',{});
      const initial=before.value.store.profiles[0];
      let value=await window.pywebview.api.request('newProfile',{name:'Verification workspace'});assert(value.ok,'Profile creation');
      await refresh();assert(document.getElementById('profileSelect').selectedOptions[0].textContent==='Verification workspace','Profile not rendered');
      await selectControl('pad3');document.getElementById('labelInput').value='Quiet clip';document.getElementById('audioVolume').value='0';document.getElementById('actionSelect').value='none';await saveEditor();
      const saved=await window.pywebview.api.request('snapshot',{});
      const p=saved.value.store.profiles.find(p=>p.id===saved.value.store.activeProfile);
      assert(p.pages[0].banks.A.pad3.audioVolume===0,'Zero gain was not retained');
      const imported=importForEditor([window.checkClip]);selected='pad4';loadEditor();await imported;await refresh();
      assert(controls().pad3.action==='playAudio','Imported clip missed captured target');
      assert(controls().pad4.action==='none','Imported clip changed a newly selected pad');
      assert(controls().pad3.audioVolume===0,'Import reset zero gain');
      await selectControl('pad3');document.getElementById('actionSelect').value='macro';draft.steps=[{type:'delay',milliseconds:250},{type:'typeText',value:'dry run only'}];renderFields();renderSteps();
      const preview=await window.pywebview.api.request('macroPreview',{...target,control:collect()});assert(preview.ok&&preview.value.length===2,'Macro dry run');
      draft.steps=[];loadEditor();
      assert(document.querySelector('[data-id="pad13"]').style.order==='0','Physical pad orientation');
      await window.pywebview.api.request('newPage',{name:'Creative'});await refresh();
      assert(document.getElementById('pageSelect').selectedOptions[0].textContent==='Creative','Page not rendered');
      await window.pywebview.api.request('switchPage',{bank:'B'});await refresh();assert(document.getElementById('bankB').classList.contains('active'),'Bank switch');
      const shape=await window.pywebview.api.request('waveform',{path:window.checkClip,width:120});assert(shape.ok&&shape.value.peaks.length===120,'Waveform');
      for(const view of ['soundboard','profiles','device','settings','studio']){await showView(view);assert(!document.getElementById('view-'+view).classList.contains('hidden'),'View '+view);}
      await window.pywebview.api.request('pause',{paused:true});await refresh();assert(document.getElementById('pauseBtn').textContent.includes('Resume'),'Pause state');
      await window.pywebview.api.request('pause',{paused:false});
      await window.pywebview.api.request('switchProfile',{id:initial.id});await refresh();
      return {pads:16,knobs:8,profile:true,page:true,bank:true,zeroVolume:true,navigation:true,pause:true,importTarget:true,macroPreview:true,physicalPadOrientation:true,waveform:true};
    })()"""
    window.run_js(
        'window.__checkResult=null;'
        + script
        + '.then(value=>window.__checkResult={ok:true,value}).catch(error=>window.__checkResult={ok:false,error:String(error)})'
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = window.evaluate_js('window.__checkResult')
        if result is not None:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('UI checks did not finish')
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'UI check failed'))
    results.append(result['value'])
    inspected = controller.audio.command('inspect', {'value': str(fixture)}, wait=True)
    controller.audio.command(
        'play',
        {
            'value': str(fixture),
            'control': 'verification',
            'volume': 0,
            'trimStart': 0.1,
            'trimEnd': 0.4,
            'loop': True,
            'fadeIn': 0.02,
            'fadeOut': 0.02,
        },
        wait=True,
    )
    try:
        time.sleep(0.5)
        playing = controller.audio.snapshot()['players']
        if not playing or playing[0]['volume'] != 0 or not playing[0]['loop']:
            raise RuntimeError('Packaged audio worker verification failed')
        results.append({'nativeAudio': True, 'duration': inspected['duration'], 'silentTrimmedLoop': True})
    finally:
        controller.audio.command('stop', wait=True)
    if '--hardware-read' in sys.argv or '--hardware-colors' in sys.argv:
        controller.request('connect')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and (controller.connection['state'] != 'connected' or controller.device_busy):
            time.sleep(0.1)
        if controller.connection['state'] != 'connected':
            raise RuntimeError('Packaged MIDI connection failed: ' + str(controller.connection))
        controller._detect_preset()
        active = controller.detected_preset()
        window.evaluate_js('refresh()')
        time.sleep(0.3)
        assert window.evaluate_js("Number(document.getElementById('rgbPreset').value)") == active
        assert window.evaluate_js("document.getElementById('rgbPreset').disabled")
        for bank in ['A', 'B']:
            read = controller.request('readRGB', {'preset': 0, 'bank': bank})
            if not read['ok']:
                raise RuntimeError(read['error'])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and (
                controller.rgb_state.get('bank') != bank
                or controller.rgb_state['state'] != 'synced'
                or controller.device_busy
            ):
                time.sleep(0.1)
            if controller.rgb_state.get('bank') != bank or controller.rgb_state['state'] != 'synced':
                raise RuntimeError('Packaged RGB read failed: ' + str(controller.rgb_state))
            assert controller.rgb_state['preset'] == active
            results.append(
                {
                    'nativeHardwareReadBank': bank,
                    'activePreset': active + 1,
                    'automaticPresetSelector': True,
                    'pads': len(controller.rgb_state['colors']),
                    'performanceInput': controller.primary,
                    'configurationInput': controller.rgb.port,
                }
            )
    if '--hardware-colors' in sys.argv:
        from verify_ui_colors import check_colors

        results.append(check_colors(window, controller, root))
    for width in [1440, 1100, 800]:
        window.resize(width, 900)
        time.sleep(0.25)
        geometry = window.evaluate_js(
            "({width:innerWidth,body:document.body.scrollWidth,content:document.querySelector('.content').clientWidth,inspector:getComputedStyle(document.querySelector('.studio-layout')).gridTemplateColumns})"
        )
        if geometry['body'] > geometry['width'] + 2:
            raise RuntimeError('Horizontal page overflow at ' + str(width))
        results.append({'layoutWidth': width, **geometry})
    window.hide()
    time.sleep(0.4)
    assert controller.action_thread.is_alive() and controller.transport.thread.is_alive()
    window.show()
    logging.info('UI check passed %s', results)
    (root / 'ui-check.json').write_text(
        json.dumps({'ok': True, 'results': results, 'hiddenRuntimeAlive': True}, indent=2)
    )
    controller.quitting = True
    window.destroy()


if __name__ == '__main__':
    sys.exit(main())
