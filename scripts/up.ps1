<#
.SYNOPSIS
    Recreates the Azure demo after scripts/down.ps1 (terraform apply).

.DESCRIPTION
    Applies infra/app, then infra/databricks (passing the new GitHub identity client ID),
    then, unless -SkipGitHub is given, writes the new IDs/names to the GitHub secrets and
    variables and starts deploy-app.yml and deploy-databricks.yml to push the code.

    Must run locally with `az login` as subscription Owner, because infra/app creates the
    role assignments for the GitHub identity. A recreated identity gets a new client ID,
    and the web apps get a new random suffix (new URLs), which is why GitHub is updated.

.EXAMPLE
    .\scripts\up.ps1
.EXAMPLE
    .\scripts\up.ps1 -Only app -AutoApprove
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'app', 'databricks')]
    [string]$Only = 'all',
    [switch]$AutoApprove,
    [switch]$SkipGitHub,
    [switch]$SkipDeploy
)

. (Join-Path $PSScriptRoot 'azure-common.ps1')

Assert-Tools (-not $SkipGitHub)

function Invoke-Apply([string]$Stack, [string[]]$ExtraArgs) {
    Write-Step "terraform apply infra/$Stack"
    Initialize-Stack $Stack
    $applyArgs = @("-chdir=$($Stacks[$Stack])", 'apply', '-input=false', '-lock-timeout=5m') + $ExtraArgs
    if ($AutoApprove) { $applyArgs += '-auto-approve' }
    Invoke-Native terraform $applyArgs
}

# infra/app is always needed: its outputs feed infra/databricks and GitHub.
if ($Only -ne 'databricks') {
    Invoke-Apply 'app' @()
} else {
    Initialize-Stack 'app'
}
$app = Get-StackOutputs 'app'
if (-not $app.github_identity_client_id) { throw 'infra/app has no outputs. Run: .\scripts\up.ps1 -Only app' }

$dbx = $null
if ($Only -ne 'app') {
    Invoke-Apply 'databricks' @("-var=github_identity_client_id=$($app.github_identity_client_id.value)")
    $dbx = Get-StackOutputs 'databricks'
}

if (-not $SkipGitHub) {
    Write-Step 'Updating GitHub secrets and variables'
    $secrets = [ordered]@{
        AZURE_CLIENT_ID       = $app.github_identity_client_id.value
        AZURE_TENANT_ID       = $app.tenant_id.value
        AZURE_SUBSCRIPTION_ID = $app.subscription_id.value
    }
    foreach ($name in $secrets.Keys) {
        Invoke-Native gh @('secret', 'set', $name, '--body', $secrets[$name])
    }

    $vars = [ordered]@{
        TFSTATE_RESOURCE_GROUP  = Get-BackendValue 'resource_group_name'
        TFSTATE_STORAGE_ACCOUNT = Get-BackendValue 'storage_account_name'
        API_APP_NAME            = $app.api_app_name.value
        UI_APP_NAME             = $app.ui_app_name.value
    }
    if ($dbx) {
        $vars.DATABRICKS_HOST = $dbx.workspace_url.value
        $vars.DATABRICKS_CLUSTER_ID = $dbx.cluster_id.value
    }
    foreach ($name in $vars.Keys) {
        Invoke-Native gh @('variable', 'set', $name, '--body', $vars[$name])
    }

    if (-not $SkipDeploy) {
        Write-Step 'Starting deploy workflows on main'
        Invoke-Native gh @('workflow', 'run', 'deploy-app.yml', '--ref', 'main')
        if ($dbx) { Invoke-Native gh @('workflow', 'run', 'deploy-databricks.yml', '--ref', 'main') }
        Write-Host 'Follow progress with: gh run list --limit 5'
    }
}

Write-Step 'Done'
Write-Host "UI:  $($app.ui_url.value)"
Write-Host "API: $($app.api_url.value)"
if ($dbx) {
    Write-Host "Databricks: $($dbx.workspace_url.value)"
    Write-Host 'New workspace: re-upload the simulated fleet and run the job (README, step 5).'
}
