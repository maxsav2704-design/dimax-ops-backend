# Test: link user -> soft-delete installer -> create new installer -> link same user again (must succeed)
$ErrorActionPreference = 'Stop'
$baseUrl = "http://localhost:8001"

# Get installer1 user_id from DB
$userIdLine = docker compose exec -T db psql -U postgres -d dimax -t -A -c "SELECT id FROM users WHERE email='installer1@dimax.dev' LIMIT 1;"
$installer1UserId = ($userIdLine -replace "`r`n","").Trim()
if (-not $installer1UserId) { Write-Host "installer1@dimax.dev not found in DB"; exit 1 }

# Login
$loginBody = @{ company_id = "737e65ea-fa7d-4412-a878-7a3fa6a2824b"; email = "admin@dimax.dev"; password = "admin12345" } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/auth/login" -ContentType "application/json" -Body $loginBody).access_token

# 0) Unlink installer1 from any installer so we start clean
$list = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installers?limit=100" -Headers @{ Authorization = "Bearer $token" }
foreach ($i in $list) { if ($i.user_id -eq $installer1UserId) {
  Invoke-RestMethod -Method Delete -Uri "$baseUrl/api/v1/admin/installers/$($i.id)/link-user" -Headers @{ Authorization = "Bearer $token" } | Out-Null
  Write-Host "0) Unlinked user from installer $($i.id)"
  break
}}

# 1) Create installer A, link user (unique phone/email per run)
$ts = [int][double]::Parse((Get-Date -UFormat %s))
$createA = @{ full_name = "SoftDel Test A"; phone = "+97250222$($ts % 100000)"; email = "softdel.a.$ts@dimax.dev"; status = "ACTIVE"; is_active = $true } | ConvertTo-Json
$instA = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createA
$linkBody = @{ user_id = $installer1UserId } | ConvertTo-Json
$linked = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers/$($instA.id)/link-user" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $linkBody
Write-Host "1) Created A, linked user: user_id=$($linked.user_id)"

# 2) Soft-delete installer A (must clear user_id so user can be reused)
Invoke-RestMethod -Method Delete -Uri "$baseUrl/api/v1/admin/installers/$($instA.id)" -Headers @{ Authorization = "Bearer $token" } | Out-Null
Write-Host "2) Soft-deleted installer A"

# 3) Create installer B, link same user (must succeed)
$createB = @{ full_name = "SoftDel Test B"; phone = "+97250223$($ts % 100000)"; email = "softdel.b.$ts@dimax.dev"; status = "ACTIVE"; is_active = $true } | ConvertTo-Json
$instB = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createB
$linkedB = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers/$($instB.id)/link-user" -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $linkBody
Write-Host "3) Created B, linked same user: user_id=$($linkedB.user_id) OK"

Write-Host "PASS: link -> soft-delete -> new installer -> link same user"