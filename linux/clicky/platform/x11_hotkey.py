"""Global Ctrl+Alt detection on X11, through pynput's XRecord listener."""

from clicky.core.push_to_talk import HotkeyKeyKind, PushToTalkTrigger


class GlobalHotkeyListener:
    def __init__(self, push_to_talk_trigger: PushToTalkTrigger):
        self.push_to_talk_trigger = push_to_talk_trigger
        self.keyboard_listener = None

    def start(self) -> None:
        # pynput connects to the X server at import time, so a module-level import would
        # crash every command that runs without a display, including --trigger.
        from pynput import keyboard

        control_keys = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
        alt_keys = {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr}

        def classify_key(key) -> HotkeyKeyKind:
            if key in control_keys:
                return HotkeyKeyKind.CONTROL
            if key in alt_keys:
                return HotkeyKeyKind.ALT
            return HotkeyKeyKind.OTHER

        self.keyboard_listener = keyboard.Listener(
            on_press=lambda key: self.push_to_talk_trigger.key_pressed(classify_key(key)),
            on_release=lambda key: self.push_to_talk_trigger.key_released(classify_key(key)),
        )
        self.keyboard_listener.daemon = True
        self.keyboard_listener.start()
        # The listener connects on its own thread. Without this wait, a key pressed just
        # after startup is lost even though the app already says it is listening.
        self.keyboard_listener.wait()

    def stop(self) -> None:
        if self.keyboard_listener is not None:
            self.keyboard_listener.stop()
