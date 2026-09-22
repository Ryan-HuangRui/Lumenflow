"""Compatibility wrapper for :mod:`lumenflow.backends.darktable.codec`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.backends.darktable.codec import *
