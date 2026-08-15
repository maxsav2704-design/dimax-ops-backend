from __future__ import annotations

import argparse
import json
import os
import uuid

from sqlalchemy import select, text

from app.core.security.password import hash_password
from app.modules.identity.domain.enums import AdminScope, UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.reasons.infrastructure.default_seed import seed_default_reasons
from app.modules.sync.infrastructure.models import InstallerSyncStateORM
from app.shared.infrastructure.db.base import utcnow
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


def _installer_candidates(session, *, company_id: uuid.UUID, installer_user: UserORM) -> list[InstallerORM]:
    candidates = session.execute(
        select(InstallerORM).where(
            InstallerORM.company_id == company_id,
            InstallerORM.email == installer_user.email,
        )
    ).scalars().all()
    if candidates:
        return candidates
    return session.execute(
        select(InstallerORM).where(
            InstallerORM.company_id == company_id,
            InstallerORM.full_name == installer_user.full_name,
        )
    ).scalars().all()


def _merge_installer_refs(
    session,
    *,
    company_id: uuid.UUID,
    source: InstallerORM,
    target: InstallerORM,
) -> None:
    if source.id == target.id:
        return

    params = {
        "company_id": company_id,
        "source_id": source.id,
        "target_id": target.id,
    }
    for table_name in (
        "doors",
        "calendar_event_assignees",
        "completed_work",
        "installer_rates",
        "project_addon_facts",
        "sync_change_log",
    ):
        session.execute(
            text(
                f"""
                UPDATE {table_name}
                SET installer_id = :target_id
                WHERE company_id = :company_id
                  AND installer_id = :source_id
                """
            ),
            params,
        )

    source_sync = session.execute(
        select(InstallerSyncStateORM).where(
            InstallerSyncStateORM.company_id == company_id,
            InstallerSyncStateORM.installer_id == source.id,
        )
    ).scalars().first()
    target_sync = session.execute(
        select(InstallerSyncStateORM).where(
            InstallerSyncStateORM.company_id == company_id,
            InstallerSyncStateORM.installer_id == target.id,
        )
    ).scalars().first()

    if source_sync is not None:
        if target_sync is None:
            source_sync.installer_id = target.id
            session.add(source_sync)
        else:
            if source_sync.last_seen_at and (
                target_sync.last_seen_at is None or source_sync.last_seen_at > target_sync.last_seen_at
            ):
                target_sync.last_seen_at = source_sync.last_seen_at
            if source_sync.last_cursor_ack > target_sync.last_cursor_ack:
                target_sync.last_cursor_ack = source_sync.last_cursor_ack
            if not target_sync.app_version and source_sync.app_version:
                target_sync.app_version = source_sync.app_version
            if not target_sync.device_id and source_sync.device_id:
                target_sync.device_id = source_sync.device_id
            session.delete(source_sync)

    source.user_id = None
    source.is_active = False
    if source.deleted_at is None:
        source.deleted_at = utcnow()
    session.add(source)


def _reconcile_installer_for_user(
    session,
    *,
    company_id: uuid.UUID,
    installer_user: UserORM,
) -> InstallerORM | None:
    candidates = _installer_candidates(
        session,
        company_id=company_id,
        installer_user=installer_user,
    )
    if not candidates:
        return None

    linked = next((row for row in candidates if row.user_id == installer_user.id), None)
    if linked is None:
        primary = sorted(
            candidates,
            key=lambda row: (
                row.deleted_at is not None,
                not row.is_active,
                row.created_at,
            ),
        )[0]
        primary.user_id = installer_user.id
        primary.is_active = True
        primary.deleted_at = None
        linked = primary

    for candidate in candidates:
        if candidate.id == linked.id:
            continue
        _merge_installer_refs(
            session,
            company_id=company_id,
            source=candidate,
            target=linked,
        )

    return linked


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
        reason_seed = seed_default_reasons(session, company_id=company_id)

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

        admin_users = session.execute(
            select(UserORM).where(
                UserORM.company_id == company_id,
                UserORM.role == UserRole.ADMIN,
            )
        ).scalars().all()

        for admin_user in admin_users:
            admin_profile = session.execute(
                select(AdminProfileORM).where(
                    AdminProfileORM.company_id == company_id,
                    AdminProfileORM.user_id == admin_user.id,
                )
            ).scalars().first()

            if admin_profile is None:
                session.add(
                    AdminProfileORM(
                        company_id=company_id,
                        user_id=admin_user.id,
                        admin_scope=AdminScope.OWNER.value,
                        can_view_rates=True,
                        can_manage_imports=True,
                        can_manage_users=True,
                    )
                )

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
            installer = _reconcile_installer_for_user(
                session,
                company_id=company_id,
                installer_user=installer_user,
            )

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
        "reason_seed": reason_seed,
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
    print(f"REASONS: {summary['reason_seed']}")
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
