"""Bootstrap the local src-layout package for legacy script execution.

Installed users import :mod:`lumenflow` normally.  These wrappers are also
intended to keep working directly from a checkout before an editable install,
so they add only this repository's ``src`` directory to the import path.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_package_importable() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
