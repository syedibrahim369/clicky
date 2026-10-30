"""Integration check for the M1 overlay. Needs a live X11 display with a compositor.

    DISPLAY=:20 PYTHONPATH=. .venv/bin/python tests/verify_overlay_x11.py <output.png>

Maps a solid-colour window under the overlay, then proves each overlay property by
observing the display: the screenshot for rendering and translucency, a real injected
click for click-through, and the X focus and stacking order for the rest.
"""

import subprocess
import sys
import threading
import time

import mss
import mss.tools
from Xlib import X, display

BACKGROUND_RGB = (150, 40, 90)
TARGET_X = 400
TARGET_Y = 300
CURSOR_BLUE_RGB = (0x33, 0x80, 0xFF)
SECONDS_TO_WAIT_FOR_FLIGHT = 2.4
OVERLAY_HOLD_SECONDS = 6


def map_background_window(x_display):
    screen = x_display.screen()
    background_pixel = (BACKGROUND_RGB[0] << 16) | (BACKGROUND_RGB[1] << 8) | BACKGROUND_RGB[2]
    background_window = screen.root.create_window(
        0,
        0,
        screen.width_in_pixels,
        screen.height_in_pixels,
        0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=background_pixel,
        event_mask=X.ButtonPressMask,
        override_redirect=True,
    )
    background_window.map()
    x_display.sync()
    return background_window


def wait_for_button_press(x_display, background_window, timeout_seconds):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        while x_display.pending_events():
            event = x_display.next_event()
            if event.type == X.ButtonPress and event.window == background_window:
                return True
        time.sleep(0.02)
    return False


def focused_window_id(x_display):
    focused_window = x_display.get_input_focus().focus
    return focused_window if isinstance(focused_window, int) else focused_window.id


def find_overlay_windows(x_display):
    """Lists top-level windows that are mapped, override-redirect and 32-bit ARGB."""
    overlay_windows = []
    for window in x_display.screen().root.query_tree().children:
        attributes = window.get_attributes()
        if (
            attributes.map_state == X.IsViewable
            and attributes.override_redirect
            and window.get_geometry().depth == 32
        ):
            overlay_windows.append(window)
    return overlay_windows


def run_two_flights_with_a_pause():
    """Child process: flies, gets covered by the parent, then flies again mid-air redirect."""
    from clicky.platform.x11 import X11Platform

    x11_platform = X11Platform()
    x11_platform.point(0, 200, 200, "first")
    threading.Timer(2.0, lambda: x11_platform.point(0, 1270, 710, "second target near the corner")).start()
    threading.Timer(2.3, lambda: x11_platform.point(0, 1100, 650, "corner label check")).start()
    threading.Timer(5.0, x11_platform.clear).start()
    threading.Timer(5.5, x11_platform.quit).start()
    x11_platform.run_event_loop()


def verify_reraise_and_redirect(x_display, output_path):
    """Covers the overlay with a window, then checks the next flight rises above it."""
    results = {}
    child_process = subprocess.Popen([sys.executable, __file__, "--two-flights"])
    time.sleep(1.5)

    screen = x_display.screen()
    covering_window = screen.root.create_window(
        900, 500, 300, 200, 0, screen.root_depth, X.InputOutput, X.CopyFromParent,
        background_pixel=0x228B22, override_redirect=True,
    )
    covering_window.map()
    covering_window.configure(stack_mode=X.Above)
    x_display.sync()

    def overlay_is_above_covering_window():
        stacking_order = [window.id for window in screen.root.query_tree().children]
        overlay_ids = [window.id for window in find_overlay_windows(x_display)]
        return bool(overlay_ids) and min(
            stacking_order.index(overlay_id) for overlay_id in overlay_ids
        ) > stacking_order.index(covering_window.id)

    results["setup: a new window really does cover the overlay"] = not overlay_is_above_covering_window()
    time.sleep(1.0)
    results["re-raise: the next flight puts the overlay back on top"] = overlay_is_above_covering_window()

    # 0.3 s after a mid-flight redirect, plus flight time, the cursor must be at the new target.
    time.sleep(2.0)
    with mss.MSS() as screen_capture:
        screenshot = screen_capture.grab(screen_capture.monitors[1])
        mss.tools.to_png(screenshot.rgb, screenshot.size, output=output_path.replace(".png", "-redirect.png"))
    results["redirect: a new point mid-flight lands at the new target"] = (
        tuple(screenshot.pixel(1100 + 5, 650 + 7)) == CURSOR_BLUE_RGB
    )

    child_process.wait(timeout=8)
    covering_window.destroy()
    x_display.sync()
    return results


def main():
    if sys.argv[1] == "--two-flights":
        run_two_flights_with_a_pause()
        return 0

    output_path = sys.argv[1]
    results = {}
    x_display = display.Display()
    background_window = map_background_window(x_display)
    focus_before = focused_window_id(x_display)

    overlay_process = subprocess.Popen(
        [
            sys.executable, "-m", "clicky",
            "--point", str(TARGET_X), str(TARGET_Y), "settings button",
            "--hold", str(OVERLAY_HOLD_SECONDS),
        ]
    )
    time.sleep(SECONDS_TO_WAIT_FOR_FLIGHT)

    with mss.MSS() as screen_capture:
        screenshot = screen_capture.grab(screen_capture.monitors[1])
        mss.tools.to_png(screenshot.rgb, screenshot.size, output=output_path)

    def pixel_at(x, y):
        return tuple(screenshot.pixel(x, y))

    far_from_cursor = pixel_at(40, 40)
    results["translucent: desktop shows through away from the cursor"] = far_from_cursor == BACKGROUND_RGB
    print("pixel far from cursor:", far_from_cursor)

    # Inside the dart's body, down-right of the tip at its resting angle.
    cursor_body = pixel_at(TARGET_X + 8, TARGET_Y + 12)
    results["cursor is drawn in Clicky's blue"] = cursor_body == CURSOR_BLUE_RGB
    print("pixel in cursor body:", cursor_body)

    # Tip placement: solid blue just inside the tip, and none just beyond it.
    results["tip lands on target"] = (
        pixel_at(TARGET_X + 5, TARGET_Y + 7) == CURSOR_BLUE_RGB
        and pixel_at(TARGET_X - 4, TARGET_Y - 4) != CURSOR_BLUE_RGB
    )

    overlay_windows = find_overlay_windows(x_display)
    results["overlay is mapped, override-redirect and 32-bit ARGB"] = len(overlay_windows) == 1

    click_x = TARGET_X + 8
    click_y = TARGET_Y + 12
    subprocess.run(["xdotool", "mousemove", str(click_x), str(click_y), "click", "1"], check=True)
    results["click-through: a click on the cursor reaches the window below"] = wait_for_button_press(
        x_display, background_window, timeout_seconds=1.0
    )

    results["focus was not stolen"] = focused_window_id(x_display) == focus_before

    overlay_process.wait(timeout=OVERLAY_HOLD_SECONDS + 5)
    results["process exits cleanly"] = overlay_process.returncode == 0
    results["overlay is gone after clear()"] = not find_overlay_windows(x_display)

    results.update(verify_reraise_and_redirect(x_display, output_path))

    background_window.destroy()
    x_display.sync()

    for description, passed in results.items():
        print(("PASS " if passed else "FAIL ") + description)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
