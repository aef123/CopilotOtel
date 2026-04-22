#!/bin/bash
# deploy-to-azure.sh
# Deploys dashboard, session-api, and Grafana dashboard to the Azure VM.
# Run from WSL.

set -euo pipefail

KEY=~/afaustOtel.pem
VM=azureuser@otel.andrewfaust.com
DEST=/home/azureuser/otel-stack
LOCAL=/mnt/c/git/OtelCliCapture

echo "=== Creating remote directories ==="
ssh -i $KEY $VM "mkdir -p $DEST/session-api $DEST/grafana/dashboards $DEST/dashboard/dist"

echo "=== Uploading session-api ==="
scp -i $KEY $LOCAL/azure-deploy/server/session-api/server.py $VM:$DEST/session-api/server.py

echo "=== Uploading docker-compose.yaml ==="
scp -i $KEY $LOCAL/azure-deploy/server/docker-compose.yaml $VM:$DEST/docker-compose.yaml

echo "=== Uploading Grafana dashboard provisioning ==="
scp -i $KEY $LOCAL/azure-deploy/server/grafana/dashboards/dashboards.yaml $VM:$DEST/grafana/dashboards/dashboards.yaml
scp -i $KEY $LOCAL/azure-deploy/server/grafana/dashboards/copilot-otel-metrics.json $VM:$DEST/grafana/dashboards/copilot-otel-metrics.json

echo "=== Uploading dashboard SPA ==="
scp -i $KEY -r $LOCAL/dashboard/dist/* $VM:$DEST/dashboard/dist/

echo "=== Restarting services ==="
ssh -i $KEY $VM "cd $DEST && docker compose up -d --force-recreate session-api grafana nginx"

echo "=== Done ==="
