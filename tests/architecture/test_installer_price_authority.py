from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as SchemaValidationError

from app.modules.addons.api.installer_schemas import AddFactBody
from app.modules.doors.api.schemas import InstallerDoorInstallBody, InstallerDoorStatusUpdateBody
from app.modules.sync.application.service import InstallerSyncService
from app.shared.domain.errors import ValidationError


FORGED_FIELDS = {
    "price": "999.00",
    "installer_price": "999.00",
    "installer_rate_snapshot": "999.00",
    "rate_snapshot": "999.00",
    "amount_snapshot": "999.00",
    "surcharge_pct": "900.00",
    "factory_approved": True,
    "factory_approval_id": str(uuid.uuid4()),
    "price_list_version_id": str(uuid.uuid4()),
}


def test_installer_http_work_schemas_reject_every_pricing_or_approval_field():
    for schema, valid in [
        (AddFactBody, {"addon_type_id": uuid.uuid4(), "qty_done": "1.50"}),
        (InstallerDoorInstallBody, {}),
        (InstallerDoorStatusUpdateBody, {"status": "INSTALLED"}),
    ]:
        schema.model_validate(valid)
        for field, value in FORGED_FIELDS.items():
            with pytest.raises(SchemaValidationError):
                schema.model_validate({**valid, field: value})


def test_sync_work_payloads_reject_pricing_without_discarding_quantity_or_versions():
    for operation, valid in [
        ("DOOR_SET_STATUS", {"door_id": str(uuid.uuid4()), "status": "INSTALLED", "base_version": 3, "previous_version": 3}),
        ("ADDON_FACT_CREATE", {"addon_type_id": str(uuid.uuid4()), "qty_done": "1.50", "comment": "Adjustment"}),
    ]:
        InstallerSyncService._validate_work_payload(operation, valid)
        for field, value in FORGED_FIELDS.items():
            with pytest.raises(ValidationError) as error:
                InstallerSyncService._validate_work_payload(operation, {**valid, field: value})
            assert error.value.field == "payload"
            assert error.value.meta == {"unexpected_fields": [field]}
