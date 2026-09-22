from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "src" / "lumenflow" / "ui"
PAGES = {
    "runtime-status.html": ("Lite", "Full", "Allowed roots", "RawTherapee", "darktable"),
    "curation.html": (
        "Candidates",
        "Opening",
        "Detail",
        "agent_recommended_pending_user_confirmation",
        "User confirmation required",
    ),
    "review.html": (
        "Review",
        "Accept",
        "Revise",
        "Receipt",
        "Source RAW unchanged",
    ),
}


class PluginUIAssetTests(unittest.TestCase):
    def test_three_independent_mcp_app_html_assets_exist(self) -> None:
        for filename in PAGES:
            with self.subTest(filename=filename):
                document = (UI_ROOT / filename).read_text(encoding="utf-8")
                self.assertTrue(document.lower().startswith("<!doctype html>"))
                self.assertIn('name="mcp-app-mime"', document)
                self.assertIn('content="text/html;profile=mcp-app"', document)
                self.assertIn("window.openai", document)
                self.assertIn('addEventListener("message"', document)
                for bridge_phrase in (
                    "ui/initialize",
                    "ui/notifications/initialized",
                    "ui/notifications/tool-result",
                    'jsonrpc: "2.0"',
                    'protocolVersion: "2026-01-26"',
                    'appCapabilities: { availableDisplayModes: ["inline"] }',
                    "event.source === window.parent",
                    "structuredContent",
                ):
                    self.assertIn(bridge_phrase, document)
                for phrase in PAGES[filename]:
                    self.assertIn(phrase, document)

    def test_assets_have_no_network_or_dynamic_code_escape_hatches(self) -> None:
        forbidden = (
            r"<script\s+[^>]*src=",
            r"<link\s+[^>]*href\s*=\s*[\"']https?://",
            r"\bhttps?://",
            r"\b(fetch|XMLHttpRequest)\s*\(",
            r"\b(eval|Function)\s*\(",
            r"\b(document\.write|insertAdjacentHTML|innerHTML)\b",
        )
        for filename in PAGES:
            document = (UI_ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                for pattern in forbidden:
                    self.assertIsNone(re.search(pattern, document, flags=re.IGNORECASE))
                self.assertIn("textContent", document)
                self.assertIn("safeImageSource", document)

    def test_assets_honor_host_theme_and_motion_preferences(self) -> None:
        for filename in PAGES:
            document = (UI_ROOT / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn("--mcp-app-background", document)
                self.assertIn("--color-text-primary", document)
                self.assertIn("prefers-reduced-motion", document)
                self.assertIn(":focus-visible", document)

    def test_curation_asset_exposes_no_execution_control(self) -> None:
        document = (UI_ROOT / "curation.html").read_text(encoding="utf-8")
        self.assertNotIn("<button", document.lower())
        self.assertNotRegex(
            document,
            r"<button[^>]*>[^<]*(execute|apply|develop|render|run)[^<]*</button>",
        )
        self.assertIn("No execution control", document)
        self.assertIn("confirmation", document.lower())

    def test_runtime_paths_are_summarized_instead_of_rendered(self) -> None:
        document = (UI_ROOT / "runtime-status.html").read_text(encoding="utf-8")
        self.assertIn("path hidden", document.lower())
        self.assertIn("summarizeRoot", document)
        for phrase in ("path_policy", "source_roots", "output_roots", "rootCount"):
            self.assertIn(phrase, document)
        self.assertNotRegex(document, r"/(?:Users|home|private|var)/")
        self.assertNotRegex(document, r"[A-Za-z]:\\")

    def test_runtime_status_renders_feature_capabilities_independently_of_mode(self) -> None:
        document = (UI_ROOT / "runtime-status.html").read_text(encoding="utf-8")
        for phrase in (
            "features",
            "local_curation",
            "raw_preview",
            "raw_development",
            "high_depth_export",
            "Workflow capabilities",
        ):
            self.assertIn(phrase, document)

    def test_curation_accepts_manifest_and_selection_plan_shapes_without_paths(self) -> None:
        document = (UI_ROOT / "curation.html").read_text(encoding="utf-8")
        for phrase in ("manifest.candidates", "selection_plan", "status.decision", "assetLabel"):
            self.assertIn(phrase, document)
        self.assertIn("source", document)
        self.assertIn("preview", document)

    def test_review_accepts_session_and_evidence_bindings(self) -> None:
        document = (UI_ROOT / "review.html").read_text(encoding="utf-8")
        for phrase in (
            "revisions_used",
            "max_revisions",
            "source_unchanged",
            "plan_id",
            "receipt_id",
            "output_fingerprint",
        ):
            self.assertIn(phrase, document)

    def test_review_asset_carries_source_and_receipt_bound_states(self) -> None:
        document = (UI_ROOT / "review.html").read_text(encoding="utf-8")
        self.assertIn("receiptBound", document)
        self.assertIn("sourceUnmodified", document)
        self.assertIn("outputFingerprint", document)
        self.assertIn("round", document)

    def test_html_assets_are_in_package_data(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('"ui/*.html"', pyproject)


if __name__ == "__main__":
    unittest.main()
