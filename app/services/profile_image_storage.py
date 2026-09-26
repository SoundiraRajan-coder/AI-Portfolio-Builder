import logging
from functools import lru_cache

from supabase import create_client


logger = logging.getLogger(__name__)


class ProfileImageStorageError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _get_supabase_client(supabase_url, service_role_key):
    return create_client(supabase_url, service_role_key)


def _log_storage_error(exc):
    status = getattr(exc, "status_code", None) or getattr(exc, "statusCode", None)
    code = getattr(exc, "code", None) or getattr(exc, "error", None)
    message = getattr(exc, "message", None)
    logger.warning(
        "Supabase Storage upload failed: exception_type=%s status=%s code=%s message=%s",
        type(exc).__name__,
        status,
        code,
        message,
    )


def upload_profile_image(*, supabase_url, service_role_key, bucket, object_path, content, content_type):
    missing_settings = [
        name
        for name, value in {
            "SUPABASE_URL": supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
            "SUPABASE_STORAGE_BUCKET": bucket,
        }.items()
        if not value
    ]
    if missing_settings:
        raise ProfileImageStorageError(
            f"Supabase Storage configuration is missing: {', '.join(missing_settings)}."
        )

    try:
        supabase = _get_supabase_client(supabase_url, service_role_key)
        supabase.storage.get_bucket(bucket)
        storage_bucket = supabase.storage.from_(bucket)
        storage_bucket.upload(
            path=object_path,
            file=content,
            file_options={
                "content-type": content_type,
                "cache-control": "3600",
                "upsert": "true",
            },
        )
        return storage_bucket.get_public_url(object_path)
    except Exception as exc:
        _log_storage_error(exc)
        raise ProfileImageStorageError("Supabase Storage upload failed.") from exc
