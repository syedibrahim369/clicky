import pytest

from clicky.platform.x11_capture import (
    PhysicalMonitor,
    ScreenLayout,
    ScreenLayoutMismatchError,
    sort_physical_monitors,
    verify_layouts_match,
)


def monitor_dict(left, top, width, height):
    return {"left": left, "top": top, "width": width, "height": height}


def layout(left, top, width, height, device_pixel_ratio):
    return ScreenLayout(left, top, width, height, device_pixel_ratio, False)


ALL_MONITORS_ENTRY = monitor_dict(0, 0, 9999, 9999)


def test_all_monitors_entry_is_skipped_and_order_is_left_to_right():
    monitors = sort_physical_monitors(
        [ALL_MONITORS_ENTRY, monitor_dict(1920, 0, 1920, 1080), monitor_dict(0, 0, 1920, 1080)]
    )
    assert [monitor.left for monitor in monitors] == [0, 1920]


def test_mirrored_outputs_count_once():
    monitors = sort_physical_monitors(
        [ALL_MONITORS_ENTRY, monitor_dict(0, 0, 1920, 1080), monitor_dict(0, 0, 1920, 1080)]
    )
    assert len(monitors) == 1


@pytest.mark.parametrize(
    "logical_width, logical_height, scale",
    [(3072, 1920, 1.0), (2458, 1536, 1.25), (2048, 1280, 1.5), (1536, 960, 2.0)],
)
def test_your_panel_matches_at_every_scale(logical_width, logical_height, scale):
    verify_layouts_match(
        [PhysicalMonitor(0, 0, 3072, 1920)], [layout(0, 0, logical_width, logical_height, scale)]
    )


def test_logical_size_with_an_unscaled_ratio_is_rejected():
    with pytest.raises(ScreenLayoutMismatchError):
        verify_layouts_match([PhysicalMonitor(0, 0, 3072, 1920)], [layout(0, 0, 1536, 960, 1.0)])


def test_second_monitor_origin_is_checked_in_physical_pixels():
    physical_monitors = [PhysicalMonitor(0, 0, 3072, 1920), PhysicalMonitor(3072, 0, 1920, 1080)]
    logical_layouts = [layout(0, 0, 1536, 960, 2.0), layout(1536, 0, 960, 540, 2.0)]
    verify_layouts_match(physical_monitors, logical_layouts)


def test_different_monitor_counts_are_rejected():
    with pytest.raises(ScreenLayoutMismatchError):
        verify_layouts_match([PhysicalMonitor(0, 0, 3072, 1920)], [])
