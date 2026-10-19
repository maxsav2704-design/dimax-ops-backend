"""DIMAX AI background execution: the API queues, the worker claims once and runs the same pipeline."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from test_dimax_ai import API, ai_client, enabled, answer, call  # noqa: F401 (fixtures)
from app.core.config import settings
from app.modules.ai.infrastructure.models import AiTaskORM
from app.modules.ai.infrastructure.provider import ResponsesProvider
from app.modules.doors.infrastructure.models import DoorORM
from app.modules.identity.infrastructure.models import AdminProfileORM
from app.modules.issues.infrastructure.models import IssueORM
from app.modules.projects.infrastructure.models import ProjectORM
from app.shared.infrastructure.db.base import utcnow
from app.workers.ai_worker import run_once


@pytest.fixture
def background(enabled, monkeypatch):
    monkeypatch.setattr(settings, "AI_EXECUTION_MODE", "background")
    monkeypatch.setattr(settings, "AI_ACTIONS_ENABLED", True)


def payload(message="Какие объекты активны?", **extra):
    return {"request_id": str(uuid.uuid4()), "message": message, "locale": "ru", **extra}


def scripted(monkeypatch, *responses):
    sent = []
    def respond(self, **kwargs):
        sent.append({**kwargs, "items": list(kwargs["items"])})
        return responses[min(len(sent), len(responses)) - 1]
    monkeypatch.setattr(ResponsesProvider, "respond", respond)
    return sent


def test_api_queues_and_the_worker_runs_exactly_once(ai_client, background, monkeypatch, db_session):
    client, _ = ai_client
    sent = scripted(monkeypatch, answer("Фоновый ответ"))
    assert client.get(f"{API}/status").json()["execution"] == "background"
    body = payload()
    created = client.post(f"{API}/tasks", json=body)
    assert created.status_code == 200, created.text
    task = created.json()
    assert task["status"] == "RUNNING" and task["reply"] is None and sent == []
    row = db_session.get(AiTaskORM, uuid.UUID(task["id"]))
    assert row.claimed_at is None
    # The client polls; nothing happens until the worker claims the task.
    assert client.get(f"{API}/tasks/{task['id']}").json()["status"] == "RUNNING"
    assert run_once() == 1
    done = client.get(f"{API}/tasks/{task['id']}").json()
    assert done["status"] == "COMPLETED" and done["reply"]["answer"] == "Фоновый ответ" and len(sent) == 1
    assert run_once() == 0
    # Replay of the same request returns the saved state without a second run.
    assert client.post(f"{API}/tasks", json=body).json()["reply"]["answer"] == "Фоновый ответ"
    assert len(sent) == 1


def test_parallel_workers_claim_a_task_once(ai_client, background, monkeypatch):
    client, _ = ai_client
    sent = scripted(monkeypatch, answer("Once"))
    client.post(f"{API}/tasks", json=payload())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: run_once(), range(4)))
    assert sum(results) == 1 and len(sent) == 1


def test_inline_tasks_are_never_picked_by_the_worker(ai_client, enabled, monkeypatch):
    client, _ = ai_client
    sent = scripted(monkeypatch, answer("Inline"))
    monkeypatch.setattr(settings, "AI_EXECUTION_MODE", "inline")
    task = client.post(f"{API}/tasks", json=payload()).json()
    assert task["status"] == "COMPLETED" and len(sent) == 1
    assert run_once() == 0 and len(sent) == 1


def test_revoked_access_before_the_worker_runs_discards_the_answer(ai_client, background, monkeypatch, db_session):
    client, user = ai_client
    scripted(monkeypatch, answer("Must not be delivered"))
    task = client.post(f"{API}/tasks", json=payload()).json()
    profile = db_session.execute(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id)).scalar_one()
    profile.admin_scope = "FINANCE"
    db_session.commit()
    assert run_once() == 1
    row = db_session.get(AiTaskORM, uuid.UUID(task["id"]))
    db_session.refresh(row)
    assert row.status == "FAILED" and row.error_code == "AI_ACCESS_CHANGED" and row.reply is None


def test_cancelled_and_expired_tasks_are_not_executed_and_retry_requeues(ai_client, background, monkeypatch, db_session):
    client, _ = ai_client
    sent = scripted(monkeypatch, answer("Late"))
    cancelled = client.post(f"{API}/tasks", json=payload("Отмени")).json()
    assert client.post(f"{API}/tasks/{cancelled['id']}/cancel").json()["status"] == "CANCELLED"
    assert run_once() == 0 and sent == []

    queued = client.post(f"{API}/tasks", json=payload("Ждёт воркер", conversation_id=None)).json()
    row = db_session.get(AiTaskORM, uuid.UUID(queued["id"]))
    row.lease_expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert run_once() == 0 and sent == []
    interrupted = client.get(f"{API}/tasks/{queued['id']}").json()
    assert interrupted["status"] == "INTERRUPTED"
    retried = client.post(f"{API}/tasks/{queued['id']}/retry", json={"request_id": str(uuid.uuid4())}).json()
    assert retried["status"] == "RUNNING" and retried["attempt_count"] == 2
    db_session.refresh(row)
    assert row.claimed_at is None
    assert run_once() == 1 and len(sent) == 1
    assert client.get(f"{API}/tasks/{queued['id']}").json()["reply"]["answer"] == "Late"


def test_worker_run_proposals_are_confirmable_by_the_owner(ai_client, background, monkeypatch, db_session, company_id, make_door_type):
    client, _ = ai_client
    project = ProjectORM(company_id=company_id, name="Worker Project", address="W 1")
    db_session.add(project); db_session.flush()
    door = DoorORM(company_id=company_id, project_id=project.id, door_type_id=make_door_type().id, unit_label="W-1", our_price=Decimal("1"))
    db_session.add(door); db_session.commit()
    scripted(monkeypatch,
        call("propose_issue_report", {"door_id": str(door.id), "title": "Queued report", "details": None, "priority": None}, "c1"),
        answer("Предложение подготовлено"))
    task = client.post(f"{API}/tasks", json=payload("Замечание на W-1", context={"kind": "project", "id": str(project.id)})).json()
    assert task["status"] == "RUNNING" and task["proposals"] == []
    assert run_once() == 1
    done = client.get(f"{API}/tasks/{task['id']}").json()
    assert done["status"] == "COMPLETED" and done["reply"]["tools_used"] == ["project_summary", "propose_issue_report"]
    proposal = done["proposals"][0]
    assert proposal["status"] == "PROPOSED"
    executed = client.post(f"{API}/proposals/{proposal['id']}/confirm", json={"request_id": str(uuid.uuid4())}).json()
    assert executed["status"] == "EXECUTED"
    assert db_session.query(IssueORM).filter(IssueORM.door_id == door.id).one().title == "Queued report"


def test_worker_serves_the_mock_provider_without_a_key(ai_client, monkeypatch):
    client, _ = ai_client
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_EXECUTION_MODE", "background")
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: pytest.fail("No OpenAI call expected"))
    task = client.post(f"{API}/tasks", json=payload("Какие объекты активны?")).json()
    assert task["status"] == "RUNNING"
    assert run_once() == 1
    done = client.get(f"{API}/tasks/{task['id']}").json()
    assert done["status"] == "COMPLETED" and done["reply"]["provider"] == "mock"


def test_worker_marks_a_missing_context_with_a_named_code(ai_client, background, monkeypatch, db_session):
    client, _ = ai_client
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: pytest.fail("Foreign context must not reach the provider"))
    task = client.post(f"{API}/tasks", json=payload("Что здесь?", context={"kind": "project", "id": str(uuid.uuid4())})).json()
    assert task["status"] == "RUNNING"
    assert run_once() == 1
    done = client.get(f"{API}/tasks/{task['id']}").json()
    assert done["status"] == "FAILED" and done["error_code"] == "AI_CONTEXT_NOT_FOUND" and done["reply"] is None
