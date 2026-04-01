from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.db.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    TenantMixin,
    SoftDeleteMixin,
)
from app.modules.projects.domain.enums import ProjectStatus


class ProjectORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, SoftDeleteMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "name", "address", name="uq_projects_company_name_address"
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str] = mapped_column(String(400), nullable=False)
    planned_start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    planned_end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)

    developer_company: Mapped[str | None] = mapped_column(String(200), nullable=True)  # застройщик/клиент
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    developer_phone_alt: Mapped[str | None] = mapped_column(String(40), nullable=True)
    developer_whatsapp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    developer_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    address_street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address_building: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_entrance: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_lat: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    address_lng: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    address_waze_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        nullable=False,
        default=ProjectStatus.OK,
        index=True,
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACTIVE",
        server_default=text("'ACTIVE'"),
    )
    health_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="NORMAL",
        server_default=text("'NORMAL'"),
    )

    # Связи
    doors: Mapped[list["DoorORM"]] = relationship(
        back_populates="project",
        cascade="all,delete-orphan",
        passive_deletes=True,
    )


class ProjectImportRunORM(Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin):
    __tablename__ = "project_import_runs"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "project_id",
            "fingerprint",
            "import_mode",
            name="uq_project_import_runs_scope_fingerprint_mode",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    import_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mapping_profile: Mapped[str] = mapped_column(String(64), nullable=False, default="auto_v1")
    result_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
