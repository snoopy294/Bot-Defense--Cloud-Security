param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('init', 'plan', 'apply', 'destroy', 'output')]
    [string]$Action,
    [string]$Profile = 'botdef'
)
$ErrorActionPreference = 'Stop'
$labRoot = Join-Path $PSScriptRoot '../infra/envs/lab'
# Older Terraform AWS providers cannot read aws-login profiles directly.
# Keep exported temporary credentials in this process only; never print/save them.
$credentialNames = @('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_REGION')
$previousEnvironment = @{}
foreach ($name in $credentialNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location $labRoot
try {
    if ($Action -notin @('init', 'output')) {
        $labCredentials = aws configure export-credentials --profile $Profile --region us-east-1 --format process | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or -not $labCredentials.AccessKeyId) { throw 'AWS login expired or unavailable. Run aws login --profile botdef.' }
        $env:AWS_ACCESS_KEY_ID = $labCredentials.AccessKeyId
        $env:AWS_SECRET_ACCESS_KEY = $labCredentials.SecretAccessKey
        $env:AWS_SESSION_TOKEN = $labCredentials.SessionToken
        $env:AWS_REGION = 'us-east-1'
    }
    switch ($Action) {
        'init'    { terraform init -input=false -lockfile=readonly }
        'plan'    { terraform plan -input=false '-out=lab.tfplan' }
        'apply'   { terraform apply -input=false lab.tfplan }
        'destroy' { terraform destroy } # Interactive confirmation; only this local state.
        'output'  { terraform output }
    }
    if ($LASTEXITCODE -ne 0) { throw "Terraform $Action failed; inspect the output above." }
} finally {
    foreach ($name in $credentialNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
    $labCredentials = $null
    Pop-Location
}
