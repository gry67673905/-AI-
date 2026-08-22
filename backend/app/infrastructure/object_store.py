from __future__ import annotations

import asyncio
import io
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from app.errors import ConflictError, DependencyUnavailable


class MinioObjectStore:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        materials_bucket: str,
        knowledge_bucket: str,
    ) -> None:
        parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
        self._client = Minio(
            parsed.netloc or parsed.path,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
        )
        self.materials_bucket = materials_bucket
        self.knowledge_bucket = knowledge_bucket

    async def ensure_buckets(self) -> None:
        def ensure() -> None:
            for bucket in (self.materials_bucket, self.knowledge_bucket):
                if not self._client.bucket_exists(bucket):
                    try:
                        self._client.make_bucket(bucket)
                    except S3Error as exc:
                        # Two API replicas may both observe a missing bucket
                        # during first startup.  MinIO reports the loser as an
                        # error even though the desired state has already been
                        # reached.  Only tolerate the documented create race,
                        # and re-check rather than masking an authorization or
                        # connectivity failure.
                        if exc.code not in {
                            "BucketAlreadyOwnedByYou",
                            "BucketAlreadyExists",
                        } or not self._client.bucket_exists(bucket):
                            raise

        try:
            await asyncio.to_thread(ensure)
        except DependencyUnavailable:
            raise
        except Exception as exc:
            raise DependencyUnavailable("minio") from exc

    async def ping(self) -> None:
        try:
            await asyncio.to_thread(lambda: list(self._client.list_buckets()))
        except Exception as exc:
            raise DependencyUnavailable("minio") from exc

    async def put_bytes(
        self, bucket: str, object_key: str, content: bytes, content_type: str
    ) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                bucket,
                object_key,
                io.BytesIO(content),
                len(content),
                content_type=content_type,
            )
        except Exception as exc:
            raise DependencyUnavailable("minio") from exc

    async def get_bytes(self, bucket: str, object_key: str) -> bytes:
        def read() -> bytes:
            response = self._client.get_object(bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(read)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                raise ConflictError(
                    "材料对象缺失或完整性异常", "material_integrity_failed"
                ) from exc
            raise DependencyUnavailable("minio") from exc
        except Exception as exc:
            raise DependencyUnavailable("minio") from exc

    async def delete(self, bucket: str, object_key: str) -> None:
        try:
            await asyncio.to_thread(self._client.remove_object, bucket, object_key)
        except Exception as exc:
            raise DependencyUnavailable("minio") from exc


class InMemoryObjectStore:
    """Test adapter with the same no-public-link semantics as MinIO."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.materials_bucket = "materials"
        self.knowledge_bucket = "knowledge"

    async def ensure_buckets(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def put_bytes(
        self, bucket: str, object_key: str, content: bytes, content_type: str
    ) -> None:
        self.objects[(bucket, object_key)] = (content, content_type)

    async def get_bytes(self, bucket: str, object_key: str) -> bytes:
        return self.objects[(bucket, object_key)][0]

    async def delete(self, bucket: str, object_key: str) -> None:
        self.objects.pop((bucket, object_key), None)
