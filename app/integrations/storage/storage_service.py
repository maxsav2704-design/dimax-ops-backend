from __future__ import annotations

from threading import Lock
from datetime import timedelta
from io import BytesIO

from minio.error import S3Error

from app.core.config import settings
from app.integrations.storage.minio_client import get_minio

_BUCKET_READY: set[str] = set()
_BUCKET_LOCK = Lock()


class StorageService:
    @staticmethod
    def _ensure_bucket_exists(*, bucket_name: str) -> None:
        if bucket_name in _BUCKET_READY:
            return
        with _BUCKET_LOCK:
            if bucket_name in _BUCKET_READY:
                return
            client = get_minio()
            if not client.bucket_exists(bucket_name):
                try:
                    client.make_bucket(bucket_name)
                except S3Error as exc:
                    if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                        raise
            _BUCKET_READY.add(bucket_name)

    @staticmethod
    def _reset_bucket_cache_for_tests() -> None:
        # Test-only helper to isolate per-test monkeypatching of storage client.
        with _BUCKET_LOCK:
            _BUCKET_READY.clear()

    @staticmethod
    def put_pdf(*, object_key: str, content: bytes) -> None:
        StorageService._ensure_bucket_exists(bucket_name=settings.MINIO_BUCKET)
        client = get_minio()
        data = BytesIO(content)
        client.put_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=object_key,
            data=data,
            length=len(content),
            content_type="application/pdf",
        )

    @staticmethod
    def presign_get(
        *, object_key: str, expiry_seconds: int | None = None
    ) -> str:
        StorageService._ensure_bucket_exists(bucket_name=settings.MINIO_BUCKET)
        client = get_minio()
        exp = expiry_seconds or settings.MINIO_PRESIGN_EXPIRY_SEC
        return client.presigned_get_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=object_key,
            expires=timedelta(seconds=exp),
        )

    @staticmethod
    def get_object_stream(*, bucket: str, object_key: str):
        """
        Returns MinIO response object with .read().
        Caller must close it (close + release_conn).
        """
        StorageService._ensure_bucket_exists(bucket_name=bucket)
        client = get_minio()
        return client.get_object(bucket_name=bucket, object_name=object_key)

    @staticmethod
    def get_pdf(*, object_key: str) -> bytes:
        """Download object from MinIO as bytes (for email attachment in worker)."""
        StorageService._ensure_bucket_exists(bucket_name=settings.MINIO_BUCKET)
        client = get_minio()
        resp = client.get_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=object_key,
        )
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
