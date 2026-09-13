import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


VALID_STATUSES = {"completed", "failed", "running", "pending_approval"}
VALID_RISKS = {"low", "medium", "high", "critical"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def estimated_cost(input_tokens, output_tokens):
    """Demo pricing: $0.40/M input tokens and $1.60/M output tokens."""
    return round((input_tokens * 0.40 + output_tokens * 1.60) / 1_000_000, 6)


class ObservabilityStore:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._create_schema()

    def _create_schema(self):
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_run_id TEXT,
          agent_name TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
          status TEXT NOT NULL, latency_ms INTEGER NOT NULL, input_tokens INTEGER NOT NULL,
          output_tokens INTEGER NOT NULL, estimated_cost_usd REAL NOT NULL,
          tool_name TEXT, risk_level TEXT NOT NULL, contains_pii INTEGER NOT NULL,
          prompt_preview TEXT, response_preview TEXT, error_message TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tool_name TEXT NOT NULL,
          risk_level TEXT NOT NULL, status TEXT NOT NULL, decided_by TEXT,
          decision_note TEXT, created_at TEXT NOT NULL, decided_at TEXT,
          FOREIGN KEY(run_id) REFERENCES runs(id)
        );
        CREATE TABLE IF NOT EXISTS audit_events (
          id TEXT PRIMARY KEY, event_type TEXT NOT NULL, entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL, actor TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        self.connection.commit()

    def _audit(self, event_type, entity_type, entity_id, actor, details):
        self.connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), event_type, entity_type, entity_id, actor, json.dumps(details), utc_now()),
        )

    def ingest_run(self, payload, actor="agent-sdk"):
        with self._lock:
            return self._ingest_run(payload, actor)

    def _ingest_run(self, payload, actor="agent-sdk"):
        status = payload.get("status", "completed")
        risk = payload.get("riskLevel", "low")
        if status not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        if risk not in VALID_RISKS:
            raise ValueError(f"riskLevel must be one of: {', '.join(sorted(VALID_RISKS))}")
        required = ["agentName", "traceId"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError("Missing required fields: " + ", ".join(missing))
        latency = int(payload.get("latencyMs", 0))
        input_tokens = int(payload.get("inputTokens", 0))
        output_tokens = int(payload.get("outputTokens", 0))
        if min(latency, input_tokens, output_tokens) < 0:
            raise ValueError("latencyMs and token values must be non-negative")
        run_id = str(uuid.uuid4())
        pii = bool(payload.get("containsPii", False))
        tool = payload.get("toolName")
        self.connection.execute(
            """INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, payload["traceId"], payload.get("parentRunId"), payload["agentName"],
             payload.get("model", "unknown"), payload.get("promptVersion", "unversioned"), status,
             latency, input_tokens, output_tokens, estimated_cost(input_tokens, output_tokens), tool, risk,
             int(pii), None if pii else payload.get("promptPreview"), None if pii else payload.get("responsePreview"),
             payload.get("errorMessage"), utc_now()),
        )
        approval_id = None
        if tool and risk in {"high", "critical"}:
            approval_id = str(uuid.uuid4())
            self.connection.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, 'pending', NULL, NULL, ?, NULL)",
                (approval_id, run_id, tool, risk, utc_now()),
            )
        self._audit("run.ingested", "run", run_id, actor, {"riskLevel": risk, "containsPii": pii, "approvalId": approval_id})
        self.connection.commit()
        return {"id": run_id, "approvalId": approval_id}

    def metrics(self):
        with self._lock:
            return self._metrics()

    def _metrics(self):
        row = self.connection.execute("""
          SELECT COUNT(*) AS run_count,
                 COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
                 COALESCE(ROUND(AVG(latency_ms), 1), 0) AS avg_latency_ms,
                 COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens,
                 COALESCE(ROUND(SUM(estimated_cost_usd), 4), 0) AS cost
          FROM runs
        """).fetchone()
        return {"runs": row["run_count"], "failures": row["failed_count"], "failureRate": round((row["failed_count"] / row["run_count"] * 100) if row["run_count"] else 0, 1), "averageLatencyMs": row["avg_latency_ms"], "tokens": row["tokens"], "estimatedCostUsd": row["cost"], "pendingApprovals": self.connection.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0]}

    def runs(self, limit=50):
        with self._lock:
            return [dict(row) for row in self.connection.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

    def run(self, run_id):
        with self._lock:
            return self._run(run_id)

    def _run(self, run_id):
        row = self.connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["trace"] = [dict(item) for item in self.connection.execute("SELECT * FROM runs WHERE trace_id = ? ORDER BY created_at", (row["trace_id"],)).fetchall()]
        return result

    def approvals(self):
        with self._lock:
            return [dict(row) for row in self.connection.execute("""
          SELECT approvals.*, runs.agent_name, runs.trace_id FROM approvals
          JOIN runs ON runs.id = approvals.run_id ORDER BY approvals.created_at DESC
        """).fetchall()]

    def decide_approval(self, approval_id, decision, actor, note=""):
        with self._lock:
            if decision not in {"approved", "rejected"}:
                raise ValueError("decision must be approved or rejected")
            existing = self.connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if not existing:
                return None
            if existing["status"] != "pending":
                raise ValueError("approval has already been decided")
            decided_at = utc_now()
            self.connection.execute(
                "UPDATE approvals SET status = ?, decided_by = ?, decision_note = ?, decided_at = ? WHERE id = ?",
                (decision, actor or "dashboard-user", note, decided_at, approval_id),
            )
            # A decision is not tool execution. It only updates the recorded run state.
            next_status = "completed" if decision == "approved" else "failed"
            error = None if decision == "approved" else "Approval rejected. Tool was not executed."
            self.connection.execute(
                "UPDATE runs SET status = ?, error_message = COALESCE(?, error_message) WHERE id = ?",
                (next_status, error, existing["run_id"]),
            )
            self._audit("approval." + decision, "approval", approval_id, actor or "dashboard-user", {"runId": existing["run_id"], "note": note})
            self.connection.commit()
            return dict(self.connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone())

    def audit(self):
        with self._lock:
            return [dict(row) for row in self.connection.execute("SELECT * FROM audit_events ORDER BY rowid DESC LIMIT 100").fetchall()]

    def close(self):
        self.connection.close()

    def seed_if_empty(self):
        with self._lock:
            if self.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]:
                return
            parent = self._ingest_run({"agentName": "claims-assistant", "traceId": "trace-claims-001", "model": "gpt-4.1-mini", "promptVersion": "claims-v4", "status": "completed", "latencyMs": 780, "inputTokens": 430, "outputTokens": 115, "toolName": "policy_search", "riskLevel": "low", "promptPreview": "Find policy exclusions", "responsePreview": "Two exclusions found."}, "demo-seed")
            self._ingest_run({"agentName": "policy-search-tool", "traceId": "trace-claims-001", "parentRunId": parent["id"], "model": "gpt-4.1-mini", "promptVersion": "claims-v4", "status": "completed", "latencyMs": 210, "inputTokens": 80, "outputTokens": 40, "toolName": "policy_search", "riskLevel": "low"}, "demo-seed")
            self._ingest_run({"agentName": "payment-support", "traceId": "trace-payments-019", "model": "gpt-4.1-mini", "promptVersion": "payments-v2", "status": "pending_approval", "latencyMs": 230, "inputTokens": 178, "outputTokens": 42, "toolName": "issue_refund", "riskLevel": "high", "containsPii": True, "promptPreview": "Refund card ****4242", "responsePreview": "Proposed refund $48.00"}, "demo-seed")
            self._ingest_run({"agentName": "invoice-triage", "traceId": "trace-invoice-103", "model": "gpt-4.1-mini", "promptVersion": "invoice-v1", "status": "failed", "latencyMs": 1450, "inputTokens": 650, "outputTokens": 0, "toolName": "document_lookup", "riskLevel": "medium", "errorMessage": "Upstream document provider timed out."}, "demo-seed")
