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
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))
WATCHER_FRESHNESS_SECONDS = int(os.environ.get("WATCHER_FRESHNESS_SECONDS", "300"))
IDLE_TIMEOUT_SECONDS = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "300"))  # 5 minutes
SKIP_AUTH = os.environ.get("SKIP_AUTH", "false").lower() == "true"
TENANT_ID = os.environ.get("TENANT_ID", "")
EXPECTED_AUDIENCE = os.environ.get("EXPECTED_AUDIENCE", "")

LOOKBACK_MAP = {
    "6h": 6, "12h": 12, "24h": 24, "2d": 48, "7d": 168,
}


def parse_lookback(qs):
    """Parse ?lookback=6h|12h|24h|2d|7d from query string, return hours."""
    params = urllib.parse.parse_qs(qs)
    val = params.get("lookback", [""])[0]
    return LOOKBACK_MAP.get(val, LOOKBACK_HOURS)

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
        expected_issuers = [
            f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
            f"https://sts.windows.net/{TENANT_ID}/",
        ]
        if payload.get("iss") not in expected_issuers:
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
            options={"verify_iss": False},
        )
    except ImportError:
        pass  # PyJWT not installed, basic checks above are sufficient for dev
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Tempo helpers
# ---------------------------------------------------------------------------

def query_tempo(traceql, limit=500, lookback_hours=None):
    lh = lookback_hours or LOOKBACK_HOURS
    now = int(time.time())
    start = now - (lh * 3600)
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
# Loki helpers
# ---------------------------------------------------------------------------

def query_loki_range(logql, start_ns, end_ns, limit=5000):
    params = {
        "query": logql,
        "start": str(start_ns),
        "end": str(end_ns),
        "limit": str(limit),
        "direction": "backward",
    }
    url = f"{LOKI_URL}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=15)
    return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Watcher state: latest per (host, session, epoch) from Loki
# ---------------------------------------------------------------------------

def get_watcher_state():
    """Return the current live + orphan sessions known to the watcher daemon.

    Reads recent heartbeat / state_transition log records from
    service_name=copilot-session-watcher in Loki, groups by
    (host_name, session_id, session_epoch), keeps the newest per group, and
    drops anything whose latest state is `ended`."""
    now_ns = int(time.time() * 1_000_000_000)
    start_ns = now_ns - WATCHER_FRESHNESS_SECONDS * 1_000_000_000
    try:
        data = query_loki_range(
            '{service_name="copilot-session-watcher"}',
            start_ns, now_ns, limit=5000)
    except Exception as e:
        return {
            "sessions": [],
            "queriedAt": _iso(now_ns),
            "freshnessWindowSeconds": WATCHER_FRESHNESS_SECONDS,
            "error": str(e),
        }

    latest = {}  # (host, sid, epoch) -> {ts_ns, stream-labels}
    for stream in data.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        sid = labels.get("session_id")
        if not sid:
            continue
        host = labels.get("host_name", "")
        epoch = labels.get("session_epoch", "1")
        try:
            epoch_i = int(epoch)
        except ValueError:
            epoch_i = 1
        key = (host, sid, epoch_i)
        for ts_str, _line in stream.get("values", []):
            try:
                ts_ns = int(ts_str)
            except ValueError:
                continue
            prev = latest.get(key)
            if prev is None or ts_ns > prev["ts_ns"]:
                latest[key] = {"ts_ns": ts_ns, "labels": labels}

    sessions = []
    for (host, sid, epoch), rec in latest.items():
        labels = rec["labels"]
        state = (labels.get("state_current") or "").lower()
        if state == "ended":
            continue
        # For closed sessions, use closed_at (when it transitioned to closed), not last observation time
        last_obs_iso = labels.get("closed_at") if state == "closed" else None
        last_activity = _iso_to_ms(last_obs_iso) if last_obs_iso else _iso_to_ms(_iso(rec["ts_ns"]))
        sessions.append({
            "sessionId": sid,
            "epoch": epoch,
            "host": host,
            "tool": labels.get("tool_name") or "unknown",
            "state": state or "unknown",
            "lastObservedAt": _iso(rec["ts_ns"]),
            "lastObservedAgeSeconds": round((now_ns - rec["ts_ns"]) / 1e9, 1),
            "serviceVersion": labels.get("service_version"),
            "lastActivityMs": last_activity,
        })
    sessions.sort(key=lambda s: (s["host"], s["tool"], s["sessionId"]))
    return {
        "sessions": sessions,
        "queriedAt": _iso(now_ns),
        "freshnessWindowSeconds": WATCHER_FRESHNESS_SECONDS,
    }


def _iso(ns):
    """Nanosecond epoch -> RFC3339 string (UTC)."""
    import datetime
    return datetime.datetime.fromtimestamp(ns / 1e9, tz=datetime.timezone.utc).isoformat()


def _iso_to_ms(iso_str):
    """ISO 8601 string -> milliseconds since epoch."""
    if not iso_str:
        return 0
    import datetime
    try:
        # Handle both '2026-05-23T...' and '2026-05-23T...Z' formats
        iso_str = iso_str.replace('Z', '+00:00')
        dt = datetime.datetime.fromisoformat(iso_str)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Session computation (enriched)
# ---------------------------------------------------------------------------

def query_recent_metric_activity():
    """Query Prometheus for sessions with actual metric changes in last 2 min.
    Uses increase() to detect real activity, not just stale cumulative counters.
    Returns a dict: session_id -> now_ms (if active)."""
    now_ms = int(time.time() * 1000)
    active = {}
    # Try multiple metric names — Copilot and Claude emit different ones
    metric_queries = [
        'increase(gen_ai_client_token_usage_count{gen_ai_conversation_id!=""}[2m])',
        'increase(gen_ai_client_operation_duration_count{gen_ai_conversation_id!=""}[2m])',
        'increase(github_copilot_tool_call_count_total{gen_ai_conversation_id!=""}[2m])',
    ]
    for promql in metric_queries:
        try:
            result = query_prometheus(f'max by (gen_ai_conversation_id) ({promql})')
            for s in result.get("data", {}).get("result", []):
                sid = s["metric"].get("gen_ai_conversation_id", "")
                val = float(s["value"][1])
                if sid and val > 0:
                    active[sid] = now_ms
        except Exception:
            pass
    return active


def _span_session_id(span):
    """Claude Code emits session.id; Copilot emits gen_ai.conversation.id.
    Either is sufficient — they're the conversation/session key."""
    return (get_attr(span, "gen_ai.conversation.id")
            or get_attr(span, "session.id"))


def compute_sessions(lookback_hours=None):
    lh = lookback_hours or LOOKBACK_HOURS
    # Copilot's per-turn root span (older shape: gen_ai semconv)
    copilot_data = query_tempo(
        '{resource.service.name="github-copilot" && name="invoke_agent"}'
        ' | select(span.gen_ai.conversation.id, span.gen_ai.agent.version,'
        ' span.gen_ai.response.model, span.gen_ai.usage.input_tokens,'
        ' span.gen_ai.usage.output_tokens, resource.host.name)',
        lookback_hours=lh,
    )
    # Claude Code's per-prompt root span (new beta tracing shape) — one span
    # per user interaction, carries session.id + user_prompt + duration.
    # The llm_request child spans carry token counts and model name.
    claude_interactions = query_tempo(
        '{resource.service.name="claude-code" && name="claude_code.interaction"}'
        ' | select(span.session.id, span.gen_ai.conversation.id,'
        ' span.user_prompt, span.user_prompt_length,'
        ' span.interaction.sequence, resource.host.name)',
        lookback_hours=lh,
    )
    claude_llm = query_tempo(
        '{resource.service.name="claude-code" && name="claude_code.llm_request"}'
        ' | select(span.session.id, span.gen_ai.conversation.id,'
        ' span.gen_ai.request.model, span.input_tokens,'
        ' span.cache_read_tokens, span.cache_creation_tokens,'
        ' resource.host.name)',
        lookback_hours=lh,
    )
    # Generic Claude fallback for installations without the beta tracing flag
    # (in case they emit the older gen_ai-style spans).
    claude_data = query_tempo(
        '{resource.service.name=~"claude.*"}'
        ' | select(span.gen_ai.conversation.id, span.gen_ai.response.model,'
        ' span.gen_ai.usage.input_tokens, span.gen_ai.usage.output_tokens,'
        ' resource.host.name, resource.service.name)',
        lookback_hours=lh,
    )
    # Chat spans carry the model name (invoke_agent often doesn't)
    chat_data = query_tempo(
        '{resource.service.name=~"github-copilot|claude.*" && name=~"chat.*"}'
        ' | select(span.gen_ai.conversation.id, span.gen_ai.response.model)',
        lookback_hours=lh,
    )
    children_data = query_tempo(
        '{resource.service.name=~"github-copilot|claude.*" && name!="invoke_agent"'
        ' && name!="permission"} | select(span.gen_ai.conversation.id)',
        lookback_hours=lh,
    )
    # Short-lookback query for recent activity (catches in-progress turns)
    recent_children = query_tempo(
        '{resource.service.name=~"github-copilot|claude.*" && name!="invoke_agent"'
        ' && name!="permission"} | select(span.gen_ai.conversation.id)',
        lookback_hours=min(lh, 1),
        limit=200,
    )

    sessions = defaultdict(lambda: {
        "max_time": 0, "min_time": float("inf"), "turns": 0,
        "version": "", "duration_ns": 0, "host": "", "model": "",
        "total_input_tokens": 0, "total_output_tokens": 0,
        "trace_ids": set(), "source": "",
        "last_prompt": "", "last_prompt_at": 0,
    })
    children_max = defaultdict(int)

    def _capture_last_prompt(data):
        """For each session, remember the user_prompt from the most recent
        claude_code.interaction span. Run after process_spans so sessions{} is
        keyed."""
        for trace in data.get("traces", []):
            for ss in trace.get("spanSets", []):
                for span in ss.get("spans", []):
                    sid = _span_session_id(span)
                    if not sid: continue
                    prompt = get_attr(span, "user_prompt") or ""
                    if not prompt: continue
                    t = int(span["startTimeUnixNano"]) // 1_000_000
                    rec = sessions[sid]
                    if t > rec.get("last_prompt_at", 0):
                        rec["last_prompt"] = prompt
                        rec["last_prompt_at"] = t

    def process_spans(data, source_name, is_root):
        """is_root=True means each span counts as a turn AND seeds the session."""
        for trace in data.get("traces", []):
            trace_id = trace.get("traceID", "")
            for ss in trace.get("spanSets", []):
                for span in ss.get("spans", []):
                    sid = _span_session_id(span)
                    if not sid:
                        continue
                    t = int(span["startTimeUnixNano"]) // 1_000_000
                    dur = int(span.get("durationNanos", 0))
                    end_t = t + dur // 1_000_000
                    rec = sessions[sid]
                    if is_root:
                        rec["turns"] += 1
                    rec["min_time"] = min(rec["min_time"], t)
                    if trace_id:
                        rec["trace_ids"].add(trace_id)
                    if end_t > rec["max_time"]:
                        rec["max_time"] = end_t
                        if is_root:
                            rec["duration_ns"] = dur
                    if source_name and not rec["source"]:
                        rec["source"] = source_name
                    ver = get_attr(span, "gen_ai.agent.version")
                    if ver:
                        rec["version"] = ver
                    host = get_attr(span, "host.name")
                    if host:
                        rec["host"] = host
                    # Copilot puts model on root; Claude puts it on llm_request
                    model = (get_attr(span, "gen_ai.response.model")
                             or get_attr(span, "gen_ai.request.model")
                             or get_attr(span, "model"))
                    if model:
                        rec["model"] = model
                    # Token-attribute names differ across tools/span types
                    inp = (get_attr(span, "gen_ai.usage.input_tokens")
                           or get_attr(span, "input_tokens"))
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

    process_spans(copilot_data, "Copilot", is_root=True)
    process_spans(claude_data, "Claude", is_root=True)
    process_spans(claude_interactions, "Claude", is_root=True)
    process_spans(claude_llm, "Claude", is_root=False)
    _capture_last_prompt(claude_interactions)

    # Build trace_id -> session_id map from invoke_agent spans
    trace_to_session = {}
    for sid, rec in sessions.items():
        for tid in rec["trace_ids"]:
            trace_to_session[tid] = sid

    # Also build trace_id -> session_id from chat spans (chat spans complete
    # quickly and may carry gen_ai.conversation.id even during in-progress turns)
    for trace in chat_data.get("traces", []):
        trace_id = trace.get("traceID", "")
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                sid = _span_session_id(span)
                model = get_attr(span, "gen_ai.response.model")
                if sid and trace_id:
                    trace_to_session[trace_id] = sid
                if sid and model and sid in sessions and not sessions[sid]["model"]:
                    sessions[sid]["model"] = model

    def _process_children(data):
        """Extract latest child span end-time per session using trace_id fallback."""
        unmatched_traces = set()
        for trace in data.get("traces", []):
            trace_id = trace.get("traceID", "")
            for ss in trace.get("spanSets", []):
                for span in ss.get("spans", []):
                    sid = _span_session_id(span)
                    if not sid:
                        sid = trace_to_session.get(trace_id)
                    if not sid:
                        if trace_id:
                            unmatched_traces.add(trace_id)
                        continue
                    # Update mapping for future lookups
                    if trace_id and trace_id not in trace_to_session:
                        trace_to_session[trace_id] = sid
                    t = int(span["startTimeUnixNano"]) // 1_000_000
                    dur = int(span.get("durationNanos", 0))
                    end_t = t + dur // 1_000_000
                    children_max[sid] = max(children_max[sid], end_t)
        return unmatched_traces

    _process_children(children_data)
    unmatched = _process_children(recent_children)

    # For unmatched recent traces, fetch the full trace to find session_id
    # (handles in-progress turns where invoke_agent hasn't landed in Tempo yet)
    resolved = 0
    for tid in sorted(unmatched)[:5]:  # cap at 5 fetches
        try:
            trace_data = get_trace(tid)
            found_sid = None
            for batch in trace_data.get("batches", []):
                for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
                    for span in scope.get("spans", []):
                        for attr in span.get("attributes", []):
                            if attr.get("key") == "gen_ai.conversation.id":
                                v = attr.get("value", {})
                                found_sid = v.get("stringValue", "")
                                break
                        if found_sid:
                            break
                if found_sid:
                    break
            if found_sid:
                trace_to_session[tid] = found_sid
                resolved += 1
                # Re-scan recent_children for this trace
                for trace in recent_children.get("traces", []):
                    if trace.get("traceID") == tid:
                        for ss in trace.get("spanSets", []):
                            for span in ss.get("spans", []):
                                t = int(span["startTimeUnixNano"]) // 1_000_000
                                dur = int(span.get("durationNanos", 0))
                                end_t = t + dur // 1_000_000
                                children_max[found_sid] = max(
                                    children_max[found_sid], end_t)
        except Exception:
            pass

    all_ids = set(list(sessions.keys()) + list(children_max.keys()))
    # Query Prometheus for recent metric activity to detect responding state
    try:
        metric_activity = query_recent_metric_activity()
    except Exception:
        metric_activity = {}

    rows = []
    now_ms = int(time.time() * 1000)
    for sid in all_ids:
        c = sessions.get(sid)
        c_time = c["max_time"] if c else 0
        a_time = children_max.get(sid, 0)
        metric_time = metric_activity.get(sid, 0)
        last_activity = max(c_time, a_time, metric_time)
        age_s = (now_ms - last_activity) / 1000 if last_activity > 0 else float("inf")

        # Adaptive idle threshold: if the last turn was long (autopilot),
        # allow up to last_turn_duration before marking idle.
        last_turn_s = c["duration_ns"] / 1e9 if c else 0
        idle_threshold = max(IDLE_TIMEOUT_SECONDS, last_turn_s)

        # Responding: metrics show real activity (increase > 0) in last 2 min
        if metric_time > 0:
            status = "Responding"
        elif age_s < IDLE_TIMEOUT_SECONDS:
            status = "Active"
        elif age_s < idle_threshold:
            # Within expected turn duration - likely mid-turn in autopilot
            status = "Active"
        elif last_activity > 0:
            status = "Idle"
        else:
            status = "Idle"

        rows.append({
            "session_id": sid,
            "status": status,
            "source": c["source"] if c else "",
            "host": c["host"] if c else "",
            "model": c["model"] if c else "",
            "last_activity": last_activity,
            "first_seen": c["min_time"] if c and c["min_time"] != float("inf") else last_activity,
            "turns": c["turns"] if c else 0,
            "last_turn_duration_s": round(c["duration_ns"] / 1e9, 1) if c else 0,
            "total_input_tokens": c["total_input_tokens"] if c else 0,
            "total_output_tokens": c["total_output_tokens"] if c else 0,
            "cli_version": c["version"] if c else "",
            "last_prompt": c.get("last_prompt", "") if c else "",
            "last_prompt_at": c.get("last_prompt_at", 0) if c else 0,
        })

    # Merge in sessions known to the watcher daemon but not yet seen in Tempo
    # (newly opened sessions, or sessions whose tool emits no traces).
    seen_ids = {r["session_id"] for r in rows}
    try:
        watcher = get_watcher_state().get("sessions", [])
    except Exception:
        watcher = []
    now_ms = int(time.time() * 1000)
    for ws in watcher:
        sid = ws["sessionId"]
        if sid in seen_ids:
            # Tempo had data; just tag the row with the watcher's view of state.
            for r in rows:
                if r["session_id"] == sid:
                    r["watcher_state"] = ws.get("state")
                    r["watcher_host"] = ws.get("host")
                    r["watcher_tool"] = ws.get("tool")
                    if not r.get("host"):
                        r["host"] = ws.get("host", "")
                    if not r.get("source"):
                        r["source"] = (ws.get("tool") or "").capitalize()
            continue
        # Watcher knows a session Tempo doesn't — surface it from the daemon.
        watcher_state = (ws.get("state") or "").lower()
        status = {
            "active": "Active",
            "idle": "Idle",
            "live": "Active",
            "closed": "Closed",
            "orphan": "Closed",  # backward-compat for daemons still emitting old label
        }.get(watcher_state, "Unknown")
        # Use lastActivityMs from watcher (which is closed_at for closed sessions, or lastObservedAt otherwise)
        last_activity = ws.get("lastActivityMs", now_ms)
        rows.append({
            "session_id": sid,
            "status": status,
            "source": (ws.get("tool") or "").capitalize(),
            "host": ws.get("host", ""),
            "model": "",
            "last_activity": last_activity,
            "first_seen": last_activity,
            "turns": 0,
            "last_turn_duration_s": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "cli_version": ws.get("serviceVersion", ""),
            "last_prompt": "",
            "last_prompt_at": 0,
            "watcher_state": ws.get("state"),
            "watcher_host": ws.get("host"),
            "watcher_tool": ws.get("tool"),
        })

    rows.sort(key=lambda r: r["last_activity"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Session detail: all turns (invoke_agent spans) for a session
# ---------------------------------------------------------------------------

def get_session_detail(session_id):
    # Copilot's per-turn root spans for this session
    copilot_turns = query_tempo(
        '{resource.service.name="github-copilot" && name="invoke_agent"'
        f' && span.gen_ai.conversation.id="{session_id}"}}'
        ' | select(span.gen_ai.response.model, span.gen_ai.usage.input_tokens,'
        ' span.gen_ai.usage.output_tokens, span.gen_ai.agent.version,'
        ' resource.host.name)'
    )
    # Claude older shape (pre-beta) if any
    claude_turns = query_tempo(
        '{resource.service.name=~"claude.*"'
        f' && span.gen_ai.conversation.id="{session_id}"}}'
        ' | select(span.gen_ai.response.model, span.gen_ai.usage.input_tokens,'
        ' span.gen_ai.usage.output_tokens, resource.host.name,'
        ' resource.service.name)'
    )
    # Claude new beta tracing — one span per user prompt + per LLM call + per tool
    claude_interactions = query_tempo(
        '{resource.service.name="claude-code" && name="claude_code.interaction"'
        f' && (span.session.id="{session_id}" || span.gen_ai.conversation.id="{session_id}")}}'
        ' | select(span.session.id, span.gen_ai.conversation.id,'
        ' span.user_prompt, span.user_prompt_length,'
        ' span.interaction.sequence, resource.host.name)'
    )
    claude_llm = query_tempo(
        '{resource.service.name="claude-code" && name="claude_code.llm_request"'
        f' && (span.session.id="{session_id}" || span.gen_ai.conversation.id="{session_id}")}}'
        ' | select(span.gen_ai.request.model, span.input_tokens,'
        ' span.cache_read_tokens, span.cache_creation_tokens)'
    )
    # Chat spans carry the model (invoke_agent often doesn't)
    chat_spans = query_tempo(
        '{resource.service.name=~"github-copilot|claude.*" && name=~"chat.*"'
        f' && span.gen_ai.conversation.id="{session_id}"}}'
        ' | select(span.gen_ai.response.model)'
    )
    # Build trace_id -> model map from chat spans
    trace_models = {}
    for trace in chat_spans.get("traces", []):
        trace_id = trace.get("traceID", "")
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                model = get_attr(span, "gen_ai.response.model")
                if model and trace_id:
                    trace_models[trace_id] = model

    turns = []
    host = ""
    version = ""

    def extract_turns(data):
        nonlocal host, version
        for trace in data.get("traces", []):
            trace_id = trace.get("traceID", "")
            for ss in trace.get("spanSets", []):
                for span in ss.get("spans", []):
                    start_ns = int(span["startTimeUnixNano"])
                    dur_ns = int(span.get("durationNanos", 0))
                    model = get_attr(span, "gen_ai.response.model") or ""
                    if not model:
                        model = trace_models.get(trace_id, "")
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

    extract_turns(copilot_turns)
    extract_turns(claude_turns)

    # Index Claude llm_request spans by trace_id so we can attach token totals
    # + model name to the matching interaction.
    llm_by_trace = {}
    for trace in claude_llm.get("traces", []):
        tid = trace.get("traceID", "")
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                entry = llm_by_trace.setdefault(tid, {"input": 0, "output": 0,
                                                       "cache_read": 0,
                                                       "cache_create": 0,
                                                       "model": ""})
                try: entry["input"] += int(get_attr(span, "input_tokens") or 0)
                except (ValueError, TypeError): pass
                try: entry["cache_read"] += int(get_attr(span, "cache_read_tokens") or 0)
                except (ValueError, TypeError): pass
                try: entry["cache_create"] += int(get_attr(span, "cache_creation_tokens") or 0)
                except (ValueError, TypeError): pass
                m = get_attr(span, "gen_ai.request.model") or get_attr(span, "model")
                if m: entry["model"] = m

    # Convert Claude interaction spans into turn rows. Each interaction = 1
    # user prompt, so it's the right granularity for the per-turn table.
    for trace in claude_interactions.get("traces", []):
        trace_id = trace.get("traceID", "")
        for ss in trace.get("spanSets", []):
            for span in ss.get("spans", []):
                start_ns = int(span["startTimeUnixNano"])
                dur_ns = int(span.get("durationNanos", 0))
                h = get_attr(span, "host.name")
                if h: host = h
                llm = llm_by_trace.get(trace_id, {})
                prompt = get_attr(span, "user_prompt") or ""
                turns.append({
                    "trace_id": trace_id,
                    "span_id": span.get("spanID", ""),
                    "start_time": start_ns // 1_000_000,
                    "duration_s": round(dur_ns / 1e9, 1),
                    "model": llm.get("model", ""),
                    "input_tokens": llm.get("input", 0),
                    "output_tokens": llm.get("output", 0),
                    "cache_read_tokens": llm.get("cache_read", 0),
                    "cache_creation_tokens": llm.get("cache_create", 0),
                    "user_prompt": prompt,
                    "user_prompt_length": int(get_attr(span, "user_prompt_length") or 0),
                    "sequence": int(get_attr(span, "interaction.sequence") or 0),
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

def get_metrics_token_usage(lookback_hours=None):
    lh = lookback_hours or LOOKBACK_HOURS
    now = int(time.time())
    start = now - (lh * 3600)
    result = query_prometheus_range(
        'sum by (gen_ai_token_type) (rate(gen_ai_client_token_usage_count[5m]))',
        start, now, "60s"
    )
    # Build a time-indexed map: {timestamp_ms: {input: v, output: v}}
    points = {}
    for s in result.get("data", {}).get("result", []):
        token_type = s["metric"].get("gen_ai_token_type", "unknown")
        key = "input" if "input" in token_type.lower() else "output"
        for v in s["values"]:
            ts = int(float(v[0]) * 1000)
            if ts not in points:
                points[ts] = {"timestamp": ts, "input": 0, "output": 0}
            points[ts][key] = float(v[1])
    return sorted(points.values(), key=lambda p: p["timestamp"])


def get_metrics_operations(lookback_hours=None):
    lh = lookback_hours or LOOKBACK_HOURS
    now = int(time.time())
    start = now - (lh * 3600)
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
        items.append({"model": model, "totalInput": float(s["value"][1]), "totalOutput": 0, "count": 1})
    return items


def get_metrics_tools():
    result = query_prometheus(
        'sum by (gen_ai_tool_name) (github_copilot_tool_call_count)'
    )
    items = []
    for s in result.get("data", {}).get("result", []):
        tool = s["metric"].get("gen_ai_tool_name", "unknown")
        items.append({"tool": tool, "count": float(s["value"][1]), "avgDurationMs": 0})
    items.sort(key=lambda x: x["count"], reverse=True)
    return items


def get_health_summary(lookback_hours=None):
    sessions = compute_sessions(lookback_hours)
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parsed.query
        lookback_hours = parse_lookback(qs)

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

        # --- Dashboard API routes (auth required) ---
        if path.startswith("/dashboard-api"):
            token = self._get_bearer_token()
            if not validate_jwt_basic(token):
                return self._error(401, "Authentication required")

        # --- Legacy API routes (auth required) ---
        if path.startswith("/api/"):
            token = self._get_bearer_token()
            if not validate_jwt_basic(token):
                return self._error(401, "Authentication required")

        # Session list (also used by Grafana Infinity datasource at /api/sessions)
        if path in ("/api/sessions", "/dashboard-api/sessions"):
            try:
                return self._json_response(compute_sessions(lookback_hours))
            except Exception as e:
                return self._error(500, str(e))

        # Watcher state: current live + orphan sessions from the daemon
        if path in ("/api/sessions/state", "/dashboard-api/sessions/state"):
            try:
                return self._json_response(get_watcher_state())
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
                return self._json_response(get_metrics_token_usage(lookback_hours))
            except Exception as e:
                return self._error(500, str(e))

        # Metrics: operation duration time series
        if path == "/dashboard-api/metrics/operations":
            try:
                return self._json_response(get_metrics_operations(lookback_hours))
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

        # Debug: show what Prometheus has for a session (for troubleshooting)
        m = re.match(r"^/dashboard-api/debug/session/([^/]+)$", path)
        if m:
            sid = m.group(1)
            debug = {"session_id": sid, "metrics": {}, "traces": {}}
            # Check various metrics for this session
            for metric in [
                "gen_ai_client_token_usage_count",
                "gen_ai_client_operation_duration_count",
                "github_copilot_tool_call_count_total",
            ]:
                try:
                    r = query_prometheus(
                        f'{metric}{{gen_ai_conversation_id="{sid}"}}')
                    debug["metrics"][metric] = r.get("data", {}).get("result", [])
                except Exception as e:
                    debug["metrics"][metric] = {"error": str(e)}
            # Check all metric labels for this session
            try:
                r = query_prometheus(
                    f'{{gen_ai_conversation_id="{sid}"}}')
                debug["metrics"]["all_with_session_id"] = r.get("data", {}).get("result", [])
            except Exception as e:
                debug["metrics"]["all_with_session_id"] = {"error": str(e)}
            # Recent children via trace_id
            try:
                sessions_data = compute_sessions(lookback_hours)
                for s in sessions_data:
                    if s["session_id"] == sid:
                        debug["session_status"] = s
                        break
            except Exception as e:
                debug["session_status"] = {"error": str(e)}
            return self._json_response(debug)

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
