"""Planned platform for GNOME on Wayland. Not implemented.

GNOME has no layer-shell, so a small GNOME Shell extension will draw the overlay and
expose it over D-Bus. Screenshots will go through the extension or the portal, and a
GNOME custom shortcut will fire the trigger with `python -m clicky --trigger`.
"""
