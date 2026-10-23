param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^sha256:[a-f0-9]{64}$')]
    [string]$BackendImage,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^sha256:[a-f0-9]{64}$')]
    [string]$PostgresImage
)
$ErrorActionPreference = 'Stop'
# Leave headroom for Windows and Docker; never pause working services automatically.
if ($IsWindows -or $env:OS -eq 'Windows_NT') {
    $freeMiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024
    if ($freeMiB -lt 1024) {
        throw 'At least 1 GiB free host RAM is required before starting isolated acceptance. No containers were created.'
    }
}
$backend = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runId = [guid]::NewGuid().ToString('N')
$database = "dimax-outbox-db-$runId"
$runner = "dimax-outbox-tests-$runId"
$label = "dimax.outbox-acceptance=$runId"
$url = 'postgresql+psycopg2://outbox_acceptance:synthetic-local-only@127.0.0.1:5432/dimax_acceptance_tests'

function Invoke-CheckedDocker {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Isolated acceptance Docker command failed ($LASTEXITCODE)" }
}

try {
    Invoke-CheckedDocker @('image', 'inspect', $BackendImage, '--format', '{{.Id}}')
    Invoke-CheckedDocker @('image', 'inspect', $PostgresImage, '--format', '{{.Id}}')
    Invoke-CheckedDocker @(
        'run', '-d', '--pull', 'never', '--name', $database, '--label', $label,
        '--network', 'none', '--read-only', '--user', 'postgres', '--memory', '160m',
        '--pids-limit', '96', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m',
        '--tmpfs', '/var/run/postgresql:rw,noexec,nosuid,mode=1777,size=4m',
        '--env', 'PGDATA=/tmp/pgdata', '--env', 'POSTGRES_USER=outbox_acceptance',
        '--env', 'POSTGRES_PASSWORD=synthetic-local-only', '--env', 'POSTGRES_DB=dimax_acceptance_tests',
        $PostgresImage, 'postgres', '-c', 'shared_buffers=8MB', '-c', 'max_connections=12',
        '-c', 'work_mem=1MB', '-c', 'maintenance_work_mem=16MB'
    )
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        & docker exec $database pg_isready -h 127.0.0.1 -U outbox_acceptance -d dimax_acceptance_tests
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Temporary PostgreSQL did not become ready' }
    $program = @'
import os
import sys
from alembic.config import Config
from alembic import command
assert os.environ['APP_ENV'] == 'test'
assert os.environ['DATABASE_URL'] == os.environ['TEST_DATABASE_URL']
assert '@127.0.0.1:5432/dimax_acceptance_tests' in os.environ['DATABASE_URL']
command.upgrade(Config('/workspace/alembic.ini'), 'head')
import pytest
sys.exit(pytest.main([
    '-p', 'no:cacheprovider', '-q', '-x', '--tb=short',
    '/workspace/tests/integration/test_outbox_smtp_recovery.py',
    '/workspace/tests/integration/test_outbox_retry_policy.py',
    '/workspace/tests/integration/test_outbox_api.py',
    '/workspace/tests/test_outbox_commit_boundary.py',
    '/workspace/tests/test_smtp_sender.py',
    '/workspace/tests/test_smtp_tls_transport.py',
]))
'@
    Invoke-CheckedDocker @(
        'run', '--pull', 'never', '--name', $runner, '--label', $label,
        '--network', "container:$database", '--read-only', '--memory', '256m',
        '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', '--workdir', '/workspace',
        '--env', 'PYTHONPATH=/workspace:/workspace/tests', '--env', 'APP_ENV=test',
        '--env', 'JWT_SECRET=synthetic-outbox-acceptance-only-not-a-production-secret',
        '--env', "DATABASE_URL=$url", '--env', "TEST_DATABASE_URL=$url",
        '--env', 'DIMAX_OUTBOX_SMTP_ACCEPTANCE=1', '--env', 'EMAIL_ENABLED=true',
        '--env', 'WHATSAPP_ENABLED=false', '--env', 'WHATSAPP_FALLBACK_TO_EMAIL=false',
        '--env', 'PUBLIC_BASE_URL=https://api.dimax.example',
        '--env', 'PUBLIC_APP_BASE_URL=https://ops.dimax.example',
        '--mount', "type=bind,source=$backend\app,target=/workspace/app,readonly",
        '--mount', "type=bind,source=$backend\scripts,target=/workspace/scripts,readonly",
        '--mount', "type=bind,source=$backend\tests,target=/workspace/tests,readonly",
        '--mount', "type=bind,source=$backend\alembic,target=/workspace/alembic,readonly",
        '--mount', "type=bind,source=$backend\alembic.ini,target=/workspace/alembic.ini,readonly",
        '--entrypoint', 'python', $BackendImage, '-B', '-c', $program
    )
} finally {
    # Remove only this invocation's named, labelled containers; never prune volumes/images.
    foreach ($name in @($runner, $database)) {
        $owner = & docker inspect --format '{{index .Config.Labels "dimax.outbox-acceptance"}}' $name 2>$null
        if ($LASTEXITCODE -eq 0 -and $owner -eq $runId) {
            & docker rm -f -v $name
            if ($LASTEXITCODE -ne 0) { Write-Warning "Could not remove owned test container: $name" }
        }
    }
}
