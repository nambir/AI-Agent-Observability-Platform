import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import ObservabilityStore, estimated_cost


class ObservabilityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ObservabilityStore(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def payload(self, **overrides):
        value = {"agentName": "test-agent", "traceId": "trace-1", "latencyMs": 100, "inputTokens": 100, "outputTokens": 50}
        value.update(overrides)
        return value

    def test_calculates_cost(self):
        self.assertEqual(estimated_cost(1_000_000, 1_000_000), 2.0)

    def test_high_risk_tool_creates_pending_approval(self):
        result = self.store.ingest_run(self.payload(toolName="issue_refund", riskLevel="high"))
        self.assertIsNotNone(result["approvalId"])
        self.assertEqual(self.store.approvals()[0]["status"], "pending")

    def test_pii_prevents_preview_persistence(self):
        result = self.store.ingest_run(self.payload(containsPii=True, promptPreview="private", responsePreview="private"))
        run = self.store.run(result["id"])
        self.assertIsNone(run["prompt_preview"])
        self.assertIsNone(run["response_preview"])

    def test_decision_creates_audit_event(self):
        result = self.store.ingest_run(self.payload(toolName="issue_refund", riskLevel="critical"))
        approval = self.store.decide_approval(result["approvalId"], "approved", "reviewer", "Verified account")
        self.assertEqual(approval["status"], "approved")
        self.assertEqual(self.store.audit()[0]["event_type"], "approval.approved")
        run = self.store.run(result["id"])
        self.assertEqual(run["status"], "completed")

    def test_reject_does_not_execute_and_marks_failed(self):
        result = self.store.ingest_run(self.payload(toolName="issue_refund", riskLevel="high", status="pending_approval"))
        self.store.decide_approval(result["approvalId"], "rejected", "reviewer", "Wrong account")
        run = self.store.run(result["id"])
        self.assertEqual(run["status"], "failed")
        self.assertIn("not executed", run["error_message"])
