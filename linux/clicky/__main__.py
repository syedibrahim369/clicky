"""Command line entry point: `python -m clicky` from the linux/ directory."""

import argparse
import signal
import sys
import threading
from pathlib import Path

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
    argument_parser.add_argument(
        "--trigger",
        action="store_true",
        help="start or stop recording in the running app, for use from a desktop shortcut",
    )
    argument_parser.add_argument(
        "--dump-captures",
        type=Path,
        metavar="DIRECTORY",
        help="save each screenshot to DIRECTORY, for checking what the model would see",
    )
    argument_parser.add_argument(
        "--no-voice",
        action="store_true",
        help="test the hotkey and capture only: no microphone and no speech model",
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


def run_trigger_command() -> int:
    # Imports nothing from Qt or X11, so a shortcut gets a fast response on any desktop.
    from clicky.core.trigger_socket import (
        TriggerSocketError,
        default_trigger_socket_path,
        send_toggle_request,
    )

    try:
        print(send_toggle_request(default_trigger_socket_path()))
    except TriggerSocketError as trigger_socket_error:
        print(f"clicky: {trigger_socket_error}", file=sys.stderr)
        return 1
    return 0


def report_captured_screens(captured_screens, dump_directory: Path | None) -> None:
    for screen_index, captured_screen in enumerate(captured_screens):
        print(
            f"screen {screen_index}: logical {captured_screen.width}x{captured_screen.height}"
            f"+{captured_screen.left}+{captured_screen.top},"
            f" png {captured_screen.png_width}x{captured_screen.png_height},"
            f" scale {captured_screen.scale_factor},"
            f" mouse here: {captured_screen.contains_mouse_cursor}",
            flush=True,
        )
        if dump_directory is not None:
            dump_directory.mkdir(parents=True, exist_ok=True)
            (dump_directory / f"screen-{screen_index}.png").write_bytes(captured_screen.png_bytes)


def run_hotkey_test_mode(x11_platform, dump_directory: Path | None) -> None:
    """Reports triggers and captures only, without touching the microphone."""
    from clicky.platform.base import TriggerEvent

    def capture_and_report() -> None:
        report_captured_screens(x11_platform.capture(), dump_directory)

    def handle_trigger_event(trigger_event: TriggerEvent) -> None:
        print(f"trigger: {trigger_event.value}", flush=True)
        if trigger_event == TriggerEvent.RELEASED:
            # Capturing is too slow to run on the thread that delivers key events.
            threading.Thread(target=capture_and_report, daemon=True).start()

    x11_platform.on_trigger(handle_trigger_event)


def start_voice_pipeline(x11_platform, dump_directory: Path | None) -> None:
    from clicky.core.audio_capture import MicrophoneRecorder
    from clicky.core.config import load_settings
    from clicky.core.orchestrator import Orchestrator
    from clicky.core.speech_to_text import FasterWhisperSpeechToText

    settings = load_settings()
    speech_to_text = FasterWhisperSpeechToText(settings.whisper_model)
    orchestrator = Orchestrator(
        x11_platform,
        MicrophoneRecorder(),
        speech_to_text,
        captured_screens_observer=lambda captured_screens: report_captured_screens(
            captured_screens, dump_directory
        ),
    )
    x11_platform.on_trigger(orchestrator.handle_trigger_event)
    orchestrator.start()

    def load_speech_model() -> None:
        print(f"loading speech model {settings.whisper_model}", flush=True)
        try:
            speech_to_text.load_model()
        except Exception as model_load_error:
            print(f"clicky: could not load the speech model: {model_load_error}", flush=True)
            return
        print("speech model ready", flush=True)

    threading.Thread(target=load_speech_model, daemon=True).start()


def run_listening_mode(dump_directory: Path | None, is_voice_enabled: bool) -> int:
    from clicky.core.trigger_socket import TriggerSocketError
    from clicky.platform.x11 import UnsupportedDisplayError, X11Platform

    try:
        x11_platform = X11Platform()
        if is_voice_enabled:
            start_voice_pipeline(x11_platform, dump_directory)
        else:
            run_hotkey_test_mode(x11_platform, dump_directory)
    except (UnsupportedDisplayError, TriggerSocketError) as startup_error:
        print(f"clicky: {startup_error}", file=sys.stderr)
        return 1

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    print("Listening. Hold Ctrl+Alt to talk. Ctrl+C to quit.", flush=True)
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

    if arguments.trigger:
        return run_trigger_command()

    return run_listening_mode(arguments.dump_captures, not arguments.no_voice)


if __name__ == "__main__":
    sys.exit(main())
