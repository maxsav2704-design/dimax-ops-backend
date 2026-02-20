from __future__ import annotations

from fastapi import APIRouter

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
from app.modules.installers.api.admin_link import router as admin_installers_link
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

router.include_router(auth_router)
router.include_router(admin_projects)
router.include_router(admin_project_addons)
router.include_router(installer_projects)
router.include_router(admin_journals)
router.include_router(admin_journals_send)
router.include_router(admin_journals_files)
router.include_router(admin_journals_share)
router.include_router(public_journals)
router.include_router(public_files)
router.include_router(admin_files)
router.include_router(admin_outbox)
router.include_router(twilio_webhooks)
router.include_router(admin_calendar)
router.include_router(installer_calendar)
router.include_router(admin_installers)
router.include_router(admin_installers_link)
router.include_router(admin_installer_rates)
router.include_router(admin_dashboard)
router.include_router(admin_reports)
router.include_router(admin_addons)
router.include_router(installer_addons)
router.include_router(admin_sync)
router.include_router(admin_sync_health)
router.include_router(installer_sync)
router.include_router(admin_doors)
router.include_router(installer_doors)
