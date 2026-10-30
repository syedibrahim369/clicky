"""The blue cursor: one transparent, click-through window per monitor.

Each window paints the same desktop-wide cursor state translated by its own origin, so
a flight between monitors crosses the gap with no hand-off logic: whichever windows the
cursor overlaps draw it, and the rest clip it away.
"""

import math
from enum import Enum, auto

from PySide6.QtCore import QElapsedTimer, QObject, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from clicky.core.pointer_motion import (
    RESTING_ROTATION_DEGREES,
    FlightPlan,
    flight_frame_at,
    interpolate_rotation_degrees,
    place_label_bubble,
    plan_flight,
)
from clicky.platform.x11_capture import ScreenLayout

# Same value as DS.Colors.overlayCursorBlue in Clicky's DesignSystem.swift.
CURSOR_BLUE = QColor("#3380FF")

ANIMATION_FRAME_INTERVAL_MILLISECONDS = 16
SETTLE_ROTATION_DURATION_SECONDS = 0.18
LABEL_POP_DURATION_SECONDS = 0.25
LABEL_MILLISECONDS_PER_CHARACTER = 30
FADE_OUT_DURATION_SECONDS = 0.25

# A long notched dart, not Clicky's equilateral triangle. An equilateral triangle looks
# the same from three directions, so at rest it appeared to point right, past the target.
DART_LENGTH_PIXELS = 26.0
DART_HALF_WIDTH_PIXELS = 10.0
DART_NOTCH_DEPTH_PIXELS = 6.0
GLOW_RADIUS_PIXELS = 30.0
LABEL_HORIZONTAL_PADDING_PIXELS = 8
LABEL_VERTICAL_PADDING_PIXELS = 4
LABEL_CORNER_RADIUS_PIXELS = 6
LABEL_FONT_PIXEL_SIZE = 13

# Must cover the dart at peak flight scale plus its glow, or repaints leave trails.
CURSOR_REPAINT_MARGIN_PIXELS = 60


class CursorMode(Enum):
    HIDDEN = auto()
    FLYING = auto()
    SETTLING = auto()
    POINTING = auto()
    FADING = auto()


class ScreenOverlayWindow(QWidget):
    """A full-screen window that draws the cursor and never takes clicks or focus."""

    def __init__(self, overlay_controller: "CursorOverlayController", screen_geometry: QRect):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.X11BypassWindowManagerHint
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.overlay_controller = overlay_controller
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(screen_geometry)

    def paintEvent(self, paint_event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(-self.geometry().topLeft().toPointF())
        self.overlay_controller.paint_cursor(painter)


class CursorOverlayController(QObject):
    """Owns the cursor's animation state and the per-monitor windows that show it."""

    def __init__(self):
        super().__init__()
        self.overlay_windows: list[ScreenOverlayWindow] = []
        self.overlay_window_geometries: list[QRect] = []
        self.latest_screen_layouts: list[ScreenLayout] = []
        self.overlay_was_visible_for_capture = False

        self.cursor_mode = CursorMode.HIDDEN
        self.cursor_x = 0.0
        self.cursor_y = 0.0
        self.cursor_rotation_degrees = RESTING_ROTATION_DEGREES
        self.cursor_scale = 1.0
        self.cursor_opacity = 1.0

        self.current_flight_plan: FlightPlan | None = None
        self.settle_start_rotation_degrees = RESTING_ROTATION_DEGREES

        self.label_text = ""
        self.label_font = QFont()
        self.label_font.setPixelSize(LABEL_FONT_PIXEL_SIZE)
        self.label_font.setWeight(QFont.Weight.Medium)
        self.label_rect = QRectF()
        self.visible_label_character_count = 0
        self.label_pop_scale = 1.0

        self.previous_repaint_rect = QRect()
        self.mode_elapsed_timer = QElapsedTimer()
        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(ANIMATION_FRAME_INTERVAL_MILLISECONDS)
        self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation_timer.timeout.connect(self.advance_animation)

    def sorted_screens(self):
        """Screens left to right. mss will sort the same way, so indexes always agree."""
        return sorted(
            QGuiApplication.screens(),
            key=lambda screen: (screen.geometry().left(), screen.geometry().top()),
        )

    def fly_to(self, screen_index: int, screen_x: float, screen_y: float, label_text: str) -> None:
        screens = self.sorted_screens()
        if not 0 <= screen_index < len(screens):
            raise ValueError(f"screen {screen_index} does not exist; found {len(screens)} screen(s)")
        screen_geometry = screens[screen_index].geometry()

        self.synchronize_overlay_windows_with_screens()

        if self.cursor_mode in (CursorMode.HIDDEN, CursorMode.FADING):
            mouse_position = QCursor.pos()
            self.cursor_x = float(mouse_position.x())
            self.cursor_y = float(mouse_position.y())
            self.cursor_rotation_degrees = RESTING_ROTATION_DEGREES

        for overlay_window in self.overlay_windows:
            overlay_window.show()
            # The window manager ignores bypass windows, so nothing keeps them on top.
            # Anything raised since the last flight would otherwise cover the cursor.
            overlay_window.raise_()

        target_x = screen_geometry.left() + min(max(screen_x, 0), screen_geometry.width() - 1)
        target_y = screen_geometry.top() + min(max(screen_y, 0), screen_geometry.height() - 1)

        self.label_text = label_text
        self.visible_label_character_count = 0
        self.label_pop_scale = 0.5
        self.label_rect = self.compute_label_rect(target_x, target_y, screen_geometry)
        self.cursor_opacity = 1.0

        self.current_flight_plan = plan_flight(self.cursor_x, self.cursor_y, target_x, target_y)
        self.enter_mode(CursorMode.FLYING)
        self.animation_timer.start()

    def fade_out(self) -> None:
        if self.cursor_mode in (CursorMode.HIDDEN, CursorMode.FADING):
            return
        self.enter_mode(CursorMode.FADING)
        self.animation_timer.start()

    def prepare_for_capture(self) -> None:
        """Hides the cursor at once and records the screen layout. Runs on the main thread.

        Unlike ScreenCaptureKit, mss cannot exclude our windows from a screenshot, so a
        visible cursor must be gone before the grab. There is no fade: it has to be off
        screen now, and the model must never see it.
        """
        self.overlay_was_visible_for_capture = self.cursor_mode != CursorMode.HIDDEN
        self.animation_timer.stop()
        self.cursor_mode = CursorMode.HIDDEN
        for overlay_window in self.overlay_windows:
            overlay_window.hide()

        mouse_position = QCursor.pos()
        self.latest_screen_layouts = [
            ScreenLayout(
                left=screen.geometry().left(),
                top=screen.geometry().top(),
                width=screen.geometry().width(),
                height=screen.geometry().height(),
                device_pixel_ratio=screen.devicePixelRatio(),
                contains_mouse_cursor=screen.geometry().contains(mouse_position),
            )
            for screen in self.sorted_screens()
        ]

    def enter_mode(self, cursor_mode: CursorMode) -> None:
        self.cursor_mode = cursor_mode
        self.mode_elapsed_timer.restart()

    def seconds_in_current_mode(self) -> float:
        return self.mode_elapsed_timer.elapsed() / 1000.0

    def advance_animation(self) -> None:
        if self.cursor_mode == CursorMode.FLYING:
            self.advance_flight()
        elif self.cursor_mode == CursorMode.SETTLING:
            self.advance_settle()
        elif self.cursor_mode == CursorMode.POINTING:
            self.advance_label_reveal()
        elif self.cursor_mode == CursorMode.FADING:
            self.advance_fade()
        self.repaint_cursor_area()

    def advance_flight(self) -> None:
        # Progress comes from the clock, not a frame count, so a slow frame on an
        # integrated GPU drops frames instead of stretching the flight.
        linear_progress = self.seconds_in_current_mode() / self.current_flight_plan.duration_seconds
        flight_frame = flight_frame_at(self.current_flight_plan, linear_progress)
        self.cursor_x = flight_frame.x
        self.cursor_y = flight_frame.y
        self.cursor_rotation_degrees = flight_frame.rotation_degrees
        self.cursor_scale = flight_frame.scale

        if linear_progress >= 1.0:
            self.cursor_scale = 1.0
            self.settle_start_rotation_degrees = self.cursor_rotation_degrees
            self.enter_mode(CursorMode.SETTLING)

    def advance_settle(self) -> None:
        """Turns the cursor to its resting angle around the tip, so the tip stays on target."""
        settle_progress = min(self.seconds_in_current_mode() / SETTLE_ROTATION_DURATION_SECONDS, 1.0)
        self.cursor_rotation_degrees = interpolate_rotation_degrees(
            self.settle_start_rotation_degrees, RESTING_ROTATION_DEGREES, settle_progress
        )
        if settle_progress >= 1.0:
            self.enter_mode(CursorMode.POINTING)

    def advance_label_reveal(self) -> None:
        elapsed_seconds = self.seconds_in_current_mode()
        pop_progress = min(elapsed_seconds / LABEL_POP_DURATION_SECONDS, 1.0)

        # Back-out easing overshoots 1.0 slightly, which reads as a bounce.
        overshoot = 1.70158
        shifted_progress = pop_progress - 1.0
        eased_pop = 1.0 + shifted_progress * shifted_progress * (
            (overshoot + 1.0) * shifted_progress + overshoot
        )
        self.label_pop_scale = 0.5 + 0.5 * eased_pop

        self.visible_label_character_count = min(
            int(elapsed_seconds * 1000 / LABEL_MILLISECONDS_PER_CHARACTER),
            len(self.label_text),
        )

        label_is_fully_revealed = self.visible_label_character_count == len(self.label_text)
        if label_is_fully_revealed and pop_progress >= 1.0:
            # Nothing moves while pointing, so idle costs no CPU during a long reply.
            self.animation_timer.stop()

    def advance_fade(self) -> None:
        fade_progress = min(self.seconds_in_current_mode() / FADE_OUT_DURATION_SECONDS, 1.0)
        self.cursor_opacity = 1.0 - fade_progress
        if fade_progress >= 1.0:
            self.animation_timer.stop()
            self.cursor_mode = CursorMode.HIDDEN
            # Hiding keeps the windows out of later screenshots.
            for overlay_window in self.overlay_windows:
                overlay_window.hide()

    def synchronize_overlay_windows_with_screens(self) -> None:
        """Rebuilds the windows when monitors have been plugged in or removed."""
        screen_geometries = [screen.geometry() for screen in self.sorted_screens()]
        if screen_geometries == self.overlay_window_geometries:
            return
        for overlay_window in self.overlay_windows:
            overlay_window.close()
            overlay_window.deleteLater()
        self.overlay_windows = [
            ScreenOverlayWindow(self, screen_geometry) for screen_geometry in screen_geometries
        ]
        self.overlay_window_geometries = screen_geometries

    def compute_label_rect(self, target_x: float, target_y: float, screen_geometry: QRect) -> QRectF:
        if not self.label_text:
            return QRectF()
        font_metrics = QFontMetrics(self.label_font)
        bubble_width = font_metrics.horizontalAdvance(self.label_text) + 2 * LABEL_HORIZONTAL_PADDING_PIXELS
        bubble_height = font_metrics.height() + 2 * LABEL_VERTICAL_PADDING_PIXELS
        bubble_x, bubble_y = place_label_bubble(
            target_x,
            target_y,
            bubble_width,
            bubble_height,
            screen_geometry.left(),
            screen_geometry.top(),
            screen_geometry.width(),
            screen_geometry.height(),
        )
        return QRectF(bubble_x, bubble_y, bubble_width, bubble_height)

    def repaint_cursor_area(self) -> None:
        """Repaints only around the cursor, since a full-screen ARGB repaint at 60 Hz is costly."""
        margin = CURSOR_REPAINT_MARGIN_PIXELS
        cursor_rect = QRect(
            int(self.cursor_x) - margin, int(self.cursor_y) - margin, 2 * margin, 2 * margin
        )
        repaint_rect = cursor_rect.united(self.label_rect.toAlignedRect().adjusted(-12, -12, 12, 12))
        area_to_repaint = repaint_rect.united(self.previous_repaint_rect)
        self.previous_repaint_rect = repaint_rect

        for overlay_window in self.overlay_windows:
            window_origin = overlay_window.geometry().topLeft()
            overlay_window.update(area_to_repaint.translated(-window_origin))

    def paint_cursor(self, painter: QPainter) -> None:
        if self.cursor_mode == CursorMode.HIDDEN:
            return
        painter.setOpacity(self.cursor_opacity)
        self.paint_dart(painter)
        if self.cursor_mode in (CursorMode.POINTING, CursorMode.FADING):
            self.paint_label(painter)

    def paint_dart(self, painter: QPainter) -> None:
        painter.save()
        painter.translate(self.cursor_x, self.cursor_y)
        # Rotating and scaling around the tip keeps the exact pointing pixel on target.
        painter.rotate(self.cursor_rotation_degrees)
        painter.scale(self.cursor_scale, self.cursor_scale)

        dart_center = QPointF(0.0, DART_LENGTH_PIXELS / 2.0)

        glow_gradient = QRadialGradient(dart_center, GLOW_RADIUS_PIXELS)
        glow_color = QColor(CURSOR_BLUE)
        glow_color.setAlpha(110)
        glow_gradient.setColorAt(0.0, glow_color)
        glow_color.setAlpha(0)
        glow_gradient.setColorAt(1.0, glow_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow_gradient)
        painter.drawEllipse(dart_center, GLOW_RADIUS_PIXELS, GLOW_RADIUS_PIXELS)

        dart_path = QPainterPath(QPointF(0.0, 0.0))
        dart_path.lineTo(-DART_HALF_WIDTH_PIXELS, DART_LENGTH_PIXELS)
        dart_path.lineTo(0.0, DART_LENGTH_PIXELS - DART_NOTCH_DEPTH_PIXELS)
        dart_path.lineTo(DART_HALF_WIDTH_PIXELS, DART_LENGTH_PIXELS)
        dart_path.closeSubpath()
        painter.setBrush(CURSOR_BLUE)
        painter.drawPath(dart_path)
        painter.restore()

    def paint_label(self, painter: QPainter) -> None:
        if not self.label_text:
            return
        painter.save()
        label_center = self.label_rect.center()
        painter.translate(label_center)
        painter.scale(self.label_pop_scale, self.label_pop_scale)
        painter.translate(-label_center)

        # Stacked translucent outlines stand in for Clicky's blurred shadow, which
        # would be far slower in software on a laptop with no dedicated GPU.
        glow_color = QColor(CURSOR_BLUE)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for glow_width, glow_alpha in ((10, 40), (6, 70)):
            glow_color.setAlpha(glow_alpha)
            painter.setPen(QPen(glow_color, glow_width))
            painter.drawRoundedRect(
                self.label_rect, LABEL_CORNER_RADIUS_PIXELS, LABEL_CORNER_RADIUS_PIXELS
            )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CURSOR_BLUE)
        painter.drawRoundedRect(self.label_rect, LABEL_CORNER_RADIUS_PIXELS, LABEL_CORNER_RADIUS_PIXELS)

        painter.setFont(self.label_font)
        painter.setPen(QColor("white"))
        font_metrics = QFontMetrics(self.label_font)
        text_baseline = QPointF(
            self.label_rect.left() + LABEL_HORIZONTAL_PADDING_PIXELS,
            self.label_rect.top() + LABEL_VERTICAL_PADDING_PIXELS + font_metrics.ascent(),
        )
        painter.drawText(text_baseline, self.label_text[: self.visible_label_character_count])
        painter.restore()
