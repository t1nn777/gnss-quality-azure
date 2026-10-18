# Shared helpers for up.ps1 / down.ps1 (dot-sourced). Windows PowerShell 5.1 compatible.

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Stacks = @{
    app        = Join-Path $RepoRoot 'infra\app'
    databricks = Join-Path $RepoRoot 'infra\databricks'
}

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    # Runs a native command and stops the script on a non-zero exit code.
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function Assert-Tools([bool]$NeedGitHub) {
    foreach ($tool in @('az', 'terraform')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool not found on PATH" }
    }
    # Windows PowerShell 5.1 turns redirected native stderr into errors; relax around probes.
    $ErrorActionPreference = 'Continue'
    $account = az account show --query '{name:name, id:id}' -o json 2>$null
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw "Not logged in to Azure. Run: az login" }
    $account = ($account -join "`n") | ConvertFrom-Json
    Write-Host "Azure subscription: $($account.name) ($($account.id))"

    if ($NeedGitHub) {
        if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "gh not found on PATH (or pass -SkipGitHub)" }
        $ErrorActionPreference = 'Continue'
        gh auth status *> $null
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -ne 0) { throw "Not logged in to GitHub. Run: gh auth login (or pass -SkipGitHub)" }
    }
}

function Assert-StackConfig([string]$Stack) {
    $dir = $Stacks[$Stack]
    foreach ($file in @('backend.hcl', 'terraform.tfvars')) {
        if (-not (Test-Path (Join-Path $dir $file))) {
            throw "Missing infra/$Stack/$file. Copy it from $file.example (see README, Deploy to Azure)."
        }
    }
}

function Initialize-Stack([string]$Stack) {
    Assert-StackConfig $Stack
    Invoke-Native terraform @("-chdir=$($Stacks[$Stack])", 'init', '-input=false', '-backend-config=backend.hcl')
}

function Get-StackOutputs([string]$Stack) {
    $json = terraform "-chdir=$($Stacks[$Stack])" output -json
    if ($LASTEXITCODE -ne 0) { throw "terraform output failed for infra/$Stack" }
    return ($json -join "`n") | ConvertFrom-Json
}

function Get-BackendValue([string]$Key) {
    # Reads `key = "value"` from infra/app/backend.hcl.
    $line = Get-Content (Join-Path $Stacks.app 'backend.hcl') |
        Where-Object { $_ -match "^\s*$Key\s*=" } | Select-Object -First 1
    if (-not $line) { throw "$Key not found in infra/app/backend.hcl" }
    return ($line -replace '^[^=]*=\s*"?([^"]*)"?.*$', '$1').Trim()
}
