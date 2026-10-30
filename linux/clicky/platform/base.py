"""The contract between Clicky's core and a display server."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class TriggerEvent(Enum):
    PRESSED = "pressed"
    RELEASED = "released"


@dataclass(frozen=True)
class CapturedScreen:
    """One monitor's screenshot and where that monitor sits on the desktop.

    `left`, `top`, `width` and `height` are logical pixels in desktop coordinates, the
    same units `Platform.point` takes after subtracting the origin. The PNG is in
    physical pixels, so `scale_factor` is physical pixels per logical pixel.
    """

    png_bytes: bytes
    left: int
    top: int
    width: int
    height: int
    scale_factor: float


class Platform(Protocol):
    def on_trigger(self, callback: Callable[[TriggerEvent], None]) -> None:
        """Registers the callback fired when the push-to-talk hotkey goes down or up."""
        ...

    def capture(self) -> list[CapturedScreen]:
        """Screenshots every monitor, in the order `point` numbers them."""
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
