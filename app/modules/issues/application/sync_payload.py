from app.modules.sync.domain.enums import SyncChangeType


def build_issue_sync_payload(issue, *, project_id) -> dict:
    return {
        "id": str(issue.id),
        "door_id": str(issue.door_id),
        "project_id": str(project_id),
        "status": issue.status.value if hasattr(issue.status, "value") else str(issue.status),
        "title": issue.title,
        "details": issue.details,
    }


def publish_issue_change(uow, *, issue, door) -> None:
    uow.session.flush()
    uow.sync_change_log.add_change(
        company_id=issue.company_id,
        change_type=SyncChangeType.ISSUE,
        entity_id=issue.id,
        project_id=door.project_id,
        installer_id=door.installer_id,
        payload=build_issue_sync_payload(issue, project_id=door.project_id),
    )
