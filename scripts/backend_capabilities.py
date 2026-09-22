"""Compatibility wrapper for :mod:`lumenflow.backend_capabilities`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.backend_capabilities import *

if __name__ == "__main__":
    main()
