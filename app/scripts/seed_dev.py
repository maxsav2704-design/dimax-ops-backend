from __future__ import annotations

import argparse
import json
import os
import uuid

from sqlalchemy import select

from app.core.security.password import hash_password
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.sync.infrastructure.models import InstallerSyncStateORM
from app.shared.infrastructure.db.session import SessionLocal


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
    value = os.getenv(name)
    return value if value and value.strip() else default


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed reproducible dev users/installers.")
    parser.add_argument(
        "--emit-json",
        action="store_true",
        help="Emit machine-readable JSON summary instead of human-readable output.",
    )
    return parser.parse_args()


def _primary_installer_seed() -> dict:
    for item in SEED_USERS:
        if str(item["role"]).upper() == "INSTALLER":
            return item
    raise RuntimeError("No installer user configured in SEED_USERS.")


def seed_dev() -> dict:
    app_env = _env("APP_ENV", "dev")
    if app_env.lower() != "dev":
        raise SystemExit(f"seed_dev is blocked for APP_ENV={app_env}. Set APP_ENV=dev.")

    company_name = _env("DEV_SEED_COMPANY_NAME", "DIMAX DEV")

    with SessionLocal() as session:
        company = session.execute(
            select(CompanyORM).where(CompanyORM.name == company_name)
        ).scalars().first()

        if not company:
            company = CompanyORM(id=uuid.uuid4(), name=company_name, is_active=True)
            session.add(company)
            session.flush()

        company_id = company.id
        company_name = company.name

        created_users: list[tuple[str, str]] = []
        reused_users: list[tuple[str, str]] = []

        for seed_user in SEED_USERS:
            role = UserRole[seed_user["role"]] if isinstance(seed_user["role"], str) else seed_user["role"]
            user = session.execute(
                select(UserORM).where(
                    UserORM.company_id == company_id,
                    UserORM.email == seed_user["email"],
                )
            ).scalars().first()

            if user is None:
                raw_password = str(seed_user["password"] or "").strip()
                password_bytes = raw_password.encode("utf-8")
                if len(password_bytes) > 72:
                    raise SystemExit(
                        f"DEV password too long for bcrypt: {len(password_bytes)} bytes (limit 72)."
                    )
                user = UserORM(
                    id=uuid.uuid4(),
                    company_id=company_id,
                    email=seed_user["email"],
                    full_name=seed_user["full_name"],
                    role=role,
                    password_hash=hash_password(raw_password),
                    is_active=True,
                )
                session.add(user)
                created_users.append((role.name, seed_user["email"]))
            else:
                changed = False
                if user.full_name != seed_user["full_name"]:
                    user.full_name = seed_user["full_name"]
                    changed = True
                if user.role != role:
                    user.role = role
                    changed = True
                if changed:
                    session.add(user)
                reused_users.append((role.name, seed_user["email"]))

        session.flush()

        installer_users = session.execute(
            select(UserORM).where(
                UserORM.company_id == company_id,
                UserORM.role == UserRole.INSTALLER,
            )
        ).scalars().all()

        created_installers = 0
        reused_installers = 0
        created_sync = 0
        reused_sync = 0

        for installer_user in installer_users:
            installer = session.execute(
                select(InstallerORM).where(
                    InstallerORM.company_id == company_id,
                    InstallerORM.user_id == installer_user.id,
                )
            ).scalars().first()

            if installer is None:
                installer = InstallerORM(
                    company_id=company_id,
                    user_id=installer_user.id,
                    full_name=installer_user.full_name,
                    email=installer_user.email,
                    phone=None,
                    status="ACTIVE",
                    is_active=True,
                )
                session.add(installer)
                session.flush()
                created_installers += 1
            else:
                reused_installers += 1

            sync_state = session.execute(
                select(InstallerSyncStateORM).where(
                    InstallerSyncStateORM.company_id == company_id,
                    InstallerSyncStateORM.installer_id == installer.id,
                )
            ).scalars().first()

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

    primary_installer = _primary_installer_seed()
    return {
        "company_name": company_name,
        "company_id": str(company_id),
        "created": created_users,
        "reused": reused_users,
        "created_installers": created_installers,
        "reused_installers": reused_installers,
        "created_sync_state": created_sync,
        "reused_sync_state": reused_sync,
        "users": [
            {
                "role": item["role"],
                "email": item["email"],
                "password": item["password"],
            }
            for item in SEED_USERS
        ],
        "primary_installer": {
            "email": primary_installer["email"],
            "password": primary_installer["password"],
        },
    }


def _print_human(summary: dict) -> None:
    print("DEV SEED DONE")
    print(f"company_name: {summary['company_name']}")
    print(f"company_id:   {summary['company_id']}")
    print("")
    print("CREATED:", summary["created"] if summary["created"] else "none")
    print("REUSED: ", summary["reused"] if summary["reused"] else "none")
    print("")
    print("INSTALLERS / SYNC_STATE:")
    print(
        f"CREATED installers: {summary['created_installers']}, REUSED installers: {summary['reused_installers']}"
    )
    print(
        f"CREATED sync_state: {summary['created_sync_state']}, REUSED sync_state: {summary['reused_sync_state']}"
    )
    print("")
    print("LOGIN CREDS:")
    for item in summary["users"]:
        label = "ADMIN" if item["role"] == "ADMIN" else item["email"].split("@")[0].upper()
        print(f"  {label}: {item['email']} / {item['password']}")


def main() -> None:
    args = _parse_args()
    summary = seed_dev()
    if args.emit_json:
        print(json.dumps(summary, ensure_ascii=True))
        return
    _print_human(summary)


if __name__ == "__main__":
    main()
