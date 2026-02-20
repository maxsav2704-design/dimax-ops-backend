# Link User for Installers — manual test.
# Prereqs: API on 8001, DB seeded (admin@dimax.dev, installer1@dimax.dev).
# Get token and installer1 user_id (e.g. from DB: SELECT id FROM users WHERE email='installer1@dimax.dev';)
$baseUrl = "http://localhost:8001"

# Login as admin
$loginBody = @{ company_id = "737e65ea-fa7d-4412-a878-7a3fa6a2824b"; email = "admin@dimax.dev"; password = "admin12345" } | ConvertTo-Json
$resp = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/auth/login" -ContentType "application/json" -Body $loginBody
$token = $resp.access_token

# Get installer1 user UUID (replace with actual from your DB if different)
# psql: SELECT id FROM users WHERE email = 'installer1@dimax.dev';
$installer1UserId = $env:INSTALLER1_USER_ID
if (-not $installer1UserId) {
  Write-Host "Set INSTALLER1_USER_ID (UUID of user installer1@dimax.dev). Example: `$env:INSTALLER1_USER_ID = 'uuid-here'"
  exit 1
}

# 1) Create installer A
$createA = @{ full_name = "Link Test A"; phone = "+972501111001"; email = "link.a@dimax.dev"; status = "ACTIVE"; is_active = $true } | ConvertTo-Json
$instA = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createA
Write-Host "1) Created installer A id=$($instA.id)"

# 2) Link user installer1 to A
$linkBody = @{ user_id = $installer1UserId } | ConvertTo-Json
$linked = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers/$($instA.id)/link-user" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $linkBody
Write-Host "2) Link A: user_id=$($linked.user_id)"

# 3) Create installer B
$createB = @{ full_name = "Link Test B"; phone = "+972501111002"; email = "link.b@dimax.dev"; status = "ACTIVE"; is_active = $true } | ConvertTo-Json
$instB = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createB
Write-Host "3) Created installer B id=$($instB.id)"

# 4) Try to link same user to B -> 409
try {
  Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers/$($instB.id)/link-user" `
    -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $linkBody
  Write-Host "4) FAIL: expected 409"
} catch {
  if ($_.Exception.Response.StatusCode.value__ -eq 409) { Write-Host "4) OK: got 409 (user already linked)" }
  else { throw }
}

# 5) Unlink A
$unlinked = Invoke-RestMethod -Method Delete -Uri "$baseUrl/api/v1/admin/installers/$($instA.id)/link-user" `
  -Headers @{ Authorization = "Bearer $token" }
Write-Host "5) Unlink A: user_id=$($unlinked.user_id) (expect empty)"

# 6) Now link same user to B -> 200
$linkedB = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers/$($instB.id)/link-user" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $linkBody
Write-Host "6) Link B: user_id=$($linkedB.user_id) (expect installer1 id)"

Write-Host "Done. GET installer B:"
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installers/$($instB.id)" `
  -Headers @{ Authorization = "Bearer $token" } | ConvertTo-Json -Depth 5
