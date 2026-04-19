import json
import urllib.request

TEMPO_UID = "P214B5B846CF3925F"
PROM_UID = "prometheus"
DASH_UID = "copilot-mission-control"

dashboard = {
    "dashboard": {
        "uid": DASH_UID,
        "title": "Copilot CLI - Mission Control",
        "tags": ["copilot", "opentelemetry", "genai", "mission-control"],
        "timezone": "browser",
        "refresh": "10s",
        "time": {"from": "now-3h", "to": "now"},
        "templating": {"list": []},
        "panels": [
            # ── Row: Active Sessions ──
            {
                "type": "row",
                "title": "Active & Recent Sessions",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
                "collapsed": False,
            },

            # Panel: Stat - total active sessions (had activity in last 15m)
            {
                "type": "stat",
                "title": "Sessions (last 15m)",
                "gridPos": {"h": 4, "w": 4, "x": 0, "y": 1},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id)',
                        "tableType": "spans",
                    }
                ],
                "options": {
                    "reduceOptions": {
                        "calcs": ["count"],
                    },
                    "colorMode": "background",
                    "textMode": "value",
                },
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "thresholds"},
                        "thresholds": {
                            "steps": [
                                {"value": None, "color": "dark-blue"},
                                {"value": 1, "color": "blue"},
                            ]
                        },
                    },
                    "overrides": [],
                },
                "timeFrom": "15m",
            },
            # Panel: Stat - total prompts (last 15m)
            {
                "type": "stat",
                "title": "Prompts (last 15m)",
                "gridPos": {"h": 4, "w": 4, "x": 4, "y": 1},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="chat"}',
                        "tableType": "spans",
                    }
                ],
                "options": {
                    "reduceOptions": {"calcs": ["count"]},
                    "colorMode": "background",
                    "textMode": "value",
                },
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "thresholds"},
                        "thresholds": {
                            "steps": [
                                {"value": None, "color": "dark-green"},
                                {"value": 1, "color": "green"},
                            ]
                        },
                    },
                    "overrides": [],
                },
                "timeFrom": "15m",
            },
            # Panel: Stat - tool calls (last 15m)
            {
                "type": "stat",
                "title": "Tool Calls (last 15m)",
                "gridPos": {"h": 4, "w": 4, "x": 8, "y": 1},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name=~"execute_tool.*"}',
                        "tableType": "spans",
                    }
                ],
                "options": {
                    "reduceOptions": {"calcs": ["count"]},
                    "colorMode": "background",
                    "textMode": "value",
                },
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "thresholds"},
                        "thresholds": {
                            "steps": [
                                {"value": None, "color": "dark-orange"},
                                {"value": 1, "color": "orange"},
                            ]
                        },
                    },
                    "overrides": [],
                },
                "timeFrom": "15m",
            },
            # Panel: Activity sparkline
            {
                "type": "timeseries",
                "title": "Activity Timeline",
                "description": "Tool calls over time - a flat line means idle, spikes mean active work.",
                "gridPos": {"h": 4, "w": 12, "x": 12, "y": 1},
                "datasource": {"type": "prometheus", "uid": PROM_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": "increase(github_copilot_tool_call_count_total[1m])",
                        "legendFormat": "tool calls/min",
                    },
                    {
                        "refId": "B",
                        "datasource": {"type": "prometheus", "uid": PROM_UID},
                        "expr": "increase(gen_ai_client_operation_duration_seconds_count[1m])",
                        "legendFormat": "LLM calls/min",
                    },
                ],
                "fieldConfig": {
                    "defaults": {
                        "custom": {
                            "drawStyle": "bars",
                            "fillOpacity": 40,
                            "stacking": {"mode": "normal"},
                            "showPoints": "never",
                        },
                    },
                    "overrides": [],
                },
                "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
            },

            # ── Main table: Most Recent Prompt Per Session ──
            #
            # Each invoke_agent span = one user prompt turn.
            # The span only appears once the turn COMPLETES.
            # So: if you see a recent invoke_agent, that turn is DONE.
            # If a session had activity (chat/tool spans) more recently
            # than its last invoke_agent, it's likely STILL WORKING.
            #
            # We show the latest invoke_agent per trace as "last completed turn".
            # Status logic: duration present = completed.
            {
                "type": "table",
                "title": "Session Status - Last Completed Turn",
                "description": "Shows the most recent completed prompt turn per session. Each invoke_agent span represents one full user prompt cycle. If a session is still processing a prompt, that turn won't appear here yet (spans export on completion). A session with very recent activity in the timeline above but no recent row here is likely still working.",
                "gridPos": {"h": 12, "w": 24, "x": 0, "y": 5},
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
                    "footer": {"enablePagination": True},
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.conversation.id"},
                            "properties": [
                                {"id": "displayName", "value": "Session ID"},
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
                            "matcher": {"id": "byName", "options": "gen_ai.agent.version"},
                            "properties": [
                                {"id": "displayName", "value": "CLI Version"},
                            ],
                        },
                        {
                            "matcher": {"id": "byName", "options": "duration"},
                            "properties": [
                                {"id": "unit", "value": "ns"},
                                {"id": "displayName", "value": "Turn Duration"},
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
                        # Hide the raw trace ID column (used by links)
                        {
                            "matcher": {"id": "byName", "options": "traceIdHidden"},
                            "properties": [
                                {"id": "custom.hidden", "value": True},
                            ],
                        },
                        {
                            "matcher": {"id": "byName", "options": "service.name"},
                            "properties": [
                                {"id": "custom.hidden", "value": True},
                            ],
                        },
                    ],
                },
            },

            # ── Row: In-Progress Detection ──
            {
                "type": "row",
                "title": "Currently Working? (child span activity)",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 17},
                "collapsed": False,
            },
            # Panel: Recent child spans (chat + tools) - these export
            # DURING a turn, unlike invoke_agent which only exports after.
            # If you see recent spans here but no matching invoke_agent
            # in the table above, that session is still working.
            {
                "type": "table",
                "title": "Recent LLM Calls (last 5 min)",
                "description": "Chat spans export as they complete, even while the parent turn is still running. If you see activity here with no corresponding completed turn above, that session is still working on a prompt.",
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": 18},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="chat"} | select(span.gen_ai.conversation.id, span.gen_ai.response.model)',
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
                            "matcher": {"id": "byName", "options": "gen_ai.conversation.id"},
                            "properties": [{"id": "displayName", "value": "Session ID"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.response.model"},
                            "properties": [{"id": "displayName", "value": "Model"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "duration"},
                            "properties": [{"id": "unit", "value": "ns"}, {"id": "displayName", "value": "Call Duration"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "traceIdHidden"},
                            "properties": [{"id": "custom.hidden", "value": True}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "service.name"},
                            "properties": [{"id": "custom.hidden", "value": True}],
                        },
                    ],
                },
                "timeFrom": "5m",
            },
            {
                "type": "table",
                "title": "Recent Tool Calls (last 5 min)",
                "description": "Tool execution spans. Recent tool activity with no completed turn = session still working.",
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": 18},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name=~"execute_tool.*"} | select(span.gen_ai.conversation.id, span.gen_ai.tool.name)',
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
                            "matcher": {"id": "byName", "options": "gen_ai.conversation.id"},
                            "properties": [{"id": "displayName", "value": "Session ID"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "gen_ai.tool.name"},
                            "properties": [{"id": "displayName", "value": "Tool"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "duration"},
                            "properties": [{"id": "unit", "value": "ns"}, {"id": "displayName", "value": "Exec Duration"}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "traceIdHidden"},
                            "properties": [{"id": "custom.hidden", "value": True}],
                        },
                        {
                            "matcher": {"id": "byName", "options": "service.name"},
                            "properties": [{"id": "custom.hidden", "value": True}],
                        },
                    ],
                },
                "timeFrom": "5m",
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
print(f"Dashboard created: http://localhost:3000{result['url']}")
print(f"Status: {result['status']}")
