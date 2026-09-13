# AI Agent Observability Platform

A control room for AI Agent runs. It records **what the AI Agent did**, **what it cost**, and **who approved** a high-risk tool.

**Simple example:** A customer in a food app writes “My order arrived cold. Refund me.” The AI Agent looks up the order and calls `issue_refund`. This app stores the run: model, prompt version, latency, tokens, and estimated cost. Because a refund spends money, it waits in an approval queue. A person approves or rejects it. The audit row stays. The customer never opens this site.

A lookup can finish on its own. A refund, an email, or a pay change does not run until a person decides. If the request contains personal data, the prompt preview is not stored.

Python standard library, SQLite, and a browser dashboard. It runs locally without API keys or a cloud account.

**What I built here:** run ingestion, trace view, cost and failure metrics, a high-risk approval queue, an append-only audit log, and a local dashboard.

---

## Where this fits

A shopping cart, a food app, a bank, or a clinic already has its own screens. The customer uses those. This app sits behind them, for the team that put an AI Agent on support chat.

You need it when that AI Agent can spend money, send mail, or change a customer record, and someone still has to explain later what it did, what it cost, and who said yes.

| Everyday app | What the customer says | What the AI Agent may do | Why this app is in the path |
|---|---|---|---|
| **Food delivery** | “My order arrived cold. Refund me.” | Look up the order, then call `issue_refund`. | The lookup is a trace. The refund waits for a person. Cost and prompt version stay on the run. |
| **Shopping cart** | “Where is my parcel? Email me the invoice.” | Track the order, then email a document. | Tracking can finish on its own. Emailing waits for approval. An address or card fragment is not stored. |
| **Banking** | “I don’t recognise this card charge.” | Pull the transaction, then reverse it. | A wrong reversal moves money. The decision and reviewer note stay in the audit feed. |
| **Travel booking** | “Cancel this flight and refund the fare.” | Read the booking, then cancel and refund. | A cancel cannot be undone. The queue holds it until someone approves or rejects it. |
| **Insurance** | “Pay this claim.” | Read the policy, then propose a payout. | The policy answer is a trace. The payout is high risk and needs a reviewer. |
| **Clinic** | “Email my visit summary to me.” | Find the appointment, then send the summary. | The summary is personal. The send waits, and the prompt preview is not kept. |
| **Payroll** | “Email my payslip” or “Change this salary.” | Read the record, then mail it or change pay. | Reading can be logged. Mailing or changing pay does not run until a person decides. |
| **Accounts payable** | “What is the retention rule for this invoice?” | Search the policy, or try to delete or change it. | A failed or slow lookup shows up as a trace. Delete or retention change waits for approval. |

**Food delivery, in one pass.** The customer stays in the food app. The AI Agent looks up the order and calls `issue_refund`. This dashboard stores the run: latency, tokens, estimated cost, model, and prompt version. Because a refund is high risk, it appears in the approval queue. A reviewer approves or rejects it. The audit row remains. The customer never opens this site.

**Shopping cart, in one pass.** “Where is my parcel?” is low risk. If the answer is slow or wrong, the trace is enough to see which prompt version failed. “Email me the invoice” is not low risk. That tool stays pending until someone decides, and personal data in the request is not saved.

## Who this is for

This is an internal operations app for people who run AI Agents at work. It is not a consumer product, and it is not the chat screen where an end customer talks to an AI Agent.

| Role | Why they open it |
|---|---|
| **AI engineer** | See which AI Agent, model, and prompt version failed, how long it took, which tool it called, and what it cost. |
| **Full stack developer** | Post run telemetry from the AI Agent or its SDK (`POST /api/v1/runs`) and confirm traces, approvals, and audit records landed. |
| **Product owner** | Watch failure rate, latency, and estimated spend, and decide whether a high-risk tool (refund, email, salary change, payout) should be allowed. |
| **Business analyst** | Read the approval queue and audit feed: who requested a high-risk action, who approved or rejected it, and why. |

A consumer never signs in here. Their refund, email, or payroll change is the *action an AI Agent tried to take*. This app is the control room that records that attempt and requires a person to approve or reject it.

## The problems this solves

| Problem | What goes wrong | What this does |
|---|---|---|
| **AI Agent failures and cost are invisible** | An AI Agent gives a poor answer, times out, or becomes expensive—but the team cannot connect the failure to its prompt version, model, tool call, latency, token use, or trace. Debugging becomes guesswork. | Every run records its trace ID, AI Agent, model, prompt version, tool, status, latency, tokens, estimated cost, and error. The dashboard turns this into a trace explorer and operating metrics. |
| **High-risk AI Agent tools need human accountability** | An AI Agent can attempt an irreversible action such as issuing a refund, sending an email, or changing customer data, with no reviewable decision trail. This creates security, compliance, and trust risk. | High- and critical-risk tool calls automatically enter an approval queue. An approve/reject decision, reviewer, note, and audit event are retained for review. |

Seeded data includes a failed `invoice-triage` run and a pending `issue_refund` approval so you can click through traces, cost, and the audit trail without sending a request first.

## What it does

- Ingests AI Agent runs with model, prompt version, token, latency, tool-call, and error metadata
- Groups related work by trace ID and renders parent/child spans
- Calculates run volume, failure rate, average latency, token use, and estimated cost
- Creates approval records for `high` / `critical` risk actions
- Captures an append-only audit record for ingestion and approval decisions
- Avoids storing raw prompt/response text when a run is marked as containing PII

```text
AI Agent / SDK
    │ POST run telemetry
    ▼
Ingestion API ──► SQLite (runs, spans, approvals, audit)
    │                         │
    └─────────────────────────┴──► Dashboard / trace explorer / approval queue
```

## Demo screens and workflow

The screenshots use sample telemetry seeded on first run.

### 1. Operations dashboard

The dashboard provides a quick operational view: volume, failure rate, latency, estimated model cost, recent traces, pending approvals, and audit activity. Seeded rows include a failed `invoice-triage` run and a parent/child claims trace.

![AI Agent Observatory operations dashboard](docs/screenshots/01-dashboard-mock.png)

### 2. High-risk action review

When an AI Agent requests a high- or critical-risk tool, the platform creates a pending approval. A reviewer can approve or reject it; either outcome is written to the audit feed. A decision updates the recorded run status. It does not execute the tool.

![High-risk approval and trace workflow](docs/screenshots/02-approval-mock.png)

### Event flow

```mermaid
sequenceDiagram
    participant A as AI Agent / SDK
    participant I as Ingestion API
    participant S as Telemetry store
    participant D as Dashboard
    participant H as Human reviewer

    A->>I: POST run, tokens, latency, tool, risk
    I->>S: Persist run and append audit event
    alt Low or medium risk
        S-->>D: Trace and metrics available
    else High or critical risk tool
        I->>S: Create pending approval
        S-->>D: Show approval queue item
        H->>I: Approve or reject with note
        I->>S: Record immutable decision audit event
        S-->>D: Update approval and audit panels
    end
```

## Run locally

Requires Python 3.11+.

```powershell
cd "AI-Agent-Observability-Platform"
python apps/api/main.py
```

Open http://127.0.0.1:8300. The first run creates a local SQLite database and sample telemetry.

Docker (dashboard is included; the process listens on `0.0.0.0` inside the container):

```powershell
docker compose up --build
```

## API examples

Create a low-risk completed run:

```powershell
$body = @{
  agentName = "support-ai"
  traceId = "trace-support-104"
  model = "gpt-4.1-mini"
  promptVersion = "support-v3"
  status = "completed"
  latencyMs = 842
  inputTokens = 320
  outputTokens = 96
  toolName = "knowledge_search"
  riskLevel = "low"
  containsPii = $false
} | ConvertTo-Json

Invoke-RestMethod http://127.0.0.1:8300/api/v1/runs -Method Post -ContentType 'application/json' -Body $body
```

High-risk input creates a pending approval automatically:

```json
{
  "agentName": "claims-ai",
  "traceId": "trace-claims-7",
  "status": "pending_approval",
  "toolName": "issue_refund",
  "riskLevel": "high",
  "latencyMs": 210,
  "inputTokens": 120,
  "outputTokens": 30
}
```

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/metrics` | Operations dashboard metrics |
| `GET /api/v1/runs` | Recent AI Agent runs |
| `GET /api/v1/runs/{id}` | Run plus trace spans |
| `POST /api/v1/runs` | Ingest a run |
| `GET /api/v1/approvals` | Pending and decided approval records |
| `POST /api/v1/approvals/{id}/decision` | Record approve/reject decision |
| `GET /api/v1/audit` | Immutable audit feed |

## Tests

```powershell
cd apps/api
python -m unittest discover -s tests -v
```

Tests cover cost calculation, PII-safe persistence, high-risk approval generation, and approval audit records.

## Further work

OpenTelemetry collectors, Postgres/ClickHouse for telemetry, Redis/Kafka for asynchronous ingestion, object storage for approved redacted payloads, and an identity provider. Audit events stay separate from observability data so retention policies can differ.

## Safety notes

- This service never executes tools. It records telemetry supplied by the AI Agent.
- `containsPii: true` prevents raw prompt/response previews from being persisted.
- An approval decision is an auditable control, not proof that a tool execution succeeded.
- Sample data is synthetic.
