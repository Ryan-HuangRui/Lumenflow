"""Compatibility wrapper for :mod:`lumenflow.core.review`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.core.review import *

if __name__ == "__main__":
    main()
