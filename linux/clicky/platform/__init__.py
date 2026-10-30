"""Display-server integrations. Everything X11, Qt or Wayland specific lives here.

This package is only ever imported as `clicky.platform`. It must never be put on
sys.path directly, because a top-level `platform` would shadow Python's standard
library module of the same name and break dependencies that import it.
"""
