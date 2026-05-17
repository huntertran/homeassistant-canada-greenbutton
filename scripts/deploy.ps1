<#
.SYNOPSIS
  Deploy canada_greenbutton integration + Lovelace card to a live Home Assistant via SSH/SCP.
  Interactive: prompts for each option with sensible defaults.

.EXAMPLE
  .\deploy.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# --- Defaults ---------------------------------------------------------------
$Defaults = @{
    HAHost     = "192.168.x.x"
    User       = "root"
    Port       = "22"
    ConfigDir  = "/config"
    Restart    = "n"
    Samples    = "n"
}

function Read-WithDefault([string]$Label, [string]$Default) {
    $val = Read-Host "$Label [$Default]"
    if ([string]::IsNullOrWhiteSpace($val)) { return $Default }
    return $val.Trim()
}

function Read-YesNo([string]$Label, [string]$Default) {
    while ($true) {
        $val = Read-Host "$Label (y/n) [$Default]"
        if ([string]::IsNullOrWhiteSpace($val)) { $val = $Default }
        $val = $val.Trim().ToLower()
        if ($val -in @("y", "yes")) { return $true }
        if ($val -in @("n", "no"))  { return $false }
        Write-Host "  Enter y or n." -ForegroundColor Yellow
    }
}

# --- Interactive prompts ----------------------------------------------------
Write-Host "`n=== Canada GreenButton — Deploy ===" -ForegroundColor Cyan
Write-Host "Press Enter to accept the default shown in brackets.`n" -ForegroundColor DarkGray

$HAHost         = Read-WithDefault "HA host or IP" $Defaults.HAHost
$User           = Read-WithDefault "SSH user"       $Defaults.User
$Port           = [int](Read-WithDefault "SSH port" $Defaults.Port)
$ConfigDir      = Read-WithDefault "Remote config dir" $Defaults.ConfigDir
$DoRestart      = Read-YesNo "Restart HA after deploy?" $Defaults.Restart
$IncludeSamples = Read-YesNo "Copy sample XMLs from green-button-visualizer?" $Defaults.Samples

# --- Path resolution --------------------------------------------------------
$RepoRoot         = Split-Path -Parent $PSScriptRoot
$LocalIntegration = Join-Path $RepoRoot "custom_components\canada_greenbutton"
$LocalCard        = Join-Path $RepoRoot "custom_cards\canada-greenbutton-card\canada-greenbutton-card.js"
$LocalSamples     = Join-Path (Split-Path -Parent $RepoRoot) "green-button-visualizer\data"

$Target  = "$User@${HAHost}"
$SshOpts = @("-p", "$Port", "-o", "StrictHostKeyChecking=accept-new")
$ScpOpts = @("-P", "$Port", "-o", "StrictHostKeyChecking=accept-new")

# --- Summary ---------------------------------------------------------------
Write-Host "`n--- Plan ---" -ForegroundColor Cyan
Write-Host "  Target:      $Target`:$ConfigDir"
Write-Host "  Integration: $LocalIntegration"
Write-Host "  Card:        $LocalCard"
Write-Host "  Samples:     $(if ($IncludeSamples) { $LocalSamples } else { '(skipped)' })"
Write-Host "  Restart:     $(if ($DoRestart) { 'yes' } else { 'no' })"

if (-not (Read-YesNo "`nProceed?" "y")) {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

# --- Helpers ---------------------------------------------------------------
function Invoke-SSH([string]$Cmd) {
    Write-Host "ssh> $Cmd" -ForegroundColor DarkGray
    & ssh @SshOpts $Target $Cmd
    if ($LASTEXITCODE -ne 0) { throw "ssh failed: $Cmd (exit $LASTEXITCODE)" }
}

function Invoke-SCP([string[]]$ScpArgs) {
    Write-Host "scp> $($ScpArgs -join ' ')" -ForegroundColor DarkGray
    & scp @ScpOpts @ScpArgs
    if ($LASTEXITCODE -ne 0) { throw "scp failed (exit $LASTEXITCODE)" }
}

# --- Sanity check ----------------------------------------------------------
foreach ($p in @($LocalIntegration, $LocalCard)) {
    if (-not (Test-Path $p)) { throw "Missing local path: $p" }
}
if ($IncludeSamples -and -not (Test-Path $LocalSamples)) {
    Write-Warning "Samples dir not found: $LocalSamples — will skip"
    $IncludeSamples = $false
}

# --- Remote prep -----------------------------------------------------------
Write-Host "`nDeploying..." -ForegroundColor Cyan
Invoke-SSH "mkdir -p $ConfigDir/custom_components $ConfigDir/www $ConfigDir/canada_greenbutton"
Invoke-SSH "rm -rf $ConfigDir/custom_components/canada_greenbutton"

# --- Push integration ------------------------------------------------------
Invoke-SCP @("-r", "$LocalIntegration", "${Target}:$ConfigDir/custom_components/")
Invoke-SSH "find $ConfigDir/custom_components/canada_greenbutton -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; true"

# --- Push card -------------------------------------------------------------
Invoke-SCP @("$LocalCard", "${Target}:$ConfigDir/www/canada-greenbutton-card.js")

# --- Samples ---------------------------------------------------------------
if ($IncludeSamples) {
    Get-ChildItem -Path $LocalSamples -Filter *.xml | ForEach-Object {
        Invoke-SCP @("$($_.FullName)", "${Target}:$ConfigDir/canada_greenbutton/")
    }
}

# --- Restart ---------------------------------------------------------------
if ($DoRestart) {
    Write-Host "Restarting HA core..." -ForegroundColor Cyan
    Invoke-SSH "ha core restart 2>/dev/null || systemctl restart home-assistant@homeassistant 2>/dev/null || echo 'Restart manually via UI: Settings > System > Restart'"
} else {
    Write-Host "Skipped HA restart. Restart manually for Python changes to take effect." -ForegroundColor Yellow
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "Next: hard-refresh browser (Ctrl+Shift+R) to reload card." -ForegroundColor Green
