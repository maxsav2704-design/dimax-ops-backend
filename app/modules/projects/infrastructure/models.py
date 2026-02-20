from __future__ import annotations

import uuid
from sqlalchemy import Enum, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
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
    address: Mapped[str] = mapped_column(String(400), nullable=False)

    developer_company: Mapped[str | None] = mapped_column(String(200), nullable=True)  # застройщик/клиент
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        nullable=False,
        default=ProjectStatus.OK,
        index=True,
    )

    # Связи
    doors: Mapped[list["DoorORM"]] = relationship(
        back_populates="project",
        cascade="all,delete-orphan",
        passive_deletes=True,
    )
