from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from conftest import TestSessionLocal, TestUnitOfWork as AiTestUow
from test_dimax_ai import API, ai_client, enabled, answer
from app.api.v1.deps import get_current_user
from app.core.config import settings
from app.modules.ai.api.schemas import AiTaskRequest
from app.modules.ai.infrastructure.models import AiTaskORM
from app.modules.ai.infrastructure.provider import AiProviderError, ResponsesProvider
from app.modules.ai.infrastructure.task_store import TaskStore
from app.modules.audit.infrastructure.models import AuditLogORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.shared.domain.errors import Conflict
from app.shared.infrastructure.db.base import utcnow


def payload(**extra):
    return {"request_id": str(uuid.uuid4()), "message": "Find recorded positions", "locale": "ru", **extra}


def store(user):
    return TaskStore(user, lambda: AiTestUow(TestSessionLocal), settings.AI_TIMEOUT_SEC)


def test_saved_result_is_replayed_without_provider_even_when_disabled(ai_client, enabled, monkeypatch, db_session):
    client, user = ai_client
    calls = []
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: calls.append(k) or answer("Saved answer"))
    body = payload()
    first = client.post(f"{API}/tasks", json=body)
    assert first.status_code == 200, first.text
    task = first.json()
    assert task["status"] == "COMPLETED" and task["reply"]["answer"] == "Saved answer"
    assert first.headers["cache-control"] == "no-store"
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr(""))
    second = client.post(f"{API}/tasks", json=body)
    assert second.json() == task and len(calls) == 1
    # Fresh store/session reconstructs the task without any process-local state.
    assert store(user).get(uuid.UUID(task["id"])).reply.answer == "Saved answer"
    history = client.get(f"{API}/conversations/{task['conversation_id']}/tasks").json()
    assert history["items"] == [task]
    logs = db_session.scalars(select(AuditLogORM).where(AuditLogORM.entity_id == uuid.UUID(task["id"]))).all()
    assert len(logs) == 1 and "Find recorded" not in json.dumps(logs[0].after)


@pytest.mark.parametrize("changed", [{"message": "Different"}, {"locale": "he"}, {"conversation_id": str(uuid.uuid4())}])
def test_request_id_cannot_be_rebound_to_different_input(ai_client, enabled, monkeypatch, changed):
    client, _ = ai_client
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: answer())
    body = payload()
    assert client.post(f"{API}/tasks", json=body).status_code == 200
    assert client.post(f"{API}/tasks", json={**body, **changed}).status_code == 409


def test_parallel_claims_across_database_sessions_have_one_execution(ai_client):
    _, user = ai_client
    body = AiTaskRequest(**payload())
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: store(user).start(body), range(4)))
    assert len({task.id for task, _ in claims}) == 1
    assert sum(attempt is not None for _, attempt in claims) == 1


def test_second_http_submission_observes_running_task_without_second_model_call(ai_client, enabled, monkeypatch):
    client, _ = ai_client
    entered, release = Event(), Event()
    calls = []
    def respond(*a, **k):
        calls.append(1); entered.set()
        assert release.wait(10)
        return answer("One execution")
    monkeypatch.setattr(ResponsesProvider, "respond", respond)
    body = payload()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(lambda: client.post(f"{API}/tasks", json=body))
        try:
            assert entered.wait(10)
            second = client.post(f"{API}/tasks", json=body)
            assert second.status_code == 200 and second.json()["status"] == "RUNNING"
        finally:
            release.set()
        completed = first.result(timeout=10)
    assert completed.json()["id"] == second.json()["id"]
    assert completed.json()["status"] == "COMPLETED" and len(calls) == 1


@pytest.mark.parametrize("foreign_company", [False, True])
def test_history_and_task_controls_are_private_to_owner(ai_client, enabled, monkeypatch, db_session, make_user, foreign_company):
    client, user = ai_client
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: answer("Private history"))
    task = client.post(f"{API}/tasks", json=payload()).json()
    cid = uuid.uuid4() if foreign_company else user.company_id
    if foreign_company:
        db_session.add(CompanyORM(id=cid, name="Foreign AI test company", is_active=True)); db_session.commit()
    other = make_user(role=UserRole.ADMIN, company=cid)
    client.app.dependency_overrides[get_current_user] = lambda: replace(user, id=other.id, company_id=cid)
    try:
        assert client.get(f"{API}/conversations").json()["items"] == []
        assert client.get(f"{API}/tasks/{task['id']}").status_code == 404
        assert client.get(f"{API}/conversations/{task['conversation_id']}/tasks").status_code == 404
        assert client.post(f"{API}/tasks/{task['id']}/cancel").status_code == 404
        assert client.post(f"{API}/tasks/{task['id']}/retry", json={"request_id": str(uuid.uuid4())}).status_code == 404
        assert client.post(f"{API}/tasks", json=payload(conversation_id=task["conversation_id"])).status_code == 404
    finally:
        if foreign_company:
            db_session.query(AdminProfileORM).filter_by(company_id=cid).delete()
            db_session.query(UserORM).filter_by(company_id=cid).delete()
            db_session.query(CompanyORM).filter_by(id=cid).delete()
            db_session.commit()


def test_scope_change_hides_old_history_and_replay(ai_client, enabled, monkeypatch, db_session):
    client, user = ai_client
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: answer("Owner context"))
    body = payload()
    task = client.post(f"{API}/tasks", json=body).json()
    profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
    profile.admin_scope = "VIEWER"; db_session.commit()
    client.app.dependency_overrides[get_current_user] = lambda: replace(user, admin_scope="VIEWER")
    assert client.get(f"{API}/conversations").json()["items"] == []
    assert client.get(f"{API}/tasks/{task['id']}").status_code == 404
    assert client.post(f"{API}/tasks", json=body).status_code == 404
    # No mixing old higher-scope history into a new conversation.
    fresh = client.post(f"{API}/tasks", json=payload()).json()
    assert fresh["conversation_id"] != task["conversation_id"]


def test_revocation_during_durable_task_discards_answer_and_records_failure(ai_client, enabled, monkeypatch, db_session):
    client, user = ai_client
    def respond(*a, **k):
        profile = db_session.scalar(select(AdminProfileORM).where(AdminProfileORM.user_id == user.id))
        profile.admin_scope = "FINANCE"; db_session.commit()
        return answer("Do not publish")
    monkeypatch.setattr(ResponsesProvider, "respond", respond)
    result = client.post(f"{API}/tasks", json=payload())
    assert result.status_code == 403 and "Do not publish" not in result.text
    db_session.expire_all()
    task = db_session.scalar(select(AiTaskORM).where(AiTaskORM.owner_user_id == user.id))
    assert task.status == "FAILED" and task.error_code == "AI_ACCESS_CHANGED" and task.reply is None


def test_expired_run_can_be_restarted_once_with_explicit_retry_token(ai_client, enabled, monkeypatch, db_session):
    client, user = ai_client
    task, old_attempt = store(user).start(AiTaskRequest(**payload()))
    row = db_session.get(AiTaskORM, task.id)
    row.lease_expires_at = utcnow() - timedelta(seconds=1); db_session.commit()
    recovered = client.get(f"{API}/tasks/{task.id}").json()
    assert recovered["status"] == "INTERRUPTED"
    calls = []
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: calls.append(1) or answer("Recovered"))
    token = {"request_id": str(uuid.uuid4())}
    retried = client.post(f"{API}/tasks/{task.id}/retry", json=token)
    assert retried.json()["status"] == "COMPLETED" and retried.json()["attempt_count"] == 2
    assert client.post(f"{API}/tasks/{task.id}/retry", json=token).json() == retried.json()
    assert len(calls) == 1
    late = store(user).finish(task.id, old_attempt, store(user).get(task.id).reply,
        tools=[], provider_requests=1, duration_ms=1)
    assert late.reply.answer == "Recovered"


def test_failed_task_requires_explicit_retry_and_has_three_attempt_limit(ai_client, enabled, monkeypatch):
    client, _ = ai_client
    calls = []
    def fail(*a, **k):
        calls.append(1); raise AiProviderError("AI_PROVIDER_LIMIT")
    monkeypatch.setattr(ResponsesProvider, "respond", fail)
    body = payload()
    first = client.post(f"{API}/tasks", json=body).json()
    assert first["status"] == "FAILED" and first["error_code"] == "AI_PROVIDER_LIMIT"
    assert client.post(f"{API}/tasks", json=body).json() == first and len(calls) == 1
    token = {"request_id": str(uuid.uuid4())}
    second = client.post(f"{API}/tasks/{first['id']}/retry", json=token).json()
    assert second["attempt_count"] == 2
    assert client.post(f"{API}/tasks/{first['id']}/retry", json=token).json() == second and len(calls) == 2
    assert client.post(f"{API}/tasks/{first['id']}/retry", json={"request_id": str(uuid.uuid4())}).json()["attempt_count"] == 3
    assert client.post(f"{API}/tasks/{first['id']}/retry", json={"request_id": str(uuid.uuid4())}).status_code == 409
    assert len(calls) == 3


def test_retry_replay_remains_available_after_model_is_switched_off(ai_client, enabled, monkeypatch):
    client, _ = ai_client
    def fail(*a, **k):
        raise AiProviderError("AI_PROVIDER_UNAVAILABLE")
    monkeypatch.setattr(ResponsesProvider, "respond", fail)
    task = client.post(f"{API}/tasks", json=payload()).json()
    token = {"request_id": str(uuid.uuid4())}
    second = client.post(f"{API}/tasks/{task['id']}/retry", json=token).json()
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    assert client.post(f"{API}/tasks/{task['id']}/retry", json=token).json() == second


def test_old_attempt_cannot_publish_into_active_retry(ai_client, db_session):
    _, user = ai_client
    task, old_attempt = store(user).start(AiTaskRequest(**payload()))
    row = db_session.get(AiTaskORM, task.id)
    row.lease_expires_at = utcnow() - timedelta(seconds=1); db_session.commit()
    store(user).get(task.id)
    retried, new_attempt = store(user).retry(task.id, uuid.uuid4())
    from app.modules.ai.api.schemas import AiReply
    late_reply = AiReply(run_id=task.id, answer="Stale attempt", sources=[], tools_used=[], provider_requests=1)
    late = store(user).finish(task.id, old_attempt, late_reply, tools=[], provider_requests=1, duration_ms=1)
    assert late.status == "RUNNING" and late.reply is None and new_attempt != old_attempt
    current_reply = late_reply.model_copy(update={"answer": "Current attempt"})
    completed = store(user).finish(task.id, new_attempt, current_reply, tools=[], provider_requests=1, duration_ms=1)
    assert completed.status == "COMPLETED" and completed.reply.answer == "Current attempt"


def test_cancel_wins_over_provider_response_and_cannot_be_retried(ai_client, enabled, monkeypatch):
    client, user = ai_client
    def respond(*a, **k):
        task = store(user).tasks(store(user).conversations(1, 0).items[0].id, 1, 0).items[0]
        assert client.post(f"{API}/tasks/{task.id}/cancel").json()["status"] == "CANCELLED"
        return answer("Late answer")
    monkeypatch.setattr(ResponsesProvider, "respond", respond)
    result = client.post(f"{API}/tasks", json=payload()).json()
    assert result["status"] == "CANCELLED" and result["reply"] is None
    assert client.post(f"{API}/tasks/{result['id']}/retry", json={"request_id": str(uuid.uuid4())}).status_code == 409


def test_history_reaches_next_turn_without_replaying_old_tool_payloads(ai_client, enabled, monkeypatch):
    client, _ = ai_client
    requests = []
    def respond(*a, **kwargs):
        requests.append(kwargs)
        return answer("Recorded earlier" if len(requests) == 1 else "Follow-up")
    monkeypatch.setattr(ResponsesProvider, "respond", respond)
    first = client.post(f"{API}/tasks", json=payload(message="First question")).json()
    second = client.post(f"{API}/tasks", json=payload(message="Follow up", conversation_id=first["conversation_id"])).json()
    assert second["status"] == "COMPLETED"
    assert requests[1]["items"] == [
        {"role": "user", "content": "First question"}, {"role": "assistant", "content": "Recorded earlier"},
        {"role": "user", "content": "Follow up"}]
    assert "Re-read tools for current facts" in requests[1]["instructions"]
    page = client.get(f"{API}/conversations/{first['conversation_id']}/tasks?limit=1").json()
    assert page["has_more"] and page["items"][0]["id"] == second["id"]


def test_only_one_active_task_per_conversation_and_no_key_creates_nothing(ai_client, monkeypatch):
    client, user = ai_client
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr(""))
    assert client.post(f"{API}/tasks", json=payload()).status_code == 503
    assert store(user).conversations(20, 0).items == []
    first, _ = store(user).start(AiTaskRequest(**payload()))
    with pytest.raises(Conflict):
        store(user).start(AiTaskRequest(**payload(conversation_id=str(first.conversation_id))))


def test_memory_context_is_bounded_and_old_failed_task_cannot_retry_after_followup(ai_client, enabled, monkeypatch):
    client, user = ai_client
    monkeypatch.setattr(ResponsesProvider, "respond", lambda *a, **k: answer("x" * 16000))
    first = client.post(f"{API}/tasks", json=payload(message="One")).json()
    second = client.post(f"{API}/tasks", json=payload(message="Two", conversation_id=first["conversation_id"])).json()
    third, attempt = store(user).start(AiTaskRequest(**payload(conversation_id=first["conversation_id"])))
    history = store(user).history(third.id, attempt)
    assert len(history) == 2 and sum(len(item["content"]) for item in history) <= 24000
    assert history[0]["content"] == "Two"
    # An interrupted old turn cannot be inserted behind a later turn.
    store(user).cancel(third.id)
    with AiTestUow(TestSessionLocal) as uow:
        row = uow.session.get(AiTaskORM, uuid.UUID(second["id"]))
        row.status = "FAILED"; row.reply = None; row.error_code = "AI_TASK_FAILED"
    assert client.post(f"{API}/tasks/{second['id']}/retry", json={"request_id": str(uuid.uuid4())}).status_code == 409
