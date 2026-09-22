"""Compatibility wrapper for :mod:`lumenflow.core.edit_intent`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.core.edit_intent import *

if __name__ == "__main__":
    main()
