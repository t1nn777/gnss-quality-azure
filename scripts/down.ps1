<#
.SYNOPSIS
    Tears down the Azure demo so it stops costing money (terraform destroy).

.DESCRIPTION
    Destroys infra/databricks first, then infra/app. The bootstrap storage account
    (Terraform state, a few cents per month) is kept so scripts/up.ps1 can recreate
    everything. Stopping a web app is not enough: the B1 plan is billed while it exists.

    Unless -SkipGitHub is given, the GitHub variables that gate the workflows are
    removed so pushes to main skip deploys instead of failing against deleted resources.

.EXAMPLE
    .\scripts\down.ps1
.EXAMPLE
    .\scripts\down.ps1 -Only databricks -AutoApprove
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'app', 'databricks')]
    [string]$Only = 'all',
    [switch]$AutoApprove,
    [switch]$SkipGitHub
)

. (Join-Path $PSScriptRoot 'azure-common.ps1')

Assert-Tools (-not $SkipGitHub)

$order = @('databricks', 'app') | Where-Object { $Only -eq 'all' -or $Only -eq $_ }

foreach ($stack in $order) {
    Write-Step "terraform destroy infra/$stack"
    Initialize-Stack $stack
    $destroyArgs = @("-chdir=$($Stacks[$stack])", 'destroy', '-input=false', '-lock-timeout=5m')
    if ($AutoApprove) { $destroyArgs += '-auto-approve' }
    Invoke-Native terraform $destroyArgs
}

if (-not $SkipGitHub) {
    Write-Step 'Removing GitHub variables so workflows skip'
    $vars = @()
    if ($order -contains 'databricks') { $vars += 'DATABRICKS_HOST', 'DATABRICKS_CLUSTER_ID' }
    if ($order -contains 'app') { $vars += 'API_APP_NAME', 'UI_APP_NAME', 'TFSTATE_STORAGE_ACCOUNT' }
    $ErrorActionPreference = 'Continue'
    foreach ($name in $vars) {
        gh variable delete $name *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host "  deleted $name" } else { Write-Host "  $name not set" }
    }
    $ErrorActionPreference = 'Stop'
}

Write-Step 'Resource groups still tagged project=gnss-quality-azure'
Invoke-Native az @('group', 'list', '--tag', 'project=gnss-quality-azure', '--query', '[].name', '-o', 'tsv')
Write-Host '(rg-gnss-tfstate is expected: it holds the Terraform state for up.ps1.)'
