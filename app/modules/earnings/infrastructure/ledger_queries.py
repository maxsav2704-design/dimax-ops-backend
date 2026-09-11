from __future__ import annotations

import uuid

from sqlalchemy import and_, not_, select
from sqlalchemy.sql.elements import ColumnElement

from app.modules.earnings.infrastructure.models import CompletedWorkORM


def active_completed_work_filter(company_id: uuid.UUID) -> ColumnElement[bool]:
    """Current work, distinct from dated movements in the earnings statement."""
    reversed_ids = select(CompletedWorkORM.correction_ref_id).where(
        CompletedWorkORM.company_id == company_id,
        CompletedWorkORM.entry_type == "REVERSAL",
        CompletedWorkORM.correction_ref_id.is_not(None),
    )
    return and_(
        CompletedWorkORM.company_id == company_id,
        CompletedWorkORM.entry_type.in_(("ORIGINAL", "CORRECTION")),
        not_(CompletedWorkORM.id.in_(reversed_ids)),
    )
