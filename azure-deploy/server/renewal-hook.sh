#!/bin/bash
# Certbot deploy hook — installed to /etc/letsencrypt/renewal-hooks/deploy/.
#
# nginx mounts the `letsencrypt` Docker volume, NOT /etc/letsencrypt. Certbot
# renews the host path only, so without this hook a renewal is invisible to
# nginx and it keeps serving the old cert until it expires. That is exactly
# what happened Jul 20 2026: the Jun 20 renewal succeeded on the host while
# the volume still held the April cert.
#
# Runs as root, only after a certificate actually renews.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/home/azureuser/otel-stack}"

log() { logger -t certbot-deploy-hook "$*"; echo "[certbot-deploy-hook] $*"; }

log "renewal detected; syncing certs into the letsencrypt Docker volume"

# -aL dereferences live/ symlinks into real files and preserves the 0600 on
# privkey.pem. The rm is required: cp fails against the populated volume.
docker run --rm \
    -v letsencrypt:/target \
    -v /etc/letsencrypt:/etc/letsencrypt:ro \
    alpine sh -c 'rm -rf /target/live /target/archive \
                  && cp -aL /etc/letsencrypt/live /target/live \
                  && cp -aL /etc/letsencrypt/archive /target/archive'

log "volume synced; reloading nginx"

# Don't fail the hook if nginx happens to be down — the cert is already in the
# volume and will be picked up whenever it next starts.
if docker compose -f "${COMPOSE_DIR}/docker-compose.yaml" exec -T nginx nginx -s reload; then
    log "nginx reloaded"
else
    log "WARNING: nginx reload failed (container down?); cert is staged in the volume"
fi
