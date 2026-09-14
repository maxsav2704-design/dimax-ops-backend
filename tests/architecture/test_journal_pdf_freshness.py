from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.journal.application import admin_files_service as module


@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("operation", ["download", "share"])
def test_unsigned_pdf_is_refreshed_but_signed_pdf_is_preserved(monkeypatch, signed, operation):
    company_id, journal_id = uuid4(), uuid4()
    uow = Mock()
    uow.journals.get.return_value = SimpleNamespace(
        signed_at=datetime.now(timezone.utc) if signed else None,
    )
    old = SimpleNamespace(bucket="test", file_path="old.pdf", mime_type="application/pdf")
    new = SimpleNamespace(bucket="test", file_path="new.pdf", mime_type="application/pdf")
    uow.journals.get_file.return_value = old
    build = Mock(return_value=new)
    stream = Mock(return_value=Mock())
    token = Mock(return_value="test-token")
    monkeypatch.setattr(module, "_ensure_pdf", build)
    monkeypatch.setattr(module.StorageService, "get_object_stream", stream)
    monkeypatch.setattr(module.FileTokenService, "create_token_for_object", token)
    if operation == "download":
        module.JournalAdminFilesService.prepare_pdf_download(
            uow, company_id=company_id, journal_id=journal_id,
            actor_user_id=uuid4(), ip=None, user_agent=None,
        )
        assert stream.call_args.kwargs["object_key"] == (old.file_path if signed else new.file_path)
    else:
        module.JournalAdminFilesService.share_pdf(
            uow, company_id=company_id, journal_id=journal_id,
            ttl_sec=3600, uses=1, audience=None,
        )
        assert token.call_args.kwargs["object_key"] == (old.file_path if signed else new.file_path)
    if signed:
        build.assert_not_called()
    else:
        build.assert_called_once_with(uow, company_id=company_id, journal_id=journal_id)
