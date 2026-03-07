from __future__ import annotations

from app.core.config import settings
from app.integrations.storage import storage_service as storage_module
from app.integrations.storage.storage_service import StorageService


class _FakeMinio:
    def __init__(self, *, exists: bool) -> None:
        self.exists = exists
        self.bucket_exists_calls = 0
        self.make_bucket_calls = 0
        self.put_calls = 0

    def bucket_exists(self, _bucket_name: str) -> bool:
        self.bucket_exists_calls += 1
        return self.exists

    def make_bucket(self, _bucket_name: str) -> None:
        self.make_bucket_calls += 1
        self.exists = True

    def put_object(
        self,
        *,
        bucket_name: str,
        object_name: str,
        data,
        length: int,
        content_type: str,
    ) -> None:
        _ = (bucket_name, object_name, content_type)
        assert length >= 0
        assert data is not None
        self.put_calls += 1


def test_put_pdf_bootstraps_bucket_if_missing(monkeypatch):
    fake = _FakeMinio(exists=False)
    monkeypatch.setattr(storage_module, "get_minio", lambda: fake)
    monkeypatch.setattr(settings, "MINIO_BUCKET", "dimax-test-bootstrap")
    StorageService._reset_bucket_cache_for_tests()

    StorageService.put_pdf(object_key="journals/a.pdf", content=b"%PDF")

    assert fake.bucket_exists_calls == 1
    assert fake.make_bucket_calls == 1
    assert fake.put_calls == 1


def test_put_pdf_uses_bucket_cache(monkeypatch):
    fake = _FakeMinio(exists=True)
    monkeypatch.setattr(storage_module, "get_minio", lambda: fake)
    monkeypatch.setattr(settings, "MINIO_BUCKET", "dimax-test-cache")
    StorageService._reset_bucket_cache_for_tests()

    StorageService.put_pdf(object_key="journals/a.pdf", content=b"%PDF")
    StorageService.put_pdf(object_key="journals/b.pdf", content=b"%PDF")

    assert fake.bucket_exists_calls == 1
    assert fake.make_bucket_calls == 0
    assert fake.put_calls == 2

