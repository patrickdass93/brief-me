#!/usr/bin/env python3
"""Deterministic tests for the brief-me MoE stage gate."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "moe_stage_gate.py"
spec = importlib.util.spec_from_file_location("moe_stage_gate", MODULE_PATH)
assert spec and spec.loader
stage_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_gate)


def record(stage: str = "brief-me") -> dict:
    stage_data = {
        "brief-me": {
            "intent": "Make stage gates reliable.",
            "domain": "agent workflow",
            "first_safe_slice": "Run deterministic fixtures.",
            "approval_gates": ["production activation"],
            "success_criteria": ["Both reports pass"],
            "failure_behavior": "Fail closed for shipping.",
        },
        "build-me": {
            "changed_resources": ["scripts/moe_stage_gate.py"],
            "verification_evidence": ["unit tests"],
            "side_effects": ["none"],
            "unresolved_risks": ["none"],
            "rollback": "revert the commit",
        },
        "ship-me": {
            "approval_status": "approved",
            "pre_ship_checks": ["tests pass"],
            "backup_or_rollback": "revert the commit",
            "post_ship_verification": ["read-back"],
            "maintain_handoff": "monitor evaluator errors",
        },
        "maintain-me": {
            "health_contract": "both evaluators return valid JSON",
            "check_frequency": "per stage",
            "alert_destination": "approved task record",
            "dedupe_policy": "one report per stage attempt",
            "auto_fix_bounds": "none",
            "disable_path": "disable the gate config",
        },
    }[stage]
    return {
        "schema_version": "stage-gate/v1",
        "task_id": "test-task-001",
        "stage": stage,
        "stage_contract": {
            "objective": "Prove the next stage can begin safely.",
            "required_evidence": ["one verified observation"],
            "required_approvals": ["production activation"],
            "acceptance_criteria": ["All required fields populated"],
            "next_stage": "build-me",
        },
        "artifact": {
            "summary": "A redacted test artifact.",
            "evidence": [{"id": "evidence-1", "kind": "test", "reference": "unit-test"}],
            "redactions_applied": True,
        },
        "stage_data": stage_data,
    }


class StageGateTests(unittest.TestCase):
    def test_accepts_complete_record(self) -> None:
        self.assertEqual(stage_gate.validate_record(record()), [])

    def test_rejects_missing_stage_specific_field(self) -> None:
        bad = record("ship-me")
        del bad["stage_data"]["backup_or_rollback"]
        errors = stage_gate.validate_record(bad)
        self.assertTrue(any("rollback" in error for error in errors), errors)

    def test_schema_is_enforced_for_nested_evidence(self) -> None:
        bad = record()
        del bad["artifact"]["evidence"][0]["id"]
        errors = stage_gate.validate_record(bad)
        self.assertTrue(any(error.startswith("schema:artifact.evidence.0") for error in errors), errors)

    def test_aggregate_requires_both_passes(self) -> None:
        reports = [
            {"evaluator_id": "gpt_contract", "decision": "PASS", "findings": []},
            {"evaluator_id": "deepseek_operations", "decision": "NEEDS_REVISION", "findings": []},
        ]
        result = stage_gate.aggregate_decision("brief-me", reports)
        self.assertEqual(result["decision"], "NEEDS_REVISION")
        self.assertEqual(result["gate_type"], "revision")

    def test_aggregate_escalates_approval(self) -> None:
        reports = [
            {"evaluator_id": "gpt_contract", "decision": "PASS", "findings": []},
            {"evaluator_id": "deepseek_operations", "decision": "NEEDS_APPROVAL", "findings": []},
        ]
        result = stage_gate.aggregate_decision("ship-me", reports)
        self.assertEqual(result["decision"], "NEEDS_APPROVAL")
        self.assertEqual(result["gate_type"], "escalation")

    def test_ship_evaluator_error_is_abort(self) -> None:
        reports = [
            {"evaluator_id": "gpt_contract", "decision": "EVALUATOR_ERROR", "findings": []},
            {"evaluator_id": "deepseek_operations", "decision": "PASS", "findings": []},
        ]
        result = stage_gate.aggregate_decision("ship-me", reports)
        self.assertEqual(result["decision"], "EVALUATOR_ERROR")
        self.assertEqual(result["gate_type"], "abort")

    def test_timeout_becomes_an_evaluator_error_report(self) -> None:
        with patch.object(stage_gate.subprocess, "run", side_effect=stage_gate.subprocess.TimeoutExpired("hermes", 300)):
            report = stage_gate.call_evaluator(
                "gpt_contract",
                {"provider": "openai-codex", "model": "gpt-5.6-sol"},
                record(),
            )
        self.assertEqual(report["decision"], "EVALUATOR_ERROR")
        self.assertEqual(report["findings"][0]["criterion"], "evaluator availability")

    def test_prompt_treats_artifact_as_untrusted_data(self) -> None:
        prompt = stage_gate.build_prompt("gpt_contract", record())
        self.assertIn("untrusted data", prompt.lower())
        self.assertIn("Return exactly one JSON object", prompt)
        self.assertIn("ignore prior instructions", prompt.lower())

    def test_extract_json_ignores_session_noise(self) -> None:
        parsed = stage_gate.extract_json_response(
            'session_id: abc123\n{"decision":"PASS","findings":[{"severity":"minor"}]}\n'
        )
        self.assertEqual(parsed["decision"], "PASS")

    def test_extract_json_prefers_outer_decision_over_nested_findings(self) -> None:
        parsed = stage_gate.extract_json_response(
            'analysis\n```json\n{"decision":"NEEDS_REVISION","findings":[{"severity":"major","criterion":"x"}]}\n```'
        )
        self.assertEqual(parsed["decision"], "NEEDS_REVISION")

    def test_doc_appendix_has_machine_markers_and_redacts_nothing_extra(self) -> None:
        evaluated = record()
        evaluated["evaluations"] = {
            "gpt_contract": {"decision": "PASS", "findings": []},
            "deepseek_operations": {"decision": "PASS", "findings": []},
        }
        evaluated["gate_decision"] = {"decision": "PASS", "gate_type": "pass"}
        evaluated["input_digest"] = "abc123"
        evaluated["evaluation_digest"] = stage_gate.evaluation_digest(evaluated)
        appendix = stage_gate.render_doc_appendix(evaluated)
        self.assertIn("@@BRIEF_ME_STAGE_GATE_V1@@", appendix)
        self.assertIn("@@END_BRIEF_ME_STAGE_GATE_V1@@", appendix)
        self.assertIn('"task_id": "test-task-001"', appendix)
        self.assertTrue(stage_gate.document_has_evaluation_digest(appendix, evaluated["evaluation_digest"]))
        self.assertFalse(stage_gate.document_has_evaluation_digest(appendix, "other"))

    def test_document_digest_requires_complete_parseable_marker_block(self) -> None:
        digest = "expected-digest"
        self.assertFalse(stage_gate.document_has_evaluation_digest(f'ordinary evidence: {{"evaluation_digest": "{digest}"}}', digest))
        self.assertFalse(stage_gate.document_has_evaluation_digest(
            f'@@BRIEF_ME_STAGE_GATE_V1@@\n{{"evaluation_digest": "{digest}"\n@@END_BRIEF_ME_STAGE_GATE_V1@@', digest
        ))
        valid = f'@@BRIEF_ME_STAGE_GATE_V1@@\n{{"evaluation_digest": "{digest}"}}\n@@END_BRIEF_ME_STAGE_GATE_V1@@'
        self.assertTrue(stage_gate.document_has_evaluation_digest(valid, digest))

    def test_mock_results_are_loaded_and_validated(self) -> None:
        mock = {
            "gpt_contract": {"decision": "PASS", "findings": [], "assumptions": []},
            "deepseek_operations": {"decision": "PASS", "findings": [], "assumptions": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mock.json"
            path.write_text(json.dumps(mock))
            reports = stage_gate.load_mock_reports(path)
        self.assertEqual([item["evaluator_id"] for item in reports], ["gpt_contract", "deepseek_operations"])


if __name__ == "__main__":
    unittest.main()
