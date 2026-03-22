param(
    [ValidateSet(
        "help",
        "setup",
        "install-backend-deps",
        "install-ui-deps",
        "build-all",
        "build-backend",
        "build-odoo",
        "up",
        "down",
        "logs",
        "logs-backend",
        "logs-odoo",
        "seed",
        "test",
        "test-ui",
        "test-api",
        "verify-code",
        "verify-ui",
        "verify-stack",
        "verify",
        "clean",
        "shell-odoo",
        "shell-db"
    )]
    [string]$Task = "help"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    & $Action
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Show-Help {
    @"
Available tasks:
  help
  setup
  install-backend-deps
  install-ui-deps
  build-all
  build-backend
  build-odoo
  up
  down
  logs
  logs-backend
  logs-odoo
  seed
  test
  test-ui
  test-api
  verify-code
  verify-ui
  verify-stack
  verify
  clean
  shell-odoo
  shell-db

Examples:
  powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 verify
  powershell -ExecutionPolicy Bypass -File infrastructure/scripts/workflow.ps1 logs-backend
"@
}

Push-Location $projectRoot
try {
    switch ($Task) {
        "help" { Show-Help }
        "setup" {
            if (-not (Test-Path ".env")) {
                Copy-Item ".env.example" ".env"
                Write-Host "WARNUNG: .env erstellt - Werte ausfuellen!"
                exit 1
            }
            Invoke-Step { docker compose build }
        }
        "install-backend-deps" {
            Push-Location "backend"
            try {
                Invoke-Step { python -m pip install --target .deps -r requirements-dev.txt }
            }
            finally {
                Pop-Location
            }
        }
        "install-ui-deps" {
            Invoke-Step { npm.cmd install }
            Invoke-Step { npx.cmd playwright install chromium }
        }
        "build-all" { Invoke-Step { docker compose build } }
        "build-backend" { Invoke-Step { docker compose build backend } }
        "build-odoo" { Invoke-Step { docker compose build odoo } }
        "up" { Invoke-Step { docker compose up -d } }
        "down" { Invoke-Step { docker compose down } }
        "logs" { Invoke-Step { docker compose logs -f --tail=50 } }
        "logs-backend" { Invoke-Step { docker compose logs -f --tail=50 backend } }
        "logs-odoo" { Invoke-Step { docker compose logs -f --tail=50 odoo } }
        "seed" {
            $odooDb = if ($env:ODOO_DB) { $env:ODOO_DB } else { "picking" }
            $odooUser = if ($env:ODOO_USER) { $env:ODOO_USER } else { "admin" }
            Invoke-Step { python infrastructure/scripts/seed-odoo.py --url http://localhost:8069 --db $odooDb --user $odooUser --api-key $env:ODOO_API_KEY }
        }
        "test" {
            Push-Location "backend"
            try {
                $previousPythonPath = $env:PYTHONPATH
                $depsPath = (Get-Location).Path + "\.deps"
                if ($previousPythonPath) {
                    $env:PYTHONPATH = "$depsPath;$previousPythonPath"
                } else {
                    $env:PYTHONPATH = $depsPath
                }
                Invoke-Step { python -m pytest -p pytest_asyncio tests/ -v }
            }
            finally {
                $env:PYTHONPATH = $previousPythonPath
                Pop-Location
            }
        }
        "test-ui" { Invoke-Step { npx.cmd playwright test } }
        "test-api" { Invoke-Step { python infrastructure/scripts/test-api.py } }
        "verify-code" {
            Invoke-Step { & $PSCommandPath test }
        }
        "verify-ui" {
            Invoke-Step { & $PSCommandPath test-ui }
        }
        "verify-stack" {
            Invoke-Step { & $PSCommandPath test-api }
        }
        "verify" {
            Invoke-Step { & $PSCommandPath verify-code }
            Invoke-Step { & $PSCommandPath verify-ui }
            Invoke-Step { & $PSCommandPath verify-stack }
        }
        "clean" { Invoke-Step { docker compose down -v --rmi local } }
        "shell-odoo" {
            $odooDb = if ($env:ODOO_DB) { $env:ODOO_DB } else { "picking" }
            Invoke-Step { docker compose exec odoo odoo shell -d $odooDb }
        }
        "shell-db" {
            $postgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "odoo" }
            $odooDb = if ($env:ODOO_DB) { $env:ODOO_DB } else { "picking" }
            Invoke-Step { docker compose exec db psql -U $postgresUser -d $odooDb }
        }
    }
}
finally {
    Pop-Location
}
