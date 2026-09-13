import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from service import ObservabilityStore

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "apps" / "web"
DATABASE = Path(os.getenv("OBSERVABILITY_DB", str(ROOT / "data" / "observability.db")))
store = ObservabilityStore(DATABASE)
store.seed_if_empty()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def send_json(self, status, body):
        encoded = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_body(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self.send_json(HTTPStatus.OK, {"status": "ok"})
        if path == "/api/v1/metrics":
            return self.send_json(HTTPStatus.OK, store.metrics())
        if path == "/api/v1/runs":
            return self.send_json(HTTPStatus.OK, {"items": store.runs()})
        if path.startswith("/api/v1/runs/"):
            value = store.run(path.rsplit("/", 1)[-1])
            return self.send_json(HTTPStatus.OK if value else HTTPStatus.NOT_FOUND, value or {"error": "run not found"})
        if path == "/api/v1/approvals":
            return self.send_json(HTTPStatus.OK, {"items": store.approvals()})
        if path == "/api/v1/audit":
            return self.send_json(HTTPStatus.OK, {"items": store.audit()})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            body = self.read_body()
            if path == "/api/v1/runs":
                return self.send_json(HTTPStatus.CREATED, store.ingest_run(body, self.headers.get("X-Actor", "agent-sdk")))
            if path.startswith("/api/v1/approvals/") and path.endswith("/decision"):
                approval_id = path.split("/")[-2]
                value = store.decide_approval(approval_id, body.get("decision"), body.get("actor", "dashboard-user"), body.get("note", ""))
                return self.send_json(HTTPStatus.OK if value else HTTPStatus.NOT_FOUND, value or {"error": "approval not found"})
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})


if __name__ == "__main__":
    host = os.getenv("OBSERVABILITY_HOST", "127.0.0.1")
    port = int(os.getenv("OBSERVABILITY_PORT", "8300"))
    print(f"AI Agent Observability Platform listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
