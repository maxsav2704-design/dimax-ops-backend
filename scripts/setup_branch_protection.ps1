param(
    [Parameter(Mandatory = $true)]
    [string]$Repo,
    [string]$Branch = "main",
    [string[]]$RequiredChecks = @("Backend Tests / quality-gate"),
    [int]$RequiredApprovals = 1,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($RequiredApprovals -lt 0 -or $RequiredApprovals -gt 6) {
    throw "RequiredApprovals must be in range 0..6."
}

$payload = @{
    required_status_checks = @{
        strict = $true
        contexts = $RequiredChecks
    }
    enforce_admins = $false
    required_pull_request_reviews = @{
        dismiss_stale_reviews = $true
        require_code_owner_reviews = $false
        required_approving_review_count = $RequiredApprovals
    }
    restrictions = $null
    required_linear_history = $true
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_conversation_resolution = $true
    lock_branch = $false
    allow_fork_syncing = $true
}

$json = $payload | ConvertTo-Json -Depth 10

if ($DryRun) {
    Write-Output $json
    exit 0
}

gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated. Run 'gh auth login' first."
}

$json | gh api `
    --method PUT `
    -H "Accept: application/vnd.github+json" `
    "/repos/$Repo/branches/$Branch/protection" `
    --input -

if ($LASTEXITCODE -ne 0) {
    throw "Failed to apply branch protection for $Repo/$Branch."
}

Write-Host "Branch protection updated for $Repo/$Branch"
