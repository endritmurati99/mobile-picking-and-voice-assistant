param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$appRoot = Join-Path $repoRoot "Mobile Picking und Voice Assistant"
$brainRoot = Join-Path $repoRoot "Notzien (Obsidian)"
$workflowScript = Join-Path $appRoot "infrastructure\scripts\workflow.ps1"

if (-not (Test-Path $workflowScript)) {
    throw "Workflow-Skript nicht gefunden: $workflowScript"
}

if ($Args.Count -gt 0 -and $Args[0] -eq "paths") {
    Write-Host "repo  = $repoRoot"
    Write-Host "app   = $appRoot"
    Write-Host "brain = $brainRoot"
    exit 0
}

if ($Args.Count -eq 0) {
    & $workflowScript help
    exit $LASTEXITCODE
}

& $workflowScript @Args
exit $LASTEXITCODE
