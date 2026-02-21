from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM
from app.modules.rates.infrastructure.models import InstallerRateORM


def test_admin_installers_get_does_not_leak_other_company(
    client, db_session, make_installer
):
    foreign_company_id = uuid.uuid4()
    foreign_installer = make_installer(
        full_name="Foreign Installer",
        phone="+10000002001",
        company=foreign_company_id,
    )

    try:
        resp = client.get(f"/api/v1/admin/installers/{foreign_installer.id}")
        assert resp.status_code == 404, resp.text
    finally:
        db_session.execute(
            text("DELETE FROM installers WHERE id = :iid"),
            {"iid": foreign_installer.id},
        )
        db_session.commit()


def test_admin_installers_create_rejects_foreign_user_id(client, db_session, make_user):
    foreign_company_id = uuid.uuid4()
    db_session.add(
        CompanyORM(
            id=foreign_company_id,
            name=f"Foreign {foreign_company_id}",
            is_active=True,
        )
    )
    db_session.commit()

    foreign_user = make_user(
        role=UserRole.INSTALLER,
        is_active=True,
        company=foreign_company_id,
    )

    try:
        resp = client.post(
            "/api/v1/admin/installers",
            json={
                "full_name": "Cross Tenant Link",
                "phone": "+10000002002",
                "status": "ACTIVE",
                "is_active": True,
                "user_id": str(foreign_user.id),
            },
        )
        assert resp.status_code == 400, resp.text
    finally:
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM users WHERE company_id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.execute(
            text("DELETE FROM companies WHERE id = :cid"),
            {"cid": foreign_company_id},
        )
        db_session.commit()


def test_admin_installer_rates_list_does_not_leak_other_company(
    client, db_session, make_installer, make_door_type
):
    foreign_company_id = uuid.uuid4()
    foreign_installer = make_installer(
        full_name="Foreign Rate Installer",
        phone="+10000002003",
        company=foreign_company_id,
    )
    foreign_door_type = make_door_type(
        name="Foreign Door Type",
        company=foreign_company_id,
    )
    foreign_rate = InstallerRateORM(
        company_id=foreign_company_id,
        installer_id=foreign_installer.id,
        door_type_id=foreign_door_type.id,
        price=Decimal("333.00"),
    )
    db_session.add(foreign_rate)
    db_session.commit()

    try:
        resp = client.get("/api/v1/admin/installer-rates")
        assert resp.status_code == 200, resp.text
        ids = {x["id"] for x in resp.json()}
        assert str(foreign_rate.id) not in ids
    finally:
        db_session.execute(
            text("DELETE FROM installer_rates WHERE id = :rid"),
            {"rid": foreign_rate.id},
        )
        db_session.execute(
            text("DELETE FROM installers WHERE id = :iid"),
            {"iid": foreign_installer.id},
        )
        db_session.execute(
            text("DELETE FROM door_types WHERE id = :did"),
            {"did": foreign_door_type.id},
        )
        db_session.commit()


def test_admin_installer_rates_create_rejects_foreign_installer_or_door_type(
    client, db_session, make_installer, make_door_type
):
    local_installer = make_installer(
        full_name="Local Installer for Isolation",
        phone="+10000002010",
    )
    local_door_type = make_door_type(name="Local Door Type for Isolation")
    foreign_company_id = uuid.uuid4()
    foreign_installer = make_installer(
        full_name="Foreign Installer for Rate",
        phone="+10000002004",
        company=foreign_company_id,
    )
    foreign_door_type = make_door_type(
        name="Foreign Door for Rate",
        company=foreign_company_id,
    )

    try:
        resp_installer = client.post(
            "/api/v1/admin/installer-rates",
            json={
                "installer_id": str(foreign_installer.id),
                "door_type_id": str(local_door_type.id),
                "price": "100.00",
            },
        )
        assert resp_installer.status_code == 400, resp_installer.text

        resp_door_type = client.post(
            "/api/v1/admin/installer-rates",
            json={
                "installer_id": str(local_installer.id),
                "door_type_id": str(foreign_door_type.id),
                "price": "100.00",
            },
        )
        assert resp_door_type.status_code == 400, resp_door_type.text
    finally:
        db_session.execute(
            text("DELETE FROM installers WHERE id = :iid"),
            {"iid": foreign_installer.id},
        )
        db_session.execute(
            text("DELETE FROM door_types WHERE id = :did"),
            {"did": foreign_door_type.id},
        )
        db_session.commit()
