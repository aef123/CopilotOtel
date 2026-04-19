import json
import urllib.request

TEMPO_UID = "P214B5B846CF3925F"
DASH_UID = "copilot-mission-control"

# Strategy: Two queries + joinByField
# Query A: invoke_agent spans → group by session → last completed turn time, turn count
# Query B: ALL child spans (last 2 min window) → group by session → if rows exist, session is active
# After join: sessions with child activity data = Active, without = Idle

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
                    # A: Completed turns (invoke_agent only, full time range)
                    {
                        "refId": "completed",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id, span.gen_ai.agent.version)',
                        "tableType": "spans",
                    },
                    # B: Recent child activity (chat + tools, last 2 min)
                    {
                        "refId": "active",
                        "datasource": {"type": "tempo", "uid": TEMPO_UID},
                        "queryType": "traceql",
                        "query": '{resource.service.name="github-copilot" && name!="invoke_agent" && name!="permission"} | select(span.gen_ai.conversation.id)',
                        "tableType": "spans",
                    },
                ],
                "transformations": [
                    # 1. Keep only the completed turns frame
                    {"id": "filterByRefId", "options": {"include": "completed"}},
                    # 2. Group by session
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
                    # 3. Rename and organize
                    {
                        "id": "organize",
                        "options": {
                            "renameByName": {
                                "gen_ai.conversation.id": "Session ID",
                                "gen_ai.agent.version (lastNotNull)": "CLI Version",
                                "time (max)": "Last Completed Turn",
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
                    "sortBy": [{"displayName": "Last Completed Turn", "desc": True}],
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
                            "matcher": {"id": "byName", "options": "Last Completed Turn"},
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

# Push it, then we'll iterate on active detection
data = json.dumps(dashboard).encode("utf-8")
req = urllib.request.Request(
    "http://localhost:3000/api/dashboards/db",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(f"Dashboard v3: http://localhost:3000{result['url']}")
print(f"Status: {result['status']}")

# Now test: can we get the active query's data separately?
# We'll check if we can detect sessions with child activity more recent
# than their last invoke_agent.
print("\n--- Checking active detection feasibility ---")

# Get completed turns grouped by session
body = json.dumps({
    "queries": [{
        "refId": "A",
        "datasource": {"type": "tempo", "uid": TEMPO_UID},
        "queryType": "traceql",
        "query": '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id)',
        "tableType": "spans",
    }],
    "from": "now-6h",
    "to": "now",
}).encode()
req = urllib.request.Request("http://localhost:3000/api/ds/query", data=body, headers={"Content-Type": "application/json"}, method="POST")
result = json.loads(urllib.request.urlopen(req).read())
fields = result["results"]["A"]["frames"][0]["schema"]["fields"]
vals = result["results"]["A"]["frames"][0]["data"]["values"]

from collections import defaultdict
completed = defaultdict(int)  # session -> max completed time
fi = {f["name"]: i for i, f in enumerate(fields)}
for r in range(len(vals[0])):
    sid = vals[fi["gen_ai.conversation.id"]][r]
    t = vals[fi["time"]][r]
    if sid and t:
        completed[sid] = max(completed[sid], t)

# Get child activity
body = json.dumps({
    "queries": [{
        "refId": "B",
        "datasource": {"type": "tempo", "uid": TEMPO_UID},
        "queryType": "traceql",
        "query": '{resource.service.name="github-copilot" && name!="invoke_agent" && name!="permission"} | select(span.gen_ai.conversation.id)',
        "tableType": "spans",
    }],
    "from": "now-6h",
    "to": "now",
}).encode()
req = urllib.request.Request("http://localhost:3000/api/ds/query", data=body, headers={"Content-Type": "application/json"}, method="POST")
result = json.loads(urllib.request.urlopen(req).read())
frames = result["results"]["B"].get("frames", [])
children = defaultdict(int)
if frames:
    fields2 = frames[0]["schema"]["fields"]
    vals2 = frames[0]["data"]["values"]
    fi2 = {f["name"]: i for i, f in enumerate(fields2)}
    for r in range(len(vals2[0])):
        sid = vals2[fi2.get("gen_ai.conversation.id", -1)][r] if "gen_ai.conversation.id" in fi2 else None
        t = vals2[fi2["time"]][r]
        if sid and t:
            children[sid] = max(children[sid], t)

print("\nPer-session comparison:")
all_sessions = set(list(completed.keys()) + list(children.keys()))
for sid in all_sessions:
    c = completed.get(sid, 0)
    a = children.get(sid, 0)
    status = "ACTIVE (child > completed)" if a > c else "IDLE"
    print(f"  {sid[:16]}... completed={c} child={a} -> {status}")
