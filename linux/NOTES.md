# Clicky for Linux: working notes

Read this first when picking the port up in a fresh session. Branch: `feature/linux-port`.

## Status
- [x] M1 Overlay
- [x] M2 Trigger + capture
- [ ] M3 Speech-to-text
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
    .venv/bin/python -m clicky --trigger

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
- **Agreed for later milestones:**
- **Agreed for later milestones:**
  - Capture on key release, before transcription (M2 does this in its listening mode).
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
- A real VT switch during a hold: the release may never arrive, leaving the hold active until
  Ctrl+Alt is next pressed and released. **M3 must cap recording length** for this reason, and
  because a forgotten `--trigger` toggle would otherwise record indefinitely.
- Multi-monitor is unit-tested only, with fake geometry. Hot-plugging is not exercised.
