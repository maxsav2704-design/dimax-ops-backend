from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.application.uow import AbstractUnitOfWork
from app.shared.infrastructure.db.session import SessionLocal
from app.modules.audit.infrastructure.repositories import AuditRepository
from app.modules.companies.infrastructure.repositories import (
    CompanyPlanRepository,
    CompanyRepository,
)
from app.modules.doors.infrastructure.repositories import DoorRepository
from app.modules.issues.infrastructure.repositories import IssueRepository
from app.modules.projects.infrastructure.repositories import (
    ProjectImportRunRepository,
    ProjectRepository,
)
from app.modules.identity.infrastructure.repositories import UserRepository
from app.modules.identity.infrastructure.refresh_tokens_repo import (
    RefreshTokenRepository,
)
from app.modules.journal.infrastructure.repositories import JournalRepository
from app.modules.calendar.infrastructure.repositories import CalendarRepository
from app.modules.installers.infrastructure.repositories import InstallerRepository
from app.modules.installers.infrastructure.rates_repository import InstallerRatesRepository
from app.modules.outbox.infrastructure.repositories import OutboxRepository
from app.modules.files.infrastructure.repositories import (
    FileDownloadEventRepository,
    FileTokenRepository,
)
from app.modules.addons.infrastructure.repositories import (
    AddonTypeRepository,
    ProjectAddonFactRepository,
    ProjectAddonPlanRepository,
)
from app.modules.sync.infrastructure.repositories import (
    InstallerSyncStateRepository,
    SyncChangeLogGCRepository,
    SyncChangeLogRepository,
    SyncEventRepository,
)
from app.modules.door_types.infrastructure.repositories import DoorTypeRepository
from app.modules.reasons.infrastructure.repositories import ReasonRepository
from app.modules.settings.infrastructure.repositories import CompanySettingsRepository
from app.modules.settings.infrastructure.models import CommunicationTemplateORM  # noqa: F401


class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self) -> None:
        self.session: Session | None = None

    def __enter__(self):
        self.session = SessionLocal()

        # подключаем репозитории
        self.users = UserRepository(self.session)
        self.refresh_tokens = RefreshTokenRepository(self.session)
        self.companies = CompanyRepository(self.session)
        self.company_plans = CompanyPlanRepository(self.session)
        self.doors = DoorRepository(self.session)
        self.issues = IssueRepository(self.session)
        self.projects = ProjectRepository(self.session)
        self.project_import_runs = ProjectImportRunRepository(self.session)
        self.audit = AuditRepository(self.session)
        self.journals = JournalRepository(self.session)
        self.calendar = CalendarRepository(self.session)
        self.installers = InstallerRepository(self.session)
        self.installer_rates = InstallerRatesRepository(self.session)
        self.outbox = OutboxRepository(self.session)
        self.file_tokens = FileTokenRepository(self.session)
        self.file_download_events = FileDownloadEventRepository(self.session)
        self.addon_types = AddonTypeRepository(self.session)
        self.addon_plans = ProjectAddonPlanRepository(self.session)
        self.addon_facts = ProjectAddonFactRepository(self.session)
        self.sync_events = SyncEventRepository(self.session)
        self.sync_change_log = SyncChangeLogRepository(self.session)
        self.sync_state = InstallerSyncStateRepository(self.session)
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

    def __exit__(self, exc_type, exc, tb):
        try:
            super().__exit__(exc_type, exc, tb)
        finally:
            if self.session is not None:
                self.session.close()
