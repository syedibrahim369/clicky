# Clicky for Linux: working notes

Read this first when picking the port up in a fresh session. Branch: `feature/linux-port`.

## Status
- [x] M1 Overlay
- [x] M2 Trigger + capture
- [x] M3 Speech-to-text
- [ ] M4 Brain + pointing
- [ ] M5 Voice
- [ ] M6 Polish

## Running things
All commands run from `linux/`.

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    scripts/dev-x11.sh                       # nested desktop on DISPLAY=:20; --stop to end it
    DISPLAY=:20 .venv/bin/python -m clicky --point 400 300 "test" --screen 0
    .venv/bin/python -m pytest -q tests
    DISPLAY=:20 PYTHONPATH=. .venv/bin/python tests/verify_overlay_x11.py /tmp/out.png
    DISPLAY=:20 .venv/bin/python -m clicky --dump-captures /tmp/clicky-captures   # hold Ctrl+Alt
    DISPLAY=:20 .venv/bin/python -m clicky --no-voice     # hotkey and capture only, mic stays off
    .venv/bin/python -m clicky --trigger

    # Speech check: plays clips into a temporary virtual mic, so no talking is needed.
    # Needs clips from tests/generate_speech_fixtures.py (which needs Piper and two voices).
    DISPLAY=:20 PYTHONPATH=. .venv/bin/python tests/verify_speech_x11.py <clips directory>

    # HiDPI + hotkey + socket check, at the real panel size. Changes Xft.dpi on the display
    # it runs against, so only ever run it on a nested display:
    scripts/dev-x11.sh --size 3072x1920 --display 21
    DISPLAY=:21 PYTHONPATH=. .venv/bin/python tests/verify_capture_x11.py

## Decisions
- **Package layout:** code lives in `linux/clicky/{core,platform}`. A top-level `platform/`
  would shadow Python's stdlib `platform` module.
- **Platform protocol:** the four specified methods plus `run_event_loop()` and `quit()`,
  because Qt owns the main thread and core must not import Qt.
- **One overlay window per monitor:** all windows paint one shared desktop-wide cursor
  state, so flights between monitors need no hand-off.
- **Cursor shape:** a notched dart, not Clicky's equilateral triangle, which looked like it
  pointed right of the target at rest. It rotates around its tip, so the tip stays on target.
- **Screen numbering:** screens are sorted by (left, top) so Qt and mss indexes agree.
  `--screen` is 0-based. Clicky's `screenN` tag is 1-based with the cursor's screen first,
  so M4 has to map between them.
- **Overlay hidden when idle:** windows unmap after `clear()`, keeping them out of screenshots.
- **Re-raise before each flight:** bypass-WM windows are not kept on top by the WM.
- **Display checks:** refuses XWayland (it would run but not work) and displays with no
  compositor (the translucent window would be a black, input-ignoring full-screen window).
- **Pixel units:** `Platform.point` and `CapturedScreen.left/top/width/height` are logical;
  the PNG is physical. Convert through a fraction of the image size, then multiply by logical
  width and height, so a later image downscale cannot move the cursor. Verified at Xft.dpi
  scales 1, 1.25, 1.5 and 2 at 3072x1920: tip within 1.4 physical px of a known marker.
- **Layout mismatch is an error:** `verify_layouts_match` raises if mss and Qt disagree,
  because a silent mismatch would point at the wrong place.
- **Capture hides the overlay immediately** with no fade, then waits 80 ms for the
  compositor, because mss cannot exclude our windows.
- **Hotkey semantics:** holds under 0.3 s, and Ctrl+Alt+another key, give `CANCELLED`, not a
  question. While a `--trigger` recording runs, the hotkey is ignored. `--trigger` can stop a
  recording that the hotkey started.
- **Trigger socket:** `$XDG_RUNTIME_DIR/clicky-trigger.sock`, mode 0600 from the moment it is
  bound (umask, not chmod). There is no /tmp fallback. Also acts as the single-instance lock.
  A hard kill leaves a stale file, which the next start replaces.
- **pynput stays:** the evdev build worked, so the XRecord fallback was not needed.
- **Speech-to-text defaults:** `base.en`, int8, 4 threads, beam 5, VAD on. Over 16 synthetic
  clips of about 2 s on the i7-1355U (mean transcribe time, clips exact, before hotwords):

      tiny.en  4 threads beam 1   0.81 s   14/16
      base.en  4 threads beam 1   1.51 s   15/16
      base.en 10 threads beam 1   1.20 s   15/16
      base.en  4 threads beam 5   1.66 s   16/16
      small.en 6 threads beam 1   3.44 s   16/16

  Thread count made little difference for base.en and the spread looks like noise, so 4 keeps
  the CPU free for the LLM. Beam 1 misheard "GNOME" as "NONE".
- **Hotwords:** stand in for Clicky's AssemblyAI keyterms. Without them the real pipeline
  heard "Bluetooth" as "blue cheese". With them: 16/16 in 3 runs, with no added latency, and
  four unrelated test phrases were not pulled toward desktop words.
- **End-to-end M3 result:** 1.6 s from key release to text, about 2.2 s model load at launch,
  about 550 MB app memory, 35 ms to open the microphone. All on synthetic speech.
- **Order on release:** screenshot, then stop the mic, then transcribe. The mic keeps running
  during the screenshot, which also protects a last word from an early release.
- **Recording limit:** 60 s, enforced by the orchestrator. It then calls
  `Platform.end_active_trigger()`, a seventh Platform method, so a later toggle starts fresh.
- **Interrupting:** any new press abandons work in progress. Whisper cannot be stopped, so the
  thread finishes and discards its own result, using a question number.
- **Audio stays in memory.** Nothing is written to disk.
- **Agreed for later milestones:**
- **Speech-to-text defaults:** `base.en`, int8, 4 threads, beam 5, VAD on. Over 16 synthetic
  clips of about 2 s on the i7-1355U (mean transcribe time, clips exact, before hotwords):

      tiny.en  4 threads beam 1   0.81 s   14/16
      base.en  4 threads beam 1   1.51 s   15/16
      base.en 10 threads beam 1   1.20 s   15/16
      base.en  4 threads beam 5   1.66 s   16/16
      small.en 6 threads beam 1   3.44 s   16/16

  Thread count made little difference for base.en and the spread looks like noise, so 4 keeps
  the CPU free for the LLM. Beam 1 misheard "GNOME" as "NONE".
- **Hotwords:** stand in for Clicky's AssemblyAI keyterms. Without them the real pipeline
  heard "Bluetooth" as "blue cheese". With them: 16/16 in 3 runs, with no added latency, and
  four unrelated test phrases were not pulled toward desktop words.
- **End-to-end M3 result:** 1.6 s from key release to text, about 2.2 s model load at launch,
  about 550 MB app memory, 35 ms to open the microphone. All on synthetic speech.
- **Order on release:** screenshot, then stop the mic, then transcribe. The mic keeps running
  during the screenshot, which also protects a last word from an early release.
- **Recording limit:** 60 s, enforced by the orchestrator. It then calls
  `Platform.end_active_trigger()`, a seventh Platform method, so a later toggle starts fresh.
- **Interrupting:** any new press abandons work in progress. Whisper cannot be stopped, so the
  thread finishes and discards its own result, using a question number.
- **Audio stays in memory.** Nothing is written to disk.
- **Agreed for later milestones:**
  - 0-1000 coordinates, with axis order declared per provider and confirmed by test.
  - Gemini development runs on fixtures to save quota.
  - Piper runs as a separate process and is not vendored (it is GPL-3.0; this repo is MIT).
  - Local mode tests both `qwen3-vl:2b` and `qwen3-vl:4b-instruct`, for speed and accuracy.

## Gotchas
- `python-xlib`'s `has_extension()` only knows extensions it wraps and returned False for
  XWAYLAND. Use `"XWAYLAND" in display.list_extensions()`.
- `$XDG_SESSION_TYPE` says `wayland` inside the nested display too, so it cannot be used to
  detect XWayland. Qt also needs `QT_QPA_PLATFORM=xcb` forced, or it ignores `DISPLAY`.
- Xephyr's dual-screen mode reports a broken layout, so multi-monitor cannot be tested nested.
- `mss.mss()` is deprecated in 10.2; use `mss.MSS()`.
- python-xlib window objects from separate calls should be compared by `.id`.
- The X server consumes the press of Ctrl+Alt+F1..F12 as a VT switch, so apps only see the
  release. `PushToTalkTrigger` therefore cancels on a non-modifier release too. The cost: a
  letter still being released as Ctrl+Alt goes down cancels that hold.
- pynput's `Listener.start()` returns before it is connected; call `wait()`, or early key
  presses are lost.
- Xephyr's `-resizeable` shrinks the root to fit the host window, so `--size` is ignored.
- The tip must be measured by coverage, not exact colour: antialiasing moves an exact match
  1-2 px inside the dart.
- PortAudio's default device is PipeWire and accepts 16 kHz, so we do not resample.
- To test against a virtual mic, set `PIPEWIRE_ALSA='{ target.object=<node> }'` for one process.
  `PIPEWIRE_NODE` gave silence. System defaults are left alone either way.
- The Hugging Face downloader can crash on small files after the large one finishes, and a
  bare rerun fetches just what is missing. Piper's voice downloader left truncated `.onnx`
  files on a flaky connection with no error, so check sizes or SHA-256 after downloading.
- 0600 on the trigger socket blocks other users, not other processes running as the same
  user. Unix permissions cannot separate those.

## Deferred
- **"Cursor buddy follows the mouse":** Clicky's cursor stays beside the mouse all the time.
  Here it appears only when pointing. A possible later feature; it would need a 60 Hz
  position poll and the overlay mapped constantly, so it must then be excluded from captures.

## What's left to check
- Everything so far ran on nested Xephyr. A real "GNOME on Xorg" session is still untested.
- Your Wayland session uses fractional 1.25, a Wayland-only Mutter feature (and shows
  `Xft.dpi: 192`), so the Xorg session's scale may well differ. All four scales pass nested.
  Confirm from `scale` in the `screen 0:` line of the listening mode.
- **A real human voice on the laptop mic has not been tested.** Run this for real latency and
  accuracy; only a 1 s level check of the real mic was done (it opens and has signal).
- A real VT switch during a hold: the release may never arrive. The 60 s limit now covers it.
- `qwen3-vl:4b-instruct` is not pulled yet. Only `qwen3-vl:2b` is, and M4 must compare both.
- Multi-monitor is unit-tested only, with fake geometry. Hot-plugging is not exercised.
