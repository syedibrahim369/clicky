# Clicky for Linux: working notes

Read this first when picking the port up in a fresh session. Branch: `feature/linux-port`.

## Status
- [x] M1 Overlay
- [ ] M2 Trigger + capture
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
- **Agreed for later milestones:**
  - `--trigger` toggles over a Unix socket in `$XDG_RUNTIME_DIR`, mode 0600.
  - Capture on key release, before transcription.
  - 0-1000 coordinates, with axis order declared per provider and confirmed by test.
  - Gemini development runs on fixtures to save quota.
  - Piper runs as a separate process and is not vendored (it is GPL-3.0; this repo is MIT).
  - Local mode tests both `qwen3-vl:2b` and `qwen3-vl:4b-instruct`, for speed and accuracy.
  - If pynput's evdev build fails, use python-xlib XRecord to detect the key hold.

## Gotchas
- `python-xlib`'s `has_extension()` only knows extensions it wraps and returned False for
  XWAYLAND. Use `"XWAYLAND" in display.list_extensions()`.
- `$XDG_SESSION_TYPE` says `wayland` inside the nested display too, so it cannot be used to
  detect XWayland. Qt also needs `QT_QPA_PLATFORM=xcb` forced, or it ignores `DISPLAY`.
- Xephyr's dual-screen mode reports a broken layout, so multi-monitor cannot be tested nested.
- `mss.mss()` is deprecated in 10.2; use `mss.MSS()`.
- python-xlib window objects from separate calls should be compared by `.id`.
- 0600 on the trigger socket blocks other users, not other processes running as the same
  user. Unix permissions cannot separate those.

## Deferred
- **"Cursor buddy follows the mouse":** Clicky's cursor stays beside the mouse all the time.
  Here it appears only when pointing. A possible later feature; it would need a 60 Hz
  position poll and the overlay mapped constantly, so it must then be excluded from captures.

## What's left to check
- Everything so far ran on nested Xephyr. A real "GNOME on Xorg" session is still untested.
- Your panel is 3072x1920, so a real X11 session may use HiDPI scaling. Qt geometry is
  logical and mss is physical; M2 must verify `scale_factor` there.
- Hot-plugging monitors rebuilds the windows, but that path has not been exercised.
