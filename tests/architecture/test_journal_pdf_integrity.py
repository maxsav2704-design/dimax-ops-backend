from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pypdf import PdfReader

from app.integrations.pdf.generator import PdfGenerator, _format_timestamp
from app.modules.journal.application.signature_validation import validate_signature_payload
from app.modules.journal.application.use_cases import JournalUseCases
from app.shared.domain.errors import Conflict, ValidationError


def test_signed_export_preserves_legacy_archive_without_reading_live_metadata():
    company_id, journal_id = uuid4(), uuid4()
    uow = Mock()
    uow.journals.get.return_value = SimpleNamespace(signed_at=datetime.now(timezone.utc))
    archive = SimpleNamespace(file_path="legacy-signed.pdf")
    uow.journals.get_file.return_value = archive
    assert JournalUseCases.export_pdf(uow, company_id=company_id, journal_id=journal_id) is archive
    uow.journals.get.assert_called_once_with(company_id=company_id, journal_id=journal_id, for_update=True)
    uow.projects.get.assert_not_called()
    uow.journals.upsert_file.assert_not_called()


def test_missing_signed_archive_cannot_be_reconstructed_from_changed_project():
    uow = Mock()
    uow.journals.get.return_value = SimpleNamespace(signed_at=datetime.now(timezone.utc))
    uow.journals.get_file.return_value = None
    with pytest.raises(Conflict, match="restore"):
        JournalUseCases.export_pdf(uow, company_id=uuid4(), journal_id=uuid4())
    uow.projects.get.assert_not_called()


def test_unsigned_pdf_cannot_be_finalized_as_a_signature():
    uow = Mock()
    uow.journals.get.return_value = SimpleNamespace(signed_at=None)
    with pytest.raises(Conflict, match="before signing"):
        JournalUseCases.export_pdf(uow, company_id=uuid4(), journal_id=uuid4(), finalize_signature=True)


def test_repeated_signature_finalization_reuses_completed_archive():
    company_id, journal_id = uuid4(), uuid4()
    uow = Mock()
    uow.journals.get.return_value = SimpleNamespace(signed_at=datetime.now(timezone.utc))
    archive = SimpleNamespace(
        file_path=f"journals/{company_id}/{journal_id}/journal_{journal_id}_signed.pdf"
    )
    uow.journals.get_file.return_value = archive
    assert JournalUseCases.export_pdf(
        uow, company_id=company_id, journal_id=journal_id, finalize_signature=True
    ) is archive
    uow.projects.get.assert_not_called()
    uow.journals.upsert_file.assert_not_called()


@pytest.mark.parametrize("value, expected", [
    ("2026-09-14T13:12:00Z", "14.09.2026 16:12"),
    ("2026-01-14T13:12:00+00:00", "14.01.2026 15:12"),
    ("2026-09-14T16:12:00+03:00", "14.09.2026 16:12"),
    (None, "-"),
])
def test_pdf_timestamps_match_israel_business_time(value, expected):
    assert _format_timestamp(value) == expected


def test_real_pdf_contains_notes_and_local_work_time():
    content = PdfGenerator.journal_pdf(
        journal={"id": "qa-journal", "title": "QA acceptance", "notes": "Keep <position> & comment\nSecond note"},
        items=[{"unit_label": "A-201", "door_type_name": "Entrance", "installed_at": "2026-09-14T13:12:00Z"}],
    )
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
    assert "Keep <position> & comment" in text
    assert "Second note" in text
    assert "14.09.2026 16:12" in text
    assert "Asia/Jerusalem" in text


def valid_signature():
    return {"viewport": {"width": 300, "height": 120},
            "strokes": [[{"x": 20, "y": 30}, {"x": 80, "y": 60}]]}


@pytest.mark.parametrize("payload", [
    {}, {"strokes": [1, 2]},
    {**valid_signature(), "viewport": {"width": 0, "height": 120}},
    {**valid_signature(), "viewport": {"width": 1e-320, "height": 120}},
    {**valid_signature(), "viewport": {"width": "bad", "height": 120}},
    {**valid_signature(), "strokes": []},
    {**valid_signature(), "strokes": [[{"x": 20, "y": 30}]]},
    {**valid_signature(), "strokes": [[{"x": 20, "y": 30}] * 2]},
    {**valid_signature(), "strokes": [[{"x": float("nan"), "y": 30}, {"x": 80, "y": 60}]]},
    {**valid_signature(), "strokes": [[{"x": True, "y": 30}, {"x": 80, "y": 60}]]},
    {**valid_signature(), "strokes": [[{"x": -30, "y": -30}, {"x": -20, "y": -20}]]},
    {**valid_signature(), "strokes": valid_signature()["strokes"] * 101},
    {**valid_signature(), "strokes": [valid_signature()["strokes"][0] * 10001]},
])
def test_signature_rejects_blank_invalid_or_unbounded_payload(payload):
    with pytest.raises(ValidationError):
        validate_signature_payload(payload)


def test_signature_accepts_current_canvas_format_and_captured_pointer_outside_canvas():
    payload = valid_signature()
    payload["strokes"][0].append({"x": 350, "y": 70})
    validate_signature_payload(payload)
