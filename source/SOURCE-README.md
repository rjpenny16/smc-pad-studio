# Maintaining this build

The production entry point is `main.py`. `controller.py` exposes a single allowlisted bridge to the bundled `studio.html`; the bridge has no external HTTP endpoint. MIDI uses Windows WinMM, actions use Windows input APIs, audio uses Windows MediaPlayer, and the native shell uses pywebview/WebView2 with a WinForms tray.

Use Windows x64 Python 3.14 (the release was built with 3.14.4). Run `build.ps1` to install pinned direct dependencies and build the EXE. The icon is already included; Pillow is not a runtime or build dependency.

Run safe regression tests with `python test_studio.py`. They execute no desktop shortcuts and perform no hardware writes. Native audio tests use generated silence. Fake transport tests check corrupt replies, port/address filtering, duplicate Bank B records, acknowledgement rejection and color readback failures.

Run `python main.py --ui-check --no-dialog` for a real native WebView2/bridge check; it automatically uses a separate verification directory unless `SMC_STUDIO_DATA` is explicitly supplied. The same flags work on the packaged EXE. The test checks profile/page/bank state, zero volume, captured audio import targets, macro preview, physical pad orientation, view navigation, responsive widths and live workers while the window is hidden. Reports appear in `ui-check.json` beside the test's startup log.

`SMC_STUDIO_DATA` overrides the data folder for development/testing. Production profiles are never silently imported from browser storage; legacy JSON imports are explicit.

Hardware verification is opt-in: `python verify_hardware.py --hardware report.json`. Close other MIDI apps first. This script briefly changes Pad 1 on hardware preset 1 in both banks, verifies readback, restores it, checks full-bank original-color writes, and compares the complete configuration before/after. It writes only validated RGB addresses and attempts recovery if a test fails. Do not run it while performing live with the controller.
