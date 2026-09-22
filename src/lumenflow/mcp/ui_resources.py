"""Versioned, self-contained MCP Apps resources."""

from __future__ import annotations

from importlib import resources


UI_MIME_TYPE = "text/html;profile=mcp-app"
STATUS_UI_URI = "ui://lumenflow/runtime-status/v1.html"
CURATION_UI_URI = "ui://lumenflow/curation/v1.html"
REVIEW_UI_URI = "ui://lumenflow/review/v1.html"

UI_RESOURCE_META = {
    "ui": {
        "prefersBorder": True,
        "csp": {
            "connectDomains": [],
            "resourceDomains": [],
            "frameDomains": [],
        },
    }
}


def tool_ui_meta(resource_uri: str) -> dict[str, object]:
    """Return standards-first tool metadata plus the ChatGPT compatibility alias."""

    return {
        "ui": {"resourceUri": resource_uri},
        "openai/outputTemplate": resource_uri,
    }


def load_ui_document(filename: str) -> str:
    """Load one immutable packaged UI document."""

    return resources.files("lumenflow.ui").joinpath(filename).read_text(encoding="utf-8")


__all__ = [
    "CURATION_UI_URI",
    "REVIEW_UI_URI",
    "STATUS_UI_URI",
    "UI_MIME_TYPE",
    "UI_RESOURCE_META",
    "load_ui_document",
    "tool_ui_meta",
]
