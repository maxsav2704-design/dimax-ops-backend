from __future__ import annotations

import uuid
from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.modules.identity.domain.enums import UserRole


class CompanyORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("company_id", "email", name="uq_users_company_email"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        server_default=text("'ACTIVE'"),
        nullable=False,
    )


class AdminProfileORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "admin_profiles"
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", name="uq_admin_profiles_company_user"),
        Index("ix_admin_profiles_company_scope", "company_id", "admin_scope"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    admin_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    can_view_rates: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    can_manage_imports: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    can_manage_users: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
