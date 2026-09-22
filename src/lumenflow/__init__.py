"""Reusable Lumenflow core contracts.

The first installable package slice contains the low-level configuration,
driver-safety, backend-capability, and task-state modules.  The historical
``scripts/`` entry points remain available as compatibility wrappers.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "backends",
    "backend_capabilities",
    "config",
    "core",
    "driver_adapter",
    "execution",
    "task_store",
]
