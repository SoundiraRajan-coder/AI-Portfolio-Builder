from app.database import get_db_connection


ITEM_DEFINITIONS = {
    "skills": {
        "table": "skills",
        "fields": ("name", "category", "proficiency"),
        "order_by": "display_order, created_at DESC",
    },
    "education": {
        "table": "education",
        "fields": (
            "institution",
            "degree",
            "field_of_study",
            "start_date",
            "end_date",
            "is_current",
            "description",
        ),
        "order_by": "display_order, start_date DESC NULLS LAST",
    },
    "experience": {
        "table": "work_experiences",
        "fields": (
            "company_name",
            "job_title",
            "location",
            "start_date",
            "end_date",
            "is_current",
            "description",
        ),
        "order_by": "display_order, start_date DESC NULLS LAST",
    },
    "projects": {
        "table": "projects",
        "fields": (
            "name",
            "summary",
            "description",
            "project_url",
            "repository_url",
            "start_date",
            "end_date",
            "is_current",
        ),
        "order_by": "display_order, created_at DESC",
    },
    "certifications": {
        "table": "certifications",
        "fields": (
            "name",
            "issuing_organization",
            "issue_date",
            "expiration_date",
            "credential_id",
            "credential_url",
        ),
        "order_by": "display_order, issue_date DESC NULLS LAST",
    },
}


def get_profile_page_data(user_id):
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.email, u.display_name, u.avatar_url,
                       p.headline, p.phone, p.bio, p.location,
                       p.github_url, p.linkedin_url, p.website_url
                FROM users AS u
                LEFT JOIN user_profiles AS p ON p.user_id = u.id
                WHERE u.id = %s
                """,
                (user_id,),
            )
            user_row = cursor.fetchone()
            if not user_row:
                return None

            data = {
                "user": {
                    "id": str(user_row[0]),
                    "email": user_row[1],
                    "display_name": user_row[2] or "",
                    "avatar_url": user_row[3] or "",
                    "headline": user_row[4] or "",
                    "phone": user_row[5] or "",
                    "bio": user_row[6] or "",
                    "location": user_row[7] or "",
                    "github_url": user_row[8] or "",
                    "linkedin_url": user_row[9] or "",
                    "website_url": user_row[10] or "",
                }
            }

            for kind, definition in ITEM_DEFINITIONS.items():
                cursor.execute(
                    f"""
                    SELECT id, {', '.join(definition['fields'])}
                    FROM {definition['table']}
                    WHERE user_id = %s
                    ORDER BY {definition['order_by']}
                    """,
                    (user_id,),
                )
                data[kind] = [
                    {"id": str(row[0]), **dict(zip(definition["fields"], row[1:]))}
                    for row in cursor.fetchall()
                ]

    return data


def save_profile_details(user_id, profile):
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET display_name = %s, avatar_url = %s,
                    updated_at = timezone('utc', now())
                WHERE id = %s
                """,
                (profile["display_name"], profile["avatar_url"], user_id),
            )
            cursor.execute(
                """
                INSERT INTO user_profiles
                    (user_id, headline, phone, bio, location, github_url,
                     linkedin_url, website_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    headline = EXCLUDED.headline,
                    phone = EXCLUDED.phone,
                    bio = EXCLUDED.bio,
                    location = EXCLUDED.location,
                    github_url = EXCLUDED.github_url,
                    linkedin_url = EXCLUDED.linkedin_url,
                    website_url = EXCLUDED.website_url,
                    updated_at = timezone('utc', now())
                """,
                (
                    user_id,
                    profile["headline"],
                    profile["phone"],
                    profile["bio"],
                    profile["location"],
                    profile["github_url"],
                    profile["linkedin_url"],
                    profile["website_url"],
                ),
            )
        connection.commit()


def create_item(user_id, kind, values):
    definition = ITEM_DEFINITIONS[kind]
    columns = ", ".join(("user_id", *definition["fields"]))
    placeholders = ", ".join(["%s"] * (len(definition["fields"]) + 1))
    query = f"INSERT INTO {definition['table']} ({columns}) VALUES ({placeholders})"
    _execute_item_query(query, (user_id, *(values[field] for field in definition["fields"])))


def update_item(user_id, kind, item_id, values):
    definition = ITEM_DEFINITIONS[kind]
    assignments = ", ".join(f"{field} = %s" for field in definition["fields"])
    query = f"""
        UPDATE {definition['table']}
        SET {assignments}, updated_at = timezone('utc', now())
        WHERE id = %s AND user_id = %s
    """
    return _execute_item_query(
        query,
        (*(values[field] for field in definition["fields"]), item_id, user_id),
    )


def delete_item(user_id, kind, item_id):
    table = ITEM_DEFINITIONS[kind]["table"]
    return _execute_item_query(
        f"DELETE FROM {table} WHERE id = %s AND user_id = %s",
        (item_id, user_id),
    )


def _execute_item_query(query, values):
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, values)
            rowcount = cursor.rowcount
        connection.commit()
    return rowcount
