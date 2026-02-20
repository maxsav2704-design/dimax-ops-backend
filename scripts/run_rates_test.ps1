# Wrapper: get IDs then run test (avoids docker exec inside test script)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot)

docker compose up -d db api | Out-Null
Start-Sleep -Seconds 20

$installerRaw = docker compose exec -T db psql -U postgres -d dimax -t -A -c "select id from installers where deleted_at is null order by created_at limit 1;"
$doorTypeRaw  = docker compose exec -T db psql -U postgres -d dimax -t -A -c "select id from door_types order by code limit 1;"
$installerId = if ($installerRaw) { $installerRaw.ToString().Trim() } else { "" }
$doorTypeId  = if ($doorTypeRaw) { $doorTypeRaw.ToString().Trim() } else { "" }

if (-not $installerId -or -not $doorTypeId) {
  Write-Host "Could not get IDs from DB. installer_id='$installerId' door_type_id='$doorTypeId'"
  Write-Host "Check: installers have rows? door_types have rows? (seed or insert)"
  exit 1
}

$env:INSTALLER_ID = $installerId
$env:DOOR_TYPE_ID = $doorTypeId
& "$PSScriptRoot\test_installer_rates_crud.ps1"
