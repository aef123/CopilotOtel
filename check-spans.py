import json, urllib.request

body = json.dumps({
    "queries": [{
        "refId": "A",
        "datasource": {"type": "tempo", "uid": "P214B5B846CF3925F"},
        "queryType": "traceql",
        "query": '{resource.service.name="github-copilot" && name="chat"} | select(span.gen_ai.conversation.id, span.gen_ai.response.model)',
        "tableType": "spans",
    }],
    "from": "now-1h",
    "to": "now",
}).encode()
req = urllib.request.Request("http://localhost:3000/api/ds/query", data=body, headers={"Content-Type": "application/json"}, method="POST")
result = json.loads(urllib.request.urlopen(req).read())
fields = result["results"]["A"]["frames"][0]["schema"]["fields"]
data = result["results"]["A"]["frames"][0]["data"]
print("Fields:", [f["name"] for f in fields])
rows = len(data["values"][0])
for r in range(max(0, rows-3), rows):
    row = {fields[i]["name"]: data["values"][i][r] for i in range(len(fields))}
    print(f"Row {r}:", json.dumps(row, indent=2))
