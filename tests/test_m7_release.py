"""M7 release-evidence contract tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from elly.evaluation import catalog, run_release_evidence


class M7ReleaseEvidenceTests(unittest.TestCase):
    def test_catalog_is_exactly_thirty_cases(self):
        cases = catalog()
        self.assertEqual(30, len(cases))
        self.assertEqual("EVAL-001", cases[0].case_id)
        self.assertEqual("EVAL-030", cases[-1].case_id)

    def test_report_pins_every_case_and_does_not_fake_release(self):
        report = run_release_evidence(
            regression_status="pass", hardware_status="pass",
            recorded_at=__import__("datetime").datetime(2026, 8, 4, tzinfo=__import__("datetime").timezone.utc),
        )
        self.assertEqual(30, len(report.records))
        self.assertTrue(all(record.model_id == "qwen3:8b" for record in report.records))
        self.assertEqual("pass", report.deterministic_gate)
        self.assertEqual("pending", report.quality_gate)
        self.assertEqual("pass", report.hardware_gate)
        self.assertFalse(report.releasable)

    def test_report_serializes_pinned_metadata(self):
        report = run_release_evidence()
        with TemporaryDirectory() as directory:
            path = f"{directory}/evidence.json"
            report.write_json(path)
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(30, len(document["records"]))
        self.assertIn("fixture_version", document["records"][0])
        self.assertIn("prompt_version", document["records"][0])

    def test_report_defaults_cannot_claim_unrun_gates_passed(self):
        report = run_release_evidence()
        self.assertEqual("pending", report.deterministic_gate)
        self.assertEqual("pending", report.hardware_gate)
        self.assertFalse(report.releasable)

    def test_hosted_path_exceptions_are_not_mislabeled_as_test_coverage(self):
        report = run_release_evidence(regression_status="pass")
        records = {record.case_id: record for record in report.records}
        for case_id in ("EVAL-024", "EVAL-025"):
            self.assertEqual("approved_exception", records[case_id].evidence_class)
            self.assertEqual("pending", records[case_id].status)


if __name__ == "__main__":
    unittest.main()
