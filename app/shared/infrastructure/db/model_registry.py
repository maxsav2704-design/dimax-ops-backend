from __future__ import annotations

from importlib import import_module

_MODEL_MODULES = (
    "app.modules.identity.infrastructure.models",
    "app.modules.identity.infrastructure.refresh_tokens_models",
    "app.modules.audit.infrastructure.models",
    "app.modules.door_types.infrastructure.models",
    "app.modules.reasons.infrastructure.models",
    "app.modules.installers.infrastructure.models",
    "app.modules.library.infrastructure.models",
    "app.modules.rates.infrastructure.models",
    "app.modules.projects.infrastructure.models",
    "app.modules.doors.infrastructure.models",
    "app.modules.doors.infrastructure.history_models",
    "app.modules.issues.infrastructure.models",
    "app.modules.journal.infrastructure.models",
    "app.modules.calendar.infrastructure.models",
    "app.modules.outbox.infrastructure.models",
    "app.modules.files.infrastructure.models",
    "app.modules.documents.infrastructure.models",
    "app.webhooks.models",
    "app.modules.addons.infrastructure.models",
    "app.modules.sync.infrastructure.models",
    "app.modules.earnings.infrastructure.models",
    "app.modules.companies.infrastructure.models",
    "app.modules.settings.infrastructure.models",
)

_imported = False


def import_all_orm_models() -> None:
    global _imported

    if _imported:
        return

    for module_name in _MODEL_MODULES:
        import_module(module_name)

    _imported = True
