"""Sync audit block 7: change-log cursors must become visible in order, and a
device whose cursor is ahead of the server gets a cold snapshot."""
from __future__ import annotations

import threading
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.sync.domain.enums import SyncChangeType
from app.modules.sync.infrastructure.repositories import SyncChangeLogRepository


def _add_change(session: Session, company_id: uuid.UUID) -> None:
    SyncChangeLogRepository(session).add_change(
        company_id=company_id,
        change_type=SyncChangeType.PROJECT_BASE,
        entity_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        installer_id=None,
        payload={"name": "ordering"},
    )
    session.flush()


def test_change_log_writers_of_one_company_commit_in_cursor_order(db_session, company_id):
    """Without the company lock a second writer could take a higher cursor and commit
    first, so a reader served that cursor would never see the lower one."""
    _add_change(db_session, company_id)  # holds the company row until commit
    second_done = threading.Event()
    second_error: list[BaseException] = []

    def second_writer():
        session = Session(bind=db_session.get_bind())
        try:
            _add_change(session, company_id)
            session.commit()
            second_done.set()
        except BaseException as exc:  # noqa: BLE001 - surfaced through the assertion below
            second_error.append(exc)
            session.rollback()
            second_done.set()
        finally:
            session.close()

    thread = threading.Thread(target=second_writer, daemon=True)
    thread.start()
    # The second writer must wait for the first transaction, not overtake it.
    assert not second_done.wait(timeout=1.0)
    db_session.commit()
    assert second_done.wait(timeout=10.0)
    thread.join(timeout=5.0)
    assert not second_error, second_error[0]

    cursors = [
        row[0]
        for row in db_session.execute(
            text("SELECT cursor_id FROM sync_change_log WHERE company_id = :cid ORDER BY cursor_id"),
            {"cid": str(company_id)},
        )
    ]
    assert len(cursors) == 2 and cursors[0] < cursors[1]


def test_installer_sync_ahead_of_server_cursor_gets_a_cold_snapshot(client_installer):
    response = client_installer.post(
        "/api/v1/installer/sync",
        json={"since_cursor": 10_000_000, "ack_cursor": 0, "events": [], "device_id": "ahead-device"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reset_required"] is True
    assert body["snapshot"] is not None
