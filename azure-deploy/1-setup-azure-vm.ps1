<#
.SYNOPSIS
    Creates a small Azure VM to host the OTel/Grafana stack.

.DESCRIPTION
    Creates a B2s Ubuntu VM with a public IP and DNS label.
    Opens ports 443 (Grafana), 4318 (OTLP), and 22 (SSH).
    Optionally locks OTLP port to specific source IPs.

.EXAMPLE
    .\1-setup-azure-vm.ps1 -ResourceGroup "rg-copilot-otel" -Location "eastus" -VmName "mycopilototel"
#>

param(
    [Parameter(Mandatory)]
    [string]$ResourceGroup,

    [string]$Location = "eastus",

    [Parameter(Mandatory, HelpMessage = "VM name, also used as DNS label (<name>.region.cloudapp.azure.com)")]
    [string]$VmName,

    [string]$VmSize = "Standard_B2s",
    [string]$AdminUser = "azureuser",

    [string[]]$AllowOtlpFromIps = @()
)

$ErrorActionPreference = "Stop"

Write-Host "=== Creating resource group ===" -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location --output none

Write-Host "=== Creating VM ===" -ForegroundColor Cyan
$vmResult = az vm create `
    --resource-group $ResourceGroup `
    --name $VmName `
    --image "Canonical:ubuntu-24_04-lts:server:latest" `
    --size $VmSize `
    --admin-username $AdminUser `
    --generate-ssh-keys `
    --public-ip-sku Standard `
    --output json | ConvertFrom-Json

$publicIp = $vmResult.publicIpAddress
Write-Host "  Public IP: $publicIp"

Write-Host "=== Setting DNS label ===" -ForegroundColor Cyan
$ipName = az network public-ip list `
    --resource-group $ResourceGroup `
    --query "[0].name" -o tsv

az network public-ip update `
    --resource-group $ResourceGroup `
    --name $ipName `
    --dns-name $VmName `
    --output none

$fqdn = "$VmName.$Location.cloudapp.azure.com"
Write-Host "  FQDN: $fqdn"

Write-Host "=== Configuring NSG ===" -ForegroundColor Cyan
$nsgName = az network nsg list `
    --resource-group $ResourceGroup `
    --query "[0].name" -o tsv

# Port 443 (Grafana): open to all
az network nsg rule create `
    --resource-group $ResourceGroup `
    --nsg-name $nsgName `
    --name AllowHTTPS `
    --priority 1010 `
    --destination-port-ranges 443 `
    --access Allow `
    --protocol Tcp `
    --output none

# Port 80 (Let's Encrypt challenge, temporary)
az network nsg rule create `
    --resource-group $ResourceGroup `
    --nsg-name $nsgName `
    --name AllowHTTP `
    --priority 1020 `
    --destination-port-ranges 80 `
    --access Allow `
    --protocol Tcp `
    --output none

# Port 4318 (OTLP)
$otlpSource = if ($AllowOtlpFromIps.Count -gt 0) { $AllowOtlpFromIps -join " " } else { "*" }
az network nsg rule create `
    --resource-group $ResourceGroup `
    --nsg-name $nsgName `
    --name AllowOTLP `
    --priority 1030 `
    --destination-port-ranges 4318 `
    --source-address-prefixes $otlpSource `
    --access Allow `
    --protocol Tcp `
    --output none

Write-Host "`n=== VM Ready ===" -ForegroundColor Green
Write-Host @"

  SSH:    ssh ${AdminUser}@${fqdn}
  FQDN:  $fqdn

Next steps:
  1. SSH into the VM
  2. Copy the server/ folder to the VM:
     scp -r server/* ${AdminUser}@${fqdn}:~/otel-stack/
  3. On the VM: cd ~/otel-stack && bash deploy.sh $fqdn

"@
