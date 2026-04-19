import json
import urllib.request

TEMPO_UID = "P214B5B846CF3925F"
PROM_UID = "prometheus"
DASH_UID = "copilot-cli-sessions"

dashboard = {
    "dashboard": {
        "uid": DASH_UID,
        "title": "Copilot CLI Sessions",
        "tags": ["copilot", "opentelemetry", "genai"],
        "timezone": "browser",
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "session_id",
                    "type": "textbox",
                    "label": "Session (Conversation ID)",
                    "current": {"value": ""},
                    "options": [],
                },
            ]
        },
        "panels": [
            # ── Row: Sessions Overview ──
            {
                "type": "row",
                "title": "Sessions Overview",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
                "collapsed": False,
            },
            # Panel: All Sessions table (spans mode for attribute columns)
            {
                "type": "table",
                "title": "All Sessions",
                "description": "Each row is an agent invocation. Click the conversation ID to drill into a session.",
                "gridPos": {"h": 10, "w": 24, "x": 0, "y": 1},
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
                "options": {
                    "showHeader": True,
                    "sortBy": [{"displayName": "Start time", "desc": True}],
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "Duration"},
                            "properties": [
                                {"id": "unit", "value": "ns"},
                            ],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.conversation.id"},
                            "properties": [
                                {"id": "displayName", "value": "Session ID"},
                                {
                                    "id": "links",
                                    "value": [
                                        {
                                            "title": "Drill into session",
                                            "url": "/d/" + DASH_UID + "/copilot-cli-sessions?var-session_id=${__value.raw}",
                                            "targetBlank": False,
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "matcher": {"id": "byName", "options": "Span ID"},
                            "properties": [
                                {
                                    "id": "links",
                                    "value": [
                                        {
                                            "title": "View trace waterfall",
                                            "url": "/explore?schemaVersion=1&panes={\"a\":{\"datasource\":\"" + TEMPO_UID + "\",\"queries\":[{\"refId\":\"A\",\"queryType\":\"traceql\",\"query\":\"${__data.fields.traceIdHidden}\"}]}}",
                                            "targetBlank": True,
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            },
            # Panel: Token usage
            {
                "type": "timeseries",
                "title": "Token Usage Over Time",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 11},
                "datasource": {"type": "prometheus", "uid": PROM_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": 'rate(gen_ai_client_token_usage_sum[5m])',
                        "legendFormat": "tokens/sec",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "custom": {"drawStyle": "bars", "fillOpacity": 30},
                    },
                    "overrides": [],
                },
            },
            # Panel: LLM duration
            {
                "type": "timeseries",
                "title": "LLM Call Duration",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 11},
                "datasource": {"type": "prometheus", "uid": PROM_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": 'rate(gen_ai_client_operation_duration_sum[5m]) / rate(gen_ai_client_operation_duration_count[5m])',
                        "legendFormat": "avg duration (s)",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "s",
                        "custom": {"drawStyle": "line", "fillOpacity": 10},
                    },
                    "overrides": [],
                },
            },

            # ── Row: Session Detail ──
            {
                "type": "row",
                "title": "Session Detail: $session_id",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 19},
                "collapsed": False,
            },
            # Panel: All spans in session
            {
                "type": "table",
                "title": "All Spans in Session",
                "description": "Every span for the selected session: LLM calls, tool executions, permissions.",
                "gridPos": {"h": 10, "w": 24, "x": 0, "y": 20},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && span.gen_ai.conversation.id="$session_id"} | select(span.gen_ai.operation.name, span.gen_ai.tool.name, span.gen_ai.response.model)',
                        "tableType": "spans",
                    }
                ],
                "options": {
                    "showHeader": True,
                    "sortBy": [{"displayName": "Start time", "desc": False}],
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "Duration"},
                            "properties": [{"id": "unit", "value": "ns"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.operation.name"},
                            "properties": [{"id": "displayName", "value": "Operation"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.tool.name"},
                            "properties": [{"id": "displayName", "value": "Tool"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.response.model"},
                            "properties": [{"id": "displayName", "value": "Model"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "Span ID"},
                            "properties": [
                                {
                                    "id": "links",
                                    "value": [
                                        {
                                            "title": "View trace waterfall",
                                            "url": "/explore?schemaVersion=1&panes={\"a\":{\"datasource\":\"" + TEMPO_UID + "\",\"queries\":[{\"refId\":\"A\",\"queryType\":\"traceql\",\"query\":\"${__data.fields.traceIdHidden}\"}]}}",
                                            "targetBlank": True,
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            },

            # ── Row: Prompt Detail ──
            {
                "type": "row",
                "title": "Individual Prompts (LLM Calls)",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 30},
                "collapsed": False,
            },
            # Panel: Chat spans
            {
                "type": "table",
                "title": "LLM Chat Calls",
                "description": "Each row is one prompt/response cycle within the session.",
                "gridPos": {"h": 10, "w": 12, "x": 0, "y": 31},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="chat" && span.gen_ai.conversation.id="$session_id"} | select(span.gen_ai.response.model, span.gen_ai.response.finish_reasons)',
                        "tableType": "spans",
                    }
                ],
                "options": {
                    "showHeader": True,
                    "sortBy": [{"displayName": "Start time", "desc": False}],
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "Duration"},
                            "properties": [{"id": "unit", "value": "ns"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.response.model"},
                            "properties": [{"id": "displayName", "value": "Model"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "Span ID"},
                            "properties": [
                                {
                                    "id": "links",
                                    "value": [
                                        {
                                            "title": "View trace waterfall",
                                            "url": "/explore?schemaVersion=1&panes={\"a\":{\"datasource\":\"" + TEMPO_UID + "\",\"queries\":[{\"refId\":\"A\",\"queryType\":\"traceql\",\"query\":\"${__data.fields.traceIdHidden}\"}]}}",
                                            "targetBlank": True,
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            },
            # Panel: Tool calls
            {
                "type": "table",
                "title": "Tool Executions",
                "description": "All tool calls within the session.",
                "gridPos": {"h": 10, "w": 12, "x": 12, "y": 31},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name=~"execute_tool.*" && span.gen_ai.conversation.id="$session_id"} | select(span.gen_ai.tool.name, span.gen_ai.tool.call.id)',
                        "tableType": "spans",
                    }
                ],
                "options": {
                    "showHeader": True,
                    "sortBy": [{"displayName": "Start time", "desc": False}],
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "Duration"},
                            "properties": [{"id": "unit", "value": "ns"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.tool.name"},
                            "properties": [{"id": "displayName", "value": "Tool"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.tool.call.id"},
                            "properties": [{"id": "displayName", "value": "Call ID"}],
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
print(f"Dashboard updated: http://localhost:3000{result['url']}")
print(f"Status: {result['status']}")
