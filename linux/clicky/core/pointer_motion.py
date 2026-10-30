"""Pure geometry for the blue cursor: its flight arc and where its label bubble sits.

The flight constants come from `animateBezierFlightArc` in Clicky's OverlayWindow.swift.
This module has no Qt imports so the motion can be unit-tested without a display.
"""

import math
from dataclasses import dataclass

MINIMUM_FLIGHT_DURATION_SECONDS = 0.6
MAXIMUM_FLIGHT_DURATION_SECONDS = 1.4
FLIGHT_PIXELS_PER_SECOND = 800.0
MAXIMUM_ARC_HEIGHT_PIXELS = 80.0
ARC_HEIGHT_AS_FRACTION_OF_DISTANCE = 0.2
PEAK_FLIGHT_SCALE_INCREASE = 0.3

# The tip points up-left at rest, like a normal mouse pointer.
RESTING_ROTATION_DEGREES = -35.0

LABEL_BUBBLE_HORIZONTAL_OFFSET_PIXELS = 34
LABEL_BUBBLE_VERTICAL_OFFSET_PIXELS = 14


@dataclass(frozen=True)
class FlightPlan:
    start_x: float
    start_y: float
    control_x: float
    control_y: float
    end_x: float
    end_y: float
    duration_seconds: float


@dataclass(frozen=True)
class FlightFrame:
    x: float
    y: float
    rotation_degrees: float
    scale: float


def plan_flight(start_x: float, start_y: float, end_x: float, end_y: float) -> FlightPlan:
    distance = math.hypot(end_x - start_x, end_y - start_y)
    duration_seconds = min(
        max(distance / FLIGHT_PIXELS_PER_SECOND, MINIMUM_FLIGHT_DURATION_SECONDS),
        MAXIMUM_FLIGHT_DURATION_SECONDS,
    )

    # Lifting the midpoint upward (negative y) turns the straight line into an arc.
    arc_height = min(distance * ARC_HEIGHT_AS_FRACTION_OF_DISTANCE, MAXIMUM_ARC_HEIGHT_PIXELS)
    return FlightPlan(
        start_x=start_x,
        start_y=start_y,
        control_x=(start_x + end_x) / 2.0,
        control_y=(start_y + end_y) / 2.0 - arc_height,
        end_x=end_x,
        end_y=end_y,
        duration_seconds=duration_seconds,
    )


def flight_frame_at(flight_plan: FlightPlan, linear_progress: float) -> FlightFrame:
    """Returns the cursor's pose at `linear_progress` (0 to 1) through the flight."""
    linear_progress = min(max(linear_progress, 0.0), 1.0)

    # Smoothstep eases the cursor in and out instead of moving at constant speed.
    eased_progress = linear_progress * linear_progress * (3.0 - 2.0 * linear_progress)
    remaining_progress = 1.0 - eased_progress

    # Quadratic bezier: B(t) = (1-t)^2 P0 + 2(1-t)t P1 + t^2 P2
    x = (
        remaining_progress * remaining_progress * flight_plan.start_x
        + 2.0 * remaining_progress * eased_progress * flight_plan.control_x
        + eased_progress * eased_progress * flight_plan.end_x
    )
    y = (
        remaining_progress * remaining_progress * flight_plan.start_y
        + 2.0 * remaining_progress * eased_progress * flight_plan.control_y
        + eased_progress * eased_progress * flight_plan.end_y
    )

    # Face the direction of travel using the curve's tangent, B'(t).
    tangent_x = 2.0 * remaining_progress * (flight_plan.control_x - flight_plan.start_x) + (
        2.0 * eased_progress * (flight_plan.end_x - flight_plan.control_x)
    )
    tangent_y = 2.0 * remaining_progress * (flight_plan.control_y - flight_plan.start_y) + (
        2.0 * eased_progress * (flight_plan.end_y - flight_plan.control_y)
    )
    if math.hypot(tangent_x, tangent_y) < 1e-6:
        # A zero-length flight has no direction, and atan2(0, 0) would snap it sideways.
        rotation_degrees = RESTING_ROTATION_DEGREES
    else:
        # +90 because the tip points up at 0 degrees while atan2 measures from rightward.
        rotation_degrees = math.degrees(math.atan2(tangent_y, tangent_x)) + 90.0

    scale = 1.0 + math.sin(linear_progress * math.pi) * PEAK_FLIGHT_SCALE_INCREASE
    return FlightFrame(x=x, y=y, rotation_degrees=rotation_degrees, scale=scale)


def interpolate_rotation_degrees(
    start_rotation_degrees: float, end_rotation_degrees: float, progress: float
) -> float:
    """Interpolates along the shorter way round so the cursor never spins a full turn."""
    shortest_difference = (end_rotation_degrees - start_rotation_degrees + 180.0) % 360.0 - 180.0
    return start_rotation_degrees + shortest_difference * progress


def place_label_bubble(
    target_x: float,
    target_y: float,
    bubble_width: float,
    bubble_height: float,
    screen_left: float,
    screen_top: float,
    screen_width: float,
    screen_height: float,
) -> tuple[float, float]:
    """Returns the bubble's top-left corner, flipping it to stay on the target's screen."""
    screen_right = screen_left + screen_width
    screen_bottom = screen_top + screen_height

    bubble_x = target_x + LABEL_BUBBLE_HORIZONTAL_OFFSET_PIXELS
    if bubble_x + bubble_width > screen_right:
        bubble_x = target_x - LABEL_BUBBLE_HORIZONTAL_OFFSET_PIXELS - bubble_width

    bubble_y = target_y + LABEL_BUBBLE_VERTICAL_OFFSET_PIXELS
    if bubble_y + bubble_height > screen_bottom:
        bubble_y = target_y - LABEL_BUBBLE_VERTICAL_OFFSET_PIXELS - bubble_height

    # A label wider than the space on either side still has to stay on screen.
    bubble_x = min(max(bubble_x, screen_left), screen_right - bubble_width)
    bubble_y = min(max(bubble_y, screen_top), screen_bottom - bubble_height)
    return bubble_x, bubble_y
