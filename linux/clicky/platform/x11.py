"""The X11 platform: overlay, global hotkey, screen capture and the --trigger socket."""

import os
import sys
import threading
import time
from typing import Callable

from Xlib import display as xlib_display
from Xlib import error as xlib_error

from clicky.core.push_to_talk import PushToTalkTrigger
from clicky.core.trigger_socket import TriggerSocketServer, default_trigger_socket_path
from clicky.platform.base import CapturedScreen, TriggerEvent
from clicky.platform.x11_capture import capture_screens
from clicky.platform.x11_hotkey import GlobalHotkeyListener

# Once the overlay is unmapped the compositor still needs to draw a frame without it,
# or the grab can catch the old frame with the cursor in it.
SECONDS_FOR_COMPOSITOR_TO_DROP_OVERLAY = 0.08


class UnsupportedDisplayError(Exception):
    """Raised when the current display cannot host the overlay."""


def verify_display_supports_overlay() -> None:
    """Refuses displays where the overlay would fail, rather than misbehave on them.

    Checked up front for two reasons. XWayland looks like X11, so everything would start
    and then silently not work. And with no compositor a translucent window renders
    black, which would cover the whole screen with a window that ignores all input.
    """
    display_name = os.environ.get("DISPLAY")
    if not display_name:
        raise UnsupportedDisplayError(
            "DISPLAY is not set. Run inside an X11 session or linux/scripts/dev-x11.sh."
        )

    try:
        x_display = xlib_display.Display(display_name)
    except xlib_error.DisplayError as display_error:
        raise UnsupportedDisplayError(f"Cannot open {display_name}: {display_error}") from display_error

    try:
        # list_extensions, not has_extension: python-xlib's has_extension only knows
        # extensions it has a wrapper for, so it reports False for XWAYLAND.
        if "XWAYLAND" in x_display.list_extensions():
            raise UnsupportedDisplayError(
                f"{display_name} is XWayland, which cannot host the overlay. Log into "
                "'GNOME on Xorg', or develop on the nested display from linux/scripts/dev-x11.sh."
            )

        compositor_selection = x_display.intern_atom(f"_NET_WM_CM_S{x_display.get_default_screen()}")
        if x_display.get_selection_owner(compositor_selection) == 0:
            raise UnsupportedDisplayError(
                f"No compositor is running on {display_name}, so the overlay would "
                "render as a black screen. Start one, such as picom."
            )
    finally:
        x_display.close()


class X11Platform:
    def __init__(self):
        verify_display_supports_overlay()

        # Inside a Wayland session Qt would otherwise connect to the compositor and
        # ignore DISPLAY, so the nested dev display would never be used.
        os.environ["QT_QPA_PLATFORM"] = "xcb"

        # Imported here so that the display checks above can fail cleanly first, and so
        # that importing this module stays cheap for commands that never open a window.
        from PySide6.QtCore import QObject, Qt, Signal
        from PySide6.QtWidgets import QApplication

        from clicky.platform.x11_overlay import CursorOverlayController

        class MainThreadRequests(QObject):
            """Signals carry calls from worker threads onto Qt's main thread."""

            point_requested = Signal(int, float, float, str)
            clear_requested = Signal()
            quit_requested = Signal()
            capture_preparation_requested = Signal()

        self.application = QApplication(sys.argv[:1])
        self.application.setQuitOnLastWindowClosed(False)
        self.overlay_controller = CursorOverlayController()

        self.main_thread_requests = MainThreadRequests()
        self.main_thread_requests.point_requested.connect(self.overlay_controller.fly_to)
        self.main_thread_requests.clear_requested.connect(self.overlay_controller.fade_out)
        self.main_thread_requests.quit_requested.connect(self.application.quit)
        # Blocking, because capture() cannot grab until the overlay is really hidden.
        self.main_thread_requests.capture_preparation_requested.connect(
            self.overlay_controller.prepare_for_capture,
            Qt.ConnectionType.BlockingQueuedConnection,
        )

        self.trigger_socket_server: TriggerSocketServer | None = None
        self.global_hotkey_listener: GlobalHotkeyListener | None = None

    def screen_count(self) -> int:
        return len(self.overlay_controller.sorted_screens())

    def on_trigger(self, callback: Callable[[TriggerEvent], None]) -> None:
        push_to_talk_trigger = PushToTalkTrigger(callback)

        # The socket starts first: it briefly changes the process umask while binding,
        # which must happen before the hotkey listener adds another thread.
        self.trigger_socket_server = TriggerSocketServer(
            default_trigger_socket_path(), push_to_talk_trigger.toggle
        )
        self.trigger_socket_server.start()

        self.global_hotkey_listener = GlobalHotkeyListener(push_to_talk_trigger)
        self.global_hotkey_listener.start()

    def capture(self) -> list[CapturedScreen]:
        if threading.current_thread() is threading.main_thread():
            # A blocking signal sent to our own thread would deadlock.
            self.overlay_controller.prepare_for_capture()
            self.application.processEvents()
        else:
            self.main_thread_requests.capture_preparation_requested.emit()

        if self.overlay_controller.overlay_was_visible_for_capture:
            time.sleep(SECONDS_FOR_COMPOSITOR_TO_DROP_OVERLAY)

        return capture_screens(self.overlay_controller.latest_screen_layouts)

    def point(self, screen: int, x: float, y: float, label: str) -> None:
        self.main_thread_requests.point_requested.emit(screen, x, y, label)

    def clear(self) -> None:
        self.main_thread_requests.clear_requested.emit()

    def run_event_loop(self) -> None:
        try:
            self.application.exec()
        finally:
            if self.global_hotkey_listener is not None:
                self.global_hotkey_listener.stop()
            if self.trigger_socket_server is not None:
                self.trigger_socket_server.stop()

    def quit(self) -> None:
        self.main_thread_requests.quit_requested.emit()
