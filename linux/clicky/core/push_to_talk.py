"""Turns raw key presses and --trigger toggles into push-to-talk events.

Both input sources feed one object so they cannot disagree about whether a recording is
in progress. This holds no X11 code: any display backend reports keys here.
"""

import threading
import time
from enum import Enum, auto
from typing import Callable

from clicky.platform.base import TriggerEvent

# Shorter holds are treated as accidental. Ctrl and Alt also start most desktop
# shortcuts, so brief presses are common and should not send a question to the model.
MINIMUM_HOLD_SECONDS = 0.3


class HotkeyKeyKind(Enum):
    CONTROL = auto()
    ALT = auto()
    OTHER = auto()


class ActivationSource(Enum):
    HOTKEY = auto()
    TOGGLE = auto()


class PushToTalkTrigger:
    def __init__(
        self,
        event_callback: Callable[[TriggerEvent], None],
        monotonic_clock: Callable[[], float] = time.monotonic,
    ):
        self.event_callback = event_callback
        self.monotonic_clock = monotonic_clock
        # Keys arrive on the listener thread and toggles on the socket thread. Reentrant
        # so that a callback may safely call back into this object.
        self.state_lock = threading.RLock()
        self.is_control_held = False
        self.is_alt_held = False
        self.active_source: ActivationSource | None = None
        self.hold_started_at = 0.0
        # After Ctrl+Alt+T, keeping Ctrl+Alt down must not start a new recording.
        self.is_waiting_for_modifiers_to_clear = False

    def key_pressed(self, key_kind: HotkeyKeyKind) -> None:
        with self.state_lock:
            if key_kind == HotkeyKeyKind.OTHER:
                self.cancel_hotkey_hold_used_as_shortcut()
                return

            if key_kind == HotkeyKeyKind.CONTROL:
                self.is_control_held = True
            else:
                self.is_alt_held = True

            both_modifiers_held = self.is_control_held and self.is_alt_held
            if both_modifiers_held and self.active_source is None and not self.is_waiting_for_modifiers_to_clear:
                self.active_source = ActivationSource.HOTKEY
                self.hold_started_at = self.monotonic_clock()
                self.event_callback(TriggerEvent.PRESSED)

    def key_released(self, key_kind: HotkeyKeyKind) -> None:
        with self.state_lock:
            if key_kind == HotkeyKeyKind.OTHER:
                # The X server consumes the press of Ctrl+Alt+F1..F12 as a VT switch, so
                # applications only ever see the release of those keys.
                self.cancel_hotkey_hold_used_as_shortcut()
                return

            if key_kind == HotkeyKeyKind.CONTROL:
                self.is_control_held = False
            else:
                self.is_alt_held = False

            if not self.is_control_held and not self.is_alt_held:
                self.is_waiting_for_modifiers_to_clear = False

            if self.active_source == ActivationSource.HOTKEY:
                self.active_source = None
                held_seconds = self.monotonic_clock() - self.hold_started_at
                was_held_long_enough = held_seconds >= MINIMUM_HOLD_SECONDS
                self.event_callback(
                    TriggerEvent.RELEASED if was_held_long_enough else TriggerEvent.CANCELLED
                )

    def cancel_hotkey_hold_used_as_shortcut(self) -> None:
        if self.active_source == ActivationSource.HOTKEY:
            self.active_source = None
            self.is_waiting_for_modifiers_to_clear = True
            self.event_callback(TriggerEvent.CANCELLED)

    def toggle(self) -> str:
        """Starts or stops a recording, returning "recording" or "stopped".

        A desktop shortcut only fires once and cannot be held, hence a toggle. A toggle
        can also stop a recording the hotkey started.
        """
        with self.state_lock:
            if self.active_source is None:
                self.active_source = ActivationSource.TOGGLE
                self.event_callback(TriggerEvent.PRESSED)
                return "recording"

            self.active_source = None
            self.event_callback(TriggerEvent.RELEASED)
            return "stopped"
