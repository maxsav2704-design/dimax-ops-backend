from __future__ import annotations

from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email

from app.modules.identity.domain.enums import UserRole
from app.shared.domain.errors import NotFound, ValidationError


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return validate_email(
            value.strip(), check_deliverability=False
        ).normalized.lower()
    except EmailNotValidError:
        return None


@dataclass(frozen=True)
class JournalSubmissionReadiness:
    developer_email: str | None
    admin_emails: tuple[str, ...]
    has_work: bool

    @property
    def can_submit(self) -> bool:
        return bool(self.developer_email and self.admin_emails and self.has_work)

    def require(self) -> None:
        if not self.has_work:
            raise ValidationError("Journal has no completed work")
        if not self.developer_email:
            raise ValidationError(
                "Project developer email must be configured before signing"
            )
        if not self.admin_emails:
            raise ValidationError(
                "At least one active administrator email is required"
            )


class JournalSubmissionPolicy:
    @staticmethod
    def evaluate(
        uow,
        *,
        journal,
        project=None,
        door_items=None,
        addon_items=None,
    ) -> JournalSubmissionReadiness:
        project = project or uow.projects.get(
            company_id=journal.company_id,
            project_id=journal.project_id,
        )
        if project is None:
            raise NotFound("Project not found")
        if door_items is None:
            door_items = uow.journals.list_items(
                company_id=journal.company_id,
                journal_id=journal.id,
            )
        if addon_items is None:
            addon_items = uow.journals.list_addon_items(
                company_id=journal.company_id,
                journal_id=journal.id,
            )
        admin_emails = tuple(
            uow.users.list_active_emails_by_role(
                company_id=journal.company_id,
                role=UserRole.ADMIN,
            )
        )
        return JournalSubmissionReadiness(
            developer_email=normalize_email(project.contact_email),
            admin_emails=admin_emails,
            has_work=bool(door_items or addon_items),
        )
