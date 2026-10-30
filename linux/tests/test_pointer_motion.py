import math

import pytest

from clicky.core.pointer_motion import (
    MAXIMUM_ARC_HEIGHT_PIXELS,
    MAXIMUM_FLIGHT_DURATION_SECONDS,
    MINIMUM_FLIGHT_DURATION_SECONDS,
    RESTING_ROTATION_DEGREES,
    flight_frame_at,
    interpolate_rotation_degrees,
    place_label_bubble,
    plan_flight,
)


def test_flight_starts_and_ends_exactly_on_its_endpoints():
    flight_plan = plan_flight(10, 20, 500, 400)
    first_frame = flight_frame_at(flight_plan, 0.0)
    last_frame = flight_frame_at(flight_plan, 1.0)
    assert (first_frame.x, first_frame.y) == (10, 20)
    assert (last_frame.x, last_frame.y) == (500, 400)


def test_duration_is_clamped_at_both_ends():
    assert plan_flight(0, 0, 10, 0).duration_seconds == MINIMUM_FLIGHT_DURATION_SECONDS
    assert plan_flight(0, 0, 5000, 0).duration_seconds == MAXIMUM_FLIGHT_DURATION_SECONDS


def test_arc_rises_above_a_level_flight_by_a_capped_amount():
    flight_plan = plan_flight(0, 300, 2000, 300)
    assert flight_plan.control_y == 300 - MAXIMUM_ARC_HEIGHT_PIXELS
    assert flight_frame_at(flight_plan, 0.5).y < 300


def test_scale_peaks_at_midpoint_and_returns_to_normal():
    flight_plan = plan_flight(0, 0, 500, 0)
    assert flight_frame_at(flight_plan, 0.5).scale == pytest.approx(1.3)
    assert flight_frame_at(flight_plan, 1.0).scale == pytest.approx(1.0)


def test_cursor_faces_its_direction_of_travel():
    level_rightward_midpoint = flight_frame_at(plan_flight(0, 0, 500, 0), 0.5)
    assert level_rightward_midpoint.rotation_degrees == pytest.approx(90.0)


def test_progress_past_the_end_stays_on_target():
    last_frame = flight_frame_at(plan_flight(0, 0, 100, 100), 1.7)
    assert (last_frame.x, last_frame.y) == (100, 100)


def test_zero_length_flight_has_a_finite_resting_pose():
    frame = flight_frame_at(plan_flight(50, 50, 50, 50), 0.5)
    assert (frame.x, frame.y) == (50, 50)
    assert frame.rotation_degrees == RESTING_ROTATION_DEGREES
    assert math.isfinite(frame.scale)


def test_rotation_takes_the_short_way_round():
    assert interpolate_rotation_degrees(170.0, -170.0, 0.5) == pytest.approx(180.0)


def test_label_sits_right_of_and_below_the_target_when_there_is_room():
    bubble_x, bubble_y = place_label_bubble(100, 100, 80, 24, 0, 0, 1280, 720)
    assert bubble_x > 100
    assert bubble_y > 100


def test_label_flips_at_the_bottom_right_corner():
    bubble_x, bubble_y = place_label_bubble(1270, 710, 80, 24, 0, 0, 1280, 720)
    assert bubble_x + 80 <= 1270
    assert bubble_y + 24 <= 710


def test_label_stays_on_a_monitor_that_does_not_start_at_the_origin():
    bubble_x, bubble_y = place_label_bubble(1285, 5, 80, 24, 1280, 0, 1920, 1080)
    assert bubble_x >= 1280
    assert bubble_y >= 0


def test_label_wider_than_the_screen_is_pinned_to_the_left_edge_area():
    bubble_x, _ = place_label_bubble(100, 100, 5000, 24, 0, 0, 1280, 720)
    assert bubble_x <= 0
