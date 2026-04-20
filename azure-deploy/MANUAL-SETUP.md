# Manual Azure Setup Guide

If you prefer to create Azure resources through the portal (or CLI) instead of running the setup scripts, here's everything you need.

## Azure Resources

### 1. Resource Group

- **Name**: `rg-copilot-otel` (or whatever you like)
- **Region**: your choice (e.g. East US)

### 2. Virtual Machine

- **Image**: Ubuntu 24.04 LTS
- **Size**: Standard_B2ls_v2 (2 vCPU, 4GB, ~$30/mo)
- **Auth**: SSH key
- **Admin user**: `azureuser`
- **Public IP**: Standard SKU
- **OS Disk**: 32GB (default)

### 3. Public IP

- **SKU**: Standard
- **Assignment**: Static (so the IP doesn't change on VM restart)
- No DNS label needed since you're using a custom domain

### 4. NSG Rules

Add these to the VM's network security group:

| Priority | Name | Port | Source | Protocol |
|----------|------|------|--------|----------|
| 1010 | AllowHTTPS | 443 | Any | TCP |
| 1020 | AllowHTTP | 80 | Any | TCP |
| 1030 | AllowOTLP | 4318 | Any (or your IPs) | TCP |
| (default) | SSH | 22 | Any | TCP |

Port 80 is only needed for the initial Let's Encrypt certificate challenge. You can close it after.

## DNS (Your Provider)

Create an A record pointing your custom domain to the VM's public IP:

| Type | Name | Value |
|------|------|-------|
| A | `otel` | `<VM's public IP address>` |

Verify propagation before proceeding:

```
nslookup otel.andrewfaust.com
```

## Entra ID App Registrations

### App 1: "Copilot OTel Ingest" (machine-to-server auth)

- **Sign-in audience**: Single tenant (this org only)
- **Manifest**: Set `accessTokenAcceptedVersion` to `2`
- **Credentials**: Certificates only (added per-machine later by `setup-client.ps1`)
- **No redirect URIs needed**
- **Create a service principal** for the app

Save the **Application (client) ID**. This becomes `OTEL_CLIENT_ID`.

### App 2: "Copilot OTel Grafana" (user sign-in)

- **Sign-in audience**: Single tenant (this org only)
- **Redirect URI** (Web platform): `https://otel.andrewfaust.com/login/azuread`
- **Client secret**: Create one (1 year expiry is fine)
- **Create a service principal** for the app

Save the **Application (client) ID** as `GRAFANA_CLIENT_ID` and the **secret value** as `GRAFANA_CLIENT_SECRET`.

## Values Summary

These go into the server's `.env` file when you deploy the stack:

```
TENANT_ID=<your Azure AD tenant ID>
OTEL_CLIENT_ID=<App 1 client ID>
GRAFANA_CLIENT_ID=<App 2 client ID>
GRAFANA_CLIENT_SECRET=<App 2 secret value>
SERVER_DOMAIN=otel.andrewfaust.com
```

## Next Steps

Once all resources are created and DNS is propagating, continue with **Step 4: Deploy the Server Stack** in the [main README](README.md).
