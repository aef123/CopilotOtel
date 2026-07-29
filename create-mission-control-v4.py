import base64
import json
import os
import urllib.request
import time

# Target Grafana. Defaults to a local dev instance. For the homelab:
#   GRAFANA_URL=http://192.168.30.10:3000 GRAFANA_TOKEN=<service-account-token> python <this>
# The homelab Grafana is not anonymous-admin, so GRAFANA_TOKEN is required there.
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN")
# Basic-auth fallback, so this can be driven from the VM using the admin password out of
# /opt/docker/secrets/observability.env without minting a service-account token first.
GRAFANA_USER = os.environ.get("GRAFANA_USER")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD")

# Datasource UIDs — must match the TARGET Grafana's datasources.
#
# TEMPO_UID was hardcoded to "P214B5B846CF3925F", the UID Grafana deterministically assigns an
# unpinned datasource named "Tempo". Correct on the old standalone Azure stack -- but on the merged
# homelab Grafana that same UID belongs to the LAB Tempo (syslog traces), while CLI traces live in a
# separate Tempo pinned to uid "tempo". Left as-is, every trace panel silently queries the wrong
# backend and renders empty with no error.
TEMPO_UID = os.environ.get("TEMPO_UID", "tempo")
INFINITY_UID = os.environ.get("INFINITY_UID", "session-api")
PROM_UID = os.environ.get("PROM_UID", "prometheus")
DASH_UID = "copilot-mission-control"


def _headers(extra=None):
    h = dict(extra or {})
    if GRAFANA_TOKEN:
        h["Authorization"] = f"Bearer {GRAFANA_TOKEN}"
    elif GRAFANA_USER:
        basic = base64.b64encode(f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode()).decode()
        h["Authorization"] = f"Basic {basic}"
    return h


# Wait for Grafana to be ready
for i in range(10):
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"{GRAFANA_URL}/api/health", headers=_headers())
        )
        break
    except Exception:
        time.sleep(2)

dashboard = {
    "dashboard": {
        "uid": DASH_UID,
        "title": "Copilot CLI - Mission Control",
        "tags": ["copilot", "opentelemetry", "genai"],
        "timezone": "browser",
        "refresh": "10s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "panels": [
            {
                "type": "table",
                "title": "Session Status",
                "gridPos": {"h": 16, "w": 24, "x": 0, "y": 0},
                "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": INFINITY_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": INFINITY_UID},
                        "type": "json",
                        "source": "url",
                        "url": "http://session-api:8080/api/sessions",
                        "format": "table",
                        "url_options": {"method": "GET"},
                        "root_selector": "",
                        "columns": [
                            {"selector": "session_id", "text": "Session ID", "type": "string"},
                            {"selector": "status", "text": "Status", "type": "string"},
                            {"selector": "host", "text": "Machine", "type": "string"},
                            {"selector": "last_activity", "text": "Last Activity", "type": "number"},
                            {"selector": "turns", "text": "Turns", "type": "number"},
                            {"selector": "last_turn_duration_s", "text": "Last Turn (sec)", "type": "number"},
                            {"selector": "cli_version", "text": "CLI Version", "type": "string"},
                        ],
                    }
                ],
                "options": {
                    "showHeader": True,
                    "sortBy": [{"displayName": "Last Activity", "desc": True}],
                    "footer": {"enablePagination": True},
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "Status"},
                            "properties": [
                                {
                                    "id": "mappings",
                                    "value": [
                                        {"type": "value", "options": {"Active": {"text": "🟢 Active", "color": "green"}}},
                                        {"type": "value", "options": {"Idle": {"text": "⏸ Idle", "color": "text"}}},
                                        {"type": "value", "options": {"Unknown": {"text": "? Unknown", "color": "orange"}}},
                                    ],
                                },
                                {
                                    "id": "custom.cellOptions",
                                    "value": {"type": "color-text"},
                                },
                            ],
                        },
                        {
                            "matcher": {"id": "byName", "options": "Session ID"},
                            "properties": [
                                {
                                    "id": "links",
                                    "value": [
                                        {
                                            "title": "Open session detail",
                                            "url": "/d/copilot-cli-sessions/copilot-cli-sessions?var-session_id=${__value.raw}",
                                            "targetBlank": False,
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "matcher": {"id": "byName", "options": "Last Activity"},
                            "properties": [
                                {"id": "unit", "value": "dateTimeFromNow"},
                            ],
                        },
                    ],
                },
            },
            {
                "type": "timeseries",
                # Token rate for EVERY client, not just Copilot. Copilot CLI emits the gen_ai
                # semconv metric; Claude Code emits claude_code_token_usage_tokens_total and is
                # split by `job` into claude-code (CLI) and claude-code-desktop (app). `job` is the
                # only reliable discriminator -- service_name is absent on Claude CLI series.
                # This panel previously showed only gen_ai_client_token_usage_count, so all Claude
                # usage (CLI and app alike) was invisible here.
                "title": "Token rate — all clients",
                "gridPos": {"h": 10, "w": 24, "x": 0, "y": 16},
                "datasource": {"type": "prometheus", "uid": PROM_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": "sum(rate(gen_ai_client_token_usage_count[$__rate_interval]))",
                        "legendFormat": "github-copilot",
                        "format": "time_series",
                    },
                    {
                        "refId": "B",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": "sum by (job) (rate(claude_code_token_usage_tokens_total[$__rate_interval]))",
                        "legendFormat": "{{job}}",
                        "format": "time_series",
                    },
                ],
                "options": {
                    "legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "single"},
                },
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "palette-classic"},
                        "unit": "cps",
                        "custom": {
                            "drawStyle": "line",
                            "lineInterpolation": "linear",
                            "lineWidth": 1,
                            "fillOpacity": 0,
                            "pointSize": 5,
                            "showPoints": "auto",
                        },
                    },
                    "overrides": [],
                },
            },
        ],
    },
    "overwrite": True,
}

data = json.dumps(dashboard).encode("utf-8")
req = urllib.request.Request(
    f"{GRAFANA_URL}/api/dashboards/db",
    data=data,
    headers=_headers({"Content-Type": "application/json"}),
    method="POST",
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"Dashboard: {GRAFANA_URL}{result['url']}")
print(f"Status: {result['status']}")
print(f"Datasources: prom={PROM_UID} tempo={TEMPO_UID} infinity={INFINITY_UID}")
