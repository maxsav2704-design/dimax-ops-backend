from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import UserORM
from app.modules.installers.domain.errors import InvalidUserLink, UserAlreadyLinked
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.sync.infrastructure.models import InstallerSyncStateORM


# Поля, которые разрешено обновлять через PATCH (не трогаем id, company_id, created_at и т.д.)
INSTALLER_UPDATE_ALLOWED = {
    "full_name",
    "phone",
    "email",
    "address",
    "passport_id",
    "notes",
    "status",
    "is_active",
}

HEALTH_STATUS_OK = "OK"


class InstallersAdminService:
    def __init__(self, session) -> None:
        self.session = session

    def _ensure_user_same_company(
        self, company_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        u = self.session.execute(
            select(UserORM.id).where(
                UserORM.id == user_id, UserORM.company_id == company_id
            )
        ).first()
        if not u:
            raise InvalidUserLink("user_id not found in this company")

    def create(self, company_id: uuid.UUID, data) -> InstallerORM:
        if data.user_id:
            self._ensure_user_same_company(company_id, data.user_id)

        obj = InstallerORM(
            company_id=company_id,
            full_name=data.full_name,
            phone=data.phone,
            email=data.email,
            address=data.address,
            passport_id=data.passport_id,
            notes=data.notes,
            status=data.status,
            is_active=data.is_active,
            user_id=data.user_id,
        )
        self.session.add(obj)
        self.session.flush()

        state = self.session.execute(
            select(InstallerSyncStateORM).where(
                InstallerSyncStateORM.company_id == company_id,
                InstallerSyncStateORM.installer_id == obj.id,
            )
        ).scalars().first()
        if not state:
            self.session.add(
                InstallerSyncStateORM(
                    company_id=company_id,
                    installer_id=obj.id,
                    last_cursor_ack=0,
                    last_seen_at=None,
                    health_status=HEALTH_STATUS_OK,
                    health_lag=None,
                    health_days_offline=None,
                    last_alert_at=None,
                    last_alert_lag=None,
                )
            )
        return obj

    def update(
        self, company_id: uuid.UUID, installer: InstallerORM, data
    ) -> InstallerORM:
        payload = data.model_dump(exclude_unset=True)
        for f, v in payload.items():
            if f in INSTALLER_UPDATE_ALLOWED:
                setattr(installer, f, v)
        self.session.add(installer)
        return installer

    def soft_delete(self, installer: InstallerORM) -> None:
        installer.deleted_at = datetime.now(timezone.utc)
        installer.is_active = False
        # В проекте status — строка (ACTIVE/BUSY/INACTIVE); при удалении ставим INACTIVE
        installer.status = "INACTIVE"
        # Очищаем привязку, чтобы user можно было привязать к другому installer (unique index).
        # Историю привязок при необходимости вести через audit/event log, а не через user_id в удалённой записи.
        installer.user_id = None
        self.session.add(installer)

    def _get_user_for_link(
        self, company_id: uuid.UUID, user_id: uuid.UUID
    ) -> UserORM:
        """Get user by id and company; must exist, role INSTALLER, and is_active."""
        row = self.session.execute(
            select(UserORM).where(
                UserORM.id == user_id,
                UserORM.company_id == company_id,
            )
        ).scalars().first()
        if not row:
            raise InvalidUserLink("user not found or wrong company")
        if row.role != UserRole.INSTALLER:
            raise InvalidUserLink("user role must be INSTALLER")
        if not row.is_active:
            raise InvalidUserLink("user is inactive")
        return row

    def link_user(
        self,
        company_id: uuid.UUID,
        installer: InstallerORM,
        user_id: uuid.UUID,
        get_installer_by_user_id_any,
    ) -> InstallerORM:
        """Link user to installer. Validates user exists, INSTALLER role, and no other installer has this user."""
        self._get_user_for_link(company_id, user_id)
        other = get_installer_by_user_id_any(company_id=company_id, user_id=user_id)
        if other is not None and other.id != installer.id:
            raise UserAlreadyLinked("user is already linked to another installer")
        installer.user_id = user_id
        self.session.add(installer)
        return installer

    def unlink_user(self, installer: InstallerORM) -> InstallerORM:
        """Remove user link from installer."""
        installer.user_id = None
        self.session.add(installer)
        return installer
