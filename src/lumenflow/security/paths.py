"""Fail-closed, symlink-aware filesystem allowlists."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


class PathPolicyError(ValueError):
    """A stable path-policy failure suitable for an MCP error envelope."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


def _configured_roots(
    config: dict[str, Any],
    key: str,
    environment: Mapping[str, str],
    env_key: str,
) -> list[str]:
    security = config.get("security")
    value = security.get(key) if isinstance(security, dict) else None
    if value is None:
        raw = environment.get(env_key, "")
        return [item for item in raw.split(os.pathsep) if item]
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise PathPolicyError(
            "INVALID_ALLOWED_ROOTS", f"security.{key} must be an array of paths"
        )
    return value


def _normalize_roots(values: list[str], field: str) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in values:
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        if not path.is_absolute():
            raise PathPolicyError(
                "INVALID_ALLOWED_ROOTS", f"{field} entries must be absolute paths"
            )
        resolved = path.resolve(strict=False)
        if not resolved.is_dir():
            raise PathPolicyError(
                "INVALID_ALLOWED_ROOTS", f"{field} root is not a directory: {path}"
            )
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


class AllowedRoots:
    """Resolved source and output roots used by every filesystem-facing tool."""

    def __init__(self, source_roots: tuple[Path, ...], output_roots: tuple[Path, ...]) -> None:
        self.source_roots = source_roots
        self.output_roots = output_roots

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        environment: Mapping[str, str] | None = None,
    ) -> "AllowedRoots":
        env = os.environ if environment is None else environment
        source_values = _configured_roots(
            config,
            "allowed_source_roots",
            env,
            "LUMENFLOW_ALLOWED_SOURCE_ROOTS",
        )
        output_values = _configured_roots(
            config,
            "allowed_output_roots",
            env,
            "LUMENFLOW_ALLOWED_OUTPUT_ROOTS",
        )
        return cls(
            _normalize_roots(source_values, "allowed_source_roots"),
            _normalize_roots(output_values, "allowed_output_roots"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.source_roots and self.output_roots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "source_roots": [str(path) for path in self.source_roots],
            "output_roots": [str(path) for path in self.output_roots],
        }

    def require_configured(self) -> None:
        if not self.configured:
            raise PathPolicyError(
                "ALLOWED_ROOTS_REQUIRED",
                "configure both security.allowed_source_roots and "
                "security.allowed_output_roots before accessing photos",
            )

    @staticmethod
    def _require_absolute(path: Path, field: str) -> Path:
        if not path.is_absolute():
            raise PathPolicyError(
                "ABSOLUTE_PATH_REQUIRED", f"{field} must be an absolute path"
            )
        return path.resolve(strict=False)

    @staticmethod
    def _contained(path: Path, roots: tuple[Path, ...]) -> bool:
        for root in roots:
            try:
                path.relative_to(root)
            except ValueError:
                continue
            return True
        return False

    def require_source(self, path: Path, field: str) -> Path:
        self.require_configured()
        resolved = self._require_absolute(path, field)
        if not self._contained(resolved, self.source_roots):
            raise PathPolicyError(
                "PATH_NOT_ALLOWED", f"{field} is outside allowed source roots: {path}"
            )
        return resolved

    def require_output(self, path: Path, field: str) -> Path:
        self.require_configured()
        resolved = self._require_absolute(path, field)
        if not self._contained(resolved, self.output_roots):
            raise PathPolicyError(
                "PATH_NOT_ALLOWED", f"{field} is outside allowed output roots: {path}"
            )
        return resolved

    def require_read(self, path: Path, field: str) -> Path:
        """Allow non-RAW inputs from either explicitly trusted root class."""

        self.require_configured()
        resolved = self._require_absolute(path, field)
        if not self._contained(resolved, self.source_roots + self.output_roots):
            raise PathPolicyError(
                "PATH_NOT_ALLOWED", f"{field} is outside all allowed roots: {path}"
            )
        return resolved
