from __future__ import annotations


def read_journal_snapshot(uow, *, journal) -> dict:
    """Serialize stored work rows after the caller has authorized the journal."""
    scope = {"company_id": journal.company_id, "journal_id": journal.id}
    items = uow.journals.list_items(**scope)
    addon_items = uow.journals.list_addon_items(**scope)
    project = uow.projects.get(
        company_id=journal.company_id, project_id=journal.project_id,
    )
    door_types = {
        row.id: row.name
        for row in uow.door_types.list_active(company_id=journal.company_id)
    }
    status = journal.status.value if hasattr(journal.status, "value") else str(journal.status)
    return {
        "journal": {
            "id": str(journal.id), "project_id": str(journal.project_id),
            "status": status, "title": journal.title, "notes": journal.notes,
            "pdf_locale": getattr(journal, "pdf_locale", "en"),
            "lock_header": journal.lock_header, "lock_table": journal.lock_table,
            "lock_footer": journal.lock_footer,
            "signed_at": journal.signed_at.isoformat() if journal.signed_at else None,
            "signer_name": journal.signer_name, "snapshot_version": journal.snapshot_version,
        },
        "project": {
            "name": project.name if project else "",
            "address": project.address if project else None,
            "developer_company": project.developer_company if project else None,
            "contact_name": project.contact_name if project else None,
        },
        "items": [
            {
                "unit_label": item.unit_label,
                "door_type_id": str(item.door_type_id),
                "door_type_name": door_types.get(item.door_type_id, str(item.door_type_id)),
                "installed_at": item.installed_at.isoformat() if item.installed_at else None,
            }
            for item in items
        ],
        "addon_items": [
            {
                "name": item.addon_name, "quantity": str(item.qty_done), "unit": item.unit,
                "done_at": item.done_at.isoformat(), "comment": item.comment,
            }
            for item in addon_items
        ],
    }
