"""Proposals: the only bridge between the model loop and business commands.

An action tool stores a PROPOSED row (arguments, preview, expected versions).
A separate authenticated confirmation re-checks the actor, the write scope and
the feature flag, claims the row with a client request id (idempotent), then
executes the existing business command and the EXECUTED mark in one
transaction. A lost response is recovered by repeating the same request id;
a different request id on a finished proposal never executes it again.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

from sqlalchemy import func, select, text

from app.modules.ai.api.schemas import AiProposal
from app.modules.ai.application.actions import ACTIONS
from app.modules.ai.domain.tools import TOOL_SPECS, allowed_tool_names
from app.modules.ai.infrastructure.models import AiProposalORM
from app.modules.ai.infrastructure.read_tools import load_actor
from app.modules.audit.application.service import AuditService
from app.shared.domain.errors import Conflict, DomainError, Forbidden, ForbiddenScope, NotFound, ValidationError
from app.shared.infrastructure.db.base import utcnow

PROPOSAL_NOTE = ("Not executed. The user must confirm this proposal in the DIMAX interface;"
                 " do not claim the change was saved.")


def advisory_lock(uow, user) -> None:
    # Database-backed serialization per company/user across API workers; ends with the transaction.
    key = int.from_bytes(hashlib.sha256(f"ai:{user.company_id}:{user.id}".encode()).digest()[:8], "big", signed=True)
    uow.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


class ProposalStore:
    def __init__(self, user, uow_factory, settings):
        self.user = user
        self.uow_factory = uow_factory
        self.settings = settings

    # ---- helpers -------------------------------------------------------------------
    def _actor(self, uow, *, require_action: str | None = None):
        current = load_actor(uow, self.user)
        if current.admin_scope != self.user.admin_scope:
            raise ForbiddenScope("AI permissions changed")
        if require_action and require_action not in allowed_tool_names(current):
            raise ForbiddenScope("Business actions are not available for this account")
        return current

    def _owned(self):
        return select(AiProposalORM).where(AiProposalORM.company_id == self.user.company_id,
                                           AiProposalORM.owner_user_id == self.user.id)

    @staticmethod
    def _expire(row) -> None:
        if row.status == "PROPOSED" and row.expires_at <= utcnow():
            row.status = "EXPIRED"
            row.error_code = "AI_PROPOSAL_EXPIRED"
            row.updated_at = utcnow()

    def _get(self, uow, proposal_id):
        row = uow.session.scalar(self._owned().where(AiProposalORM.id == proposal_id))
        if row is None:
            raise NotFound("AI proposal not found")
        self._expire(row)
        return row

    @staticmethod
    def view(row) -> AiProposal:
        return AiProposal.model_validate({name: getattr(row, name) for name in AiProposal.model_fields})

    @staticmethod
    def tool_output(row) -> dict:
        return {"proposal_id": str(row.id), "status": row.status, "executed": False, "preview": row.preview,
                "expires_at": row.expires_at.isoformat(), "note": PROPOSAL_NOTE}

    def _audit(self, uow, row, action, after) -> None:
        AuditService.add(uow, company_id=self.user.company_id, actor_user_id=self.user.id,
                         entity_type="AiProposal", entity_id=row.id, action=action, after=after)

    # ---- reads -----------------------------------------------------------------------
    def list_for_task(self, uow, task_id) -> list[AiProposal]:
        rows = uow.session.scalars(self._owned().where(AiProposalORM.task_id == task_id)
                                   .order_by(AiProposalORM.created_at, AiProposalORM.id)).all()
        for row in rows:
            self._expire(row)
        return [self.view(row) for row in rows]

    def get(self, proposal_id) -> AiProposal:
        with self.uow_factory() as uow:
            advisory_lock(uow, self.user)
            self._actor(uow)
            return self.view(self._get(uow, proposal_id))

    # ---- model loop: store a proposal, never execute --------------------------------
    def propose(self, *, task_id, conversation_id, name: str, args) -> dict:
        with self.uow_factory() as uow:
            advisory_lock(uow, self.user)
            self._actor(uow, require_action=name)
            count = uow.session.scalar(select(func.count(AiProposalORM.id)).where(
                AiProposalORM.company_id == self.user.company_id, AiProposalORM.task_id == task_id))
            if count >= self.settings.AI_MAX_PROPOSALS_PER_TASK:
                raise ValidationError("Proposal limit for this task reached; ask the user to confirm or reject the existing ones")
            preview = ACTIONS[name].preview(uow, self.user, args)
            now = utcnow()
            row = AiProposalORM(id=uuid.uuid4(), company_id=self.user.company_id, owner_user_id=self.user.id,
                                conversation_id=conversation_id, task_id=task_id, tool_name=name,
                                arguments=args.model_dump(mode="json"),
                                preview={key: preview[key] for key in ("entity", "summary", "before", "after")},
                                expected=preview["expected"], status="PROPOSED",
                                expires_at=now + timedelta(seconds=self.settings.AI_PROPOSAL_TTL_SEC),
                                created_at=now, updated_at=now)
            uow.session.add(row)
            uow.session.flush()
            self._audit(uow, row, "AI_PROPOSAL_CREATED", {"tool": name, "task_id": str(task_id),
                        "entity_kind": preview["entity"]["kind"], "entity_id": preview["entity"]["id"]})
            return self.tool_output(row)

    # ---- decisions ---------------------------------------------------------------------
    def reject(self, proposal_id) -> AiProposal:
        with self.uow_factory() as uow:
            advisory_lock(uow, self.user)
            self._actor(uow)
            row = self._get(uow, proposal_id)
            if row.status == "PROPOSED":
                row.status = "REJECTED"
                row.decided_at = utcnow()
                row.updated_at = row.decided_at
                self._audit(uow, row, "AI_PROPOSAL_REJECTED", {"tool": row.tool_name})
            return self.view(row)

    def confirm(self, proposal_id, request_id) -> AiProposal:
        # Phase 1: claim the proposal with the client's request id (short transaction, no business write).
        with self.uow_factory() as uow:
            advisory_lock(uow, self.user)
            row = self._get(uow, proposal_id)
            if row.status == "CONFIRMED" and row.confirm_request_id != request_id:
                raise Conflict("Proposal confirmation is already in progress")
            if row.status != "PROPOSED" and not (row.status == "CONFIRMED" and row.confirm_request_id == request_id):
                # EXECUTED / REJECTED / EXPIRED / FAILED / CONFLICT: a replay or a late click never executes again.
                return self.view(row)
            self._actor(uow, require_action=row.tool_name)
            if row.status == "PROPOSED":
                row.status = "CONFIRMED"
                row.confirm_request_id = request_id
                row.decided_at = utcnow()
                row.updated_at = row.decided_at
            name, arguments, expected = row.tool_name, dict(row.arguments), dict(row.expected)
        args = TOOL_SPECS[name].args.model_validate(arguments)
        # Phase 2: the business command and the EXECUTED mark succeed or fail together.
        failure = None
        try:
            with self.uow_factory() as uow:
                advisory_lock(uow, self.user)
                self._actor(uow, require_action=name)
                row = self._get(uow, proposal_id)
                if row.status != "CONFIRMED" or row.confirm_request_id != request_id:
                    return self.view(row)
                outcome = ACTIONS[name].execute(uow, self.user, args, expected)
                row.status = "EXECUTED"
                row.result = outcome
                row.error_code = None
                row.executed_at = utcnow()
                row.updated_at = row.executed_at
                self._audit(uow, row, "AI_ACTION_EXECUTED", {"tool": name, "entity_kind": row.preview["entity"]["kind"],
                            "entity_id": row.preview["entity"]["id"], "result": outcome["result"]})
                return self.view(row)
        except Conflict as exc:
            failure = ("CONFLICT", "AI_VERSION_CONFLICT", exc.message)
        except Forbidden:
            self._mark(proposal_id, request_id, "FAILED", "AI_ACCESS_CHANGED", "Access changed before execution")
            raise
        except DomainError as exc:
            failure = ("FAILED", exc.code if exc.code != "DOMAIN_ERROR" else "AI_ACTION_FAILED", exc.message)
        except Exception:
            self._mark(proposal_id, request_id, "FAILED", "AI_ACTION_FAILED", "Unexpected error")
            raise
        return self._mark(proposal_id, request_id, *failure)

    def _mark(self, proposal_id, request_id, status, code, message):
        # Internal finalization: records the outcome even when the actor lost access meanwhile.
        with self.uow_factory() as uow:
            advisory_lock(uow, self.user)
            row = uow.session.scalar(self._owned().where(AiProposalORM.id == proposal_id))
            if row is not None and row.status == "CONFIRMED" and row.confirm_request_id == request_id:
                row.status = status
                row.error_code = code
                row.result = {"message": message}
                row.updated_at = utcnow()
                self._audit(uow, row, "AI_ACTION_FAILED", {"tool": row.tool_name, "code": code, "status": status})
            return self.view(row) if row is not None else None
