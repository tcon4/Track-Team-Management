"""db/season.py — Season queries."""

from db.connection import get_connection, release_connection, fetchone, fetchall, insert_returning_id


def get_or_create_season(year: int, sport: str, school_id: int) -> int:
    conn = get_connection()
    try:
        row = fetchone(conn,
            "SELECT id FROM season WHERE year=? AND sport=? AND school_id=?",
            (year, sport, school_id))
        if row:
            return row["id"]
        return insert_returning_id(conn,
            "INSERT INTO season (year, sport, school_id) VALUES (?,?,?)",
            (year, sport, school_id))
    finally:
        release_connection(conn)


def get_seasons(school_id: int, sport: str = "XC") -> list[dict]:
    conn = get_connection()
    try:
        return fetchall(conn,
            "SELECT * FROM season WHERE school_id=? AND sport=? ORDER BY year DESC",
            (school_id, sport))
    finally:
        release_connection(conn)
