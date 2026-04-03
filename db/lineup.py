"""db/lineup.py — Lineup builder, auto-suggest, and PDF export."""

from collections import defaultdict

from db.connection import get_connection, release_connection, fetchall, fetchone, execute
from db.athlete import get_roster
from db.events import get_track_events
from db.results import get_season_best_per_event, _parse_result
from db.meet import get_meet


def get_lineup(meet_id: int) -> list[dict]:
    """All saved lineup entries for a meet."""
    conn = get_connection()
    try:
        return fetchall(conn,
            """SELECT le.*, a.first_name, a.last_name, a.gender,
                      te.name AS event_name, te.event_type, te.sort_order
               FROM lineup_entry le
               JOIN athlete a ON a.id = le.athlete_id
               JOIN track_event te ON te.id = le.event_id
               WHERE le.meet_id = ?
               ORDER BY te.sort_order, a.last_name""",
            (meet_id,))
    finally:
        release_connection(conn)


def save_lineup(meet_id: int, entries: list[dict]) -> None:
    """Replace the entire lineup for a meet."""
    conn = get_connection()
    try:
        execute(conn, "DELETE FROM lineup_entry WHERE meet_id=?", (meet_id,))
        for e in entries:
            execute(conn,
                """INSERT INTO lineup_entry (meet_id, athlete_id, event_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT (meet_id, athlete_id, event_id) DO NOTHING""",
                (meet_id, e["athlete_id"], e["event_id"]))
    finally:
        release_connection(conn)


def get_athlete_event_counts(meet_id: int) -> dict[int, int]:
    """Returns {athlete_id: event_count} for the current lineup."""
    conn = get_connection()
    try:
        rows = fetchall(conn,
            """SELECT athlete_id, COUNT(*) AS cnt
               FROM lineup_entry WHERE meet_id=?
               GROUP BY athlete_id""",
            (meet_id,))
    finally:
        release_connection(conn)
    return {r["athlete_id"]: r["cnt"] for r in rows}


def auto_suggest_lineup(meet_id: int, season_id: int,
                         max_per_individual: int = 3,
                         max_per_relay: int = 5,
                         max_per_athlete: int = 4,
                         # Legacy support
                         max_per_event: int | None = None) -> dict:
    """Generate a suggested lineup based on season bests and event assignments.
    Relays allow more entries (4 runners + 1 alternate)."""
    if max_per_event is not None:
        max_per_individual = max_per_event

    roster = get_roster(season_id)
    active_ids = {a["id"] for a in roster if a["status"] == "active"}

    bests = get_season_best_per_event(season_id)
    events = get_track_events()

    conn = get_connection()
    try:
        rows = fetchall(conn,
            """SELECT ea.event_id, ea.athlete_id
               FROM event_assignment ea
               JOIN season_roster sr
                 ON sr.athlete_id = ea.athlete_id AND sr.season_id = ea.season_id
               WHERE ea.season_id = ?""",
            (season_id,))
    finally:
        release_connection(conn)

    assigned: dict[int, list[int]] = {}
    for r in rows:
        assigned.setdefault(r["event_id"], []).append(r["athlete_id"])

    entries = []
    conflicts = []
    counts: dict[int, int] = {}

    # Process individual events first, then relays
    # This way relay slots go to athletes who still have capacity
    individual_events = [e for e in events if e["event_type"] != "relay"]
    relay_events = [e for e in events if e["event_type"] == "relay"]

    for event in individual_events + relay_events:
        eid = event["id"]
        is_relay = event["event_type"] == "relay"
        event_max = max_per_relay if is_relay else max_per_individual

        candidates = [
            aid for aid in assigned.get(eid, [])
            if aid in active_ids
        ]

        def sort_key(aid: int) -> tuple:
            best = bests.get((aid, eid))
            if best is None:
                return (1, 0)
            try:
                val = _parse_result(best)
                if event["event_type"] == "field":
                    return (0, -val)
                return (0, val)
            except (ValueError, TypeError):
                return (1, 0)

        candidates.sort(key=sort_key)

        selected = []
        for aid in candidates:
            if counts.get(aid, 0) >= max_per_athlete:
                continue
            if len(selected) >= event_max:
                break
            selected.append(aid)
            counts[aid] = counts.get(aid, 0) + 1

        for aid in selected:
            entries.append({"athlete_id": aid, "event_id": eid})

        if len(selected) < event_max and candidates:
            conflicts.append({
                "event_name": event["name"],
                "gender":     event["gender"],
                "available":  len(selected),
                "needed":     event_max,
            })

    return {"entries": entries, "conflicts": conflicts, "counts": counts}


def generate_lineup_pdf(meet_id: int, season_id: int,
                        lineup_entries: list[dict] | None = None) -> bytes:
    """Generate a landscape PDF lineup report for a meet."""
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, PageBreak
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    import io as _io

    meet = get_meet(meet_id)
    lineup = lineup_entries if lineup_entries is not None else get_lineup(meet_id)

    conn = get_connection()
    try:
        athletes = {
            r["id"]: r
            for r in fetchall(conn, "SELECT * FROM athlete")
        }
        events = {
            r["id"]: r
            for r in fetchall(conn,
                "SELECT * FROM track_event ORDER BY sort_order")
        }
    finally:
        release_connection(conn)

    gender_events: dict = {
        "M": defaultdict(list),
        "F": defaultdict(list),
    }
    for entry in lineup:
        aid = entry["athlete_id"]
        eid = entry["event_id"]
        a = athletes.get(aid)
        e = events.get(eid)
        if a and e:
            gender_events[a["gender"]][eid].append(a)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Normal"],
        fontSize=13, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceAfter=4
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Normal"],
        fontSize=9, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceBefore=8, spaceAfter=4
    )
    cell_style = ParagraphStyle(
        "cell", parent=styles["Normal"],
        fontSize=8, fontName="Helvetica",
        alignment=TA_CENTER
    )
    header_style = ParagraphStyle(
        "header", parent=styles["Normal"],
        fontSize=8, fontName="Helvetica-Bold",
        alignment=TA_CENTER
    )

    MAX_INDIVIDUAL = 3
    MAX_RELAY = 5
    meet_name = meet["name"] if meet else "Lineup"
    meet_date = meet["meet_date"] if meet else ""

    def make_section_table(gender: str, event_type: str) -> Table | None:
        section_events = [
            e for e in events.values()
            if e["gender"] == gender and e["event_type"] == event_type
            and e["id"] in gender_events[gender]
        ]
        if not section_events:
            return None

        max_slots = MAX_RELAY if event_type == "relay" else MAX_INDIVIDUAL

        headers = [
            Paragraph(f'<font color="white">{e["name"]}</font>', header_style)
            for e in section_events
        ]

        athlete_rows = []
        for slot in range(max_slots):
            row = []
            for e in section_events:
                athletes_in_event = gender_events[gender][e["id"]]
                if slot < len(athletes_in_event):
                    a = athletes_in_event[slot]
                    row.append(Paragraph(a["first_name"], cell_style))
                else:
                    row.append(Paragraph("", cell_style))
            athlete_rows.append(row)

        data = [headers] + athlete_rows
        n_cols = len(section_events)
        col_width = (9.5 * inch) / max(n_cols, 1)
        col_widths = [col_width] * n_cols

        t = Table(data, colWidths=col_widths,
                  rowHeights=[0.3 * inch] + [0.25 * inch] * max_slots)
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f5f5f5")]),
            ("FONTSIZE",     (0, 0), (-1, -1), 8),
        ]))
        return t

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.4 * inch, bottomMargin=0.4 * inch,
    )

    story = []
    for gender, gender_label in [("M", "Boys"), ("F", "Girls")]:
        if story:
            story.append(PageBreak())

        story.append(Paragraph(
            f"{gender_label.upper()} \u2014 {meet_name} \u00b7 {meet_date}",
            title_style
        ))

        for etype, section_label in [
            ("field", "Field Events"),
            ("running", "Running Events"),
            ("relay", "Relays"),
        ]:
            t = make_section_table(gender, etype)
            if t:
                story.append(Paragraph(
                    f"{gender_label.upper()} {section_label.upper()}",
                    section_style
                ))
                story.append(t)
                story.append(Spacer(1, 6))

    doc.build(story)
    return buf.getvalue()
