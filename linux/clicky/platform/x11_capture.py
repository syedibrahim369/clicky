"""Per-monitor screenshots with mss, reconciled against Qt's view of the same monitors.

mss reports physical pixels and Qt reports logical ones. They are paired here, and any
disagreement is an error: a silent mismatch would send the cursor to the wrong place.
"""

from dataclasses import dataclass

import mss
import mss.tools

from clicky.platform.base import CapturedScreen

# Qt rounds logical sizes to whole pixels, so at a fractional scale like 1.25 a 3072 wide
# panel becomes 2458 logical, which is 3072.5 physical. Two pixels covers that rounding.
MAXIMUM_PHYSICAL_PIXEL_DISCREPANCY = 2.0


class ScreenLayoutMismatchError(Exception):
    """Raised when mss and Qt disagree about the monitors."""


@dataclass(frozen=True)
class ScreenLayout:
    """What Qt reports for one monitor, in logical pixels."""

    left: int
    top: int
    width: int
    height: int
    device_pixel_ratio: float
    contains_mouse_cursor: bool


@dataclass(frozen=True)
class PhysicalMonitor:
    left: int
    top: int
    width: int
    height: int


def sort_physical_monitors(mss_monitors: list[dict]) -> list[PhysicalMonitor]:
    """Sorts monitors like the overlay does, skipping mss's all-monitors entry at index 0.

    Mirrored outputs share a rectangle, and appear once so that the counts line up.
    """
    unique_monitors = {
        PhysicalMonitor(monitor["left"], monitor["top"], monitor["width"], monitor["height"])
        for monitor in mss_monitors[1:]
    }
    return sorted(unique_monitors, key=lambda monitor: (monitor.left, monitor.top))


def verify_layouts_match(physical_monitors: list[PhysicalMonitor], screen_layouts: list[ScreenLayout]) -> None:
    if len(physical_monitors) != len(screen_layouts):
        raise ScreenLayoutMismatchError(
            f"mss found {len(physical_monitors)} monitor(s) but Qt found {len(screen_layouts)}."
        )

    for monitor, layout in zip(physical_monitors, screen_layouts):
        scale = layout.device_pixel_ratio
        discrepancies = (
            abs(monitor.left - layout.left * scale),
            abs(monitor.top - layout.top * scale),
            abs(monitor.width - layout.width * scale),
            abs(monitor.height - layout.height * scale),
        )
        if max(discrepancies) > MAXIMUM_PHYSICAL_PIXEL_DISCREPANCY:
            raise ScreenLayoutMismatchError(
                f"Monitor {monitor} does not match Qt's {layout} at scale {scale}."
            )


def capture_screens(screen_layouts: list[ScreenLayout]) -> list[CapturedScreen]:
    captured_screens = []
    # A new MSS per capture, because capture() can run on any thread and mss connections
    # must not be shared between threads.
    with mss.MSS() as screen_grabber:
        physical_monitors = sort_physical_monitors(screen_grabber.monitors)
        verify_layouts_match(physical_monitors, screen_layouts)

        for monitor, layout in zip(physical_monitors, screen_layouts):
            screenshot = screen_grabber.grab(
                {
                    "left": monitor.left,
                    "top": monitor.top,
                    "width": monitor.width,
                    "height": monitor.height,
                }
            )
            captured_screens.append(
                CapturedScreen(
                    png_bytes=mss.tools.to_png(screenshot.rgb, screenshot.size),
                    png_width=screenshot.width,
                    png_height=screenshot.height,
                    left=layout.left,
                    top=layout.top,
                    width=layout.width,
                    height=layout.height,
                    scale_factor=layout.device_pixel_ratio,
                    contains_mouse_cursor=layout.contains_mouse_cursor,
                )
            )
    return captured_screens
