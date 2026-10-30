"""Integration check for M2. Needs a nested display at the real panel size:

    scripts/dev-x11.sh --size 3072x1920 --display 21
    DISPLAY=:21 PYTHONPATH=. .venv/bin/python tests/verify_capture_x11.py

At each Xft.dpi scale this runs the round trip that decides whether pointing is accurate
on HiDPI: put a marker at a known physical pixel, capture, find the marker in the PNG,
convert it the way M4 will, fly the cursor, then measure the tip against the marker.
Then it drives the real hotkey with injected key presses, and the real --trigger socket.
"""

import io
import json
import os
import queue
import signal
import stat
import subprocess
import sys
import threading
import time

import mss
from PIL import Image, ImageChops
from Xlib import X, display

SCALE_CASES = [(96, 1.0), (120, 1.25), (144, 1.5), (192, 2.0)]
MARKER_CENTERS_PHYSICAL = [(300, 250), (1536, 960), (2700, 1700)]
MARKER_SIZE_PHYSICAL = 40
MARKER_RGB = (220, 20, 20)
CURSOR_BLUE_RGB = (0x33, 0x80, 0xFF)
SECONDS_FOR_FLIGHT_AND_LABEL = 2.2
EXPECTED_PANEL_SIZE = (3072, 1920)
MAXIMUM_TIP_ERROR_PHYSICAL_PIXELS = 3
TIP_BLUE_CHANNEL_THRESHOLD = 160


def bounding_box_of_color(image, rgb):
    difference = ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, rgb))
    exact_matches = difference.convert("L").point(lambda value: 255 if value == 0 else 0)
    return exact_matches.getbbox()


def find_cursor_tip(image):
    """Finds the dart's tip, its topmost and leftmost point at the resting angle.

    Matching the exact blue would skip the antialiased tip pixels and read a pixel or two
    inside the dart. The blue channel passes this threshold at about half coverage, which
    the glow never reaches, so the result is the tip as drawn.
    """
    blue_channel = image.convert("RGB").getchannel("B")
    return blue_channel.point(lambda value: 255 if value > TIP_BLUE_CHANNEL_THRESHOLD else 0).getbbox()[:2]


def grab_physical_screen():
    with mss.MSS() as screen_grabber:
        screenshot = screen_grabber.grab(screen_grabber.monitors[1])
    return Image.frombytes("RGB", screenshot.size, screenshot.rgb)


def run_round_trips_in_child():
    """Runs in a child process, so each case gets a fresh Qt that reads the new Xft.dpi."""
    from clicky.platform.x11 import X11Platform

    x11_platform = X11Platform()
    x_display = display.Display()
    screen = x_display.screen()
    report = {"round_trips": []}

    def map_marker(center_x, center_y):
        half_size = MARKER_SIZE_PHYSICAL // 2
        marker_window = screen.root.create_window(
            center_x - half_size, center_y - half_size,
            MARKER_SIZE_PHYSICAL, MARKER_SIZE_PHYSICAL, 0, screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=(MARKER_RGB[0] << 16) | (MARKER_RGB[1] << 8) | MARKER_RGB[2],
            override_redirect=True,
        )
        marker_window.map()
        x_display.sync()
        time.sleep(0.25)
        return marker_window

    def run_all_round_trips():
        try:
            for center_x, center_y in MARKER_CENTERS_PHYSICAL:
                marker_window = map_marker(center_x, center_y)

                capture_started_at = time.monotonic()
                captured_screen = x11_platform.capture()[0]
                report["capture_seconds"] = round(time.monotonic() - capture_started_at, 3)
                report["png_megabytes"] = round(len(captured_screen.png_bytes) / 1_000_000, 3)
                report["png_size"] = [captured_screen.png_width, captured_screen.png_height]
                report["logical_size"] = [captured_screen.width, captured_screen.height]
                report["scale_factor"] = captured_screen.scale_factor

                png_image = Image.open(io.BytesIO(captured_screen.png_bytes))
                marker_box = bounding_box_of_color(png_image, MARKER_RGB)
                found_x = (marker_box[0] + marker_box[2]) / 2
                found_y = (marker_box[1] + marker_box[3]) / 2

                # The same conversion M4 will use: image position to fraction to logical.
                logical_x = found_x / captured_screen.png_width * captured_screen.width
                logical_y = found_y / captured_screen.png_height * captured_screen.height
                x11_platform.point(0, logical_x, logical_y, "marker")
                time.sleep(SECONDS_FOR_FLIGHT_AND_LABEL)

                tip_x, tip_y = find_cursor_tip(grab_physical_screen())
                report["round_trips"].append(
                    {
                        "marker": [center_x, center_y],
                        "found_in_png": [found_x, found_y],
                        "tip": [tip_x, tip_y],
                        "error_pixels": round(((tip_x - center_x) ** 2 + (tip_y - center_y) ** 2) ** 0.5, 2),
                    }
                )

                # The cursor is on screen right now, so this proves capture removes it.
                image_with_cursor_visible = Image.open(io.BytesIO(x11_platform.capture()[0].png_bytes))
                report["cursor_leaked_into_capture"] = report.get("cursor_leaked_into_capture", False) or (
                    bounding_box_of_color(image_with_cursor_visible, CURSOR_BLUE_RGB) is not None
                )

                marker_window.destroy()
                x_display.sync()
        finally:
            print(json.dumps(report), flush=True)
            x11_platform.quit()

    threading.Thread(target=run_all_round_trips, daemon=True).start()
    x11_platform.run_event_loop()


class ListeningApp:
    def __init__(self, extra_arguments=()):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "clicky", *extra_arguments],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.output_lines = queue.Queue()
        threading.Thread(target=self.read_output, daemon=True).start()
        self.wait_for_line("Listening")

    def read_output(self):
        for output_line in self.process.stdout:
            self.output_lines.put(output_line.strip())

    def wait_for_line(self, expected_text, timeout_seconds=6.0):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                output_line = self.output_lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if expected_text in output_line:
                return output_line
        return None

    def drain_lines(self, seconds=0.5):
        time.sleep(seconds)
        lines = []
        while not self.output_lines.empty():
            lines.append(self.output_lines.get())
        return lines

    def stop(self, stop_signal=signal.SIGINT):
        self.process.send_signal(stop_signal)
        self.process.wait(timeout=5)


def xdotool(*arguments):
    subprocess.run(["xdotool", *arguments], check=True)


def run_clicky_command(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "clicky", *arguments], capture_output=True, text=True
    )


def verify_hotkey_and_socket():
    results = {}
    app = ListeningApp()
    socket_path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "clicky-trigger.sock")

    results["socket file is mode 0600"] = stat.S_IMODE(os.stat(socket_path).st_mode) == 0o600
    results["socket is owned by this user"] = os.stat(socket_path).st_uid == os.getuid()
    results["runtime directory is private (0700)"] = (
        stat.S_IMODE(os.stat(os.environ["XDG_RUNTIME_DIR"]).st_mode) == 0o700
    )

    xdotool("keydown", "ctrl", "keydown", "alt")
    time.sleep(0.6)
    xdotool("keyup", "alt", "keyup", "ctrl")
    lines = app.drain_lines(1.0)
    results["hold ctrl then alt: pressed, released, then capture"] = (
        lines[:2] == ["trigger: pressed", "trigger: released"]
        and any(line.startswith("screen 0:") for line in lines)
    )
    print("  ", lines)

    xdotool("keydown", "alt", "keydown", "ctrl")
    time.sleep(0.6)
    xdotool("keyup", "ctrl", "keyup", "alt")
    lines = app.drain_lines(1.0)
    results["hold alt then ctrl also works, released in either order"] = lines[:2] == [
        "trigger: pressed", "trigger: released",
    ]

    xdotool("keydown", "ctrl", "keydown", "alt", "keyup", "alt", "keyup", "ctrl")
    lines = app.drain_lines()
    results["quick tap is cancelled with no capture"] = lines == ["trigger: pressed", "trigger: cancelled"]

    # F7 matters separately: X consumes its press as a VT switch, so only the release shows.
    for shortcut_key in ("t", "F7"):
        xdotool("keydown", "ctrl", "keydown", "alt")
        time.sleep(0.1)
        xdotool("key", shortcut_key)
        time.sleep(0.5)
        xdotool("keyup", "alt", "keyup", "ctrl")
        lines = app.drain_lines()
        results[f"ctrl+alt+{shortcut_key} is a shortcut: cancelled, no capture"] = lines == [
            "trigger: pressed", "trigger: cancelled",
        ]

    first_toggle = run_clicky_command("--trigger")
    lines_after_start = app.drain_lines()
    second_toggle = run_clicky_command("--trigger")
    lines_after_stop = app.drain_lines(1.0)
    results["--trigger starts then stops, then captures"] = (
        first_toggle.stdout.strip() == "recording"
        and second_toggle.stdout.strip() == "stopped"
        and lines_after_start == ["trigger: pressed"]
        and "trigger: released" in lines_after_stop
        and any(line.startswith("screen 0:") for line in lines_after_stop)
    )

    second_instance = run_clicky_command()
    results["second instance is refused"] = (
        second_instance.returncode == 1 and "already running" in second_instance.stderr
    )
    results["first instance still works after the refusal"] = (
        run_clicky_command("--trigger").stdout.strip() == "recording"
    )
    run_clicky_command("--trigger")

    app.stop(signal.SIGKILL)
    results["after a hard kill --trigger reports not running"] = (
        "not running" in run_clicky_command("--trigger").stderr
    )
    restarted_app = ListeningApp()
    results["restart replaces the stale socket"] = (
        run_clicky_command("--trigger").stdout.strip() == "recording"
    )
    run_clicky_command("--trigger")
    restarted_app.stop()
    return results


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--round-trips":
        run_round_trips_in_child()
        return 0

    results = {}
    for xft_dpi, expected_scale in SCALE_CASES:
        subprocess.run(["xrdb", "-merge"], input=f"Xft.dpi: {xft_dpi}\n", text=True, check=True)
        child = subprocess.run(
            [sys.executable, __file__, "--round-trips"], capture_output=True, text=True, timeout=60
        )
        json_lines = [line for line in child.stdout.splitlines() if line.startswith("{")]
        if not json_lines:
            print(child.stdout[-800:], child.stderr[-1500:])
            results[f"scale {expected_scale}: round trip ran"] = False
            continue
        report = json.loads(json_lines[-1])
        print(f"Xft.dpi {xft_dpi}: {report}")

        prefix = f"scale {expected_scale}:"
        results[f"{prefix} Qt devicePixelRatio is as expected"] = report["scale_factor"] == expected_scale
        results[f"{prefix} PNG is the full physical panel"] = tuple(report["png_size"]) == EXPECTED_PANEL_SIZE
        results[f"{prefix} logical size times ratio equals physical"] = all(
            abs(logical * report["scale_factor"] - physical) <= 2
            for logical, physical in zip(report["logical_size"], report["png_size"])
        )
        results[f"{prefix} every tip within {MAXIMUM_TIP_ERROR_PHYSICAL_PIXELS}px of its marker"] = (
            len(report["round_trips"]) == len(MARKER_CENTERS_PHYSICAL)
            and all(
                trip["error_pixels"] <= MAXIMUM_TIP_ERROR_PHYSICAL_PIXELS for trip in report["round_trips"]
            )
        )
        results[f"{prefix} cursor is never in a capture"] = report.get("cursor_leaked_into_capture") is False

    subprocess.run(["xrdb", "-merge"], input="Xft.dpi: 96\n", text=True, check=True)
    results.update(verify_hotkey_and_socket())

    for description, passed in results.items():
        print(("PASS " if passed else "FAIL ") + description)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
