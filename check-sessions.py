import json, urllib.request

# Get all invoke_agent spans to understand the mapping
body = json.dumps({
    "queries": [{
        "refId": "A",
        "datasource": {"type": "tempo", "uid": "P214B5B846CF3925F"},
        "queryType": "traceql",
        "query": '{resource.service.name="github-copilot" && name="invoke_agent"} | select(span.gen_ai.conversation.id, span.gen_ai.agent.version)',
        "tableType": "spans",
    }],
    "from": "now-6h",
    "to": "now",
}).encode()
req = urllib.request.Request("http://localhost:3000/api/ds/query", data=body, headers={"Content-Type": "application/json"}, method="POST")
result = json.loads(urllib.request.urlopen(req).read())
fields = result["results"]["A"]["frames"][0]["schema"]["fields"]
data = result["results"]["A"]["frames"][0]["data"]

rows = len(data["values"][0])
print(f"Total invoke_agent spans: {rows}\n")

# Group by conversation ID and show latest per session
from collections import defaultdict
sessions = defaultdict(list)
for r in range(rows):
    row = {fields[i]["name"]: data["values"][i][r] for i in range(len(fields))}
    sessions[row.get("gen_ai.conversation.id", "unknown")].append(row)

for sid, spans in sessions.items():
    spans.sort(key=lambda x: x["time"], reverse=True)
    latest = spans[0]
    dur_sec = latest["duration"] / 1e9
    print(f"Session: {sid}")
    print(f"  Turns (invoke_agent count): {len(spans)}")
    print(f"  Latest trace: {latest['traceIdHidden']}")
    print(f"  Latest time: {latest['time']}")
    print(f"  Latest duration: {dur_sec:.1f}s")
    print(f"  Version: {latest.get('gen_ai.agent.version', '?')}")
    print()
