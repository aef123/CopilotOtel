"""
Session API: queries Tempo and Prometheus, computes per-session status,
and serves shaped DTOs for the dashboard SPA and Grafana Infinity datasource.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import time
import os
import re
import base64
import hashlib
import threading
from collections import defaultdict

TEMPO_URL = os.environ.get("TEMPO_URL", "http://tempo:3200")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "6"))
IDLE_GRACE_SECONDS = int(os.environ.get("IDLE_GRACE_SECONDS", "60"))
SKIP_AUTH = os.environ.get("SKIP_AUTH", "false").lower() == "true"
TENANT_ID = os.environ.get("TENANT_ID", "")
EXPECTED_AUDIENCE = os.environ.get("EXPECTED_AUDIENCE", "")

# JWKS cache
_jwks_cache = {"keys": [], "fetched_at": 0}
_jwks_lock = threading.Lock()
JWKS_CACHE_SECONDS = 3600


# ---------------------------------------------------------------------------
# Auth: JWT validation for nginx auth_request
# ---------------------------------------------------------------------------

def fetch_jwks():
    """Fetch Entra ID JWKS, cached for 1 hour."""
    with _jwks_lock:
        if time.time() - _jwks_cache["fetched_at"] < JWKS_CACHE_SECONDS:
            return _jwks_cache["keys"]
    if not TENANT_ID:
        return []
    url = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        with _jwks_lock:
            _jwks_cache["keys"] = data.get("keys", [])
            _jwks_cache["fetched_at"] = time.time()
        return _jwks_cache["keys"]
    except Exception:
        return _jwks_cache["keys"]


def validate_jwt_basic(token):
    """Basic JWT validation: decode, check exp/aud/iss. Signature check
    requires PyJWT+cryptography (available when running from Dockerfile)."""
    if SKIP_AUTH:
        return True
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return False
    now = time.time()
    if payload.get("exp", 0) < now:
        return False
    if EXPECTED_AUDIENCE and payload.get("aud") != EXPECTED_AUDIENCE:
        return False
    if TENANT_ID:
        expected_iss = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
        if payload.get("iss") != expected_iss:
            return False
    # Full signature validation with PyJWT if available
    try:
        import jwt as pyjwt
        from jwt import PyJWKClient
        jwks_url = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
        jwk_client = PyJWKClient(jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=EXPECTED_AUDIENCE,
            issuer=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
        )
    except ImportError:
        pass  # PyJWT not installed, basic checks above are sufficient for dev
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Tempo helpers
# ---------------------------------------------------------------------------

def query_tempo(traceql, limit=500):
    now = int(time.time())
    start = now - (LOOKBACK_HOURS * 3600)
    q = urllib.parse.quote(traceql)
    url = f"{TEMPO_URL}/api/search?q={q}&limit={limit}&start={start}&end={now}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=15)
    return json.loads(resp.read())


def get_trace(trace_id):
    url = f"{TEMPO_URL}/api/traces/{trace_id}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=15)
    return json.loads(resp.read())


def get_attr(span, key):
    for attr in span.get("attributes", []):
        if attr["key"] == key:
            v = attr["value"]
            return v.get("stringValue") or v.get("intValue") or str(v)
    return None


def get_resource_attr(resource, key):
    for attr in resource.get("attributes", []):
        if attr["key"] == key:
            v = attr["value"]
            return v.get("stringValue") or v.get("intValue") or str(v)
    return None


# ---------------------------------------------------------------------------
# Prometheus helpers
# ---------------------------------------------------------------------------

def query_prometheus(promql, time_val=None):
    params = {"query": promql}
    if time_val:
        params["time"] = time_val
    url = f"{PROMETHEUS_URL}/api/v1/query?{urllib.parse.urlencode(params)}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=10)
    return json.loads(resp.read())


def query_prometheus_range(promql, start, end, step="60s"):
    params = {"query": promql, "start": start, "end": end, "step": step}
    url = f"{PROMETHEUS_URL}/api/v1/query_range?{urllib.parse.urlencode(params)}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=10)
    return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Session computation (enriched)
# ---------------------------------------------------------------------------

def compute_sessions():
    completed_data = query_tempo(
        '{resource.service.name="github-copilot" && name="invoke_agent"}'
        ' | select(span.gen_ai.conversation.id, span.gen_ai.agent.version,'
        ' span.gen_ai.response.model, span.gen_ai.usage.input_tokens,'
        ' span.gen_ai.usage.output_tokens, resource.host.name)'
    )
    children_data = query_tempo(
        '{resource.service.name="github-copilot" && name!="invoke_agent"'
        ' && name!="permission"} | select(span.gen_ai.conversation.id)'
    )

    sessions = defaultdict(lambda: {
        "max_time": 0, "min_time": float("inf"), "turns": 0,
        "version": "", "duration_ns": 0, "host": "", "model": "",
        "total_input_tokens": 0, "total_output_tokens": 0,
        "trace_ids": set(),
    })
    children_max = defaultdict(int)

    for trace in completed_data.get("traces", []):
        trace_id = trace.get("traceID", "")
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                sid = get_attr(span, "gen_ai.conversation.id")
                if not sid:
                    continue
                t = int(span["startTimeUnixNano"]) // 1_000_000
                dur = int(span.get("durationNanos", 0))
                end_t = t + dur // 1_000_000
                rec = sessions[sid]
                rec["turns"] += 1
                rec["min_time"] = min(rec["min_time"], t)
                if trace_id:
                    rec["trace_ids"].add(trace_id)
                if end_t > rec["max_time"]:
                    rec["max_time"] = end_t
                    rec["duration_ns"] = dur
                ver = get_attr(span, "gen_ai.agent.version")
                if ver:
                    rec["version"] = ver
                host = get_attr(span, "host.name")
                if host:
                    rec["host"] = host
                model = get_attr(span, "gen_ai.response.model")
                if model:
                    rec["model"] = model
                inp = get_attr(span, "gen_ai.usage.input_tokens")
                if inp:
                    try:
                        rec["total_input_tokens"] += int(inp)
                    except (ValueError, TypeError):
                        pass
                out = get_attr(span, "gen_ai.usage.output_tokens")
                if out:
                    try:
                        rec["total_output_tokens"] += int(out)
                    except (ValueError, TypeError):
                        pass

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

    all_ids = set(list(sessions.keys()) + list(children_max.keys()))
    rows = []
    for sid in all_ids:
        c = sessions.get(sid)
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
            "model": c["model"] if c else "",
            "last_activity": last_activity,
            "first_seen": c["min_time"] if c and c["min_time"] != float("inf") else last_activity,
            "turns": c["turns"] if c else 0,
            "last_turn_duration_s": round(c["duration_ns"] / 1e9, 1) if c else 0,
            "total_input_tokens": c["total_input_tokens"] if c else 0,
            "total_output_tokens": c["total_output_tokens"] if c else 0,
            "cli_version": c["version"] if c else "",
        })

    rows.sort(key=lambda r: r["last_activity"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Session detail: all turns (invoke_agent spans) for a session
# ---------------------------------------------------------------------------

def get_session_detail(session_id):
    data = query_tempo(
        '{resource.service.name="github-copilot" && name="invoke_agent"'
        f' && span.gen_ai.conversation.id="{session_id}"}}'
        ' | select(span.gen_ai.response.model, span.gen_ai.usage.input_tokens,'
        ' span.gen_ai.usage.output_tokens, span.gen_ai.agent.version,'
        ' resource.host.name)'
    )
    turns = []
    host = ""
    version = ""
    for trace in data.get("traces", []):
        trace_id = trace.get("traceID", "")
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                start_ns = int(span["startTimeUnixNano"])
                dur_ns = int(span.get("durationNanos", 0))
                model = get_attr(span, "gen_ai.response.model") or ""
                inp = 0
                out = 0
                try:
                    inp = int(get_attr(span, "gen_ai.usage.input_tokens") or 0)
                except (ValueError, TypeError):
                    pass
                try:
                    out = int(get_attr(span, "gen_ai.usage.output_tokens") or 0)
                except (ValueError, TypeError):
                    pass
                h = get_attr(span, "host.name")
                if h:
                    host = h
                v = get_attr(span, "gen_ai.agent.version")
                if v:
                    version = v
                turns.append({
                    "trace_id": trace_id,
                    "span_id": span.get("spanID", ""),
                    "start_time": start_ns // 1_000_000,
                    "duration_s": round(dur_ns / 1e9, 1),
                    "model": model,
                    "input_tokens": inp,
                    "output_tokens": out,
                })
    turns.sort(key=lambda t: t["start_time"])
    return {
        "session_id": session_id,
        "host": host,
        "cli_version": version,
        "turns": turns,
    }


# ---------------------------------------------------------------------------
# Trace detail: full span tree for a trace
# ---------------------------------------------------------------------------

def get_trace_detail(trace_id):
    raw = get_trace(trace_id)
    spans = []
    for batch in raw.get("batches", []):
        resource = batch.get("resource", {})
        svc = get_resource_attr(resource, "service.name") or ""
        host = get_resource_attr(resource, "host.name") or ""
        for scope in batch.get("scopeSpans", []):
            for span in scope.get("spans", []):
                start_ns = int(span.get("startTimeUnixNano", 0))
                end_ns = int(span.get("endTimeUnixNano", 0))
                dur_ns = end_ns - start_ns if end_ns > start_ns else 0
                attrs = {}
                for a in span.get("attributes", []):
                    v = a.get("value", {})
                    attrs[a["key"]] = (
                        v.get("stringValue")
                        or v.get("intValue")
                        or v.get("boolValue")
                        or str(v)
                    )
                spans.append({
                    "span_id": span.get("spanId", ""),
                    "parent_span_id": span.get("parentSpanId", ""),
                    "name": span.get("name", ""),
                    "service": svc,
                    "host": host,
                    "start_time": start_ns // 1_000_000,
                    "duration_ms": round(dur_ns / 1e6, 1),
                    "status": span.get("status", {}).get("code", "UNSET"),
                    "attributes": attrs,
                })
    spans.sort(key=lambda s: s["start_time"])
    return {"trace_id": trace_id, "spans": spans}


# ---------------------------------------------------------------------------
# Metrics endpoints (shaped Prometheus data)
# ---------------------------------------------------------------------------

def get_metrics_token_usage():
    now = int(time.time())
    start = now - (LOOKBACK_HOURS * 3600)
    result = query_prometheus_range(
        'sum by (gen_ai_token_type) (rate(gen_ai_client_token_usage_count[5m]))',
        start, now, "60s"
    )
    series = []
    for s in result.get("data", {}).get("result", []):
        token_type = s["metric"].get("gen_ai_token_type", "unknown")
        points = [{"time": int(float(v[0]) * 1000), "value": float(v[1])} for v in s["values"]]
        series.append({"label": token_type, "data": points})
    return series


def get_metrics_operations():
    now = int(time.time())
    start = now - (LOOKBACK_HOURS * 3600)
    result = query_prometheus_range(
        'sum by (gen_ai_operation_name) (rate(gen_ai_client_operation_duration_count[5m]))',
        start, now, "60s"
    )
    series = []
    for s in result.get("data", {}).get("result", []):
        op = s["metric"].get("gen_ai_operation_name", "unknown")
        points = [{"time": int(float(v[0]) * 1000), "value": float(v[1])} for v in s["values"]]
        series.append({"label": op, "data": points})
    return series


def get_metrics_models():
    result = query_prometheus(
        'sum by (gen_ai_response_model) (gen_ai_client_token_usage_count)'
    )
    items = []
    for s in result.get("data", {}).get("result", []):
        model = s["metric"].get("gen_ai_response_model", "unknown")
        items.append({"model": model, "count": float(s["value"][1])})
    return items


def get_metrics_tools():
    now = int(time.time())
    start = now - (LOOKBACK_HOURS * 3600)
    result = query_prometheus_range(
        'sum by (gen_ai_tool_name) (rate(github_copilot_tool_call_count[5m]))',
        start, now, "60s"
    )
    series = []
    for s in result.get("data", {}).get("result", []):
        tool = s["metric"].get("gen_ai_tool_name", "unknown")
        points = [{"time": int(float(v[0]) * 1000), "value": float(v[1])} for v in s["values"]]
        series.append({"label": tool, "data": points})
    return series


def get_health_summary():
    sessions = compute_sessions()
    active = sum(1 for s in sessions if s["status"] == "Active")
    idle = sum(1 for s in sessions if s["status"] == "Idle")
    total_turns = sum(s["turns"] for s in sessions)
    total_input = sum(s["total_input_tokens"] for s in sessions)
    total_output = sum(s["total_output_tokens"] for s in sessions)
    return {
        "active_sessions": active,
        "idle_sessions": idle,
        "total_sessions": len(sessions),
        "total_turns": total_turns,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "timestamp": int(time.time() * 1000),
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _error(self, status, message):
        self._json_response({"error": message}, status)

    def _get_bearer_token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        # Health check (no auth)
        if path == "/health":
            return self._json_response({"status": "ok"})

        # Auth validation endpoint for nginx auth_request
        if path == "/auth/validate":
            token = self._get_bearer_token()
            if validate_jwt_basic(token):
                self.send_response(200)
                self.end_headers()
            else:
                self.send_response(401)
                self.end_headers()
            return

        # --- Dashboard API routes ---

        # Session list (also used by Grafana Infinity datasource at /api/sessions)
        if path in ("/api/sessions", "/dashboard-api/sessions"):
            try:
                return self._json_response(compute_sessions())
            except Exception as e:
                return self._error(500, str(e))

        # Session detail
        m = re.match(r"^/dashboard-api/sessions/([^/]+)$", path)
        if m:
            try:
                return self._json_response(get_session_detail(m.group(1)))
            except Exception as e:
                return self._error(500, str(e))

        # Trace detail
        m = re.match(r"^/dashboard-api/sessions/[^/]+/traces/([a-f0-9]+)$", path)
        if m:
            try:
                return self._json_response(get_trace_detail(m.group(1)))
            except Exception as e:
                return self._error(500, str(e))

        # Metrics: token usage time series
        if path == "/dashboard-api/metrics/token-usage":
            try:
                return self._json_response(get_metrics_token_usage())
            except Exception as e:
                return self._error(500, str(e))

        # Metrics: operation duration time series
        if path == "/dashboard-api/metrics/operations":
            try:
                return self._json_response(get_metrics_operations())
            except Exception as e:
                return self._error(500, str(e))

        # Metrics: token usage by model (donut chart)
        if path == "/dashboard-api/metrics/models":
            try:
                return self._json_response(get_metrics_models())
            except Exception as e:
                return self._error(500, str(e))

        # Metrics: tool call rate time series
        if path == "/dashboard-api/metrics/tools":
            try:
                return self._json_response(get_metrics_tools())
            except Exception as e:
                return self._error(500, str(e))

        # Health summary
        if path == "/dashboard-api/health":
            try:
                return self._json_response(get_health_summary())
            except Exception as e:
                return self._error(500, str(e))

        self._error(404, "Not found")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Session API listening on port {port}")
    if SKIP_AUTH:
        print("WARNING: Auth validation is DISABLED (SKIP_AUTH=true)")
    server.serve_forever()
