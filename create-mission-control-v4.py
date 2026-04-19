import json
import urllib.request
import time

TEMPO_UID = "P214B5B846CF3925F"
INFINITY_UID = "session-api"
PROM_UID = "prometheus"
DASH_UID = "copilot-mission-control"

# Wait for Grafana to be ready
for i in range(10):
    try:
        urllib.request.urlopen("http://localhost:3000/api/health")
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
                "title": "gen_ai_client_token_usage_count",
                "gridPos": {"h": 10, "w": 24, "x": 0, "y": 16},
                "datasource": {"type": "prometheus", "uid": PROM_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": "sum(rate(gen_ai_client_token_usage_count[$__rate_interval]))",
                        "legendFormat": "sum(rate)",
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
    "http://localhost:3000/api/dashboards/db",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"Dashboard: http://localhost:3000{result['url']}")
print(f"Status: {result['status']}")
