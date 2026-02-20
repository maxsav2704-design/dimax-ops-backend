# Installers CRUD test. Requires $token (admin). Get it first:
# $loginBody = @{ company_id = "737e65ea-fa7d-4412-a878-7a3fa6a2824b"; email = "admin@dimax.dev"; password = "admin12345" } | ConvertTo-Json
# $resp = Invoke-RestMethod -Method Post -Uri "http://localhost:8001/api/v1/auth/login" -ContentType "application/json" -Body $loginBody
# $token = $resp.access_token
$baseUrl = "http://localhost:8001"

# 1) create
$createBody = @{
  full_name = "Installer CRUD Test"
  phone     = "+972501999888"
  email     = "crud.test@dimax.dev"
  status    = "ACTIVE"
  is_active = $true
} | ConvertTo-Json

$created = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/admin/installers" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $createBody

$created | ConvertTo-Json -Depth 10
$id = $created.id   # InstallerDTO has "id", not installer_id

# 2) list
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installers?limit=50" `
  -Headers @{ Authorization = "Bearer $token" } | ConvertTo-Json -Depth 10

# 3) patch
$patchBody = @{ full_name = "Installer CRUD Updated" } | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri "$baseUrl/api/v1/admin/installers/$id" `
  -Headers @{ Authorization = "Bearer $token" } -ContentType "application/json" -Body $patchBody | ConvertTo-Json -Depth 10

# 4) get by id
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installers/$id" `
  -Headers @{ Authorization = "Bearer $token" } | ConvertTo-Json -Depth 10

# 5) delete
Invoke-RestMethod -Method Delete -Uri "$baseUrl/api/v1/admin/installers/$id" `
  -Headers @{ Authorization = "Bearer $token" }

# 6) get must 404
try {
  Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installers/$id" `
    -Headers @{ Authorization = "Bearer $token" }
  Write-Host "FAIL: expected 404"
} catch {
  if ($_.Exception.Response.StatusCode.value__ -eq 404) { Write-Host "OK: GET after DELETE returned 404" }
  else { throw }
}

# 7) list — deleted installer must not appear
Invoke-RestMethod -Method Get -Uri "$baseUrl/api/v1/admin/installers?limit=50" `
  -Headers @{ Authorization = "Bearer $token" } | ConvertTo-Json -Depth 10
