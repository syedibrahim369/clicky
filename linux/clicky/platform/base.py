"""The contract between Clicky's core and a display server."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class TriggerEvent(Enum):
    PRESSED = "pressed"
    RELEASED = "released"
    # The hold was not a question: a quick tap, or Ctrl+Alt used as part of a shortcut.
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CapturedScreen:
    """One monitor's screenshot and where that monitor sits on the desktop.

    There are two unit systems here, and mixing them points at the wrong place on HiDPI:
    - `left`, `top`, `width` and `height` are logical pixels, the units `Platform.point`
      takes. `Platform.point` wants them relative to this screen's top-left.
    - `png_bytes`, `png_width` and `png_height` are physical pixels.

    `scale_factor` is physical pixels per logical pixel. Coordinates read off the image
    should go through a 0-1 fraction of the image size, then be multiplied by `width` and
    `height`, so that a later downscale of the image cannot change where the cursor lands.
    """

    png_bytes: bytes
    png_width: int
    png_height: int
    left: int
    top: int
    width: int
    height: int
    scale_factor: float
    contains_mouse_cursor: bool


class Platform(Protocol):
    def on_trigger(self, callback: Callable[[TriggerEvent], None]) -> None:
        """Registers the callback for push-to-talk events and starts listening for them.

        The callback runs on a background thread and must return quickly.
        """
        ...

    def end_active_trigger(self) -> None:
        """Ends the current press or toggle without firing an event.

        Used when core stops a recording itself, so the next toggle starts a new one
        rather than stopping a recording that is already over.
        """
        ...

    def capture(self) -> list[CapturedScreen]:
        """Screenshots every monitor, in the order `point` numbers them.

        Hides the cursor first so it is not in the images. Safe to call from any thread.
        """
        ...

    def point(self, screen: int, x: float, y: float, label: str) -> None:
        """Flies the cursor to (x, y), logical pixels relative to that screen's top-left.

        Safe to call from any thread.
        """
        ...

    def clear(self) -> None:
        """Fades the cursor out. Safe to call from any thread."""
        ...

    def run_event_loop(self) -> None:
        """Blocks on the main thread until `quit` is called.

        Not in the original four methods: GUI toolkits own the main thread, and this
        keeps core from needing to import one.
        """
        ...

    def quit(self) -> None:
        """Ends `run_event_loop`. Safe to call from any thread."""
        ...
