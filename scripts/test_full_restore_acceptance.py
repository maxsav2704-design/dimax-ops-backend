"""Sequential real-schema/PDF recovery with owned resources and no live mounts."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

if __package__:
    from .test_backup_restore_acceptance import docker, free_memory_mib
else:
    from test_backup_restore_acceptance import docker, free_memory_mib

LABEL = 'dimax.full-restore-acceptance'


def preflight(images, *, resume_outbox=False):
    if any(not re.fullmatch(r'sha256:[0-9a-f]{64}', image) for image in images):
        raise ValueError('Cached immutable image IDs required')
    available = free_memory_mib()
    minimum = 1024 if resume_outbox else 768
    if available < minimum:
        raise RuntimeError(f'At least {minimum} MiB free host RAM required; available={available:.0f} MiB; no resources created')
    if shutil.disk_usage(Path(__file__).resolve().parents[1]).free < 1024**3:
        raise RuntimeError('At least 1 GiB free workspace disk required')
    print(f'[full-restore] free host RAM={available:.0f} MiB; phases sequential', flush=True)


class Resources:
    def __init__(self, run_id):
        self.run_id = run_id
        self.items = []

    def owns(self, kind, name):
        result = docker(kind, 'inspect', name, check=False)
        if result.returncode:
            error = result.stderr.decode(errors='replace').strip().lower()
            messages = (f'no such {kind}: {name}', f'get {name}: no such {kind}', f'network {name} not found')
            if any(error == message or error == 'error response from daemon: ' + message for message in messages):
                return False
            raise RuntimeError(f'Cannot verify {kind} {name}; cleanup not confirmed')
        row = json.loads(result.stdout)[0]
        labels = (row.get('Config') or {}).get('Labels') if kind == 'container' else row.get('Labels')
        if (labels or {}).get(LABEL) != self.run_id:
            raise RuntimeError(f'Ownership mismatch for {kind} {name}')
        return True

    def reserve(self, kind, suffix):
        name = f'dimax-full-{self.run_id}-{suffix}'
        if self.owns(kind, name):
            raise RuntimeError('Resource already exists')
        self.items.append((kind, name))
        return name

    def remove(self, kind, name):
        if self.owns(kind, name):
            docker(kind, 'rm', *(['-f'] if kind == 'container' else []), name)
        if self.owns(kind, name):
            raise RuntimeError(f'Resource remains: {name}')

    def cleanup(self):
        failures = []
        for kind, name in reversed(self.items):
            try:
                self.remove(kind, name)
            except Exception as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError('Cleanup incomplete: ' + '; '.join(failures))


def freeze_sources(root, target, *, resume_outbox=False):
    """Copy code only; avoid dotenv, caches, Git, databases and concurrent edits."""
    selected = []
    for folder in ('app', 'alembic'):
        for path in (root / folder).rglob('*'):
            if path.is_symlink():
                raise ValueError('Symlink in source snapshot')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and not path.name.startswith('.env'):
                selected.append(path.relative_to(root))
    selected += [Path('alembic.ini'), Path('scripts/db_backup_restore_smoke.py'), Path('scripts/full_restore_probe.py')]
    if resume_outbox:
        selected += [Path('scripts/outbox_restore_probe.py'), Path('tests/test_smtp_tls_transport.py')]
    before = {str(path): sha256((root / path).read_bytes()).hexdigest() for path in selected}
    for relative in selected:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, destination)
    after = {str(path): sha256((root / path).read_bytes()).hexdigest() for path in selected}
    copied = {str(path): sha256((target / path).read_bytes()).hexdigest() for path in selected}
    if before != after or before != copied:
        raise RuntimeError('Source changed during snapshot; retry without editing Claude files')
    return sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()


def exercise(root, temporary, resources, images, *, resume_outbox=False):
    postgres_image, app_image, storage_image = images
    source, work = temporary / 'source', temporary / 'work'
    source.mkdir()
    work.mkdir()
    source_hash = freeze_sources(root, source, resume_outbox=resume_outbox)
    print('[full-restore] frozen code SHA256=' + source_hash, flush=True)
    label = ['--label', f'{LABEL}={resources.run_id}']
    network = resources.reserve('network', 'network')
    docker('network', 'create', '--internal', *label, network)

    def volume(suffix):
        name = resources.reserve('volume', suffix)
        docker('volume', 'create', *label, name)
        return name

    def container(suffix, image, options, command):
        name = resources.reserve('container', suffix)
        docker('run', '-d', '--pull', 'never', '--name', name, *label, '--network', network,
               '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--pids-limit', '96', *options, image, *command)
        return name

    pg_volume = volume('postgres-data')
    pg = container('postgres', postgres_image, [
        '--network-alias', 'recovery-db', '--user', 'postgres', '--memory', '128m', '--memory-swap', '128m',
        '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '--tmpfs', '/var/run/postgresql:rw,noexec,nosuid,mode=1777,size=4m',
        '--mount', f'type=volume,source={pg_volume},target=/var/lib/postgresql/data',
        '--env', 'POSTGRES_DB=dimax_full_source', '--env', 'POSTGRES_PASSWORD=synthetic-local-only',
        '--env', 'POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C',
    ], ['postgres', '-c', 'shared_buffers=8MB', '-c', 'max_connections=8', '-c', 'work_mem=1MB', '-c', 'maintenance_work_mem=8MB'])
    def wait_database():
        for _ in range(40):
            if docker('exec', pg, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', '-d', 'dimax_full_source', check=False).returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError('Test PostgreSQL not ready')

    wait_database()

    def job(step, database='dimax_full_source', *, outbox=False):
        env = {
            'DIMAX_FULL_RESTORE': 'synthetic-only', 'APP_ENV': 'test',
            'DATABASE_URL': f'postgresql+psycopg2://postgres:synthetic-local-only@recovery-db:5432/{database}',
            'JWT_SECRET': 'synthetic-local-only-not-a-real-secret', 'EMAIL_ENABLED': 'false',
            'WHATSAPP_ENABLED': 'false', 'AI_ENABLED': 'false',
            'MINIO_ENDPOINT': 'recovery-storage:9000', 'MINIO_BUCKET': 'dimax-recovery',
            'MINIO_ACCESS_KEY': 'synthetic-recovery', 'MINIO_SECRET_KEY': 'synthetic-local-only',
            'MINIO_SECURE': 'false', 'PYTHONPATH': '/probe', 'PYTHONDONTWRITEBYTECODE': '1',
            'PUBLIC_BASE_URL': 'https://api.dimax.example', 'PUBLIC_APP_BASE_URL': 'https://app.dimax.example',
        }
        if outbox:
            env['DIMAX_OUTBOX_RESTORE'] = 'synthetic-only'
        options = ['--memory', '256m', '--memory-swap', '256m', '--workdir', '/probe',
                   '--entrypoint', 'python', '--tmpfs', '/tmp:rw,nosuid,size=32m',
                   '--mount', f'type=bind,source={source},target=/probe,readonly',
                   '--mount', f'type=bind,source={work},target=/work']
        if os.name == 'posix':
            # Bind-mounted evidence belongs to the runner, not the image's UID.
            options += ['--user', f'{os.getuid()}:{os.getgid()}']
        for key, value in env.items():
            options += ['--env', f'{key}={value}']
        probe = 'scripts/outbox_restore_probe.py' if outbox else 'scripts/full_restore_probe.py'
        name = container(step + '-' + database, app_image, options, ['-B', probe, step])
        try:
            result = subprocess.run(['docker', 'wait', name], capture_output=True, timeout=600, check=False)
            logs = docker('logs', name, check=False)
            print((logs.stdout + logs.stderr).decode(errors='replace')[-24000:], flush=True)
            if result.returncode or result.stdout.strip() != b'0':
                raise RuntimeError(f'Acceptance step failed: {step}')
        finally:
            resources.remove('container', name)

    job('seed')
    if resume_outbox:
        job('prepare', outbox=True)
    # Keep dumps in the owned test volume: /tmp is tmpfs and is lost on stop.
    initial_dump = '/var/lib/postgresql/data/dimax-test-full.dump'
    sent_dump = '/var/lib/postgresql/data/dimax-test-sent.dump'
    docker('exec', pg, 'pg_dump', '-U', 'postgres', '-d', 'dimax_full_source', '-Fc', '-f', initial_dump)
    docker('exec', pg, 'createdb', '-U', 'postgres', '--template=template0', 'dimax_full_restored')
    docker('exec', pg, 'pg_restore', '-U', 'postgres', '-d', 'dimax_full_restored', '--exit-on-error', '--single-transaction', initial_dump)
    job('verify-db', 'dimax_full_restored')
    job('verify-db', 'dimax_full_source')
    docker('stop', '--timeout', '30', pg)
    print('PASS: database phase complete; test PostgreSQL stopped before object-store phase', flush=True)

    def storage(suffix):
        data = volume(suffix + '-data')
        name = container(suffix, storage_image, [
            '--network-alias', 'recovery-storage', '--memory', '192m', '--memory-swap', '192m',
            '--tmpfs', '/tmp:rw,nosuid,size=16m', '--mount', f'type=volume,source={data},target=/data',
            '--env', 'MINIO_ROOT_USER=synthetic-recovery', '--env', 'MINIO_ROOT_PASSWORD=synthetic-local-only',
            '--env', 'GOMEMLIMIT=128MiB', '--env', 'MINIO_BROWSER=off',
        ], ['server', '/data', '--address', ':9000'])
        # The SDK performs real health-relevant operations in the next phase.
        time.sleep(5)
        return name, data

    original, original_volume = storage('original-storage')
    job('backup-pdf')
    resources.remove('container', original)
    resources.remove('volume', original_volume)
    print('PASS: original synthetic MinIO container and data volume removed', flush=True)
    storage('restored-storage')
    job('restore-pdf', 'dimax_full_restored')
    if resume_outbox:
        # Only the owned test database starts. Normal DIMAX services are untouched.
        docker('start', pg)
        wait_database()
        job('offline', 'dimax_full_restored', outbox=True)
        job('online', 'dimax_full_restored', outbox=True)
        docker('exec', pg, 'pg_dump', '-U', 'postgres', '-d', 'dimax_full_restored', '-Fc', '-f', sent_dump)
        for step, database, archive in (
            ('sent-copy', 'dimax_full_sent', sent_dump),
            ('stale-copy', 'dimax_full_replay', initial_dump),
            ('commit-gap', 'dimax_full_uncertain', initial_dump),
        ):
            docker('exec', pg, 'createdb', '-U', 'postgres', '--template=template0', database)
            docker('exec', pg, 'pg_restore', '-U', 'postgres', '-d', database, '--exit-on-error', '--single-transaction', archive)
            job(step, database, outbox=True)
        job('verify-db', 'dimax_full_source')
        print('PASS: outbox recovery scenarios finished; stale snapshots and SMTP commit gap require operator reconciliation', flush=True)
    print('[full-restore] schema evidence=' + json.dumps(json.loads((work / 'schema-info.json').read_text())), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('postgres', 'app', 'storage'):
        parser.add_argument('--' + name + '-image', required=True)
    parser.add_argument('--resume-outbox', action='store_true', help='Also exercise restored outbox with loopback SMTP only')
    args = parser.parse_args()
    images = (args.postgres_image, args.app_image, args.storage_image)
    preflight(images, resume_outbox=args.resume_outbox)
    for image in images:
        docker('image', 'inspect', image, '--format', '{{.Id}}')
    resources = Resources(uuid4().hex)
    root = Path(__file__).resolve().parents[1]
    temp_root = root / '.tmp'
    temp_root.mkdir(exist_ok=True)
    print('[full-restore] run=' + resources.run_id, flush=True)
    with tempfile.TemporaryDirectory(prefix='full-restore-', dir=temp_root) as temporary:
        try:
            exercise(root, Path(temporary), resources, images, resume_outbox=args.resume_outbox)
        finally:
            resources.cleanup()
    print('PASS: full-schema/PDF synthetic recovery; all owned resources and temporary files removed', flush=True)


if __name__ == '__main__':
    main()
