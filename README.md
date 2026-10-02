# SMC-PAD Studio 0.6.0

Run `SMC-PAD-Studio-v0.6.0.exe`. No Python installation is needed. This is a dedicated Windows desktop window with a native MIDI/audio runtime and a tray menu. It loads its bundled interface directly; there is no localhost page or HTTP server to start.

## First session

1. Close older Control Center instances and MidiSuite so they can release the MIDI device.
2. Plug the SMC-PAD in by USB and choose **Connect device**. The Device page also offers manual performance/configuration port selection.
3. Select a pad or encoder, choose an action, then **Learn physical control** and press or turn it. Save the control. **Test** executes its action immediately.
4. For audio, choose **Audio clip**, browse or drop a supported file, and set gain, trim, playback mode, loop and fades. The Soundboard view holds imported clips and the live mixer.
5. For hardware lighting, select the correct hardware preset and A/B bank, then **Read colors**. **Use device palette** copies those colors into the local profile. Change local colors and choose **Apply palette** to write them. Saving mappings alone never writes hardware colors.

Windows can expose the configuration endpoint as `SMC-PAD`, `MIDIIN2/3 (SMC-PAD)` or `MIDIOUT2/3 (SMC-PAD)` instead of a name containing “Private.” Discovery verifies replies instead of requiring that exact label. Performance input discovery also follows actual pad/encoder activity; manual selection takes precedence.

Hardware writes are serialized, touch only the three RGB bytes for each pad, check device acknowledgements and read every color back. A failed or cancelled batch reports individual pad results. An unrecognized configuration layout blocks writes. Edited hardware MIDI layouts may therefore need the expected layout restored before RGB editing works. Select the preset currently used on the device; Studio does not switch its hardware preset.

## Everyday controls

- Profiles have application pages and separate A/B banks. Hardware bank activity follows the bank on screen. Different pages provide different action sets without rewriting hardware MIDI settings.
- App rules accept executable names separated by commas, such as `chrome.exe, msedge.exe`. Enable automatic profiles in Settings and unpin the active profile to allow switching.
- Macros support ordered actions, waits, duplication, reordering, a dry-run preview and cancellation. Dry-run executes nothing. Pause stops queued mappings/macros; Stop Audio is separate.
- Encoder controls offer absolute/relative/auto interpretation, sensitivity, inversion, acceleration and a live input preview. Choose Absolute for the stock absolute SMC-PAD encoders if auto interpretation is unsuitable.
- Ctrl-click several controls to copy an assignment while preserving each control's MIDI mapping. When several pads are selected, Apply writes their colors. Undo restores recent saved edits in this session.
- Closing the window hides it to the tray and leaves MIDI/audio running. Open, Pause, Stop Audio and Quit are available there. Launching the EXE again restores the existing window. Quit in Settings exits completely.
- Reduced motion and keyboard navigation are available. Ctrl+S saves the selected control. Escape cancels MIDI learning and dismisses dialogs/diagnostics.

Some hardware function buttons, including Shift, may not send MIDI. They remain selectable for local actions; only buttons that emit MIDI can be learned for physical triggers.

## Existing v0.4/v0.5 profiles

In the old interface choose **Export profile**, then import that JSON from Studio's Profiles view. Legacy actions, colors, mappings and audio settings migrate into Page 1 / Bank A. Learn Bank B separately. Existing clips referenced by absolute paths must still exist; export a portable ZIP from Studio to include clips, including macro audio steps.

Studio does not read a browser's private local storage. Keep your old profile export until the imported mappings are checked. Old action types remain available: shortcuts, typed text, apps/files, URLs, Windows window/desktop commands, scrolling, media/volume commands, audio playback and all knob actions.

## Local data and troubleshooting

Data lives under `%LOCALAPPDATA%\SMC-PAD Control Center`:

- `studio.json`: profiles/settings, saved atomically.
- `studio.json.bak`: previous saved state; corrupt originals are preserved when recovery runs.
- `Audio`: managed imported clips.
- `startup.log`: rotating startup/runtime logs.

Open **Connection details** for current activity, or export a troubleshooting report from Device. Startup/native setup errors display a Windows error dialog and name the log file. Missing/busy MIDI ports, codec errors, rejected RGB writes and queue overflow are reported in the interface.

Requirements: Windows x64 with Microsoft Edge WebView2 Runtime and .NET Framework 4.x (present on the Windows 11 system used for verification). WAV playback was tested with the Windows media engine. MP3/M4A/AAC/WMA/FLAC depend on the codecs available to that engine on your PC. Playback uses the default Windows output; per-device output selection is outside this release. This local build is unsigned.

## Verification and source

`VERIFICATION-v0.6.0.json` records automated backend/native-interface checks and reversible tests on the attached SMC-PAD. Both A and B had all 16 colors read, changed/read back, batch written and restored; the complete configuration matched its original bytes afterward. Physical button presses, audible output quality and USB unplug/replug remain manual checks; those are not claimed as completed automated tests.

The ZIP includes `source`, pinned dependencies, a Windows build script, regression tests and an explicit opt-in hardware verification script. No hardware writes run automatically during startup or regression tests. The protocol reference is [spectalive/smc-pad](https://github.com/spectalive/smc-pad); the implementation here was independently written from the observed wire format and validated on the attached device.
