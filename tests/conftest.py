from __future__ import annotations

import io
import os
import sys
import uuid
from collections.abc import Generator, Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1 import rate_limit
from app.api.v1.deps import CurrentUser, get_current_user, get_uow, require_admin
from app.core.config import settings
from app.core.security.password import hash_password
from app.main import create_app
from app.modules.audit.infrastructure.repositories import AuditRepository
from app.modules.addons.infrastructure.repositories import (
    AddonTypeRepository,
    ProjectAddonFactRepository,
    ProjectAddonPlanRepository,
)
from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.door_types.infrastructure.repositories import DoorTypeRepository
from app.modules.doors.infrastructure.repositories import DoorRepository
from app.modules.reasons.infrastructure.models import ReasonORM
from app.modules.reasons.infrastructure.repositories import ReasonRepository
from app.modules.identity.domain.enums import AdminScope, UserRole
from app.modules.identity.infrastructure.models import AdminProfileORM, CompanyORM, UserORM
from app.modules.identity.infrastructure.refresh_tokens_repo import RefreshTokenRepository
from app.modules.identity.infrastructure.repositories import UserRepository
from app.modules.installers.infrastructure.models import InstallerORM
from app.modules.installers.infrastructure.rates_repository import InstallerRatesRepository
from app.modules.installers.infrastructure.repositories import InstallerRepository
from app.modules.library.infrastructure.repositories import ProductLibraryRepository
from app.modules.issues.infrastructure.repositories import IssueRepository
from app.modules.documents.infrastructure.repositories import DocumentRepository
from app.modules.files.infrastructure.repositories import (
    FileDownloadEventRepository,
    FileTokenRepository,
)
from app.modules.projects.infrastructure.repositories import (
    ProjectImportRunRepository,
    ProjectRepository,
)
from app.modules.sync.infrastructure.repositories import (
    InstallerSyncStateRepository,
    InstallerSyncQueueRepository,
    SyncChangeLogGCRepository,
    SyncChangeLogRepository,
    SyncEventRepository,
)
from app.modules.settings.infrastructure.repositories import CompanySettingsRepository


def _resolve_test_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL") or settings.DATABASE_URL


TEST_ENGINE = create_engine(_resolve_test_database_url(), pool_pre_ping=True)
TestSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def reset_rate_limits_between_tests() -> Iterator[None]:
    rate_limit._reset_rate_limits_for_tests()
    yield
    rate_limit._reset_rate_limits_for_tests()


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
        self.product_library = ProductLibraryRepository(self.session)
        self.doors = DoorRepository(self.session)
        self.issues = IssueRepository(self.session)
        self.documents = DocumentRepository(self.session)
        self.file_tokens = FileTokenRepository(self.session)
        self.file_download_events = FileDownloadEventRepository(self.session)
        self.projects = ProjectRepository(self.session)
        self.project_import_runs = ProjectImportRunRepository(self.session)
        self.addon_types = AddonTypeRepository(self.session)
        self.addon_plans = ProjectAddonPlanRepository(self.session)
        self.addon_facts = ProjectAddonFactRepository(self.session)
        self.sync_events = SyncEventRepository(self.session)
        self.sync_change_log = SyncChangeLogRepository(self.session)
        self.sync_state = InstallerSyncStateRepository(self.session)
        self.sync_queue = InstallerSyncQueueRepository(self.session)
        self.sync_change_gc = SyncChangeLogGCRepository(self.session)
        self.door_types = DoorTypeRepository(self.session)
        self.reasons = ReasonRepository(self.session)
        self.settings = CompanySettingsRepository(self.session)
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
            text("DELETE FROM document_generations WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM document_templates WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM file_download_events WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM file_download_tokens WHERE company_id = :cid"),
            {"cid": cid},
        )
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
            text("DELETE FROM communication_templates WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM issues WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM completed_work WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM door_status_history WHERE company_id = :cid"),
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
            text("DELETE FROM product_library_items WHERE company_id = :cid"),
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
            text("DELETE FROM sync_queue_items WHERE company_id = :cid"),
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
            text("DELETE FROM reasons WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM refresh_sessions WHERE company_id = :cid"),
            {"cid": cid},
        )
        db_session.execute(
            text("DELETE FROM admin_profiles WHERE company_id = :cid"),
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
def admin_user(db_session: Session, company_id: uuid.UUID) -> CurrentUser:
    user_id = uuid.uuid4()
    db_session.add(
        UserORM(
            id=user_id,
            company_id=company_id,
            email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Test Admin",
            role=UserRole.ADMIN,
            password_hash=hash_password("secret123"),
            is_active=True,
            status="ACTIVE",
        )
    )
    db_session.commit()
    db_session.add(
        AdminProfileORM(
            company_id=company_id,
            user_id=user_id,
            admin_scope="OWNER",
            can_view_rates=True,
            can_manage_imports=True,
            can_manage_users=True,
        )
    )
    db_session.commit()
    return CurrentUser(id=user_id, company_id=company_id, role="ADMIN")


@pytest.fixture()
def installer_user(db_session: Session, company_id: uuid.UUID) -> CurrentUser:
    user_id = uuid.uuid4()
    db_session.add(
        UserORM(
            id=user_id,
            company_id=company_id,
            email=f"installer-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Test Installer User",
            role=UserRole.INSTALLER,
            password_hash=hash_password("secret123"),
            is_active=True,
            status="ACTIVE",
        )
    )
    db_session.commit()
    return CurrentUser(id=user_id, company_id=company_id, role="INSTALLER")


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
        with_admin_profile: bool | None = None,
    ) -> UserORM:
        cid = company or company_id
        row = UserORM(
            company_id=cid,
            email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Test User",
            role=role,
            password_hash=hash_password(password),
            is_active=is_active,
            status="ACTIVE" if is_active else "INACTIVE",
        )
        db_session.add(row)
        db_session.commit()
        if role == UserRole.ADMIN and with_admin_profile is not False:
            db_session.add(
                AdminProfileORM(
                    company_id=cid,
                    user_id=row.id,
                    admin_scope=AdminScope.OWNER.value,
                    can_view_rates=True,
                    can_manage_imports=True,
                    can_manage_users=True,
                )
            )
            db_session.commit()
        db_session.refresh(row)
        return row

    return _factory


@pytest.fixture()
def make_reason(db_session: Session, company_id: uuid.UUID):
    def _factory(
        *,
        code: str | None = None,
        name: str = "Reason",
        company: uuid.UUID | None = None,
    ) -> ReasonORM:
        cid = company or company_id
        row = ReasonORM(
            company_id=cid,
            code=code or f"reason-{uuid.uuid4().hex[:8]}",
            name=name,
            is_active=True,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row

    return _factory


# ---------------------------------------------------------------------------
# Fake in-memory StorageService — isolates all tests from MinIO/network.
# Stores uploaded objects in a dict keyed by object_key.
# Provides a file-like wrapper for get_object_stream consumers that need
# .read(n), .close(), and .release_conn().
# ---------------------------------------------------------------------------

_FAKE_STORE: dict[str, bytes] = {}

# Minimal valid PDF header so assertions like b"%PDF" in content pass.
_MINIMAL_PDF = b"%PDF-1.4 1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


class _FakeObjectStream:
    """Mimics MinIO response object: .read(n), .close(), .release_conn()."""

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


def _fake_put_pdf(*, object_key: str, content: bytes) -> None:
    _FAKE_STORE[object_key] = content


def _fake_put_object(*, object_key: str, content: bytes, content_type: str) -> None:
    del content_type
    _FAKE_STORE[object_key] = content


def _fake_get_object_stream(*, bucket: str, object_key: str) -> _FakeObjectStream:
    data = _FAKE_STORE.get(object_key, _MINIMAL_PDF)
    return _FakeObjectStream(data)


def _fake_get_pdf(*, object_key: str) -> bytes:
    return _FAKE_STORE.get(object_key, _MINIMAL_PDF)


def _fake_get_object_bytes(*, bucket: str, object_key: str) -> bytes:
    del bucket
    return _FAKE_STORE.get(object_key, _MINIMAL_PDF)


def _fake_presign_get(*, object_key: str, expiry_seconds: int | None = None) -> str:
    return f"http://fake-storage/presigned/{object_key}"


@pytest.fixture(autouse=True)
def _mock_storage_service(request):
    """
    Replace all StorageService network calls with in-memory fakes.
    Runs for every test — keeps the suite deterministic without MinIO.
    Tests requiring real MinIO should be marked @pytest.mark.minio
    and run only with the full stack (workspace.cmd up).

    Skipped for tests that explicitly test StorageService internals
    (e.g. bucket bootstrap / caching behaviour), which supply their own
    fake MinIO via monkeypatch and must exercise the real implementation.
    """
    if "test_storage_service" in request.fspath.basename:
        yield
        return

    _FAKE_STORE.clear()
    from app.integrations.storage.storage_service import StorageService
    StorageService._reset_bucket_cache_for_tests()

    with (
        patch(
            "app.integrations.storage.storage_service.StorageService.put_pdf",
            staticmethod(_fake_put_pdf),
        ),
        patch(
            "app.integrations.storage.storage_service.StorageService.put_object",
            staticmethod(_fake_put_object),
        ),
        patch(
            "app.integrations.storage.storage_service.StorageService.get_object_stream",
            staticmethod(_fake_get_object_stream),
        ),
        patch(
            "app.integrations.storage.storage_service.StorageService.get_pdf",
            staticmethod(_fake_get_pdf),
        ),
        patch(
            "app.integrations.storage.storage_service.StorageService.get_object_bytes",
            staticmethod(_fake_get_object_bytes),
        ),
        patch(
            "app.integrations.storage.storage_service.StorageService.presign_get",
            staticmethod(_fake_presign_get),
        ),
    ):
        yield
