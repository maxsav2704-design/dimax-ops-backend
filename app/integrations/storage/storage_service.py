from __future__ import annotations

from datetime import timedelta
from io import BytesIO

from app.core.config import settings
from app.integrations.storage.minio_client import get_minio


class StorageService:
    @staticmethod
    def put_pdf(*, object_key: str, content: bytes) -> None:
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
        client = get_minio()
        return client.get_object(bucket_name=bucket, object_name=object_key)

    @staticmethod
    def get_pdf(*, object_key: str) -> bytes:
        """Download object from MinIO as bytes (for email attachment in worker)."""
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
