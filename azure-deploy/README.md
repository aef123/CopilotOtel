# Azure Deployment: Copilot CLI OTel Stack

Deploy the Grafana observability stack (Grafana + Tempo + Prometheus + Loki) to Azure with certificate-based authentication for OTLP ingest and Entra ID OAuth for Grafana access.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Each Developer Machine                         │
│                                                 │
│  Copilot CLI ──► Local OTel Collector           │
│  (localhost:4318)     │                         │
│                       │ Bearer token            │
│  Certificate ──► Token Refresh (30 min)         │
│  (User Cert Store)    │                         │
│                       ▼                         │
└───────────────── HTTPS :4318 ───────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────┐
│  Azure VM (B2s ~$13/mo)                         │
│                                                 │
│  nginx (TLS)                                    │
│  ├── :443  ──► Grafana (Entra OAuth)            │
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

- **Grafana access**: Entra ID OAuth2. Only users in your tenant can sign in.
- **OTLP ingest**: Certificate-based client_credentials flow. Each machine has a certificate in the Windows user store. A scheduled task refreshes the OAuth2 token every 30 minutes. The server's OTel Collector validates tokens against Entra's JWKS endpoint.
- **No static secrets**: Private keys live in the cert store (non-exportable). Tokens rotate automatically. Revoke a machine by removing its certificate from the app registration.

## Prerequisites

- Azure subscription
- Azure CLI (`az`) installed
- Az PowerShell module (`Install-Module Az`)
- Docker on the Azure VM and on each client machine
- PowerShell 7+ on client machines (for `New-SelfSignedCertificate` and crypto APIs)
- A custom domain you control (e.g. `otel.yourdomain.com`) for TLS certificates

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

Create a CNAME record in your DNS provider:

| Type | Name | Value |
|------|------|-------|
| CNAME | `otel` | `mycopilototel.eastus.cloudapp.azure.com` |

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

After editing `.env`, start the stack:

```bash
docker compose up -d
```

### Step 5: Push the Dashboards

From your local machine, update the dashboard scripts to point at your Azure Grafana:

```powershell
# You'll need to authenticate to Grafana first via browser, then use an API key
# Or temporarily allow anonymous admin for initial dashboard push
python create-mission-control-v4.py
python create-dashboard.py
```

### Step 6: Set Up Each Client Machine

Run on each developer machine:

```powershell
cd azure-deploy\client

.\setup-client.ps1 `
    -TenantId "your-tenant-id" `
    -ClientId "your-otel-client-id" `
    -ServerUrl "https://otel.andrewfaust.com"
```

This will:
1. Generate a certificate in the Windows user store (non-exportable private key)
2. Upload the public key to the Entra app registration
3. Acquire an initial token
4. Install a scheduled task to refresh the token every 30 minutes
5. Start a local OTel Collector that forwards telemetry to Azure

Then add to your PowerShell profile:

```powershell
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
$env:OTEL_RESOURCE_ATTRIBUTES = "host.name=$env:COMPUTERNAME"
```

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
│   ├── otel-collector-config.yaml      # Collector with OIDC auth
│   ├── nginx/nginx.conf                # TLS termination
│   ├── tempo/tempo-config.yaml         # Trace storage
│   ├── prometheus/prometheus.yaml       # Metrics storage
│   ├── loki/loki-config.yaml           # Log storage
│   ├── grafana/datasources.yaml        # Provisioned datasources
│   └── session-api/server.py           # Active/idle session detection
└── client/
    ├── setup-client.ps1                # One-time client setup
    ├── refresh-token.ps1               # Token refresh (runs via scheduled task)
    ├── otel-collector-config.yaml      # Local collector config
    └── docker-compose.yaml             # Local collector container
```

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| B2s VM (2 vCPU, 4GB) | ~$13 |
| 32GB OS disk | included |
| Public IP (Standard) | ~$3 |
| Bandwidth (low volume) | ~$1 |
| **Total** | **~$17/mo** |

## Troubleshooting

**Token refresh fails**: Check `Cert:\CurrentUser\My` has the certificate. Verify the thumbprint matches what's registered in Entra.

**OIDC validation fails on server**: Ensure `accessTokenAcceptedVersion: 2` is set on the Entra app manifest. The OTel OIDC extension requires v2 tokens.

**Let's Encrypt fails**: Your custom domain's CNAME must resolve to the VM's Azure FQDN before running `deploy.sh`. Port 80 must be open during initial cert generation. Verify with `nslookup your.domain.com`.

**Grafana OAuth loop**: Check `GF_SERVER_ROOT_URL` matches the actual URL including `https://`. The redirect URI in Entra must be `https://<domain>/login/azuread`.
