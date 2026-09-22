#!/usr/bin/env python3
"""Compatibility wrapper for :mod:`lumenflow.curation.curate_photos`."""

from __future__ import annotations

from _package_compat import ensure_package_importable

ensure_package_importable()

from lumenflow.curation.curate_photos import *


if __name__ == "__main__":
    main()
