#!/usr/bin/env bash
#
# Starts a nested X11 desktop (Xephyr + xfwm4 + picom) for developing Clicky for
# Linux from inside a Wayland session. XWayland is not enough here: it cannot give
# us global hotkeys or an always-on-top overlay, but a nested X server is a real X11
# display where all of that works, and compositing (picom) makes translucency work.
#
# Usage:
#   linux/scripts/dev-x11.sh                 start at 1280x720 on display :20
#   linux/scripts/dev-x11.sh --size 1600x900
#   linux/scripts/dev-x11.sh --display 21
#   linux/scripts/dev-x11.sh --stop
#
# Then, in another terminal:
#   DISPLAY=:20 python -m clicky --point 400 300 "test" --screen 0

set -euo pipefail

nested_display_number=20
nested_screen_size="1280x720"
should_stop_existing_display=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --size)
            nested_screen_size="$2"
            shift 2
            ;;
        --display)
            nested_display_number="$2"
            shift 2
            ;;
        --stop)
            should_stop_existing_display=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

nested_display=":${nested_display_number}"
xephyr_pid_file="${XDG_RUNTIME_DIR:-/tmp}/clicky-xephyr-${nested_display_number}.pid"

if [[ "$should_stop_existing_display" == true ]]; then
    if [[ -f "$xephyr_pid_file" ]]; then
        kill "$(cat "$xephyr_pid_file")" 2>/dev/null || true
        rm -f "$xephyr_pid_file"
        echo "Stopped nested display ${nested_display}."
    else
        echo "No nested display is recorded for ${nested_display}."
    fi
    exit 0
fi

missing_commands=()
for required_command in Xephyr xfwm4 picom; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        missing_commands+=("$required_command")
    fi
done

if [[ ${#missing_commands[@]} -gt 0 ]]; then
    echo "Missing: ${missing_commands[*]}" >&2
    echo "Install with: sudo apt install xserver-xephyr xfwm4 picom" >&2
    exit 1
fi

if [[ -e "/tmp/.X11-unix/X${nested_display_number}" ]]; then
    echo "Display ${nested_display} is already in use. Stop it with --stop or pick another with --display." >&2
    exit 1
fi

# RECORD is what pynput listens through and XTEST lets tests inject the hotkey.
# Both are named explicitly so a distro default change fails loudly here, not later.
Xephyr "$nested_display" -ac -br -noreset -resizeable \
    -screen "$nested_screen_size" \
    +extension RECORD +extension XTEST +extension Composite &
xephyr_pid=$!
echo "$xephyr_pid" > "$xephyr_pid_file"

cleanup_nested_display() {
    kill "$xephyr_pid" 2>/dev/null || true
    rm -f "$xephyr_pid_file"
}
trap cleanup_nested_display EXIT

# Xephyr creates its socket asynchronously; clients started too early exit immediately.
for _ in $(seq 1 50); do
    [[ -S "/tmp/.X11-unix/X${nested_display_number}" ]] && break
    sleep 0.1
done

DISPLAY="$nested_display" xfwm4 --compositor=off &
DISPLAY="$nested_display" picom --backend xrender &

echo "Nested X11 desktop is running on DISPLAY=${nested_display} (${nested_screen_size}). Ctrl+C to stop."
wait "$xephyr_pid"
