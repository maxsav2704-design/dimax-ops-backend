"""Work stages (0088): catalog, versioned plans per door type, plan per door, per-stage assignments, facts."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

STAGE_CODE_PATTERN = r"^[A-Z][A-Z0-9_]{0,39}$"


class WorkStageDefinitionORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "work_stage_definitions"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_work_stage_code"),
        CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{0,39}$'", name="ck_work_stage_code"),
        CheckConstraint("btrim(name) <> ''", name="ck_work_stage_name"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class DoorTypeStagePlanORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "door_type_stage_plans"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_door_type_stage_plan_tenant"),
        UniqueConstraint("company_id", "door_type_id", "version", name="uq_door_type_stage_plan_version"),
        CheckConstraint("version > 0 AND btrim(reason) <> ''", name="ck_door_type_stage_plan"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    door_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("door_types.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DoorTypeStagePlanItemORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "door_type_stage_plan_items"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "plan_id"], ["door_type_stage_plans.company_id", "door_type_stage_plans.id"],
                             ondelete="RESTRICT", name="fk_stage_plan_item_plan"),
        ForeignKeyConstraint(["company_id", "stage_code"], ["work_stage_definitions.company_id", "work_stage_definitions.code"],
                             ondelete="RESTRICT", name="fk_stage_plan_item_stage"),
        UniqueConstraint("plan_id", "stage_code", name="uq_stage_plan_item_stage"),
        UniqueConstraint("plan_id", "sequence", name="uq_stage_plan_item_sequence"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stage_code: Mapped[str] = mapped_column(String(40), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class DoorWorkPlanORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "door_work_plans"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "plan_id"], ["door_type_stage_plans.company_id", "door_type_stage_plans.id"],
                             ondelete="RESTRICT", name="fk_door_work_plan_plan"),
        CheckConstraint("(replaced_at IS NULL AND replaced_by IS NULL) OR (replaced_at IS NOT NULL AND replaced_by IS NOT NULL)",
                        name="ck_door_work_plan_replacement"),
        Index("uq_door_work_plan_current", "door_id", unique=True, postgresql_where=text("replaced_at IS NULL")),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    door_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doors.id", ondelete="RESTRICT"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    applied_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))


class DoorStageAssignmentORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "door_stage_assignments"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "stage_code"], ["work_stage_definitions.company_id", "work_stage_definitions.code"],
                             ondelete="RESTRICT", name="fk_door_stage_assignment_stage"),
        CheckConstraint("(replaced_at IS NULL AND replaced_by IS NULL) OR (replaced_at IS NOT NULL AND replaced_by IS NOT NULL)",
                        name="ck_door_stage_assignment_replacement"),
        Index("uq_door_stage_assignment_current", "door_id", "stage_code", unique=True, postgresql_where=text("replaced_at IS NULL")),
        Index("ix_door_stage_assignment_installer", "company_id", "installer_id"),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    door_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doors.id", ondelete="RESTRICT"), nullable=False)
    stage_code: Mapped[str] = mapped_column(String(40), nullable=False)
    installer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("installers.id", ondelete="RESTRICT"), nullable=False)
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))


class DoorStageFactORM(Base, UUIDPrimaryKeyMixin):
    """One completion per door stage. Immutable (trigger). Never an earning by itself."""

    __tablename__ = "door_stage_facts"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "plan_id"], ["door_type_stage_plans.company_id", "door_type_stage_plans.id"],
                             ondelete="RESTRICT", name="fk_door_stage_fact_plan"),
        ForeignKeyConstraint(["company_id", "stage_code"], ["work_stage_definitions.company_id", "work_stage_definitions.code"],
                             ondelete="RESTRICT", name="fk_door_stage_fact_stage"),
        UniqueConstraint("door_id", "stage_code", name="uq_door_stage_fact_once"),
        CheckConstraint("happened_at <= received_at", name="ck_door_stage_fact_time"),
        CheckConstraint("source IN ('API', 'ADMIN', 'OFFLINE_SYNC')", name="ck_door_stage_fact_source"),
        Index("uq_door_stage_fact_client_event", "company_id", "client_event_id", unique=True, postgresql_where=text("client_event_id IS NOT NULL")),
        Index("uq_door_stage_fact_request", "company_id", "request_id", unique=True, postgresql_where=text("request_id IS NOT NULL")),
    )
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    door_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doors.id", ondelete="RESTRICT"), nullable=False)
    stage_code: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("door_stage_assignments.id", ondelete="RESTRICT"), nullable=False)
    installer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("installers.id", ondelete="RESTRICT"), nullable=False)
    happened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    client_event_id: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
