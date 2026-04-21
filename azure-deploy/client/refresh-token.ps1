<#
.SYNOPSIS
    Acquires an Entra ID access token using a certificate and writes it to a file.
    Designed to run as a scheduled task every 30 minutes.

.DESCRIPTION
    Authenticates using OAuth2 client_credentials flow with a JWT client assertion
    signed by a certificate from the Windows certificate store. No external dependencies.
    The OTel Collector's bearertokenauth extension reads the token from the output file.
#>

param(
    [Parameter(Mandatory)]
    [string]$TenantId,

    [Parameter(Mandatory)]
    [string]$ClientId,

    [Parameter(Mandatory)]
    [string]$CertThumbprint,

    [string]$TokenFilePath = "$env:USERPROFILE\.otel-token\token"
)

$ErrorActionPreference = "Stop"

function ConvertTo-Base64Url([byte[]]$bytes) {
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

# Load certificate from user store
$cert = Get-ChildItem "Cert:\CurrentUser\My\$CertThumbprint" -ErrorAction Stop
$privateKey = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)
if (-not $privateKey) {
    throw "Certificate $CertThumbprint has no accessible private key."
}

# Build JWT header with x5t (base64url-encoded SHA-1 thumbprint)
$thumbprintBytes = [byte[]]::new($cert.Thumbprint.Length / 2)
for ($i = 0; $i -lt $thumbprintBytes.Length; $i++) {
    $thumbprintBytes[$i] = [Convert]::ToByte($cert.Thumbprint.Substring($i * 2, 2), 16)
}
$x5t = ConvertTo-Base64Url $thumbprintBytes

$header = @{ alg = 'RS256'; typ = 'JWT'; x5t = $x5t } | ConvertTo-Json -Compress
$headerB64 = ConvertTo-Base64Url ([System.Text.Encoding]::UTF8.GetBytes($header))

# Build JWT payload
$now = [long]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
$payload = @{
    aud = "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token"
    iss = $ClientId
    sub = $ClientId
    jti = [Guid]::NewGuid().ToString()
    nbf = $now
    exp = $now + 300
} | ConvertTo-Json -Compress
$payloadB64 = ConvertTo-Base64Url ([System.Text.Encoding]::UTF8.GetBytes($payload))

# Sign the JWT
$dataToSign = [System.Text.Encoding]::UTF8.GetBytes("$headerB64.$payloadB64")
$signature = $privateKey.SignData(
    $dataToSign,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256,
    [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
)
$sigB64 = ConvertTo-Base64Url $signature

$clientAssertion = "$headerB64.$payloadB64.$sigB64"

# Request access token
$body = @{
    client_id             = $ClientId
    client_assertion_type = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
    client_assertion      = $clientAssertion
    grant_type            = 'client_credentials'
    scope                 = "$ClientId/.default"
}

$response = Invoke-RestMethod `
    -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
    -Method POST `
    -Body $body `
    -ContentType "application/x-www-form-urlencoded"

# Write token to file (atomic write via temp file + move)
$parentDir = Split-Path $TokenFilePath -Parent
if (-not (Test-Path $parentDir)) { New-Item -ItemType Directory -Path $parentDir -Force | Out-Null }

$tempFile = "$TokenFilePath.tmp"
[System.IO.File]::WriteAllText($tempFile, $response.access_token)
Move-Item -Path $tempFile -Destination $TokenFilePath -Force

Write-Host "Token refreshed at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'). Expires in $($response.expires_in)s."
