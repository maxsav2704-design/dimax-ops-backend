"""Container-side synthetic acceptance; never run against application services."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from difflib import unified_diff
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid

WORK = Path('/work')
BUCKET = 'dimax-recovery'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def guard():
    from sqlalchemy.engine import make_url
    from app.core.config import settings
    url = make_url(settings.DATABASE_URL)
    require(os.environ.get('DIMAX_FULL_RESTORE') == 'synthetic-only', 'Explicit acceptance flag required')
    require(url.host == 'recovery-db' and url.database in {'dimax_full_source', 'dimax_full_restored'}, 'Unsafe database coordinates')
    require(settings.MINIO_ENDPOINT == 'recovery-storage:9000' and settings.MINIO_BUCKET == BUCKET, 'Unsafe storage coordinates')
    require(not settings.EMAIL_ENABLED and not settings.WHATSAPP_ENABLED and not settings.AI_ENABLED, 'External delivery must be disabled')
    require(not Path('.env').exists(), 'No dotenv file may be present')


def save(name, value):
    (WORK / name).write_text(json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2), encoding='utf-8')


def load(name):
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def wait_storage():
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with opener.open('http://recovery-storage:9000/minio/health/ready', timeout=3) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError('Isolated MinIO not ready')


def engine():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from app.core.config import settings
    return create_engine(settings.DATABASE_URL, poolclass=NullPool)


def fingerprint(evidence_name=None):
    from scripts.db_backup_restore_smoke import snapshot_with_query
    db = engine()
    evidence = {}
    try:
        with db.connect() as connection:
            connection.exec_driver_sql("SET TIME ZONE 'UTC'")
            connection.exec_driver_sql("SET datestyle='ISO,YMD'")

            def query(sql, *, stdout=None):
                def cell(value):
                    if value is None:
                        return ''
                    if isinstance(value, bool):
                        return 't' if value else 'f'
                    return str(value)
                rows = connection.exec_driver_sql(sql)
                target = stdout if stdout is not None else BytesIO()
                for row in rows:
                    target.write(('|'.join(cell(value) for value in row) + '\n').encode('utf-8'))
                if stdout is not None:
                    return None
                value = target.getvalue()
                evidence[sql] = value.decode('utf-8')
                return value

            result = snapshot_with_query(query)
            # pg_dump restores these too; include definitions beyond base tables.
            catalogs = {
                'views': "SELECT schemaname,viewname,definition FROM pg_views WHERE schemaname='public' ORDER BY viewname",
                'routines': "SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind IN ('f','p') ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)",
                'extensions': 'SELECT extname,extversion FROM pg_extension ORDER BY extname',
                'policies': "SELECT * FROM pg_policies WHERE schemaname='public' ORDER BY tablename,policyname",
            }
            for name, sql in catalogs.items():
                result['catalog:' + name] = sha256(query(sql)).hexdigest()
            if evidence_name:
                save(evidence_name, evidence)
            return json.loads(json.dumps(result, default=lambda value: value.decode('utf-8')))
    finally:
        db.dispose()


def refs():
    from sqlalchemy import text
    db = engine()
    try:
        with db.connect() as connection:
            rows = connection.execute(text('SELECT company_id,journal_id,bucket,file_path,size_bytes,mime_type FROM journal_files ORDER BY file_path')).mappings()
            return [{key: str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()} for row in rows]
    finally:
        db.dispose()


def pdf_check(content, entry):
    require(len(content) == entry['size_bytes'], 'PDF size mismatch')
    require(sha256(content).hexdigest() == entry['sha256'], 'PDF SHA256 mismatch')
    require(content.startswith(b'%PDF'), 'Not a PDF')
    from pypdf import PdfReader
    pdf = PdfReader(BytesIO(content), strict=True)
    require(len(pdf.pages) > 0, 'Empty PDF')
    require('SYNTHETIC' in ''.join(page.extract_text() or '' for page in pdf.pages), 'PDF test marker missing')


def object_entry(row, content):
    require(row['bucket'] == BUCKET, 'Unexpected bucket')
    company, journal = str(uuid.UUID(row['company_id'])), str(uuid.UUID(row['journal_id']))
    require(row['file_path'].startswith(f'journals/{company}/{journal}/'), 'Object outside journal scope')
    require('..' not in row['file_path'].split('/') and '\\' not in row['file_path'], 'Unsafe object key')
    require(row['mime_type'] == 'application/pdf', 'Unexpected content type')
    entry = dict(row, sha256=sha256(content).hexdigest())
    pdf_check(content, entry)
    return entry


def seed():
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.shared.infrastructure.db.model_registry import import_all_orm_models
    from app.modules.identity.infrastructure.models import CompanyORM
    from app.modules.projects.infrastructure.models import ProjectORM
    from app.modules.door_types.infrastructure.models import DoorTypeORM
    from app.modules.doors.infrastructure.models import DoorORM
    from app.modules.doors.domain.enums import DoorStatus
    from app.modules.journal.infrastructure.models import JournalORM, JournalDoorItemORM, JournalFileORM, JournalSignatureORM
    from app.modules.journal.domain.enums import JournalStatus
    from app.modules.outbox.infrastructure.models import OutboxMessageORM
    from app.modules.outbox.domain.enums import OutboxChannel
    from app.integrations.pdf.generator import PdfGenerator

    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    expected_heads = sorted(ScriptDirectory.from_config(config).get_heads())
    import_all_orm_models()
    db = engine()
    now = datetime(2026, 11, 10, 9, tzinfo=timezone.utc)
    signature = {'viewport': {'width': 100, 'height': 40}, 'strokes': [[{'x': 10, 'y': 20}, {'x': 80, 'y': 10}]]}
    generated = WORK / 'generated'
    generated.mkdir()
    files = []
    try:
        with Session(db) as session:
            require(sorted(session.execute(text('SELECT version_num FROM alembic_version')).scalars()) == expected_heads, 'Alembic head mismatch')
            for number, locale in enumerate(('he', 'ru'), start=1):
                company = CompanyORM(name=f'SYNTHETIC RECOVERY {number}')
                session.add(company)
                session.flush()
                project = ProjectORM(company_id=company.id, name=f'SYNTHETIC SITE {number}', address='TEST ONLY')
                kind = DoorTypeORM(company_id=company.id, code='TEST-ENTRANCE', name='SYNTHETIC DOOR')
                session.add_all([project, kind])
                session.flush()
                door = DoorORM(company_id=company.id, project_id=project.id, door_type_id=kind.id,
                               unit_label=f'TEST-{number}-101', our_price=Decimal('0.00'),
                               status=DoorStatus.INSTALLED, installed_at=now, is_locked=False)
                journal = JournalORM(company_id=company.id, project_id=project.id, title=f'SYNTHETIC RECOVERY {number}',
                                     pdf_locale=locale, status=JournalStatus.ARCHIVED, signed_at=now,
                                     signer_name='SYNTHETIC TEST SIGNER', notes='TEST ONLY - no legal acceptance')
                session.add_all([door, journal])
                session.flush()
                session.add(JournalDoorItemORM(company_id=company.id, journal_id=journal.id, door_id=door.id,
                                               door_type_id=kind.id, unit_label=door.unit_label, installed_at=now))
                session.add(JournalSignatureORM(company_id=company.id, journal_id=journal.id,
                                                signer_name=journal.signer_name, signature_payload=signature))
                key = f'journals/{company.id}/{journal.id}/journal_{journal.id}_signed.pdf'
                content = PdfGenerator.journal_pdf(journal={
                    'id': str(journal.id), 'title': journal.title, 'pdf_locale': locale, 'signed_at': now,
                    'signer_name': journal.signer_name, 'project_name': project.name,
                    'project_address': project.address, 'notes': journal.notes,
                }, items=[{'unit_label': door.unit_label, 'door_type_name': kind.name, 'installed_at': now}], signature_payload=signature)
                row = {'company_id': str(company.id), 'journal_id': str(journal.id), 'bucket': BUCKET,
                       'file_path': key, 'size_bytes': len(content), 'mime_type': 'application/pdf'}
                entry = object_entry(row, content)
                (generated / (entry['sha256'] + '.pdf')).write_bytes(content)
                files.append(entry)
                session.add(JournalFileORM(company_id=company.id, journal_id=journal.id, kind='PDF',
                                          file_path=key, bucket=BUCKET, size_bytes=len(content), mime_type='application/pdf'))
                session.add(OutboxMessageORM(company_id=company.id, channel=OutboxChannel.EMAIL,
                    correlation_id=journal.id, scheduled_at=now,
                    payload={'to_email': 'synthetic@dimax.example', 'object_key': key, 'subject': 'SYNTHETIC ONLY'}))
            session.commit()
    finally:
        db.dispose()
    save('pdf-manifest.json', files)
    save('references.json', refs())
    snapshot = fingerprint('source-catalog-evidence.json')
    save('source-fingerprint.json', snapshot)
    save('schema-info.json', {'heads': expected_heads, 'tables': sum(key.startswith('public.') for key in snapshot)})
    print('PASS: real migrations at', expected_heads, '; tables=', load('schema-info.json')['tables'], '; synthetic PDFs=2', flush=True)


def verify_database():
    actual = fingerprint('current-catalog-evidence.json')
    expected = load('source-fingerprint.json')
    if actual != expected:
        print('Mismatched fingerprint keys:', sorted(key for key in actual.keys() | expected.keys()
              if actual.get(key) != expected.get(key)), flush=True)
        before, after = load('source-catalog-evidence.json'), load('current-catalog-evidence.json')
        for sql in before.keys() | after.keys():
            if before.get(sql) != after.get(sql):
                print('Catalog query:', sql, flush=True)
                print('\n'.join(unified_diff(before.get(sql, '').splitlines(), after.get(sql, '').splitlines(),
                                            fromfile='source', tofile='restored'))[:6000], flush=True)
        raise RuntimeError('Full schema/data/sequence fingerprint mismatch')
    require(refs() == load('references.json'), 'Restored PDF references differ')
    print('PASS: complete migrated schema and every public table match; PDF references preserved', flush=True)


def storage_backup():
    from app.integrations.storage.storage_service import StorageService
    from app.integrations.storage.minio_client import get_minio
    wait_storage()
    entries = load('pdf-manifest.json')
    require(not get_minio().bucket_exists(BUCKET), 'Source test bucket must be new')
    backup = WORK / 'pdf-backup'
    backup.mkdir()
    for entry in entries:
        content = (WORK / 'generated' / (entry['sha256'] + '.pdf')).read_bytes()
        StorageService.put_pdf(object_key=entry['file_path'], content=content)
        downloaded = StorageService.get_pdf(object_key=entry['file_path'])
        pdf_check(downloaded, entry)
        (backup / (entry['sha256'] + '.pdf')).write_bytes(downloaded)
    require(len(list(get_minio().list_objects(BUCKET, recursive=True))) == len(entries), 'Unexpected source objects')
    print('PASS: PDFs backed up from real MinIO, with SHA256 and PDF parsing', flush=True)


def storage_restore():
    from app.integrations.storage.storage_service import StorageService
    from app.integrations.storage.minio_client import get_minio
    from minio.error import S3Error
    wait_storage()
    client = get_minio()
    require(not client.bucket_exists(BUCKET), 'Restore bucket must be absent on fresh storage')
    entries = load('pdf-manifest.json')
    references = [{key: entry[key] for key in load('references.json')[0]} for entry in entries]
    require(sorted(references, key=lambda row: row['file_path']) == load('references.json'), 'Manifest differs from restored DB references')

    def restore(entry):
        content = (WORK / 'pdf-backup' / (entry['sha256'] + '.pdf')).read_bytes()
        pdf_check(content, entry)
        StorageService.put_pdf(object_key=entry['file_path'], content=content)

    def verify(entry):
        stat = client.stat_object(BUCKET, entry['file_path'])
        require(stat.content_type == 'application/pdf' and stat.size == entry['size_bytes'], 'Object metadata mismatch')
        pdf_check(StorageService.get_pdf(object_key=entry['file_path']), entry)

    for entry in entries:
        restore(entry)
        verify(entry)
    entry = entries[0]
    content = bytearray((WORK / 'pdf-backup' / (entry['sha256'] + '.pdf')).read_bytes())
    content[len(content) // 2] ^= 1
    StorageService.put_pdf(object_key=entry['file_path'], content=bytes(content))
    try:
        verify(entry)
    except RuntimeError as error:
        require(str(error) == 'PDF SHA256 mismatch', 'Unexpected corruption failure')
    else:
        raise RuntimeError('Corrupted PDF accepted')
    restore(entry)
    client.remove_object(BUCKET, entry['file_path'])
    try:
        verify(entry)
    except S3Error as error:
        require(error.code in {'NoSuchKey', 'NoSuchObject'}, 'Unexpected storage failure')
    else:
        raise RuntimeError('Missing PDF accepted')
    restore(entry)
    for entry in entries:
        verify(entry)
    require(len(list(client.list_objects(BUCKET, recursive=True))) == len(entries), 'Unexpected restored objects')
    print('PASS: fresh MinIO restores exact PDFs and metadata; corruption/missing PDF rejected; no mail or business action replayed', flush=True)


if __name__ == '__main__':
    guard()
    {'seed': seed, 'verify-db': verify_database, 'backup-pdf': storage_backup, 'restore-pdf': storage_restore}[sys.argv[1]]()
