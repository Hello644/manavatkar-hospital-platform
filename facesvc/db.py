"""Read the enrolled face gallery from the shared Postgres. Read-only; the face
service never writes to the DB."""

import os


def load_gallery():
    import psycopg

    dsn = os.environ["DATABASE_URL"]
    rows = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT staff_id, embedding FROM attendance_faceenrollment "
                "WHERE is_active = true"
            )
            for staff_id, embedding in cur.fetchall():
                # embedding is jsonb -> already a Python list
                rows.append({"staff_id": str(staff_id), "embedding": embedding})
    return rows
