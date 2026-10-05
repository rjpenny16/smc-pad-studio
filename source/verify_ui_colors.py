"""Explicit native Apply-colors test; used only with --ui-check --hardware-colors.

Runs against isolated verification profiles and restores the full device color
snapshot. Physical LED observation is still a separate human verification.
"""
import json
import sys
import time


def check_colors(window, controller, root):
    rgb=controller.rgb
    preset=controller.detected_preset()
    if preset is None:raise RuntimeError('The active hardware preset could not be read')
    for bank in ['A','B']:rgb.read_colors(preset,bank)
    baseline=bytes(rgb.flash)
    (root/'hardware-colors-before.bin').write_bytes(baseline)
    report={'activePreset':preset+1,'banks':{},'physicalObservation':'requires human confirmation'}
    try:
        window.show()
        for bank,color in [('A','#ffffff'),('B','#00ff00')]:
            script="""(async()=>{
              await mutate('switchPage',{bank:BANK});
              const ctx=context();
              for(let i=1;i<=16;i++){
                const id='pad'+i;
                await call('saveControl',{...ctx,id,control:{...controls()[id],color:COLOR}});
              }
              await refresh();loadEditor();
              if(document.getElementById('applyRGB').disabled)throw Error('Apply colors is disabled');
              document.getElementById('applyRGB').click();
              return true;
            })()""".replace('BANK',json.dumps(bank)).replace('COLOR',json.dumps(color))
            window.run_js('window.__colorCheck=null;'+script+'.then(()=>window.__colorCheck={ok:true}).catch(e=>window.__colorCheck={error:String(e)})')
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                state=controller.request('snapshot')['value']['rgb']
                ui=window.evaluate_js('window.__colorCheck')
                if ui and ui.get('error'):raise RuntimeError(ui['error'])
                if (ui and ui.get('ok') and not controller.device_busy
                        and state.get('bank')==bank and state.get('state')=='synced'
                        and len(state.get('results',[]))==16
                        and all(r['ok'] and r['color']==color for r in state['results'])):break
                time.sleep(.1)
            else:raise RuntimeError('Native Apply colors did not complete for Bank '+bank)
            written_preset=state['preset']
            actual=rgb.read_colors(written_preset,bank)
            if actual!={f'pad{i}':color for i in range(1,17)}:raise RuntimeError('Native button color readback mismatch')
            report['banks'][bank]={'nativeApplyButton':True,'verifiedPads':16,'preset':written_preset+1,'color':color}
            hold=0 if '--no-color-hold' in sys.argv else 40
            print(f'VISUAL CHECK: Bank {bank}, Preset {written_preset+1}, all 16 pads {color}.',flush=True)
            deadline=time.monotonic()+hold
            if '--wait-for-observation' in sys.argv:
                confirmation=root/f'confirm-colors-{bank}.json'
                print('WAITING FOR OBSERVATION:',str(confirmation),flush=True)
                deadline=time.monotonic()+900
                while not confirmation.exists() and time.monotonic()<deadline:time.sleep(.2)
                if not confirmation.exists():raise TimeoutError('No physical observation received for Bank '+bank)
                report['banks'][bank]['physicalObservation']=json.loads(confirmation.read_text(encoding='utf8'))
            else:
                while time.monotonic()<deadline:time.sleep(.2)
    finally:
        # The person watching can switch presets during either hold. Restore
        # every bank actually changed, including a write redirected to the new
        # live preset, rather than restoring only the preset seen at startup.
        rgb.unlock();current=bytes(rgb.flash);failures=[]
        for p in range(8):
            for bank,group in [('A',2),('B',7)]:
                addresses=[p*3539+211+(group*16+i)*26+5 for i in range(16)]
                if all(current[a:a+3]==baseline[a:a+3] for a in addresses):continue
                colors={f'pad{i+1}':'#'+baseline[a:a+3].hex() for i,a in enumerate(addresses)}
                try:
                    if not all(r['ok'] for r in rgb.apply(colors,p,bank)):failures.append((p+1,bank))
                except Exception as exc:failures.append((p+1,bank,str(exc)))
        rgb.unlock();report['fullConfigurationRestored']=bytes(rgb.flash)==baseline
        if failures:report['restoreFailures']=failures
        (root/'hardware-colors.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    if not report['fullConfigurationRestored']:raise RuntimeError('Configuration differs after native color test')
    return report
