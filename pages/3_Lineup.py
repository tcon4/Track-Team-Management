"""Lineup Builder page."""

import streamlit as st
import db
import shared

season_id = shared.setup()

year = st.session_state.current_year
sport = st.session_state.sport
school = db.get_school(st.session_state.school_id)
school_name = school["name"] if school else "—"

st.header(f"{year} {sport} Lineup Builder — {school_name}")

if sport != "Track":
    st.info("Lineup builder is for Track meets. Switch sport in the sidebar.")
    st.stop()

meets = db.get_meets(season_id)

if not meets:
    st.info("No meets on the schedule yet — add one in the Schedule tab first.")
    st.stop()

meet_options = {f"{m['meet_date']} \u00b7 {m['name']}": m["id"] for m in meets}
selected_meet_label = st.selectbox("Meet", list(meet_options.keys()))
selected_meet_id = meet_options[selected_meet_label]
selected_meet = db.get_meet(selected_meet_id)

st.caption(f"Location: {selected_meet['location']} \u00b7 "
           f"Host: {selected_meet['host_name']}")

MAX_PER_EVENT = 3
MAX_PER_ATHLETE = 4

# Load current lineup as set of (athlete_id, event_id) tuples
saved_lineup = db.get_lineup(selected_meet_id)
saved_set = {(e["athlete_id"], e["event_id"]) for e in saved_lineup}

# Session state for working lineup (before save)
lineup_key = f"lineup_{selected_meet_id}"
if lineup_key not in st.session_state:
    st.session_state[lineup_key] = saved_set

working_set: set = set(st.session_state[lineup_key])

# Action buttons
col_suggest, col_save, col_clear, col_export = st.columns([2, 2, 2, 2])

if col_suggest.button("Auto-suggest lineup", type="secondary"):
    suggestion = db.auto_suggest_lineup(
        selected_meet_id, season_id,
        MAX_PER_EVENT, MAX_PER_ATHLETE
    )
    st.session_state[lineup_key] = {
        (e["athlete_id"], e["event_id"]) for e in suggestion["entries"]
    }
    working_set = set(st.session_state[lineup_key])

    if suggestion["conflicts"]:
        for c in suggestion["conflicts"]:
            gender_label = "Boys" if c["gender"] == "M" else "Girls"
            st.warning(
                f"\u26a0 {c['event_name']} ({gender_label}): only "
                f"{c['available']} of {c['needed']} slots filled — "
                f"not enough athletes assigned or available."
            )
    else:
        st.success("Lineup suggested — review and save when ready.")
    st.rerun()

if col_save.button("Save lineup", type="primary"):
    entries = [
        {"athlete_id": aid, "event_id": eid}
        for aid, eid in st.session_state[lineup_key]
    ]
    db.save_lineup(selected_meet_id, entries)
    st.success("Lineup saved.")
    st.rerun()

if col_clear.button("Clear lineup"):
    st.session_state[lineup_key] = set()
    st.rerun()

if col_export.button("Export PDF"):
    st.session_state["export_lineup_meet"] = selected_meet_id

# PDF export download
if st.session_state.get("export_lineup_meet") == selected_meet_id:
    current_set = set(st.session_state.get(lineup_key, set()))
    if current_set != saved_set:
        st.warning(
            "Your lineup has unsaved changes — save before exporting "
            "to get the latest version."
        )
    with st.spinner("Generating PDF\u2026"):
        try:
            lineup_entries = [
                {"athlete_id": aid, "event_id": eid}
                for aid, eid in current_set
            ]
            pdf_bytes = db.generate_lineup_pdf(
                selected_meet_id, season_id,
                lineup_entries=lineup_entries
            )
            meet_slug = selected_meet["name"].replace(" ", "_").lower()
            st.download_button(
                label="\u2b07 Download lineup PDF",
                data=pdf_bytes,
                file_name=f"lineup_{meet_slug}.pdf",
                mime="application/pdf",
                type="primary",
            )
            st.session_state["export_lineup_meet"] = None
        except Exception as ex:
            st.error(f"PDF generation failed: {ex}")
            st.session_state["export_lineup_meet"] = None

st.divider()

# Compute live event counts from working set
athlete_counts: dict[int, int] = {}
for aid, eid in working_set:
    athlete_counts[aid] = athlete_counts.get(aid, 0) + 1

# Season bests for seed display
season_bests_map = db.get_season_best_per_event(season_id)

# Roster lookup
roster_all = db.get_roster(season_id)
roster_by_id = {a["id"]: a for a in roster_all}

# ---------------------------------------------------------------------------
# Lineup progress
# ---------------------------------------------------------------------------

all_events_for_progress = db.get_track_events()

with st.container(border=True):
    st.caption("Lineup progress")
    for gender_val, gender_label in [("M", "Boys"), ("F", "Girls")]:
        gender_events_prog = [
            e for e in all_events_for_progress
            if e["gender"] == gender_val
        ]
        event_counts = {}
        for aid, eid in working_set:
            a = roster_by_id.get(aid)
            if a and a["gender"] == gender_val:
                event_counts[eid] = event_counts.get(eid, 0) + 1

        total_slots = len(gender_events_prog) * MAX_PER_EVENT
        filled_slots = sum(event_counts.values())

        st.markdown(
            f"**{gender_label}** — {filled_slots}/{total_slots} slots"
        )
        badges = []
        for e in gender_events_prog:
            n = event_counts.get(e["id"], 0)
            icon = "\U0001f7e2" if n == MAX_PER_EVENT else (
                "\U0001f7e1" if n > 0 else "\U0001f534"
            )
            badges.append(f"{icon} {e['name']} {n}/{MAX_PER_EVENT}")

        row_size = 5
        for i in range(0, len(badges), row_size):
            bcols = st.columns(row_size)
            for j, badge in enumerate(badges[i:i + row_size]):
                bcols[j].caption(badge)

st.divider()

# ---------------------------------------------------------------------------
# Event-by-event grid
# ---------------------------------------------------------------------------

gender_tab_b, gender_tab_g = st.tabs(["Boys", "Girls"])

for gender_val, gtab in [("M", gender_tab_b), ("F", gender_tab_g)]:
    with gtab:
        events = db.get_track_events(gender=gender_val)
        gender_roster = [
            a for a in roster_all
            if a["gender"] == gender_val and a["status"] == "active"
        ]

        for event in events:
            eid = event["id"]

            assigned_athletes = [
                a for a in gender_roster
                if any(
                    ev["id"] == eid
                    for ev in db.get_athlete_events(a["id"], season_id)
                )
            ]

            if not assigned_athletes:
                continue

            event_selected = [
                aid for aid, e in working_set if e == eid
            ]
            count_label = f"{len(event_selected)}/{MAX_PER_EVENT}"
            over_limit = len(event_selected) > MAX_PER_EVENT

            header_color = "\U0001f534" if over_limit else (
                "\U0001f7e2" if len(event_selected) == MAX_PER_EVENT else "\u26aa"
            )

            st.markdown(
                f"**{event['name']}** &nbsp; {header_color} {count_label} entered"
            )

            for athlete in sorted(
                assigned_athletes,
                key=lambda a: (
                    season_bests_map.get((a["id"], eid)) is None,
                    season_bests_map.get((a["id"], eid), "z")
                )
            ):
                aid = athlete["id"]
                key = (aid, eid)
                is_checked = key in working_set
                sb = season_bests_map.get((aid, eid), "—")
                total_events = athlete_counts.get(aid, 0)
                at_limit = total_events >= MAX_PER_ATHLETE and not is_checked

                label = (
                    f"{athlete['last_name']}, {athlete['first_name']} "
                    f"\u00b7 Gr. {athlete['grade']} \u00b7 SB: {sb}"
                )
                if total_events >= MAX_PER_ATHLETE:
                    label += f" \u26a0 {total_events}/{MAX_PER_ATHLETE} events"

                checked = st.checkbox(
                    label,
                    value=is_checked,
                    disabled=at_limit,
                    key=f"lu_{selected_meet_id}_{aid}_{eid}",
                )

                if checked and key not in working_set:
                    working_set.add(key)
                    st.session_state[lineup_key] = working_set
                    st.rerun()
                elif not checked and key in working_set:
                    working_set.discard(key)
                    st.session_state[lineup_key] = working_set
                    st.rerun()

            st.write("")  # spacing between events

        # Athlete event count summary
        st.divider()
        st.markdown("**Athlete event totals**")
        summary_athletes = [
            a for a in gender_roster
            if athlete_counts.get(a["id"], 0) > 0
        ]
        for athlete in sorted(summary_athletes,
                              key=lambda a: -athlete_counts.get(a["id"], 0)):
            aid = athlete["id"]
            cnt = athlete_counts.get(aid, 0)
            bar = "\u2588" * cnt + "\u2591" * (MAX_PER_ATHLETE - cnt)
            warning = " \u26a0 at limit" if cnt >= MAX_PER_ATHLETE else ""
            st.caption(
                f"{athlete['last_name']}, {athlete['first_name']} "
                f"\u00b7 {bar} {cnt}/{MAX_PER_ATHLETE}{warning}"
            )
