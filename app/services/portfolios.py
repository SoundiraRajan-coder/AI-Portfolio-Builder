import re
from uuid import uuid4

from app.database import get_db_connection


STATUS_VALUES = {"draft", "published", "archived"}


def get_dashboard_portfolios(user_id):
    query = """
        SELECT p.id, p.name, p.slug, p.status, p.created_at, p.updated_at,
               pm.metadata->>'thumbnail_url' AS thumbnail_url
        FROM portfolios AS p
        LEFT JOIN portfolio_metadata AS pm
            ON pm.portfolio_id = p.id AND pm.user_id = p.user_id
        WHERE p.user_id = %s
        ORDER BY p.updated_at DESC
    """
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (user_id,))
            portfolios = [_portfolio_from_row(row) for row in cursor.fetchall()]

    return {
        "portfolios": portfolios,
        "total_portfolios": len(portfolios),
        "recently_updated": portfolios[0] if portfolios else None,
        "last_created": max(portfolios, key=lambda item: item["created_at"]) if portfolios else None,
    }


def get_portfolio(user_id, portfolio_id):
    query = """
        SELECT p.id, p.name, p.slug, p.status, p.created_at, p.updated_at,
               pm.metadata->>'thumbnail_url' AS thumbnail_url
        FROM portfolios AS p
        LEFT JOIN portfolio_metadata AS pm
            ON pm.portfolio_id = p.id AND pm.user_id = p.user_id
        WHERE p.id = %s AND p.user_id = %s
    """
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (portfolio_id, user_id))
            row = cursor.fetchone()

    return _portfolio_from_row(row) if row else None


def create_portfolio(user_id, name, status="draft"):
    portfolio_id = uuid4()
    slug = _portfolio_slug(name)
    query = """
        INSERT INTO portfolios (id, user_id, name, slug, status)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (portfolio_id, user_id, name, slug, status))
            created_id = cursor.fetchone()[0]
        connection.commit()
    return created_id


def update_portfolio(user_id, portfolio_id, name, status):
    query = """
        UPDATE portfolios
        SET name = %s, status = %s, updated_at = timezone('utc', now())
        WHERE id = %s AND user_id = %s
    """
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (name, status, portfolio_id, user_id))
            updated = cursor.rowcount
        connection.commit()
    return updated


def duplicate_portfolio(user_id, portfolio_id):
    new_id = uuid4()
    query = """
        INSERT INTO portfolios (id, user_id, name, slug, status)
        SELECT %s, user_id, name || ' (Copy)', %s, 'draft'
        FROM portfolios
        WHERE id = %s AND user_id = %s
        RETURNING id
    """
    copy_queries = (
        """
        INSERT INTO portfolio_skills (portfolio_id, user_id, skill_id, display_order)
        SELECT %s, user_id, skill_id, display_order FROM portfolio_skills
        WHERE portfolio_id = %s AND user_id = %s
        """,
        """
        INSERT INTO portfolio_education (portfolio_id, user_id, education_id, display_order)
        SELECT %s, user_id, education_id, display_order FROM portfolio_education
        WHERE portfolio_id = %s AND user_id = %s
        """,
        """
        INSERT INTO portfolio_experiences (portfolio_id, user_id, experience_id, display_order)
        SELECT %s, user_id, experience_id, display_order FROM portfolio_experiences
        WHERE portfolio_id = %s AND user_id = %s
        """,
        """
        INSERT INTO portfolio_projects (portfolio_id, user_id, project_id, display_order)
        SELECT %s, user_id, project_id, display_order FROM portfolio_projects
        WHERE portfolio_id = %s AND user_id = %s
        """,
        """
        INSERT INTO portfolio_certifications (portfolio_id, user_id, certification_id, display_order)
        SELECT %s, user_id, certification_id, display_order FROM portfolio_certifications
        WHERE portfolio_id = %s AND user_id = %s
        """,
        """
        INSERT INTO portfolio_metadata
            (portfolio_id, user_id, seo_title, seo_description, locale, public_contact_email, metadata)
        SELECT %s, user_id, seo_title, seo_description, locale, public_contact_email, metadata
        FROM portfolio_metadata WHERE portfolio_id = %s AND user_id = %s
        """,
        """
        INSERT INTO portfolio_design_specs
            (portfolio_id, user_id, generation_prompt, specification, is_custom)
        SELECT %s, user_id, generation_prompt, specification, is_custom
        FROM portfolio_design_specs WHERE portfolio_id = %s AND user_id = %s
        """,
    )
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (new_id, _portfolio_slug(f"copy-{new_id}"), portfolio_id, user_id))
            if not cursor.fetchone():
                return None
            for copy_query in copy_queries:
                cursor.execute(copy_query, (new_id, portfolio_id, user_id))
        connection.commit()
    return new_id


def delete_portfolio(user_id, portfolio_id):
    with get_db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM portfolios WHERE id = %s AND user_id = %s",
                (portfolio_id, user_id),
            )
            deleted = cursor.rowcount
        connection.commit()
    return deleted


def _portfolio_from_row(row):
    return {
        "id": str(row[0]),
        "name": row[1],
        "slug": row[2],
        "status": row[3],
        "created_at": row[4],
        "updated_at": row[5],
        "thumbnail_url": row[6],
    }


def _portfolio_slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return f"{slug[:140] or 'portfolio'}-{uuid4().hex[:8]}"
