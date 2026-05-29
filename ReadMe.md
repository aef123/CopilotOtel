# OtelCliCapture

OpenTelemetry pipeline + dashboard for **Claude Code** and **GitHub Copilot CLI**
session telemetry.

## Docs

- **[Machine setup & updates](docs/machine-setup.md)** — first-time setup *and*
  updates for a machine, so Claude and Copilot both report correctly, side by side.
- [Azure deployment (server stack)](azure-deploy/README.md) — stand up the
  Grafana/Tempo/Prometheus/Loki stack and Entra apps from scratch.
- [session-watcher daemon](session-watcher/README.md) — the per-machine daemon
  that emits session-lifecycle telemetry for both tools.
</content>
