# Azure Deployment: AI Coding Assistant OTel Stack

Deploy the Grafana observability stack (Grafana + Tempo + Prometheus + Loki) to Azure with certificate-based authentication for OTLP ingest and Entra ID OAuth for Grafana access. Supports both GitHub Copilot CLI and Claude Code telemetry.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Each Developer Machine                         │
│                                                 │
│  Copilot CLI ──┐                                │
│                ├──► Local OTel Collector         │
│  Claude Code ──┘    (localhost:4318)             │
│                       │ Bearer token             │
│  Certificate ──► Token Refresh (30 min)         │
│  (User Cert Store)    │                         │
│                       ▼                         │
└───────────────── HTTPS :4318 ───────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────┐
│  Azure VM (B2s v2 ~$61/mo)                      │
│                                                 │
│  nginx (TLS)                                    │
│  ├── :443  ──► Dashboard SPA + Grafana (Entra)  │
│  └── :4318 ──► OTel Collector (OIDC validation) │
│                   │                             │
│                   ├──► Tempo (traces)            │
│                   ├──► Prometheus (metrics)      │
│                   └──► Loki (logs)              │
│                                                 │
│  Session API (active/idle detection)            │
└─────────────────────────────────────────────────┘
```

## Security Model

- **Dashboard access**: Custom React SPA at `/dashboard/` served by nginx.
- **Grafana access**: Entra ID OAuth2. Only users in your tenant can sign in. Auto-assigned Admin role.
- **OTLP ingest**: Certificate-based client_credentials flow. Each machine has a certificate in the Windows user store. A scheduled task refreshes the OAuth2 token every 30 minutes. The server's OTel Collector validates tokens against Entra's JWKS endpoint (v1 issuer: `sts.windows.net`).
- **No static secrets**: Private keys live in the cert store. Tokens rotate automatically. Revoke a machine by removing its certificate from the app registration.

## Prerequisites

- Azure subscription
- Azure CLI (`az`) installed
- Az PowerShell module (`Install-Module Az`) for Entra setup
- Docker Desktop on the Azure VM and on each client machine
- PowerShell 7+ on client machines
- A custom domain you control (e.g. `otel.yourdomain.com`) for TLS certificates
- A client certificate installed in the Windows user cert store on each machine (can be shared across machines)

## Setup Steps

### Step 1: Create the Azure VM

```powershell
.\1-setup-azure-vm.ps1 `
    -ResourceGroup "rg-copilot-otel" `
    -Location "eastus" `
    -VmName "mycopilototel" `
    -CustomDomain "otel.andrewfaust.com"
```

Optional: lock OTLP to specific IPs with `-AllowOtlpFromIps "1.2.3.4","5.6.7.8"`.

### Step 2: Configure DNS

Create an A record in your DNS provider pointing to the VM's public IP:

| Type | Name | Value |
|------|------|-------|
| A | `otel` | `<VM's public IP address>` |

Wait for propagation, then verify:

```
nslookup otel.andrewfaust.com
```

This is required before step 4, because Let's Encrypt needs to reach your domain to issue a TLS certificate.

### Step 3: Create Entra App Registrations

Run once from any machine with the Az module, using your custom domain:

```powershell
.\2-setup-entra.ps1 `
    -TenantId "your-tenant-id" `
    -GrafanaUrl "https://otel.andrewfaust.com"
```

This creates two app registrations:
1. **Copilot OTel Ingest**: Used by machines to authenticate when pushing telemetry. Certificate-based, no secrets.
2. **Copilot OTel Grafana**: Used by Grafana for user sign-in via OAuth2.

Save the output values. You'll need them for the server `.env` file.

### Step 4: Deploy the Server Stack

Copy the server files to the VM:

```bash
scp -r azure-deploy/server/* azureuser@mycopilototel.eastus.cloudapp.azure.com:~/otel-stack/
```

SSH in and run the deploy script with your custom domain:

```bash
ssh azureuser@mycopilototel.eastus.cloudapp.azure.com
cd ~/otel-stack
bash deploy.sh otel.andrewfaust.com
```

The script will:
1. Install Docker and certbot
2. Get a Let's Encrypt TLS certificate
3. Prompt you to edit `.env` with your Entra values
4. Start the full stack

Create the `.env` file with your values:

```bash
cat > .env << 'EOF'
TENANT_ID=your-tenant-id
OTEL_CLIENT_ID=your-otel-client-id
GRAFANA_CLIENT_ID=your-grafana-client-id
GRAFANA_CLIENT_SECRET=your-grafana-client-secret
SERVER_DOMAIN=otel.yourdomain.com
GF_USERS_AUTO_ASSIGN_ORG_ROLE=Admin
LOOKBACK_HOURS=6
IDLE_GRACE_SECONDS=60
EOF
```

Then start the stack:

```bash
docker compose up -d
```

### Step 5: Deploy the Dashboard

Build the dashboard locally:

```bash
cd dashboard
npm install && npm run build
```

Copy the built files to the VM:

```bash
scp -r dashboard/dist/* azureuser@otel.yourdomain.com:~/otel-stack/dashboard/dist/
```

The dashboard is served at `https://otel.yourdomain.com/dashboard/`.

### Step 6: Set Up Each Client Machine

The client certificate must already be installed in `Cert:\CurrentUser\My` and uploaded to the Entra app registration's Certificates section. You can use a single certificate across all machines.

**Option A: Full setup (recommended for first machine)**

```powershell
cd azure-deploy\client

.\setup-client.ps1 `
    -TenantId "your-tenant-id" `
    -ClientId "your-otel-client-id" `
    -ServerUrl "https://otel.yourdomain.com" `
    -CertThumbprint "your-cert-thumbprint"
```

This generates a cert, uploads it to Entra, and does everything in Option B.

**Option B: Quick setup (recommended for additional machines)**

Copy these four files to a permanent directory (e.g. `C:\CopilotOtel`):
- `setup-machine.ps1`
- `refresh-token.ps1`
- `otel-collector-config.yaml`
- `docker-compose.yaml`

Then run:

```powershell
cd C:\CopilotOtel
.\setup-machine.ps1
```

No parameters needed. This will:
1. Find the certificate by subject name in the user cert store
2. Acquire an initial access token
3. Install a scheduled task to refresh the token every 30 minutes
4. Start a local OTel Collector (Docker) that forwards to Azure with auth
5. Set persistent user environment variables for both Copilot CLI and Claude Code

Environment variables set automatically:

| Variable | Value | Used By |
|----------|-------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Both |
| `OTEL_RESOURCE_ATTRIBUTES` | `host.name=<COMPUTERNAME>` | Both |
| `CLAUDE_CODE_ENABLE_TELEMETRY` | `1` | Claude Code |
| `OTEL_METRICS_EXPORTER` | `otlp` | Claude Code |
| `OTEL_LOGS_EXPORTER` | `otlp` | Claude Code |

Restart your terminal after setup for the env vars to take effect.

## Revoking a Machine

Remove the machine's certificate from the Entra app registration:

```
Azure Portal > App registrations > Copilot OTel Ingest > Certificates & secrets > Certificates
```

Delete the certificate for the machine. Its existing token will expire within 60-90 minutes, then it's locked out.

## File Structure

```
azure-deploy/
├── README.md                           # This file
├── 1-setup-azure-vm.ps1                # Create Azure VM
├── 2-setup-entra.ps1                   # Create Entra app registrations
├── server/
│   ├── .env.template                   # Configuration values (copy to .env)
│   ├── docker-compose.yaml             # All server services
│   ├── deploy.sh                       # Run on the VM to set up everything
│   ├── otel-collector-config.yaml      # Collector with OIDC auth (v1 issuer)
│   ├── nginx/nginx.conf                # TLS termination + dashboard SPA
│   ├── tempo/tempo-config.yaml         # Trace storage
│   ├── prometheus/prometheus.yaml       # Metrics storage
│   ├── loki/loki-config.yaml           # Log storage
│   ├── grafana/datasources.yaml        # Provisioned datasources
│   └── session-api/server.py           # Active/idle session detection
└── client/
    ├── setup-client.ps1                # Full client setup (generates cert)
    ├── setup-machine.ps1               # Quick setup (uses existing cert)
    ├── refresh-token.ps1               # Token refresh (runs via scheduled task)
    ├── otel-collector-config.yaml      # Local collector config
    └── docker-compose.yaml             # Local collector container
```

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| B2s v2 VM (2 vCPU, 8GB) | ~$61 |
| 32GB OS disk | included |
| Public IP (Standard) | ~$3 |
| Bandwidth (low volume) | ~$1 |
| **Total** | **~$65/mo** |

For a smaller deployment (1-3 devs), consider `Standard_B2ls_v2` (2 vCPU, 4GB, ~$30/mo) by passing `-VmSize "Standard_B2ls_v2"`.

## Troubleshooting

**Token refresh fails**: Check `Cert:\CurrentUser\My` has the certificate. Verify the thumbprint matches what's registered in Entra.

**Token file has BOM**: If you see "malformed jws: illegal base64 data at input byte 0", the token file has a UTF-8 BOM. The updated `refresh-token.ps1` uses `[System.IO.File]::WriteAllText()` to avoid this. Fix manually: `sed -i '1s/^\xEF\xBB\xBF//' ~/.otel-token/token`

**OIDC validation fails on server**: The `client_credentials` flow with `scope={clientId}/.default` returns a v1 token with issuer `https://sts.windows.net/{tenant}/`. The server collector config must use this v1 issuer URL, not the v2 URL (`login.microsoftonline.com/.../v2.0`).

**Port 4318 unreachable**: Check the NSG rule has `SourcePortRange=*` (not `4318`). Delete and recreate if needed: `az network nsg rule delete ... && az network nsg rule create ... --source-port-ranges '*'`

**Let's Encrypt fails**: Your custom domain must resolve to the VM's public IP before running `deploy.sh`. Port 80 must be open during initial cert generation. If retrying after a failure, use `--force-renewal`.

**Grafana shows "Page not found" at /dashboard**: Use `/dashboard/` with trailing slash. The nginx config includes a redirect from `/dashboard` to `/dashboard/`.

**Grafana user stuck as Viewer**: Set `GF_USERS_AUTO_ASSIGN_ORG_ROLE=Admin` in `.env`. If the user already exists, delete the Grafana volume and recreate: `docker compose down grafana && docker volume rm otel-stack_grafana-data && docker compose up -d grafana`

**Docker volume path error on WSL**: The `.env` file may have Windows paths (e.g. `C:/Users/...`). Convert to WSL paths: `sed -i 's|C:/Users/username|/mnt/c/Users/username|' .env`

**SCP permission denied**: Docker may have created directories as root. Fix with `sudo chown -R $USER:$USER ~/otel-stack/dashboard/`

**Windows line endings**: Files SCP'd from Windows may have `\r\n`. Fix with `sed -i 's/\r$//' filename`
