"""Compatibility wrapper for :mod:`lumenflow.task_store`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.task_store import *
