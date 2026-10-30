"""Command line entry point: `python -m clicky` from the linux/ directory."""

import argparse
import signal
import sys
import threading

CURSOR_FADE_SECONDS = 0.4


def build_argument_parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(prog="clicky")
    argument_parser.add_argument(
        "--point",
        nargs=3,
        metavar=("X", "Y", "LABEL"),
        help="fly the cursor to X,Y (pixels from the screen's top-left), then exit",
    )
    argument_parser.add_argument("--screen", type=int, default=0, help="screen index, left to right")
    argument_parser.add_argument(
        "--hold", type=float, default=4.0, help="seconds --point stays on screen, flight included"
    )
    return argument_parser


def run_point_command(target_x: float, target_y: float, label: str, screen_index: int, hold_seconds: float) -> int:
    from clicky.platform.x11 import UnsupportedDisplayError, X11Platform

    try:
        x11_platform = X11Platform()
    except UnsupportedDisplayError as unsupported_display_error:
        print(f"clicky: {unsupported_display_error}", file=sys.stderr)
        return 1

    screen_count = x11_platform.screen_count()
    if not 0 <= screen_index < screen_count:
        print(f"clicky: screen {screen_index} does not exist; found {screen_count}", file=sys.stderr)
        return 1

    # Ctrl+C has to kill the process even while Qt's event loop holds the main thread.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    x11_platform.point(screen_index, target_x, target_y, label)
    threading.Timer(hold_seconds, x11_platform.clear).start()
    threading.Timer(hold_seconds + CURSOR_FADE_SECONDS, x11_platform.quit).start()
    x11_platform.run_event_loop()
    return 0


def main() -> int:
    argument_parser = build_argument_parser()
    arguments = argument_parser.parse_args()

    if arguments.point:
        target_x_text, target_y_text, label = arguments.point
        try:
            target_x = float(target_x_text)
            target_y = float(target_y_text)
        except ValueError:
            argument_parser.error("--point needs numeric X and Y")
        return run_point_command(target_x, target_y, label, arguments.screen, arguments.hold)

    argument_parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
