# Sammelt Container-Logs und Laufzeiten eines QA-Testlaufs als Nachweis.
param(
    [Parameter(Mandatory = $true)][string]$Laufordner,
    [string]$Seit = "30m",
    [string]$Praefix = "mobilepickingundvoiceassistant"
)

$logs = Join-Path $Laufordner "logs"
New-Item -ItemType Directory -Force $logs | Out-Null

$container = @("backend", "n8n", "ollama", "odoo")
foreach ($name in $container) {
    $voll = "$Praefix-$name-1"
    docker logs --since $Seit $voll *>&1 | Set-Content (Join-Path $logs "$name.log") -Encoding utf8
}

docker exec "$Praefix-ollama-1" ollama list *>&1 | Set-Content (Join-Path $logs "ollama_models.txt") -Encoding utf8
docker ps --format "{{.Names}}`t{{.Image}}" | Set-Content (Join-Path $logs "container_images.txt") -Encoding utf8

"=== Kette (backend) ==="
Get-Content (Join-Path $logs "backend.log") |
    Select-String "quality-alerts|webhook/quality-assessment|assessment|ERROR|Traceback"

"`n=== Modell-Ladezeiten (ollama) ==="
Get-Content (Join-Path $logs "ollama.log") |
    Select-String "model loaded|loaded runners|template selection|starting llama server"

"`n=== Inferenz-Laufzeiten (ollama) ==="
Get-Content (Join-Path $logs "ollama.log") |
    Select-String "prompt eval time|^\s*eval time|total time|slot release"

"`n=== Fehler (n8n, odoo) ==="
Get-Content (Join-Path $logs "n8n.log"), (Join-Path $logs "odoo.log") |
    Select-String "ERROR|error|timeout|Timeout|Traceback" |
    Select-Object -Last 20

"`nLogs abgelegt unter: $logs"
