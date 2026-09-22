"""Compatibility wrapper for :mod:`lumenflow.execution.render`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.execution.render import *

if __name__ == "__main__":
    main()
