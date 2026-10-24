"""Real restored outbox + loopback SMTP. No external recipients or business replay."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from scripts import full_restore_probe as recovery

DATABASES = {'dimax_full_source', 'dimax_full_restored', 'dimax_full_sent',
             'dimax_full_replay', 'dimax_full_uncertain'}
STEPS = {'prepare': 'dimax_full_source', 'offline': 'dimax_full_restored',
         'online': 'dimax_full_restored', 'sent-copy': 'dimax_full_sent',
         'stale-copy': 'dimax_full_replay', 'commit-gap': 'dimax_full_uncertain'}
SMTP_HOST = 'smtp.dimax.example'


def validate_target(step, host, database, flag):
    recovery.require(flag == 'synthetic-only', 'Explicit outbox acceptance flag required')
    recovery.require(host == 'recovery-db' and STEPS.get(step) == database,
                     'Unsafe outbox recovery target or phase')


def queue():
    db = recovery.engine()
    try:
        with db.connect() as connection:
            return [json.loads(row[0]) for row in connection.exec_driver_sql(
                'SELECT row_to_json(m)::text FROM outbox_messages m ORDER BY id')]
    finally:
        db.dispose()


def business_snapshot():
    """All business rows stay exact; only explicit delivery fields may change."""
    db = recovery.engine()
    try:
        with db.connect() as connection:
            connection.exec_driver_sql("SET TIME ZONE 'UTC'")
            tables = connection.exec_driver_sql("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='public' AND table_type='BASE TABLE'
                  AND table_name <> 'outbox_messages' ORDER BY table_name
            """).scalars().all()
            result = {}
            for table in tables:
                expression = 'to_jsonb(t)'
                if table == 'journals':
                    expression += " - ARRAY['email_delivery_status','email_last_sent_at','email_last_error','updated_at']"
                quoted = connection.dialect.identifier_preparer.quote(table)
                rows = connection.exec_driver_sql(f'SELECT ({expression})::text FROM public.{quoted} t ORDER BY 1').scalars()
                result[table] = list(rows)
            recovery.require(len(result['completed_work']) == 2, 'Expected two synthetic ledger entries')
            recovery.require(len(result['journal_signatures']) == 2, 'Expected two synthetic signatures')
            return result
    finally:
        db.dispose()


def assert_business():
    recovery.require(business_snapshot() == recovery.load('outbox-business.json'),
                     'Business rows changed during recovery/delivery')
    expected = recovery.load('outbox-queue.json')
    rows = queue()
    recovery.require([(r['id'], r['payload'], r['correlation_id'], r['company_id']) for r in rows] ==
                     [(r['id'], r['payload'], r['correlation_id'], r['company_id']) for r in expected],
                     'Queue lost, duplicated or changed message identity/payload')


def prepare():
    from sqlalchemy.orm import Session
    from app.modules.installers.infrastructure.models import InstallerORM
    from app.modules.doors.infrastructure.models import DoorORM
    from app.modules.earnings.infrastructure.models import CompletedWorkORM
    from app.modules.journal.infrastructure.models import JournalORM
    from app.modules.outbox.infrastructure.models import OutboxMessageORM
    from app.modules.outbox.domain.enums import OutboxStatus, OutboxChannel
    from app.shared.infrastructure.db.model_registry import import_all_orm_models
    import_all_orm_models()
    db = recovery.engine()
    now = datetime.now(timezone.utc)
    try:
        with Session(db) as session:
            messages = session.query(OutboxMessageORM).order_by(OutboxMessageORM.id).all()
            recovery.require(len(messages) == 2, 'Fresh recovery fixture required')
            for number, message in enumerate(messages):
                journal = session.get(JournalORM, message.correlation_id)
                door = session.query(DoorORM).filter_by(company_id=message.company_id).one()
                installer = InstallerORM(company_id=message.company_id, full_name='SYNTHETIC RECOVERY INSTALLER')
                session.add(installer)
                session.flush()
                door.installer_id = installer.id
                journal.installer_id = installer.id
                # Historical synthetic ledger fixture, not factory price approval.
                session.add(CompletedWorkORM(company_id=message.company_id, project_id=door.project_id,
                    door_id=door.id, installer_id=installer.id, completed_at=door.installed_at,
                    rate_snapshot=Decimal('9.01'), amount_snapshot=Decimal('9.01'),
                    reason='SYNTHETIC historical fixture; not a real approved price'))
                message.payload = dict(message.payload, subject=f'SYNTHETIC DUE {number}',
                    body_text='Synthetic journal recovery only', cc_emails=['admin@dimax.example'],
                    attachment_name='SYNTHETIC-journal.pdf')
                message.attempts = number
                message.scheduled_at = now - timedelta(minutes=5)
            template = messages[0]
            for label, status, attempts, scheduled in (
                ('SENT', OutboxStatus.SENT, 1, now - timedelta(days=1)),
                ('FAILED', OutboxStatus.FAILED, 5, now - timedelta(days=1)),
                ('DELAYED', OutboxStatus.PENDING, 0, now + timedelta(days=30)),
            ):
                session.add(OutboxMessageORM(company_id=template.company_id,
                    correlation_id=template.correlation_id, channel=OutboxChannel.EMAIL,
                    payload=dict(template.payload, subject='SYNTHETIC ' + label), status=status,
                    attempts=attempts, max_attempts=5, scheduled_at=scheduled,
                    sent_at=now if status == OutboxStatus.SENT else None,
                    last_error='Synthetic terminal failure' if status == OutboxStatus.FAILED else None))
            session.commit()
    finally:
        db.dispose()
    recovery.save('outbox-queue.json', queue())
    recovery.save('outbox-business.json', business_snapshot())
    recovery.save('source-fingerprint.json', recovery.fingerprint('source-catalog-evidence.json'))
    print('PASS: five synthetic queue jobs and two historical ledger entries prepared before backup', flush=True)


def worker():
    from app.workers import outbox_worker
    from app.shared.infrastructure.db.model_registry import import_all_orm_models
    import_all_orm_models()
    return outbox_worker


@contextmanager
def smtp_settings(port, certificates=None):
    from app.integrations.email import smtp_sender
    original = socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        recovery.require(host in {SMTP_HOST, 'recovery-db', 'recovery-storage'}, 'Unexpected network destination')
        return original('127.0.0.1' if host == SMTP_HOST else host, port, *args, **kwargs)

    env = {}
    if certificates:
        empty = certificates / 'empty-ca'
        empty.mkdir()
        env = {'SSL_CERT_FILE': str(certificates / 'trusted.pem'), 'SSL_CERT_DIR': str(empty)}
    with (patch.object(smtp_sender, 'settings', SimpleNamespace(
        SMTP_HOST=SMTP_HOST, SMTP_PORT=port, SMTP_TLS=True, SMTP_USER='synthetic-mailer',
        SMTP_PASSWORD='synthetic-test-only', SMTP_FROM='notifications@dimax.example')),
          patch('socket.getaddrinfo', resolve), patch.dict(os.environ, env)):
        yield


@contextmanager
def smtp_capture():
    sys.path.insert(0, '/probe/tests')
    from test_smtp_tls_transport import certificates, capture_server
    with tempfile.TemporaryDirectory(prefix='dimax-recovery-smtp-') as folder:
        def mktemp(name):
            result = Path(folder) / name
            result.mkdir()
            return result
        certs = certificates.__wrapped__(SimpleNamespace(mktemp=mktemp))
        with capture_server(certs, 'valid') as server, smtp_settings(server.server_address[1], certs):
            yield server


def due_rows(rows):
    return [row for row in rows if row['payload']['subject'].startswith('SYNTHETIC DUE ')]


def assert_skipped_unchanged():
    expected = recovery.load('outbox-queue.json')
    rows = queue()
    due_ids = {row['id'] for row in due_rows(expected)}
    recovery.require([r for r in rows if r['id'] not in due_ids] ==
                     [r for r in expected if r['id'] not in due_ids],
                     'SENT, terminal FAILED or future job was changed')


def force_due():
    from sqlalchemy import text
    db = recovery.engine()
    try:
        with db.begin() as connection:
            for row in due_rows(queue()):
                connection.execute(text('UPDATE outbox_messages SET scheduled_at=:now WHERE id=:id'),
                                   {'now': datetime.now(timezone.utc) - timedelta(seconds=1), 'id': row['id']})
    finally:
        db.dispose()


def received(server):
    by_subject = {row['payload']['subject']: row for row in queue()}
    manifest = {row['file_path']: row for row in recovery.load('pdf-manifest.json')}
    ids = []
    for data in server.messages:
        mail = BytesParser(policy=policy.default).parsebytes(data)
        row = by_subject[str(mail['Subject'])]
        recovery.require(mail['To'] == row['payload']['to_email'] and mail['Cc'] == 'admin@dimax.example', 'Wrong recipient')
        attachment, = mail.iter_attachments()
        recovery.require(attachment.get_content_type() == 'application/pdf', 'Not a PDF attachment')
        recovery.require(sha256(attachment.get_payload(decode=True)).hexdigest() ==
                         manifest[row['payload']['object_key']]['sha256'], 'Wrong restored PDF attachment')
        ids.append(row['id'])
    return ids


def offline():
    assert_business()
    w = worker()
    with socket.socket() as unavailable:
        unavailable.bind(('127.0.0.1', 0))
        with smtp_settings(unavailable.getsockname()[1]):
            recovery.require(w.run_once() == 0 and w.run_once() == 0, 'SMTP outage reported delivery')
    before = {row['id']: row for row in recovery.load('outbox-queue.json')}
    for row in due_rows(queue()):
        recovery.require(row['status'] == 'PENDING' and row['attempts'] == before[row['id']]['attempts'] + 1
                         and row['sent_at'] is None and 'refused' in row['last_error'].lower(), 'Retry state not durable')
        recovery.require(datetime.fromisoformat(row['scheduled_at']) > datetime.now(timezone.utc), 'Missing retry backoff')
    assert_skipped_unchanged()
    assert_business()
    recovery.save('outbox-offline-queue.json', queue())
    print('PASS: restored queue survives SMTP refusal and backoff; no business changes', flush=True)


def online():
    recovery.require(queue() == recovery.load('outbox-offline-queue.json'), 'Retry state lost across worker process restart')
    force_due()  # Advance only synthetic retry deadlines; no real waiting or retry API bypass.
    w = worker()
    with smtp_capture() as server:
        recovery.require(w.run_once() == 2 and w.run_once() == 0, 'Expected two deliveries then idle')
        ids = received(server)
    recovery.require(sorted(ids) == sorted(row['id'] for row in due_rows(queue())), 'Duplicate or missing delivery')
    recovery.require(all(row['status'] == 'SENT' and row['sent_at'] for row in due_rows(queue())), 'SENT not durable')
    assert_skipped_unchanged()
    assert_business()
    recovery.save('outbox-online-queue.json', queue())
    recovery.save('outbox-accepted-ids.json', ids)
    print('PASS: fresh worker process submits two exact restored PDFs once; five queue identities and business ledger preserved', flush=True)


def sent_copy():
    recovery.require(queue() == recovery.load('outbox-online-queue.json'), 'Post-send backup lost durable queue state')
    with smtp_capture() as server:
        recovery.require(worker().run_once() == 0 and not server.messages, 'Post-send restore resent a completed job')
    assert_skipped_unchanged()
    assert_business()
    print('PASS: backup restored after SENT commit does not resend; FAILED and future jobs remain untouched', flush=True)


def stale_copy():
    recovery.require(queue() == recovery.load('outbox-queue.json'), 'Stale scenario must restore the original pre-send dump')
    with smtp_capture() as server:
        recovery.require(worker().run_once() == 2, 'Stale snapshot did not expose expected pending work')
        ids = received(server)
    recovery.require(sorted(ids) == sorted(recovery.load('outbox-accepted-ids.json')), 'Expected already accepted IDs')
    assert_business()
    print('RISK CONFIRMED: stale backup resubmits two previously accepted emails; business rows unchanged. Keep production worker stopped until delivery reconciliation.', flush=True)


def commit_gap():
    from sqlalchemy.orm import Session, sessionmaker
    w = worker()
    failed = False
    db = recovery.engine()

    class FailCommitOnce(Session):
        def commit(self):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError('Synthetic commit failure after SMTP acceptance')
            return super().commit()

    try:
        with smtp_capture() as server, patch.object(w, 'SessionLocal', sessionmaker(bind=db, class_=FailCommitOnce)):
            recovery.require(w.run_once() == 0 and failed, 'Expected uncertain SMTP/DB boundary')
            recovery.require(queue() == recovery.load('outbox-queue.json'), 'Failed commit persisted partial state')
            assert_business()
            recovery.require(w.run_once() == 2 and w.run_once() == 0, 'Expected retained jobs to retry')
            ids = received(server)
        recovery.require(len(ids) == 3 and len(set(ids)) == 2, 'Expected one duplicate SMTP acceptance')
        assert_business()
        print('RISK CONFIRMED: SMTP acceptance before failed DB commit can duplicate email, never earnings/signatures/work. Exactly-once SMTP is not claimed.', flush=True)
    finally:
        db.dispose()


if __name__ == '__main__':
    from sqlalchemy.engine import make_url
    from app.core.config import settings
    step = sys.argv[1]
    url = make_url(settings.DATABASE_URL)
    validate_target(step, url.host, url.database, os.environ.get('DIMAX_OUTBOX_RESTORE'))
    recovery.guard(allowed_databases=DATABASES)
    {'prepare': prepare, 'offline': offline, 'online': online, 'sent-copy': sent_copy,
     'stale-copy': stale_copy, 'commit-gap': commit_gap}[step]()
