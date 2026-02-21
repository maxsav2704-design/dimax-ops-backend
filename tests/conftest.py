from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.deps import CurrentUser, get_current_user, get_uow, require_admin
from app.core.config import settings
from app.core.security.password import hash_password
from app.main import create_app
from app.modules.audit.infrastructure.repositories import AuditRepository
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.identity.domain.enums import UserRole
from app.modules.identity.infrastructure.models import CompanyORM, UserORM
from app.modules.identity.infrastructure.refresh_tokens_repo import RefreshTokenRepository
from app.modules.identity.infrastructure.repositories import UserRepository
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.installers.infrastructure.rates_repository import InstallerRatesRepository
from app.modules.installers.infrastructure.repositories import InstallerRepository


def _resolve_test_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL") or settings.DATABASE_URL


TEST_ENGINE = create_engine(_resolve_test_database_url(), pool_pre_ping=True)
TestSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


class TestUnitOfWork:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self):
        self.session = self._session_factory()
        self.audit = AuditRepository(self.session)
        self.users = UserRepository(self.session)
        self.refresh_tokens = RefreshTokenRepository(self.session)
        self.installers = InstallerRepository(self.session)
        self.installer_rates = InstallerRatesRepository(self.session)
        return self

    def commit(self) -> None:
        assert self.session is not None
        self.session.commit()

    def rollback(self) -> None:
        assert self.session is not None
        self.session.rollback()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc:
                self.rollback()
            else:
                self.commit()
        finally:
            if self.session is not None:
                self.session.close()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def company_id(db_session: Session) -> Generator[uuid.UUID, None, None]:
    cid = uuid.uuid4()
    db_session.add(CompanyORM(id=cid, name=f"Test Company {cid}", is_active=True))
    db_session.commit()
    try:
        yield cid
    finally:
        db_session.rollback()
        db_session.execute(
            text("DELETE FROM journal_signatures WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM journal_files WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM journal_door_items WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM calendar_event_assignees WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM calendar_events WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM journals WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM issues WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM project_addon_facts WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM project_addon_plans WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM addon_types WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM doors WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM installer_rates WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM sync_events WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM audit_logs WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM sync_change_log WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM outbox_messages WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM projects WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM installer_sync_state WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM installers WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM door_types WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM auth_refresh_tokens WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM users WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM companies WHERE id = :cid"),
            {"cid": cid},
        )
        db_session.commit()


@pytest.fixture()
def admin_user(company_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(id=uuid.uuid4(), company_id=company_id, role="ADMIN")


@pytest.fixture()
def installer_user(company_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(id=uuid.uuid4(), company_id=company_id, role="INSTALLER")


@pytest.fixture()
def client(admin_user: CurrentUser) -> Iterator[TestClient]:
    app = create_app()

    def _get_uow() -> TestUnitOfWork:
        return TestUnitOfWork(TestSessionLocal)

    def _require_admin() -> CurrentUser:
        return admin_user

    app.dependency_overrides[get_uow] = _get_uow
    app.dependency_overrides[require_admin] = _require_admin

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def client_raw() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client_admin_real_uow(admin_user: CurrentUser) -> Iterator[TestClient]:
    app = create_app()

    def _require_admin() -> CurrentUser:
        return admin_user

    app.dependency_overrides[require_admin] = _require_admin

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def client_installer(installer_user: CurrentUser) -> Iterator[TestClient]:
    app = create_app()

    def _get_uow() -> TestUnitOfWork:
        return TestUnitOfWork(TestSessionLocal)

    def _get_current_user() -> CurrentUser:
        return installer_user

    app.dependency_overrides[get_uow] = _get_uow
    app.dependency_overrides[get_current_user] = _get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def make_installer(db_session: Session, company_id: uuid.UUID):
    def _factory(
        *,
        full_name: str = "Test Installer",
        phone: str | None = None,
        is_active: bool = True,
        company: uuid.UUID | None = None,
    ) -> InstallerORM:
        cid = company or company_id
        row = InstallerORM(
            company_id=cid,
            full_name=full_name,
            phone=phone,
            email=None,
            address=None,
            passport_id=None,
            notes=None,
            status="ACTIVE" if is_active else "INACTIVE",
            is_active=is_active,
            user_id=None,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return _factory


@pytest.fixture()
def make_door_type(db_session: Session, company_id: uuid.UUID):
    def _factory(
        *,
        code: str | None = None,
        name: str = "Door Type",
        company: uuid.UUID | None = None,
    ) -> DoorTypeORM:
        cid = company or company_id
        row = DoorTypeORM(
            company_id=cid,
            code=code or f"door-{uuid.uuid4().hex[:8]}",
            name=name,
            is_active=True,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return _factory


@pytest.fixture()
def make_user(db_session: Session, company_id: uuid.UUID):
    def _factory(
        *,
        email: str | None = None,
        role: UserRole = UserRole.INSTALLER,
        is_active: bool = True,
        company: uuid.UUID | None = None,
        password: str = "secret123",
    ) -> UserORM:
        cid = company or company_id
        row = UserORM(
            company_id=cid,
            email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Test User",
            role=role,
            password_hash=hash_password(password),
            is_active=is_active,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return _factory
