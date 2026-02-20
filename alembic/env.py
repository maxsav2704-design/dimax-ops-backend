from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.shared.infrastructure.db.base import Base

# --- импортируем ВСЕ ORM модели, чтобы они зарегистрировались в metadata ---
from app.modules.identity.infrastructure.models import (  # noqa: F401
    CompanyORM,
    UserORM,
)
from app.modules.identity.infrastructure.refresh_tokens_models import (  # noqa: F401
    RefreshTokenORM,
)
from app.modules.audit.infrastructure.models import AuditLogORM  # noqa: F401
from app.modules.door_types.infrastructure.models import DoorTypeORM  # noqa: F401
from app.modules.reasons.infrastructure.models import ReasonORM  # noqa: F401
from app.modules.installers.infrastructure.models import InstallerORM  # noqa: F401
from app.modules.rates.infrastructure.models import InstallerRateORM  # noqa: F401
from app.modules.projects.infrastructure.models import ProjectORM  # noqa: F401
from app.modules.doors.infrastructure.models import DoorORM  # noqa: F401
from app.modules.issues.infrastructure.models import IssueORM  # noqa: F401
from app.modules.journal.infrastructure.models import (  # noqa: F401
    JournalORM,
    JournalDoorItemORM,
    JournalSignatureORM,
    JournalFileORM,
)
from app.modules.calendar.infrastructure.models import (  # noqa: F401
    CalendarEventORM,
    CalendarEventAssigneeORM,
)
from app.modules.outbox.infrastructure.models import OutboxMessageORM  # noqa: F401
from app.modules.files.infrastructure.models import (  # noqa: F401
    FileDownloadTokenORM,
    FileDownloadEventORM,
)
from app.webhooks.models import WebhookEventORM  # noqa: F401
from app.modules.addons.infrastructure.models import (  # noqa: F401
    AddonTypeORM,
    ProjectAddonFactORM,
    ProjectAddonPlanORM,
)
from app.modules.sync.infrastructure.models import (  # noqa: F401
    InstallerSyncStateORM,
    SyncChangeLogORM,
    SyncEventORM,
)
# -------------------------------------------------------------------------

config = context.config

# логи alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# metadata
target_metadata = Base.metadata


def get_url() -> str:
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
