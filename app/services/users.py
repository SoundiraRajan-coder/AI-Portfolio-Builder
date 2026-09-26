from app.database import get_db_connection


def upsert_google_user(profile):
    """Create or update a local user from Google's OpenID profile."""
    google_subject = profile.get("sub") or profile.get("id")
    email = profile.get("email")
    if not google_subject or not email:
        raise ValueError("Google did not return the required user identity fields.")

    values = (
        google_subject,
        email,
        profile.get("name"),
        profile.get("picture"),
    )

    query = """
        INSERT INTO users (google_subject, email, display_name, avatar_url)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (google_subject) DO UPDATE SET
            email = EXCLUDED.email,
            display_name = EXCLUDED.display_name,
            avatar_url = EXCLUDED.avatar_url,
            updated_at = timezone('utc', now())
        RETURNING id, google_subject, email, display_name, avatar_url
    """

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, values)
            row = cursor.fetchone()
        connection.commit()

    return _user_from_row(row)


def get_user_by_id(user_id):
    query = """
        SELECT id, google_subject, email, display_name, avatar_url
        FROM users
        WHERE id = %s
    """

    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (user_id,))
            row = cursor.fetchone()

    return _user_from_row(row) if row else None


def _user_from_row(row):
    return {
        "id": str(row[0]),
        "google_subject": row[1],
        "email": row[2],
        "display_name": row[3],
        "avatar_url": row[4],
    }
