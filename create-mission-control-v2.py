import json
import urllib.request

TEMPO_UID = "P214B5B846CF3925F"
DASH_UID = "copilot-mission-control"

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
                "description": "One row per session. A turn only appears after it completes, so if the activity timeline shows work but a session has no recent completed turn, it's still working.",
                "gridPos": {"h": 16, "w": 24, "x": 0, "y": 0},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id, span.gen_ai.agent.version)',
                        "tableType": "spans",
                    }
                ],
                "transformations": [
                    {
                        "id": "groupBy",
                        "options": {
                            "fields": {
                                "gen_ai.conversation.id": {
                                    "aggregations": [],
                                    "operation": "groupby",
                                },
                                "gen_ai.agent.version": {
                                    "aggregations": ["lastNotNull"],
                                    "operation": "aggregate",
                                },
                                "time": {
                                    "aggregations": ["max"],
                                    "operation": "aggregate",
                                },
                                "duration": {
                                    "aggregations": ["count", "lastNotNull"],
                                    "operation": "aggregate",
                                },
                            }
                        },
                    },
                    {
                        "id": "organize",
                        "options": {
                            "renameByName": {
                                "gen_ai.conversation.id": "Session ID",
                                "gen_ai.agent.version (lastNotNull)": "CLI Version",
                                "time (max)": "Last Activity",
                                "duration (count)": "Turns",
                                "duration (lastNotNull)": "Last Turn Duration",
                            },
                            "indexByName": {
                                "gen_ai.conversation.id": 0,
                                "time (max)": 1,
                                "duration (count)": 2,
                                "duration (lastNotNull)": 3,
                                "gen_ai.agent.version (lastNotNull)": 4,
                            },
                        },
                    },
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
                        {
                            "matcher": {"id": "byName", "options": "Last Turn Duration"},
                            "properties": [
                                {"id": "unit", "value": "ns"},
                            ],
                        },
                    ],
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
