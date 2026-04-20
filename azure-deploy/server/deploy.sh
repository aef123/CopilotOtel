#!/bin/bash
# Run this ON the Azure VM after SSH-ing in.
# Usage: bash deploy.sh <server-domain>
#
# Example: bash deploy.sh otel.andrewfaust.com

set -euo pipefail

DOMAIN="${1:?Usage: deploy.sh <server-domain>}"

echo "=== Installing Docker ==="
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in for group changes."
fi

echo "=== Installing Certbot ==="
if ! command -v certbot &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq certbot
fi

echo "=== Obtaining Let's Encrypt certificate ==="
# Create the shared Docker volume for certs
docker volume create letsencrypt || true

# Get cert using standalone mode (needs port 80 open temporarily)
sudo certbot certonly --standalone \
    --non-interactive \
    --agree-tos \
    --email "admin@${DOMAIN}" \
    -d "${DOMAIN}"

# Copy certs into Docker volume
CERT_DIR="/etc/letsencrypt"
docker run --rm \
    -v letsencrypt:/target \
    -v "${CERT_DIR}:${CERT_DIR}:ro" \
    alpine sh -c "cp -rL ${CERT_DIR}/live /target/live && cp -rL ${CERT_DIR}/archive /target/archive"

echo "=== Updating nginx config with domain ==="
sed -i "s/SERVER_DOMAIN/${DOMAIN}/g" nginx/nginx.conf

echo "=== Starting stack ==="
# Copy .env.template to .env if not exists
if [ ! -f .env ]; then
    cp .env.template .env
    echo ""
    echo "*** IMPORTANT: Edit .env with your Entra IDs before continuing ***"
    echo "    Then re-run: docker compose up -d"
    exit 0
fi

docker compose up -d

echo ""
echo "=== Deployment complete ==="
echo "Grafana:  https://${DOMAIN}"
echo "OTLP:    https://${DOMAIN}:4318"
echo ""
echo "Next: run create-mission-control-v4.py against https://${DOMAIN} to push dashboards."
