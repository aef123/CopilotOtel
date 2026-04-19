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
                "gridPos": {"h": 16, "w": 24, "x": 0, "y": 0},
                "datasource": {"type": "tempo", "uid": TEMPO_UID},
                "targets": [
                    # Query A: completed turns (invoke_agent)
                    {
                        "refId": "A",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id, span.gen_ai.agent.version)',
                        "tableType": "spans",
                    },
                    # Query B: child span activity (chat + tools)
                    {
                        "refId": "B",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name!="invoke_agent" && name!="permission"} | select(span.gen_ai.conversation.id)',
                        "tableType": "spans",
                    },
                ],
                "transformations": [
                    # Group A (invoke_agent) by session: get last completed turn time
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
                    # Merge frames from both queries into one table
                    {
                        "id": "merge",
                        "options": {},
                    },
                    # Now we have two "time (max)" columns if both queries
                    # returned data for the same session. But merge may not
                    # align perfectly. Let's try a different strategy.
                ],
                "options": {
                    "showHeader": True,
                    "sortBy": [{"displayName": "Last Activity", "desc": True}],
                },
                "fieldConfig": {
                    "defaults": {
                        "custom": {"align": "auto", "filterable": True},
                    },
                    "overrides": [],
                },
            },
        ],
    },
    "overwrite": True,
}

# Actually, let me test the transformation approach more carefully
# by checking what each query returns independently first.
print("Testing query responses first...")

for label, query in [
    ("invoke_agent", '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id)'),
    ("children", '{resource.service.name="github-copilot" && name!="invoke_agent" && name!="permission"} | select(span.gen_ai.conversation.id)'),
]:
    body = json.dumps({
        "queries": [{
            "refId": "A",
            "datasource": {"type": "tempo", "uid": TEMPO_UID},
            "queryType": "traceql",
            "query": query,
            "tableType": "spans",
        }],
        "from": "now-15m",
        "to": "now",
    }).encode()
    req = urllib.request.Request("http://localhost:3000/api/ds/query", data=body, headers={"Content-Type": "application/json"}, method="POST")
    result = json.loads(urllib.request.urlopen(req).read())
    frames = result["results"]["A"].get("frames", [])
    if frames:
        fields = frames[0]["schema"]["fields"]
        data = frames[0]["data"]
        rows = len(data["values"][0])
        print(f"\n{label}: {rows} rows")
        print(f"  Fields: {[f['name'] for f in fields]}")
        # Show latest timestamp per session
        from collections import defaultdict
        sessions = defaultdict(list)
        for r in range(rows):
            sid_idx = next(i for i, f in enumerate(fields) if f["name"] == "gen_ai.conversation.id")
            time_idx = next(i for i, f in enumerate(fields) if f["name"] == "time")
            sid = data["values"][sid_idx][r]
            t = data["values"][time_idx][r]
            sessions[sid].append(t)
        for sid, times in sessions.items():
            print(f"  Session {sid[:12]}... latest_time={max(times)}")
    else:
        print(f"\n{label}: no data")
