from __future__ import annotations

import os
import uuid

from sqlalchemy import select

from app.shared.infrastructure.db.session import SessionLocal

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.sync.infrastructure.models import InstallerSyncStateORM

from app.core.security.password import hash_password


SEED_USERS = [
    {
        "email": "admin@dimax.dev",
        "password": "admin12345",
        "role": "ADMIN",
        "full_name": "DIMAX Admin",
        "phone": None,
    },
    {
        "email": "installer1@dimax.dev",
        "password": "installer12345",
        "role": "INSTALLER",
        "full_name": "Installer One",
        "phone": "+972500000001",
    },
    {
        "email": "installer2@dimax.dev",
        "password": "installer12345",
        "role": "INSTALLER",
        "full_name": "Installer Two",
        "phone": "+972500000002",
    },
]


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v and v.strip() else default


def seed_dev() -> None:
    app_env = _env("APP_ENV", "dev")
    if app_env.lower() != "dev":
        raise SystemExit(f"❌ seed_dev запрещён в APP_ENV={app_env}. Поставь APP_ENV=dev.")

    company_name = _env("DEV_SEED_COMPANY_NAME", "DIMAX DEV")

    # ВАЖНО: работаем через session, без миграций.
    with SessionLocal() as session:
        # 1) Company (идемпотентно)
        company = session.execute(
            select(CompanyORM).where(CompanyORM.name == company_name)
        ).scalars().first()

        if not company:
            company = CompanyORM(id=uuid.uuid4(), name=company_name, is_active=True)
            session.add(company)
            session.flush()

        # запоминаем до commit, чтобы не трогать ORM после него
        company_id = company.id
        company_name = company.name

        # 2) Users (идемпотентно, с починкой full_name/role при REUSED)
        created_users = []
        reused_users = []

        for u in SEED_USERS:
            role = UserRole[u["role"]] if isinstance(u["role"], str) else u["role"]

            user = (
                session.execute(
                    select(UserORM).where(
                        UserORM.company_id == company_id,
                        UserORM.email == u["email"],
                    )
                )
                .scalars()
                .first()
            )

            if user is None:
                raw = (u["password"] or "").strip()
                b = raw.encode("utf-8")
                if len(b) > 72:
                    raise SystemExit(
                        f"❌ DEV password too long for bcrypt: {len(b)} bytes (limit 72). Fix DEV_SEED_* env."
                    )
                user = UserORM(
                    id=uuid.uuid4(),
                    company_id=company_id,
                    email=u["email"],
                    full_name=u["full_name"],
                    role=role,
                    password_hash=hash_password(raw),
                    is_active=True,
                )
                session.add(user)
                created_users.append((role.name, u["email"]))
            else:
                changed = False
                if user.full_name != u["full_name"]:
                    user.full_name = u["full_name"]
                    changed = True
                if user.role != role:
                    user.role = role
                    changed = True
                if changed:
                    session.add(user)
                reused_users.append((role.name, u["email"]))

        # 3) Installers + installer_sync_state (идемпотентно)
        installer_users = (
            session.execute(
                select(UserORM).where(
                    UserORM.company_id == company_id,
                    UserORM.role == UserRole.INSTALLER,
                )
            )
            .scalars()
            .all()
        )

        created_installers = 0
        reused_installers = 0
        created_sync = 0
        reused_sync = 0

        for u in installer_users:
            # --- ensure Installer exists for this user ---
            installer = (
                session.execute(
                    select(InstallerORM).where(
                        InstallerORM.company_id == company_id,
                        InstallerORM.user_id == u.id,
                    )
                )
                .scalars()
                .first()
            )

            if installer is None:
                installer = InstallerORM(
                    company_id=company_id,
                    user_id=u.id,
                    full_name=u.full_name,
                    email=u.email,
                    phone=None,
                    status="ACTIVE",
                    is_active=True,
                )
                session.add(installer)
                session.flush()
                created_installers += 1
            else:
                reused_installers += 1

            # --- ensure InstallerSyncState exists for this installer ---
            sync_state = (
                session.execute(
                    select(InstallerSyncStateORM).where(
                        InstallerSyncStateORM.company_id == company_id,
                        InstallerSyncStateORM.installer_id == installer.id,
                    )
                )
                .scalars()
                .first()
            )

            if sync_state is None:
                sync_state = InstallerSyncStateORM(
                    company_id=company_id,
                    installer_id=installer.id,
                    last_cursor_ack=0,
                    last_seen_at=None,
                    app_version=None,
                    device_id=None,
                    health_status="OK",
                    health_lag=None,
                    health_days_offline=None,
                    last_alert_at=None,
                    last_alert_lag=None,
                )
                session.add(sync_state)
                created_sync += 1
            else:
                reused_sync += 1

        session.commit()

    print("✅ DEV SEED DONE")
    print(f"company_name: {company_name}")
    print(f"company_id:   {company_id}")
    print("")
    print("CREATED:", created_users if created_users else "none")
    print("REUSED: ", reused_users if reused_users else "none")
    print("")
    print("INSTALLERS / SYNC_STATE:")
    print(f"CREATED installers: {created_installers}, REUSED installers: {reused_installers}")
    print(f"CREATED sync_state: {created_sync}, REUSED sync_state: {reused_sync}")
    print("")
    print("LOGIN CREDS:")
    for u in SEED_USERS:
        label = "ADMIN" if u["role"] == "ADMIN" else u["email"].split("@")[0].upper()
        print(f"  {label}: {u['email']} / {u['password']}")


def main() -> None:
    seed_dev()


if __name__ == "__main__":
    main()
