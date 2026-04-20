#Requires -Modules Az.Accounts, Az.Resources
<#
.SYNOPSIS
    Creates two Entra ID app registrations:
    1. "Copilot OTel Ingest" - for machine-to-server OTLP authentication (certificate-based)
    2. "Copilot OTel Grafana" - for user sign-in to Grafana (OAuth2)

.DESCRIPTION
    Run this once from any machine with the Az PowerShell module.
    Save the output values into your server's .env file.
#>

param(
    [Parameter(Mandatory)]
    [string]$TenantId,

    [string]$OtelAppName = "Copilot OTel Ingest",
    [string]$GrafanaAppName = "Copilot OTel Grafana",

    [Parameter(Mandatory, HelpMessage = "The public URL of your Grafana server, e.g. https://myotel.eastus.cloudapp.azure.com")]
    [string]$GrafanaUrl
)

$ErrorActionPreference = "Stop"

# Connect if not already
$context = Get-AzContext -ErrorAction SilentlyContinue
if (-not $context -or $context.Tenant.Id -ne $TenantId) {
    Connect-AzAccount -TenantId $TenantId
}

# ──────────────────────────────────────────────
# App 1: OTLP Ingest (certificate auth, no UI)
# ──────────────────────────────────────────────
Write-Host "`n=== Creating '$OtelAppName' ===" -ForegroundColor Cyan

$otelApp = New-AzADApplication -DisplayName $OtelAppName -SignInAudience AzureADMyOrg

# Set accessTokenAcceptedVersion to 2 so tokens use v2 issuer format
# (Required for the OTel Collector's OIDC extension to validate tokens)
$apiBody = @{
    api = @{
        requestedAccessTokenVersion = 2
    }
}
# The Az module doesn't expose this directly; use REST
$token = (Get-AzAccessToken -ResourceUrl "https://graph.microsoft.com").Token
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
Invoke-RestMethod -Uri "https://graph.microsoft.com/v1.0/applications/$($otelApp.Id)" `
    -Method PATCH -Headers $headers `
    -Body ($apiBody | ConvertTo-Json -Depth 5)

# Create service principal
New-AzADServicePrincipal -ApplicationId $otelApp.AppId | Out-Null

Write-Host "  App ID (Client ID): $($otelApp.AppId)"
Write-Host "  Object ID:          $($otelApp.Id)"
Write-Host "  Certificates:       (upload machine certs later with client/setup-client.ps1)"

# ──────────────────────────────────────────────
# App 2: Grafana OAuth (user sign-in)
# ──────────────────────────────────────────────
Write-Host "`n=== Creating '$GrafanaAppName' ===" -ForegroundColor Cyan

$redirectUri = "$GrafanaUrl/login/azuread"

$grafanaApp = New-AzADApplication `
    -DisplayName $GrafanaAppName `
    -SignInAudience AzureADMyOrg `
    -Web @{ RedirectUris = @($redirectUri) }

# Create a client secret (valid 1 year)
$secret = New-AzADAppCredential -ApplicationId $grafanaApp.AppId -EndDate (Get-Date).AddYears(1)

# Create service principal
New-AzADServicePrincipal -ApplicationId $grafanaApp.AppId | Out-Null

Write-Host "  App ID (Client ID): $($grafanaApp.AppId)"
Write-Host "  Client Secret:      $($secret.SecretText)"
Write-Host "  Redirect URI:       $redirectUri"

# ──────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────
Write-Host "`n=== Copy these into server/.env ===" -ForegroundColor Green
Write-Host @"

TENANT_ID=$TenantId
OTEL_CLIENT_ID=$($otelApp.AppId)
GRAFANA_CLIENT_ID=$($grafanaApp.AppId)
GRAFANA_CLIENT_SECRET=$($secret.SecretText)
SERVER_DOMAIN=<your-vm-dns-label>.region.cloudapp.azure.com

"@

Write-Host "Save the OTEL_CLIENT_ID. You'll need it on each client machine." -ForegroundColor Yellow
