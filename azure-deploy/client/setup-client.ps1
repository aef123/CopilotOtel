<#
.SYNOPSIS
    Sets up a client machine to push OTel telemetry to the Azure server.

.DESCRIPTION
    1. Generates a self-signed certificate (or uses an existing thumbprint)
    2. Exports the public key (.cer) for upload to the Entra app registration
    3. Uploads the certificate to the Entra app registration
    4. Creates the token directory and initial token
    5. Installs the token refresh scheduled task
    6. Starts the local OTel collector via Docker

.EXAMPLE
    .\setup-client.ps1 -TenantId "abc-123" -ClientId "def-456" -ServerUrl "https://myotel.eastus.cloudapp.azure.com"
#>

param(
    [Parameter(Mandatory)]
    [string]$TenantId,

    [Parameter(Mandatory, HelpMessage = "The OTEL_CLIENT_ID from the Entra app registration")]
    [string]$ClientId,

    [Parameter(Mandatory, HelpMessage = "e.g. https://myotel.eastus.cloudapp.azure.com")]
    [string]$ServerUrl,

    [string]$CertThumbprint,

    [string]$TokenDir = "$env:USERPROFILE\.otel-token",
    [string]$ScriptDir = $PSScriptRoot
)

$ErrorActionPreference = "Stop"

# ──────────────────────────────────────────────
# Step 1: Certificate
# ──────────────────────────────────────────────
if (-not $CertThumbprint) {
    Write-Host "=== Generating self-signed certificate ===" -ForegroundColor Cyan
    $cert = New-SelfSignedCertificate `
        -Subject "CN=CopilotOTelClient-$env:COMPUTERNAME" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddYears(2) `
        -KeyExportPolicy NonExportable

    $CertThumbprint = $cert.Thumbprint
    Write-Host "  Created certificate: $($cert.Subject)"
    Write-Host "  Thumbprint: $CertThumbprint"
} else {
    $cert = Get-ChildItem "Cert:\CurrentUser\My\$CertThumbprint"
    if (-not $cert) { throw "Certificate with thumbprint $CertThumbprint not found in Cert:\CurrentUser\My" }
    Write-Host "=== Using existing certificate ===" -ForegroundColor Cyan
    Write-Host "  Subject: $($cert.Subject)"
}

# ──────────────────────────────────────────────
# Step 2: Export public key
# ──────────────────────────────────────────────
$cerPath = Join-Path $ScriptDir "client-$env:COMPUTERNAME.cer"
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null
Write-Host "  Exported public key to: $cerPath"

# ──────────────────────────────────────────────
# Step 3: Upload cert to Entra app registration
# ──────────────────────────────────────────────
Write-Host "`n=== Uploading certificate to Entra app registration ===" -ForegroundColor Cyan
try {
    $context = Get-AzContext -ErrorAction SilentlyContinue
    if (-not $context -or $context.Tenant.Id -ne $TenantId) {
        Connect-AzAccount -TenantId $TenantId
    }

    $certBase64 = [Convert]::ToBase64String($cert.RawData)
    New-AzADAppCredential -ApplicationId $ClientId -CertValue $certBase64
    Write-Host "  Certificate uploaded successfully."
} catch {
    Write-Host "  Could not auto-upload certificate. Upload manually:" -ForegroundColor Yellow
    Write-Host "    Azure Portal > App registrations > Copilot OTel Ingest > Certificates > Upload"
    Write-Host "    File: $cerPath"
}

# ──────────────────────────────────────────────
# Step 4: Token directory and initial token
# ──────────────────────────────────────────────
Write-Host "`n=== Setting up token refresh ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $TokenDir -Force | Out-Null

$refreshScript = Join-Path $ScriptDir "refresh-token.ps1"
& $refreshScript -TenantId $TenantId -ClientId $ClientId -CertThumbprint $CertThumbprint -TokenFilePath "$TokenDir\token"
Write-Host "  Initial token acquired."

# ──────────────────────────────────────────────
# Step 5: Scheduled task for token refresh
# ──────────────────────────────────────────────
Write-Host "`n=== Installing scheduled task ===" -ForegroundColor Cyan
$taskName = "CopilotOTelTokenRefresh"

$action = New-ScheduledTaskAction `
    -Execute "pwsh.exe" `
    -Argument "-NoProfile -NonInteractive -File `"$refreshScript`" -TenantId `"$TenantId`" -ClientId `"$ClientId`" -CertThumbprint `"$CertThumbprint`" -TokenFilePath `"$TokenDir\token`""

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "  Scheduled task '$taskName' registered (runs every 30 minutes)."

# ──────────────────────────────────────────────
# Step 6: Create local collector config
# ──────────────────────────────────────────────
Write-Host "`n=== Configuring local OTel collector ===" -ForegroundColor Cyan

$collectorCompose = Join-Path $ScriptDir "docker-compose.yaml"
$collectorConfig = Join-Path $ScriptDir "otel-collector-config.yaml"

# Write the .env file for docker-compose
$envContent = @"
SERVER_URL=$ServerUrl
TOKEN_DIR=$($TokenDir -replace '\\','/')
"@
$envContent | Set-Content (Join-Path $ScriptDir ".env")

Write-Host "  Starting local collector..."
docker compose -f $collectorCompose up -d

# ──────────────────────────────────────────────
# Step 7: Configure Copilot CLI environment
# ──────────────────────────────────────────────
Write-Host "`n=== Environment variables for Copilot CLI ===" -ForegroundColor Green
Write-Host @"

Add these to your PowerShell profile ($PROFILE) or system environment:

  `$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
  `$env:OTEL_RESOURCE_ATTRIBUTES = "host.name=$env:COMPUTERNAME"

"@

Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "  Certificate thumbprint: $CertThumbprint"
Write-Host "  Token file:             $TokenDir\token"
Write-Host "  Token refresh:          Every 30 minutes via scheduled task"
Write-Host "  Local collector:        localhost:4317 (gRPC), localhost:4318 (HTTP)"
Write-Host "  Forwarding to:          $ServerUrl:4318"
