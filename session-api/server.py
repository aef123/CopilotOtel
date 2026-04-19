"""
Lightweight API that queries Tempo and computes per-session active/idle status.
Grafana's Infinity datasource queries this endpoint.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import time
import os
from collections import defaultdict

TEMPO_URL = os.environ.get("TEMPO_URL", "http://tempo:3200")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "6"))
IDLE_GRACE_SECONDS = int(os.environ.get("IDLE_GRACE_SECONDS", "60"))


def query_tempo(traceql, limit=200):
    now = int(time.time())
    start = now - (LOOKBACK_HOURS * 3600)
    q = urllib.parse.quote(traceql)
    url = f"{TEMPO_URL}/api/search?q={q}&limit={limit}&start={start}&end={now}"
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())


def get_attr(span, key):
    for attr in span.get("attributes", []):
        if attr["key"] == key:
            v = attr["value"]
            return v.get("stringValue") or v.get("intValue") or str(v)
    return None


def compute_sessions():
    completed_data = query_tempo(
        '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id, span.gen_ai.agent.version, resource.host.name)'
    )
    children_data = query_tempo(
        '{resource.service.name="github-copilot" && name!="invoke_agent" && name!="permission"} | select(span.gen_ai.conversation.id)'
    )

    completed = defaultdict(lambda: {"max_time": 0, "turns": 0, "version": "", "duration_ns": 0, "host": ""})
    children_max = defaultdict(int)

    for trace in completed_data.get("traces", []):
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                sid = get_attr(span, "gen_ai.conversation.id")
                if not sid:
                    continue
                t = int(span["startTimeUnixNano"]) // 1_000_000
                dur = int(span.get("durationNanos", 0))
                end_t = t + dur // 1_000_000
                rec = completed[sid]
                rec["turns"] += 1
                if end_t > rec["max_time"]:
                    rec["max_time"] = end_t
                    rec["duration_ns"] = dur
                ver = get_attr(span, "gen_ai.agent.version")
                if ver:
                    rec["version"] = ver
                host = get_attr(span, "host.name")
                if host:
                    rec["host"] = host

    for trace in children_data.get("traces", []):
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                sid = get_attr(span, "gen_ai.conversation.id")
                if not sid:
                    continue
                t = int(span["startTimeUnixNano"]) // 1_000_000
                dur = int(span.get("durationNanos", 0))
                end_t = t + dur // 1_000_000
                children_max[sid] = max(children_max[sid], end_t)

    all_sessions = set(list(completed.keys()) + list(children_max.keys()))
    rows = []
    for sid in all_sessions:
        c = completed.get(sid)
        c_time = c["max_time"] if c else 0
        a_time = children_max.get(sid, 0)
        last_activity = max(c_time, a_time)

        now_ms = int(time.time() * 1000)
        age_s = (now_ms - last_activity) / 1000 if last_activity > 0 else float("inf")

        if a_time > c_time and a_time > 0:
            status = "Active"
        elif last_activity > 0 and age_s < IDLE_GRACE_SECONDS:
            status = "Active"
        elif c_time > 0:
            status = "Idle"
        else:
            status = "Unknown"

        rows.append({
            "session_id": sid,
            "status": status,
            "host": c["host"] if c else "",
            "last_activity": last_activity,
            "turns": c["turns"] if c else 0,
            "last_turn_duration_s": round(c["duration_ns"] / 1e9, 1) if c else 0,
            "cli_version": c["version"] if c else "",
        })

    rows.sort(key=lambda r: r["last_activity"], reverse=True)
    return rows


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path == "/api/sessions":
            try:
                rows = compute_sessions()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(rows).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Session API listening on port {port}")
    server.serve_forever()
