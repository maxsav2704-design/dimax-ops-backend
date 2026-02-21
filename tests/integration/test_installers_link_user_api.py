from __future__ import annotations

import uuid

from sqlalchemy import text

from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM


def test_link_and_unlink_user_success(client, make_installer, make_user):
    installer = make_installer(full_name="Link Target", phone="+10000000011")
    user = make_user(role=UserRole.INSTALLER, is_active=True)

    link_resp = client.post(
        f"/api/v1/admin/installers/{installer.id}/link-user",
        json={"user_id": str(user.id)},
    )
    assert link_resp.status_code == 200, link_resp.text
    assert link_resp.json()["user_id"] == str(user.id)

    link_again_resp = client.post(
        f"/api/v1/admin/installers/{installer.id}/link-user",
        json={"user_id": str(user.id)},
    )
    assert link_again_resp.status_code == 200, link_again_resp.text
    assert link_again_resp.json()["user_id"] == str(user.id)

    unlink_resp = client.delete(f"/api/v1/admin/installers/{installer.id}/link-user")
    assert unlink_resp.status_code == 200, unlink_resp.text
    assert unlink_resp.json()["user_id"] is None


def test_link_user_rejects_wrong_role(client, make_installer, make_user):
    installer = make_installer(full_name="Role Check", phone="+10000000012")
    admin_user = make_user(role=UserRole.ADMIN, is_active=True)

    link_resp = client.post(
        f"/api/v1/admin/installers/{installer.id}/link-user",
        json={"user_id": str(admin_user.id)},
    )
    assert link_resp.status_code == 400, link_resp.text
    assert link_resp.json()["error"]["code"] == "BAD_REQUEST"


def test_link_user_rejects_other_company(client, db_session, make_installer, make_user):
    installer = make_installer(full_name="Company Check", phone="+10000000013")
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
        link_resp = client.post(
            f"/api/v1/admin/installers/{installer.id}/link-user",
            json={"user_id": str(foreign_user.id)},
        )
        assert link_resp.status_code == 400, link_resp.text
        assert link_resp.json()["error"]["code"] == "BAD_REQUEST"
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


def test_link_user_rejects_already_linked_user(client, make_installer, make_user):
    installer_a = make_installer(full_name="Installer A", phone="+10000000014")
    installer_b = make_installer(full_name="Installer B", phone="+10000000015")
    user = make_user(role=UserRole.INSTALLER, is_active=True)

    first_link_resp = client.post(
        f"/api/v1/admin/installers/{installer_a.id}/link-user",
        json={"user_id": str(user.id)},
    )
    assert first_link_resp.status_code == 200, first_link_resp.text

    second_link_resp = client.post(
        f"/api/v1/admin/installers/{installer_b.id}/link-user",
        json={"user_id": str(user.id)},
    )
    assert second_link_resp.status_code == 409, second_link_resp.text
    assert second_link_resp.json()["error"]["code"] == "CONFLICT"
