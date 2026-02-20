# Admin Installer Rates API test (port 8001)
$ErrorActionPreference = "Stop"
$baseUrl = "http://localhost:8001"
$companyId = "737e65ea-fa7d-4412-a878-7a3fa6a2824b"

# 0) Login
$body = @{ company_id = $companyId; email = "admin@dimax.dev"; password = "admin12345" } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/auth/login" -ContentType "application/json" -Body $body).access_token
Write-Host "0) Login OK"

# 1) Get installer_id and door_type_id (from env or DB)
if ($env:INSTALLER_ID -and $env:DOOR_TYPE_ID) {
  $installerId = $env:INSTALLER_ID.Trim(); $doorTypeId = $env:DOOR_TYPE_ID.Trim()
} else {
  $installerId = (docker compose exec -T db psql -U postgres -d dimax -t -A -c "select id from installers where deleted_at is null order by created_at limit 1;").Trim()
  $doorTypeId  = (docker compose exec -T db psql -U postgres -d dimax -t -A -c "select id from door_types order by code limit 1;").Trim()
}
if (-not $installerId -or -not $doorTypeId) { Write-Host "No installer or door_type. Set INSTALLER_ID and DOOR_TYPE_ID, or run from backend with docker."; exit 1 }
Write-Host "1) installer_id=$installerId door_type_id=$doorTypeId"

# 2) CREATE rate
$createBody = @{ installer_id = $installerId; door_type_id = $doorTypeId; price = 120.00 } | ConvertTo-Json
$rate = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installer-rates" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createBody
Write-Host "2) CREATE OK id=$($rate.id) price=$($rate.price)"

# 3) LIST
$list = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installer-rates?installer_id=$installerId&limit=50" `
  -Headers @{ Authorization = "Bearer $token" }
Write-Host "3) LIST OK count=$($list.Count)"

# 4) PATCH
$rateId = $rate.id
$patchBody = @{ price = 135.50 } | ConvertTo-Json
$updated = Invoke-RestMethod -Method Patch -Uri "$baseUrl/api/v1/admin/installer-rates/$rateId" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $patchBody
Write-Host "4) PATCH OK price=$($updated.price)"

# 5) Duplicate CREATE -> 409
try {
  Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installer-rates" `
    -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createBody
  Write-Host "5) FAIL: expected 409"
} catch {
  if ($_.Exception.Response.StatusCode.value__ -eq 409) { Write-Host "5) OK: got 409 (duplicate)" }
  else { throw }
}

# 6) DELETE
Invoke-RestMethod -Method Delete -Uri "$baseUrl/api/v1/admin/installer-rates/$rateId" `
  -Headers @{ Authorization = "Bearer $token" }
Write-Host "6) DELETE OK"

# 7) Verify in DB (no rows)
$dbCheck = docker compose exec -T db psql -U postgres -d dimax -t -A -c "select count(*) from installer_rates where installer_id='$installerId' and door_type_id='$doorTypeId';"
$count = [int]($dbCheck.Trim())
if ($count -eq 0) { Write-Host "7) OK: 0 rows in DB" } else { Write-Host "7) FAIL: $count rows left" }

Write-Host "Done. Installer Rates CRUD test passed."
