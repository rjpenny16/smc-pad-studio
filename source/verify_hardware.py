"""Explicit, reversible RGB hardware check. Never called during normal startup."""

import json
from pathlib import Path
import time
from midi import Transport, RGB, ports


def verify(destination):
    report = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'banks': {}, 'restored': False}
    transport = Transport(lambda *args: None)
    rgb = RGB(transport, lambda *args: None)
    original = None
    try:
        available = ports()
        rgb.discover(available)
        rgb.unlock()
        original = bytes(rgb.flash)
        report['configurationInput'] = next(p['name'] for p in available['inputs'] if p['id'] == rgb.port)
        report['configurationOutput'] = next(p['name'] for p in available['outputs'] if p['id'] == transport.output_id)
        for bank in ['A', 'B']:
            colors = rgb.read_colors(0, bank)
            change = rgb.apply({'pad1': '#ff2020'}, 0, bank)
            assert change[0]['ok'], change
            restored = rgb.apply({'pad1': colors['pad1']}, 0, bank)
            assert restored[0]['ok'], restored
            batch = rgb.apply(colors, 0, bank)
            assert len(batch) == 16 and all(r['ok'] for r in batch), batch
            actual = rgb.read_colors(0, bank)
            assert actual == colors
            report['banks'][bank] = {
                'readPads': 16,
                'changedPadVerified': True,
                'batchVerified': 16,
                'colorsRestored': True,
            }
        rgb.unlock()
        assert bytes(rgb.flash) == original, 'Non-RGB configuration changed'
        report.update(ok=True, restored=True, fullConfigurationUnchanged=True)
    except Exception as exc:
        report.update(ok=False, error=str(exc))
        raise
    finally:
        if original is not None:
            # Restore only known, validated RGB addresses if verification failed.
            for bank in ['A', 'B']:
                expected = {
                    f'pad{i}': '#' + original[rgb.address(i, 0, bank) : rgb.address(i, 0, bank) + 3].hex()
                    for i in range(1, 17)
                }
                if not report.get('ok'):
                    try:
                        result = rgb.apply(expected, 0, bank)
                        report.setdefault('recovery', {})[bank] = all(r['ok'] for r in result)
                    except Exception as exc:
                        report.setdefault('recovery', {})[bank] = str(exc)
        transport.close()
        Path(destination).write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    import sys

    if '--hardware' not in sys.argv:
        raise SystemExit('Pass --hardware to explicitly run reversible RGB writes on preset 1.')
    verify(sys.argv[-1])
