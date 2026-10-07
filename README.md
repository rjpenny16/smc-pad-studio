# SMC-PAD Studio 0.8.0

Download `SMC-PAD-Studio-v0.8.0.exe` from this repository's **Releases** page and run it. Each release also carries `SHA256.txt` for checking the download. No Python installation is needed. This is a dedicated Windows desktop window with a native MIDI/audio runtime and a tray menu. It loads its bundled interface directly; there is no localhost page or HTTP server to start.

## First session

1. Close older Control Center instances and MidiSuite so they can release the MIDI device.
2. Plug the SMC-PAD in by USB. Studio connects by itself at startup and whenever the controller is plugged in (Settings → **Connect automatically**). **Connect device** connects by hand, and the Device page also offers manual performance/configuration port selection.
3. Select a pad or encoder and choose an action. Pads respond to their factory notes right away (Bank A 36–51, Bank B 52–67, channel 10), and the canvas highlights each control you press or turn. Use **Learn physical control** for encoders, buttons, or a controller whose notes were changed; learning an input another control used moves it rather than making both fire. Save the control. **Test** executes its action immediately.
4. For audio, choose **Audio clip**, browse or drop a supported file, and set gain, trim, playback mode, loop and fades. The Soundboard view holds imported clips and the live mixer.
5. For hardware lighting, see **Pad colors** below.

## YouTube audio and cropping

- **YouTube to MP3:** paste a youtube.com or youtu.be link into **Import from YouTube** on the Soundboard, or into **Or paste a YouTube link** in a pad's Audio clip settings, and choose Download MP3 / Get MP3. Studio saves the audio as an MP3 in your clip library, and the pad version also assigns it to that pad. Progress and Cancel appear under the field. Single videos up to 3 hours are supported; playlists and live streams are not. Only download audio you have the right to use.
- YouTube now requires a JavaScript runtime for downloads. If a download fails with a message about one, install [Deno](https://deno.com) (`winget install DenoLand.Deno`) or Node.js and restart Studio. YouTube changes often, so a download that stops working usually needs a newer Studio release with an updated yt-dlp.
- **Cropping:** every audio pad and the Soundboard's Selected clip panel show the clip's waveform. Drag either handle to set the start or end, drag the highlighted part to move the whole selection, or click the waveform to move the nearest edge there. With a handle focused, the arrow keys nudge it by 0.1 s (Shift: 1 s). **Full clip** resets the selection, and the trim fields below stay in sync for exact values. A gold line follows the clip while it plays.
- Cropping a pad is non-destructive: the pad plays only the selected part and the original file is unchanged. On the Soundboard, **Assign clip** assigns only the selected part, and **Save as new clip** writes the selection to a separate file in your library.

## Pad colors

The SMC-PAD stores eight presets, and only the one it is currently using lights the pads. A write to any other preset succeeds without any visible change, so the first step is to tell Studio which preset is active.

1. Connect the device. Studio reads its active preset directly and follows the physical **PAD BANK** switch: off is Bank A, on is Bank B. The preset selector shows the detected preset automatically.
2. Choose **Read colors**, then **Identify preset** to flash the selected bank's 16 pads white and restore them. No preset calibration is needed. Presets are changed on the controller with SHIFT plus Pads 1–8; use PAD BANK off when selecting a preset.
3. Pick colors in the editor (or **Use device palette** to start from the device's own) and choose **Apply palette**. Saving mappings alone never writes hardware colors.
4. Choose **Save to device** to keep the colors after the controller is unplugged. Without it, the device may return to its previously saved colors at power-up.

Settings → **Light pads while their audio clips play** paints a pad in the playing color while its clip plays and restores it afterwards. These temporary colors are never saved to the device.

Windows can expose the configuration endpoint as `SMC-PAD`, `MIDIIN2/3 (SMC-PAD)` or `MIDIOUT2/3 (SMC-PAD)` instead of a name containing “Private.” Discovery verifies replies instead of requiring that exact label. Performance input discovery also follows actual pad/encoder activity; manual selection takes precedence.

Hardware writes are serialized, re-establish the device session first, touch only the three RGB bytes for each pad, check device acknowledgements and read every color back. A failed or cancelled batch reports individual pad results. Bank B uses the final 16 dedicated pad records, distinct from the octave records with the same MIDI notes. A preset or pad whose records are unrecognized stays write-protected. Studio rechecks the active preset immediately before queued reads and writes. Studio never switches the hardware preset itself.

## Everyday controls

- Profiles have application pages and local mapping banks. A and B match the controller’s two physical pad banks (factory notes 36–51 and 52–67). The extra C–H mapping banks cover other MIDI note ranges; they are not extra positions of the physical PAD BANK button. Banks C–H are added to a profile the first time they are used. Different pages provide different action sets without rewriting hardware MIDI settings. Assign **Next page** or **Previous page** to a pad or button, or **Switch pages** to an encoder, to change pages from the controller while Studio is in the tray. Pages are renamed and deleted in Profiles.
- App rules accept executable names separated by commas, such as `chrome.exe, msedge.exe`. Enable automatic profiles in Settings and unpin the active profile to allow switching.
- Macros support ordered actions, waits, duplication, reordering, a dry-run preview and cancellation. Dry-run executes nothing. Pause stops queued mappings/macros; Stop Audio is separate.
- Encoder controls offer absolute/relative/auto interpretation, sensitivity, inversion, acceleration and a live input preview. Choose Absolute for the stock absolute SMC-PAD encoders if auto interpretation is unsuitable.
- Ctrl-click several controls to copy an assignment while preserving each control's MIDI mapping. When several pads are selected, Apply writes their colors. Undo restores recent saved edits in this session and names what it reverted; switching banks, pages or profiles and changing settings are not Undo steps.
- Closing the window hides it to the tray and leaves MIDI/audio running. Open, Pause, Stop Audio and Quit are available there, and the tray tooltip shows whether Studio is connected or paused. Launching the EXE again restores the existing window. Quit in Settings exits completely.
- Settings → **Start Studio when I sign in to Windows** opens Studio in the tray at sign-in, so pads work as soon as the controller is plugged in. The entry follows the EXE each time you start a newer release.
- The window opens at a size that fits your screen and remembers its size and maximized state.
- Reduced motion and keyboard navigation are available. Ctrl+S saves the selected control. Escape cancels MIDI learning and dismisses dialogs/diagnostics.

Some hardware function buttons, including Shift, may not send MIDI. They remain selectable for local actions; only buttons that emit MIDI can be learned for physical triggers.

## Existing v0.4/v0.5 profiles

In the old interface choose **Export profile**, then import that JSON from Studio's Profiles view. Legacy actions, colors, mappings and audio settings migrate into Page 1 / Bank A. Learn Bank B separately. Existing clips referenced by absolute paths must still exist; export a portable ZIP from Studio to include clips, including macro audio steps.

Studio does not read a browser's private local storage. Keep your old profile export until the imported mappings are checked. Old action types remain available: shortcuts, typed text, apps/files, URLs, Windows window/desktop commands, scrolling, media/volume commands, audio playback and all knob actions.

## Local data and troubleshooting

Data lives under `%LOCALAPPDATA%\SMC-PAD Control Center`:

- `studio.json`: profiles/settings, saved atomically.
- `studio.json.bak`: previous saved state; corrupt originals are preserved when recovery runs.
- `Audio`: managed imported clips, YouTube downloads and cropped copies.
- `startup.log`: rotating startup/runtime logs.

Open **Connection details** for current activity, or export a troubleshooting report from Device. Startup/native setup errors display a Windows error dialog and name the log file. Missing/busy MIDI ports, codec errors, rejected RGB writes and queue overflow are reported in the interface.

Requirements: Windows x64 with Microsoft Edge WebView2 Runtime and .NET Framework 4.x (present on the Windows 11 system used for verification). WAV playback was tested with the Windows media engine. MP3/M4A/AAC/WMA/FLAC depend on the codecs available to that engine on your PC. YouTube conversion, waveforms and cropping use the FFmpeg program bundled with Studio. Playback uses the default Windows output; per-device output selection is outside this release. This local build is unsigned.

## Verification and source

`VERIFICATION-v0.6.0.json` records automated backend/native-interface checks and reversible tests on the attached SMC-PAD. Both A and B had all 16 colors read, changed/read back, batch written and restored; the complete configuration matched its original bytes afterward. Physical button presses, audible output quality and USB unplug/replug remain manual checks; those are not claimed as completed automated tests.

The repository's `source` folder holds the code, pinned dependencies, a Windows build script, regression tests and an explicit opt-in hardware verification script. No hardware writes run automatically during startup or regression tests. The protocol reference is [spectalive/smc-pad](https://github.com/spectalive/smc-pad); the implementation here was independently written from the observed wire format and validated on the attached device.
