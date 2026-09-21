from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_capabilities  # noqa: E402


class BackendCapabilitiesTests(unittest.TestCase):
    def test_rawtherapee_contract_supports_preview_render_and_intent_v2(self) -> None:
        contract = backend_capabilities.backend_capabilities_for("rawtherapee")

        self.assertEqual(contract.schema_version, "lumenflow.backend_capabilities.v1")
        self.assertEqual(contract.backend_id, "rawtherapee")
        self.assertEqual(contract.require("preview.state_bound").state, "supported")
        self.assertEqual(contract.require("plan.compile.v1").state, "supported")
        self.assertEqual(contract.require("intent.compile.v2").state, "supported")
        self.assertEqual(contract.require("render").state, "supported")

    def test_unknown_capability_is_a_structured_contract_error(self) -> None:
        contract = backend_capabilities.backend_capabilities_for("rawtherapee")

        with self.assertRaises(backend_capabilities.UnknownCapabilityError) as error:
            contract.require("future.magic")

        self.assertEqual(
            error.exception.to_dict(),
            {
                "code": "BACKEND_CAPABILITY_UNKNOWN",
                "backend_id": "rawtherapee",
                "capability": "future.magic",
                "state": "unknown",
                "reason": "Capability is not declared by this backend contract",
            },
        )

    def test_lightroom_runtime_capabilities_remain_unverified_without_bridge_evidence(self) -> None:
        contract = backend_capabilities.backend_capabilities_for("lightroom")

        self.assertEqual(contract.capability("plan.compile.v1").state, "supported")
        self.assertEqual(contract.capability("preview.state_bound").state, "unverified")
        self.assertEqual(contract.capability("develop.write.verified").state, "unverified")
        with self.assertRaises(backend_capabilities.UnverifiedCapabilityError) as error:
            contract.require("preview.state_bound")
        self.assertEqual(error.exception.code, "BACKEND_CAPABILITY_UNVERIFIED")
        self.assertIn("safe_object_develop_read", error.exception.reason)
        self.assertIn("verified_state_bound_preview", error.exception.reason)

    def test_lightroom_contract_maps_independent_bridge_evidence(self) -> None:
        contract = backend_capabilities.lightroom_capabilities_from_status(
            {
                "connected": True,
                "bridge_contract": {
                    "plugin_version": "1.3.0",
                    "cli_version": "1.3.0",
                    "protocol_version": "2",
                    "version_match": True,
                    "capabilities": {
                        "safe_object_develop_read": True,
                        "verified_state_bound_preview": True,
                        "safe_object_develop_write": False,
                        "verified_export_result": False,
                    },
                },
            }
        )

        self.assertEqual(contract.require("state.read").state, "supported")
        self.assertEqual(contract.require("preview.state_bound").state, "supported")
        self.assertEqual(contract.capability("develop.write.verified").state, "unverified")
        self.assertEqual(contract.capability("export.verified").state, "unverified")
        self.assertEqual(contract.capability("render").state, "unverified")

    def test_invalid_lightroom_bridge_contract_cannot_enable_capabilities(self) -> None:
        contract = backend_capabilities.lightroom_capabilities_from_status(
            {
                "connected": True,
                "bridge_contract": {
                    "protocol_version": "1",
                    "version_match": False,
                    "capabilities": {
                        "safe_object_develop_read": True,
                        "verified_state_bound_preview": True,
                    },
                },
            }
        )

        self.assertEqual(contract.capability("preview.state_bound").state, "unverified")
        self.assertIn("unsupported bridge protocol", contract.capability("preview.state_bound").reason)

    def test_darktable_contract_exposes_only_the_live_verified_xmp_replay_slice(self) -> None:
        contract = backend_capabilities.backend_capabilities_for("darktable")

        self.assertEqual(contract.require("render.legacy").state, "supported")
        self.assertEqual(contract.require("intent.compile.v2").state, "supported")
        self.assertEqual(contract.require("preview.state_bound").state, "supported")
        self.assertEqual(contract.require("state.read").state, "supported")
        self.assertEqual(contract.require("render").state, "supported")
        self.assertEqual(contract.require("export.verified").state, "supported")

    def test_contract_schema_is_strict_and_versioned(self) -> None:
        schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "backend_capabilities.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "lumenflow.backend_capabilities.v1",
        )
        self.assertIs(schema["additionalProperties"], False)
        self.assertIs(schema["$defs"]["capability"]["additionalProperties"], False)
        capability_schema = schema["properties"]["capabilities"]
        self.assertIs(capability_schema["additionalProperties"], False)
        self.assertEqual(
            set(capability_schema["required"]),
            set(backend_capabilities.CAPABILITY_NAMES),
        )


if __name__ == "__main__":
    unittest.main()
