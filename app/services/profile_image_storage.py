from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class ProfileImageStorageError(RuntimeError):
    pass


def upload_profile_image(*, supabase_url, service_role_key, bucket, object_path, content, content_type):
    if not supabase_url or not service_role_key or not bucket:
        raise ProfileImageStorageError("Supabase Storage is not configured.")

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
        raise ProfileImageStorageError("Supabase Storage rejected the upload.") from exc
    except (URLError, ValueError, OSError) as exc:
        raise ProfileImageStorageError("Supabase Storage could not be reached.") from exc

    return f"{base_url}/storage/v1/object/public/{encoded_bucket}/{encoded_path}"
