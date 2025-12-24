$ErrorActionPreference = "Stop"

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $PSScriptRoot "..\backups"
$outFile = Join-Path $outDir ("appliance_service_{0}.dump" -f $ts)

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$db = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "appliance_service" }
$user = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "appliance_user" }

$container = "appliance_db"

docker exec -i $container pg_dump -U $user -F c -d $db | Set-Content -Encoding Byte -Path $outFile

Write-Host ("Backup created: {0}" -f $outFile)