import pytest

from clicky.core.push_to_talk import MINIMUM_HOLD_SECONDS, HotkeyKeyKind, PushToTalkTrigger
from clicky.platform.base import TriggerEvent

CONTROL = HotkeyKeyKind.CONTROL
ALT = HotkeyKeyKind.ALT
OTHER = HotkeyKeyKind.OTHER


class FakeClock:
    def __init__(self):
        self.current_seconds = 100.0

    def __call__(self):
        return self.current_seconds

    def advance(self, seconds):
        self.current_seconds += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def events():
    return []


@pytest.fixture
def trigger(clock, events):
    return PushToTalkTrigger(events.append, monotonic_clock=clock)


def press_ctrl_alt(trigger):
    trigger.key_pressed(CONTROL)
    trigger.key_pressed(ALT)


def test_hold_and_release_fires_pressed_then_released(trigger, events, clock):
    press_ctrl_alt(trigger)
    clock.advance(1.0)
    trigger.key_released(ALT)
    trigger.key_released(CONTROL)
    assert events == [TriggerEvent.PRESSED, TriggerEvent.RELEASED]


def test_either_press_order_works(trigger, events):
    trigger.key_pressed(ALT)
    trigger.key_pressed(CONTROL)
    assert events == [TriggerEvent.PRESSED]


def test_one_modifier_alone_does_nothing(trigger, events):
    trigger.key_pressed(CONTROL)
    trigger.key_released(CONTROL)
    assert events == []


def test_quick_tap_is_cancelled(trigger, events, clock):
    press_ctrl_alt(trigger)
    clock.advance(MINIMUM_HOLD_SECONDS - 0.01)
    trigger.key_released(CONTROL)
    assert events == [TriggerEvent.PRESSED, TriggerEvent.CANCELLED]


def test_desktop_shortcut_cancels_and_does_not_restart(trigger, events, clock):
    press_ctrl_alt(trigger)
    trigger.key_pressed(OTHER)
    clock.advance(1.0)
    trigger.key_released(OTHER)
    trigger.key_released(ALT)
    trigger.key_pressed(ALT)
    assert events == [TriggerEvent.PRESSED, TriggerEvent.CANCELLED]


def test_vt_switch_key_seen_only_as_a_release_still_cancels(trigger, events, clock):
    press_ctrl_alt(trigger)
    trigger.key_released(OTHER)
    clock.advance(1.0)
    trigger.key_released(ALT)
    assert events == [TriggerEvent.PRESSED, TriggerEvent.CANCELLED]


def test_hotkey_works_again_after_a_cancelled_shortcut(trigger, events):
    press_ctrl_alt(trigger)
    trigger.key_pressed(OTHER)
    trigger.key_released(ALT)
    trigger.key_released(CONTROL)
    press_ctrl_alt(trigger)
    assert events == [TriggerEvent.PRESSED, TriggerEvent.CANCELLED, TriggerEvent.PRESSED]


def test_other_keys_are_ignored_while_idle(trigger, events):
    trigger.key_pressed(OTHER)
    trigger.key_released(OTHER)
    assert events == []


def test_toggle_starts_then_stops(trigger, events):
    assert trigger.toggle() == "recording"
    assert trigger.toggle() == "stopped"
    assert events == [TriggerEvent.PRESSED, TriggerEvent.RELEASED]


def test_toggle_recording_survives_typing_and_a_hotkey_hold(trigger, events, clock):
    trigger.toggle()
    trigger.key_pressed(OTHER)
    press_ctrl_alt(trigger)
    clock.advance(1.0)
    trigger.key_released(CONTROL)
    assert events == [TriggerEvent.PRESSED]


def test_toggle_can_stop_a_hotkey_recording_without_a_second_release(trigger, events, clock):
    press_ctrl_alt(trigger)
    assert trigger.toggle() == "stopped"
    clock.advance(1.0)
    trigger.key_released(CONTROL)
    assert events == [TriggerEvent.PRESSED, TriggerEvent.RELEASED]
