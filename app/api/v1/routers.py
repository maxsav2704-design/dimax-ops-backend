from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.error_schemas import ApiErrorResponseDTO
from app.modules.identity.api.auth import router as auth_router
from app.modules.doors.api.admin import router as admin_doors
from app.modules.doors.api.installer import router as installer_doors
from app.modules.projects.api.admin import router as admin_projects
from app.modules.projects.api.admin_addons import router as admin_project_addons
from app.modules.projects.api.installer import router as installer_projects
from app.modules.journal.api.admin import router as admin_journals
from app.modules.journal.api.admin_send import router as admin_journals_send
from app.modules.journal.api.admin_files import router as admin_journals_files
from app.modules.journal.api.admin_share import router as admin_journals_share
from app.modules.journal.api.public import router as public_journals
from app.modules.calendar.api.admin import router as admin_calendar
from app.modules.calendar.api.installer import router as installer_calendar
from app.modules.installers.api.admin import router as admin_installers
from app.modules.installers.api.admin_rates import router as admin_installer_rates
from app.modules.dashboard.api.admin_dashboard import router as admin_dashboard
from app.modules.reports.api.admin import router as admin_reports
from app.modules.addons.api.admin import router as admin_addons
from app.modules.addons.api.installer import router as installer_addons
from app.modules.sync.api.admin_sync import router as admin_sync
from app.modules.sync.api.admin_sync_health import router as admin_sync_health
from app.modules.sync.api.installer_sync import router as installer_sync
from app.modules.files.api.public import router as public_files
from app.modules.files.api.admin import router as admin_files
from app.modules.outbox.api.admin import router as admin_outbox
from app.webhooks.twilio import router as twilio_webhooks


router = APIRouter(prefix="/api/v1")

SECURED_ROUTE_RESPONSES = {
    400: {
        "description": "Bad Request",
        "model": ApiErrorResponseDTO,
    },
    401: {
        "description": "Unauthorized",
        "model": ApiErrorResponseDTO,
    },
    403: {
        "description": "Forbidden",
        "model": ApiErrorResponseDTO,
    },
    404: {
        "description": "Not Found",
        "model": ApiErrorResponseDTO,
    },
    409: {
        "description": "Conflict",
        "model": ApiErrorResponseDTO,
    },
    422: {
        "description": "Validation Error",
        "model": ApiErrorResponseDTO,
    },
}

VALIDATION_ERROR_RESPONSE = {
    422: {
        "description": "Validation Error",
        "model": ApiErrorResponseDTO,
    },
}

router.include_router(auth_router, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_projects, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_project_addons, responses=SECURED_ROUTE_RESPONSES)
router.include_router(installer_projects, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_journals, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_journals_send, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_journals_files, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_journals_share, responses=SECURED_ROUTE_RESPONSES)
router.include_router(public_journals, responses=VALIDATION_ERROR_RESPONSE)
router.include_router(public_files, responses=VALIDATION_ERROR_RESPONSE)
router.include_router(admin_files, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_outbox, responses=SECURED_ROUTE_RESPONSES)
router.include_router(twilio_webhooks)
router.include_router(admin_calendar, responses=SECURED_ROUTE_RESPONSES)
router.include_router(installer_calendar, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_installers, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_installer_rates, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_dashboard, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_reports, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_addons, responses=SECURED_ROUTE_RESPONSES)
router.include_router(installer_addons, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_sync, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_sync_health, responses=SECURED_ROUTE_RESPONSES)
router.include_router(installer_sync, responses=SECURED_ROUTE_RESPONSES)
router.include_router(admin_doors, responses=SECURED_ROUTE_RESPONSES)
router.include_router(installer_doors, responses=SECURED_ROUTE_RESPONSES)
