#!/usr/bin/env python3
"""
Builds the "Claude Code - Usage" dashboard.

Every panel is driven by the four counters Claude Code actually emits:
    claude_code_token_usage_tokens_total    labels: type{input,output,cacheCreation,cacheRead}, model, query_source
    claude_code_cost_usage_USD_total        labels: model, query_source
    claude_code_session_count_total         labels: start_type{fresh,resume}
    claude_code_active_time_seconds_total   labels: type{cli,user}
plus, on all of them: host_name, session_id, terminal_type, service_version, effort.

All four are cumulative counters, so windows use increase() rather than raw values --
raw values would show a monotonically rising line that says nothing about a time range.

Usage (homelab):
    GRAFANA_URL=http://192.168.30.10:3000 GRAFANA_TOKEN=<service-account-token> \
        python3 create-usage-dashboard.py

    # or with basic auth
    GRAFANA_URL=http://192.168.30.10:3000 GRAFANA_USER=admin GRAFANA_PASSWORD=... \
        python3 create-usage-dashboard.py

Datasource UIDs default to the merged homelab Grafana's CLI-telemetry datasources.
On that instance the bare literals prometheus/loki mean the CLI backends; the LAB
backends have generated UIDs. See the homelab repo's datasources.yml.
"""
import base64
import json
import os
import urllib.request

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN")
GRAFANA_USER = os.environ.get("GRAFANA_USER")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD")

PROM = os.environ.get("PROM_UID", "prometheus")
LOKI = os.environ.get("LOKI_UID", "loki")
DASH_UID = "claude-usage"

# Label selector applied to every query, driven by the template variables.
#
# `job` is the CLI-vs-app discriminator, and it is the ONLY reliable one:
#   job="claude-code"          -> Claude Code CLI      (service_name is ABSENT, terminal=visualstudio)
#   job="claude-code-desktop"  -> Claude desktop app   (terminal=non-interactive)
# service_name cannot be used for this -- it is missing entirely on CLI series. Verified present on
# all four claude_code_* metrics.
SEL = 'job=~"$client", host_name=~"$host", model=~"$model"'
SEL_NOMODEL = 'job=~"$client", host_name=~"$host"'   # session/active-time carry no model label

_y = 0


def row(title):
    """A collapsed-header row. Grafana lays panels out by gridPos; rows just group them."""
    global _y
    p = {"type": "row", "title": title, "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y},
         "collapsed": False, "panels": []}
    _y += 1
    return p


def prom(expr, legend="", instant=False):
    return {"refId": "A", "datasource": {"type": "prometheus", "uid": PROM},
            "expr": expr, "legendFormat": legend, "instant": instant,
            "range": not instant, "format": "table" if instant else "time_series"}


def stat(title, expr, unit, x, w, decimals=None, color="text"):
    global _y
    fc = {"defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": color},
                       "thresholds": {"mode": "absolute", "steps": [{"color": color, "value": None}]}},
          "overrides": []}
    if decimals is not None:
        fc["defaults"]["decimals"] = decimals
    return {"type": "stat", "title": title, "gridPos": {"h": 4, "w": w, "x": x, "y": _y},
            "datasource": {"type": "prometheus", "uid": PROM},
            "targets": [prom(expr)],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "textMode": "auto", "graphMode": "area", "colorMode": "value",
                        "justifyMode": "auto"},
            "fieldConfig": fc}


def ts(title, targets, unit, x, y, w, h, stack=False, style="bars", legend="table"):
    return {"type": "timeseries", "title": title,
            "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "datasource": {"type": "prometheus", "uid": PROM},
            "targets": targets,
            "options": {"legend": {"displayMode": legend, "placement": "right" if legend == "table" else "bottom",
                                   "showLegend": True,
                                   "calcs": ["sum"] if legend == "table" else []},
                        "tooltip": {"mode": "multi", "sort": "desc"}},
            "fieldConfig": {"defaults": {"unit": unit,
                                         "color": {"mode": "palette-classic"},
                                         "custom": {"drawStyle": style, "lineWidth": 1,
                                                    "fillOpacity": 70 if style == "bars" else 10,
                                                    "stacking": {"mode": "normal" if stack else "none"},
                                                    "showPoints": "never",
                                                    "barAlignment": 0}},
                            "overrides": []}}


def pie(title, expr, legend, unit, x, y, w, h):
    return {"type": "piechart", "title": title, "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "datasource": {"type": "prometheus", "uid": PROM},
            "targets": [prom(expr, legend)],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "pieType": "donut", "displayLabels": ["percent"],
                        "legend": {"displayMode": "table", "placement": "right",
                                   "showLegend": True, "values": ["value"]},
                        "tooltip": {"mode": "single"}},
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"}},
                            "overrides": []}}


def bars(title, expr, legend, unit, x, y, w, h):
    return {"type": "bargauge", "title": title, "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "datasource": {"type": "prometheus", "uid": PROM},
            "targets": [prom(expr, legend)],
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "orientation": "horizontal", "displayMode": "gradient",
                        "showUnfilled": True, "valueMode": "color"},
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "continuous-GrYlRd"}},
                            "overrides": []}}


def table(title, targets, x, y, w, h, overrides=None, renames=None):
    p = {"type": "table", "title": title, "gridPos": {"h": h, "w": w, "x": x, "y": y},
         "datasource": {"type": "prometheus", "uid": PROM},
         "targets": targets,
         "options": {"showHeader": True, "footer": {"show": False},
                     "sortBy": [{"displayName": "Cost (USD)", "desc": True}]},
         "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True}},
                         "overrides": overrides or []},
         "transformations": [
             {"id": "joinByField", "options": {"byField": "Time", "mode": "outer"}},
             {"id": "organize", "options": {"excludeByName": {"Time": True},
                                            "renameByName": renames or {}}},
         ]}
    return p


panels = []

# ── Overview ────────────────────────────────────────────────────────────────────
panels.append(row("Overview — selected time range"))
panels += [
    stat("Cost", f'sum(increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))',
         "currencyUSD", 0, 4, decimals=2, color="green"),
    stat("Tokens", f'sum(increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__range]))',
         "short", 4, 4, color="blue"),
    # NOT increase(): session_count_total carries session_id, so every series appears once with a
    # constant value and increase() over any window is 0. Counting distinct session_ids that
    # reported in the window is what "how many sessions" actually means.
    stat("Sessions",
         f'count(count by (session_id) (last_over_time(claude_code_token_usage_tokens_total{{{SEL}}}[$__range])))',
         "short", 8, 3, color="purple"),
    # Claude Code's own "active time". It measures something much narrower than wall-clock --
    # observed at ~6 minutes against $8 of spend -- so it is NOT a usable denominator for a
    # cost-per-hour figure. Shown as-is, labelled for what it is.
    stat("Active time (as reported)",
         f'sum(increase(claude_code_active_time_seconds_total{{{SEL_NOMODEL}}}[$__range]))',
         "s", 11, 4, color="orange"),
    # Cache hit rate: cached reads as a share of everything that could have been a fresh
    # input read. High is good and directly reduces cost.
    stat("Cache hit rate",
         f'sum(increase(claude_code_token_usage_tokens_total{{{SEL}, type="cacheRead"}}[$__range])) / '
         f'clamp_min(sum(increase(claude_code_token_usage_tokens_total{{{SEL}, type=~"cacheRead|input"}}[$__range])), 1)',
         "percentunit", 15, 4, decimals=1, color="yellow"),
    stat("Cost / 1M tokens",
         f'sum(increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range])) / '
         f'clamp_min(sum(increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__range])) / 1e6, 0.000001)',
         "currencyUSD", 19, 3, decimals=2, color="red"),
    stat("Avg cost / session",
         f'sum(increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range])) / '
         f'clamp_min(count(count by (session_id) (last_over_time(claude_code_token_usage_tokens_total{{{SEL}}}[$__range]))), 1)',
         "currencyUSD", 22, 2, decimals=2, color="red"),
]
_y += 4

# ── Cost ────────────────────────────────────────────────────────────────────────
panels.append(row("Cost"))
panels += [
    ts("Cost over time, by model",
       [prom(f'sum by (model) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__interval]))', "{{model}}")],
       "currencyUSD", 0, _y, 14, 8, stack=True),
    pie("Cost share by model",
        f'sum by (model) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))',
        "{{model}}", "currencyUSD", 14, _y, 10, 8),
]
_y += 8
panels += [
    bars("Cost by machine",
         f'sum by (host_name) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))',
         "{{host_name}}", "currencyUSD", 0, _y, 8, 6),
    bars("Cost by query source (main vs background)",
         f'sum by (query_source) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))',
         "{{query_source}}", "currencyUSD", 8, _y, 8, 6),
    bars("Cost by terminal",
         f'sum by (terminal_type) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))',
         "{{terminal_type}}", "currencyUSD", 16, _y, 8, 6),
]
_y += 6

# ── Tokens ──────────────────────────────────────────────────────────────────────
panels.append(row("Tokens"))
panels += [
    ts("Tokens over time, by type",
       [prom(f'sum by (type) (increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__interval]))', "{{type}}")],
       "short", 0, _y, 14, 8, stack=True),
    pie("Token mix by type",
        f'sum by (type) (increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__range]))',
        "{{type}}", "short", 14, _y, 10, 8),
]
_y += 8
panels += [
    ts("Output tokens over time, by model  (the part you actually pay most for)",
       [prom(f'sum by (model) (increase(claude_code_token_usage_tokens_total{{{SEL}, type="output"}}[$__interval]))',
             "{{model}}")],
       "short", 0, _y, 14, 7, stack=True),
    bars("Tokens by model",
         f'sum by (model) (increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__range]))',
         "{{model}}", "short", 14, _y, 10, 7),
]
_y += 7

# ── Sessions & activity ─────────────────────────────────────────────────────────
panels.append(row("Sessions & activity"))
panels += [
    # Counts distinct sessions seen per interval, by how they began. increase() reads 0 here
    # (see the Sessions stat above), so count-of-series is the correct construction.
    ts("Sessions seen, by start type (fresh vs resumed)",
       [prom('count by (start_type) (count by (session_id, start_type) '
             f'(last_over_time(claude_code_session_count_total{{{SEL_NOMODEL}}}[$__interval])))',
             "{{start_type}}")],
       "short", 0, _y, 12, 7, stack=True),
    ts("Active time as reported, by type  (cli = tool work, user = you; undercounts wall-clock)",
       [prom(f'sum by (type) (increase(claude_code_active_time_seconds_total{{{SEL_NOMODEL}}}[$__interval]))',
             "{{type}}")],
       "s", 12, _y, 12, 7, stack=True),
]
_y += 7
panels += [
    table("Most expensive sessions",
          [prom(f'topk(20, sum by (session_id, host_name) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range])))',
                "", instant=True),
           dict(prom(f'sum by (session_id, host_name) (increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__range]))',
                     "", instant=True), refId="B")],
          0, _y, 24, 10,
          renames={"session_id": "Session", "host_name": "Machine",
                   "Value #A": "Cost (USD)", "Value #B": "Tokens"},
          overrides=[
              {"matcher": {"id": "byName", "options": "Cost (USD)"},
               "properties": [{"id": "unit", "value": "currencyUSD"},
                              {"id": "decimals", "value": 3},
                              {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}]},
              {"matcher": {"id": "byName", "options": "Tokens"},
               "properties": [{"id": "unit", "value": "short"}]},
          ]),
]
_y += 10

# ── Machines ────────────────────────────────────────────────────────────────────
panels.append(row("Machines"))
panels += [
    ts("Cost over time, by machine",
       [prom(f'sum by (host_name) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__interval]))',
             "{{host_name}}")],
       "currencyUSD", 0, _y, 12, 7, stack=True),
    table("Per-machine totals",
          [prom(f'sum by (host_name) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))', "", instant=True),
           dict(prom(f'sum by (host_name) (increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__range]))', "", instant=True), refId="B"),
           dict(prom(f'count by (host_name) (count by (session_id, host_name) (last_over_time(claude_code_token_usage_tokens_total{{{SEL}}}[$__range])))', "", instant=True), refId="C"),
           dict(prom(f'sum by (host_name) (increase(claude_code_active_time_seconds_total{{{SEL_NOMODEL}}}[$__range]))', "", instant=True), refId="D")],
          12, _y, 12, 7,
          renames={"host_name": "Machine", "Value #A": "Cost (USD)", "Value #B": "Tokens",
                   "Value #C": "Sessions", "Value #D": "Active time"},
          overrides=[
              {"matcher": {"id": "byName", "options": "Cost (USD)"},
               "properties": [{"id": "unit", "value": "currencyUSD"}, {"id": "decimals", "value": 2}]},
              {"matcher": {"id": "byName", "options": "Active time"},
               "properties": [{"id": "unit", "value": "s"}]},
          ]),
]
_y += 7

# ── Logs ────────────────────────────────────────────────────────────────────────
# ── CLI vs app ──────────────────────────────────────────────────────────────────
panels.append(row("CLI vs desktop app"))
panels += [
    ts("Cost over time, by client",
       [prom(f'sum by (job) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__interval]))', "{{job}}")],
       "currencyUSD", 0, _y, 12, 7, stack=True),
    ts("Tokens over time, by client",
       [prom(f'sum by (job) (increase(claude_code_token_usage_tokens_total{{{SEL}}}[$__interval]))', "{{job}}")],
       "short", 12, _y, 12, 7, stack=True),
]
_y += 7
panels += [
    pie("Cost share: CLI vs app",
        f'sum by (job) (increase(claude_code_cost_usage_USD_total{{{SEL}}}[$__range]))',
        "{{job}}", "currencyUSD", 0, _y, 8, 7),
    bars("Sessions by client",
         f'count by (job) (count by (session_id, job) (last_over_time(claude_code_token_usage_tokens_total{{{SEL}}}[$__range])))',
         "{{job}}", "short", 8, _y, 8, 7),
    bars("Cache hit rate by client",
         f'sum by (job) (increase(claude_code_token_usage_tokens_total{{{SEL}, type="cacheRead"}}[$__range])) / '
         f'clamp_min(sum by (job) (increase(claude_code_token_usage_tokens_total{{{SEL}, type=~"cacheRead|input"}}[$__range])), 1)',
         "{{job}}", "percentunit", 16, _y, 8, 7),
]
_y += 7

panels.append(row("Recent activity (logs)"))
panels.append({
    "type": "logs", "title": "Claude Code / Copilot events",
    "gridPos": {"h": 11, "w": 24, "x": 0, "y": _y},
    "datasource": {"type": "loki", "uid": LOKI},
    "targets": [{"refId": "A", "datasource": {"type": "loki", "uid": LOKI},
                 "expr": '{service_name=~"claude-code.*|copilot.*"}',
                 "queryType": "range"}],
    "options": {"showTime": True, "showLabels": False, "showCommonLabels": False,
                "wrapLogMessage": True, "prettifyLogMessage": False,
                "enableLogDetails": True, "dedupStrategy": "none",
                "sortOrder": "Descending"},
})

dashboard = {
    "uid": DASH_UID,
    "title": "Claude Code - Usage",
    "tags": ["claude", "usage", "cost", "genai"],
    "timezone": "browser",
    "refresh": "1m",
    "time": {"from": "now-7d", "to": "now"},
    "graphTooltip": 1,   # shared crosshair
    "templating": {"list": [
        {"name": "client", "label": "Client", "type": "query",
         "datasource": {"type": "prometheus", "uid": PROM},
         "definition": "label_values(claude_code_cost_usage_USD_total, job)",
         "query": {"query": "label_values(claude_code_cost_usage_USD_total, job)", "refId": "A"},
         "multi": True, "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"},
         "refresh": 2, "sort": 1},
        {"name": "host", "label": "Machine", "type": "query",
         "datasource": {"type": "prometheus", "uid": PROM},
         "definition": "label_values(claude_code_cost_usage_USD_total, host_name)",
         "query": {"query": "label_values(claude_code_cost_usage_USD_total, host_name)", "refId": "A"},
         "multi": True, "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"},
         "refresh": 2, "sort": 1},
        {"name": "model", "label": "Model", "type": "query",
         "datasource": {"type": "prometheus", "uid": PROM},
         "definition": "label_values(claude_code_cost_usage_USD_total, model)",
         "query": {"query": "label_values(claude_code_cost_usage_USD_total, model)", "refId": "A"},
         "multi": True, "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"},
         "refresh": 2, "sort": 1},
    ]},
    "panels": panels,
    "schemaVersion": 39,
}

payload = {"dashboard": dashboard, "overwrite": True,
           "message": "generated by create-usage-dashboard.py"}

req = urllib.request.Request(
    f"{GRAFANA_URL}/api/dashboards/db",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
if GRAFANA_TOKEN:
    req.add_header("Authorization", f"Bearer {GRAFANA_TOKEN}")
elif GRAFANA_USER:
    basic = base64.b64encode(f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode()).decode()
    req.add_header("Authorization", f"Basic {basic}")

result = json.loads(urllib.request.urlopen(req).read())
print(f"status : {result.get('status')}")
print(f"url    : {GRAFANA_URL}{result.get('url')}")
print(f"panels : {len([p for p in panels if p['type'] != 'row'])} "
      f"({len([p for p in panels if p['type'] == 'row'])} rows)")
