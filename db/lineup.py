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


def generate_checklist_pdf(meet_id: int, season_id: int,
                           lineup_entries: list[dict] | None = None) -> bytes:
    """Generate a meet day checklist PDF — athlete → events, sorted alphabetically.

    Designed for kids to quickly find their name and see what they're running.
    Portrait orientation, one section per gender.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle,
        Paragraph, Spacer, PageBreak
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
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

    # Build athlete → [event_name, ...] mapping, grouped by gender
    gender_athletes: dict[str, dict[int, list[str]]] = {"M": {}, "F": {}}
    for entry in lineup:
        aid = entry["athlete_id"]
        eid = entry["event_id"]
        a = athletes.get(aid)
        e = events.get(eid)
        if a and e:
            gender_athletes[a["gender"]].setdefault(aid, []).append(e["name"])

    # Sort events within each athlete by sort_order
    for gender_map in gender_athletes.values():
        for aid in gender_map:
            event_names = gender_map[aid]
            event_names.sort(
                key=lambda n: next(
                    (e["sort_order"] for e in events.values() if e["name"] == n),
                    999
                )
            )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "cl_title", parent=styles["Normal"],
        fontSize=14, fontName="Helvetica-Bold",
        alignment=TA_CENTER, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        "cl_subtitle", parent=styles["Normal"],
        fontSize=10, fontName="Helvetica",
        alignment=TA_CENTER, spaceAfter=8
    )
    name_style = ParagraphStyle(
        "cl_name", parent=styles["Normal"],
        fontSize=9, fontName="Helvetica-Bold",
    )
    event_style = ParagraphStyle(
        "cl_event", parent=styles["Normal"],
        fontSize=8, fontName="Helvetica",
    )
    # White text for header cells on dark background
    header_style = ParagraphStyle(
        "cl_header", parent=styles["Normal"],
        fontSize=8, fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    meet_name = meet["name"] if meet else "Meet"
    meet_date = meet["meet_date"] if meet else ""

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
    )

    story = []
    for gender, gender_label in [("M", "Boys"), ("F", "Girls")]:
        if story:
            story.append(PageBreak())

        story.append(Paragraph(
            f"Meet Day Checklist \u2014 {meet_name}", title_style
        ))
        story.append(Paragraph(
            f"{meet_date}  \u00b7  {gender_label}", subtitle_style
        ))

        athlete_map = gender_athletes[gender]
        if not athlete_map:
            story.append(Paragraph("No athletes in lineup.", event_style))
            continue

        # Sort alphabetically by last name, first name
        sorted_aids = sorted(
            athlete_map.keys(),
            key=lambda aid: (
                athletes[aid]["last_name"].lower(),
                athletes[aid]["first_name"].lower(),
            )
        )

        max_events = max(len(evts) for evts in athlete_map.values())

        # Header row — white text via style
        header_row = [
            Paragraph("#", header_style),
            Paragraph("Athlete", header_style),
        ]
        for i in range(max_events):
            header_row.append(Paragraph(f"Event {i+1}", header_style))
        header_row.append(Paragraph("", header_style))  # checkbox col

        data = [header_row]
        for idx, aid in enumerate(sorted_aids, 1):
            a = athletes[aid]
            event_list = athlete_map[aid]
            row = [
                Paragraph(str(idx), event_style),
                Paragraph(
                    f"{a['last_name']}, {a['first_name']}",
                    name_style
                ),
            ]
            for i in range(max_events):
                if i < len(event_list):
                    row.append(Paragraph(event_list[i], event_style))
                else:
                    row.append(Paragraph("", event_style))
            # Empty cell — the BOX style below draws the checkbox
            row.append(Paragraph("", event_style))
            data.append(row)

        # Column widths — compact layout
        num_width = 0.25 * inch
        name_width = 1.7 * inch
        check_width = 0.3 * inch
        usable = 7.5 * inch - num_width - name_width - check_width
        event_width = min(usable / max(max_events, 1), 1.3 * inch)
        col_widths = (
            [num_width, name_width]
            + [event_width] * max_events
            + [check_width]
        )

        row_height = 0.22 * inch
        t = Table(
            data, colWidths=col_widths, repeatRows=1,
            rowHeights=[0.25 * inch] + [row_height] * len(sorted_aids),
        )

        # Build style commands
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("ALIGN",         (0, 0), (0, -1), "CENTER"),
            ("ALIGN",         (-1, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("GRID",          (0, 0), (-2, -1), 0.5, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f5f5f5")]),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 3),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ]

        # Draw open checkbox squares in the last column for each data row
        check_col = 2 + max_events  # index of checkbox column
        for row_idx in range(1, len(sorted_aids) + 1):
            style_cmds.append(
                ("BOX", (check_col, row_idx), (check_col, row_idx),
                 1.0, colors.HexColor("#666666"))
            )
            style_cmds.append(
                ("BACKGROUND", (check_col, row_idx), (check_col, row_idx),
                 colors.white)
            )

        t.setStyle(TableStyle(style_cmds))

        story.append(t)
        story.append(Spacer(1, 10))
        story.append(Paragraph(
            f"{len(sorted_aids)} athletes  \u00b7  "
            f"{sum(len(athlete_map[a]) for a in sorted_aids)} total entries",
            subtitle_style
        ))

    doc.build(story)
    return buf.getvalue()
