import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)


class ProfileImageStorageError(RuntimeError):
    pass


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

    base_url = supabase_url.rstrip("/")
    encoded_bucket = quote(bucket, safe="")
    encoded_path = quote(object_path, safe="/")
    endpoint = f"{base_url}/storage/v1/object/{encoded_bucket}/{encoded_path}"
    request = Request(
        endpoint,
        data=content,
        method="POST",
        headers={
            "Authorization": f"Bearer {service_role_key}",
            "apikey": service_role_key,
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )

    try:
        with urlopen(request, timeout=15) as response:
            if response.status not in {200, 201}:
                raise ProfileImageStorageError("Supabase Storage rejected the upload.")
    except HTTPError as exc:
        if exc.code == 400:
            try:
                response_data = json.loads(exc.read(4096).decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                logger.warning("Supabase Storage upload rejected: status=%s", exc.code)
            else:
                if isinstance(response_data, dict):
                    logger.warning(
                        "Supabase Storage upload rejected: status=%s code=%s error=%s message=%s",
                        exc.code,
                        response_data.get("code"),
                        response_data.get("error"),
                        response_data.get("message"),
                    )
                else:
                    logger.warning("Supabase Storage upload rejected: status=%s", exc.code)
        raise ProfileImageStorageError(
            f"Supabase Storage upload was rejected with HTTP {exc.code}."
        ) from exc
    except (URLError, ValueError, OSError) as exc:
        raise ProfileImageStorageError("Supabase Storage could not be reached.") from exc

    return f"{base_url}/storage/v1/object/public/{encoded_bucket}/{encoded_path}"
