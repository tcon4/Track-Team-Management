"""Lineup Builder page."""

import streamlit as st
import db
import shared

season_id = shared.setup()

year = st.session_state.current_year
sport = st.session_state.sport
school = db.get_school(st.session_state.school_id)
school_name = school["name"] if school else "—"

st.title("Lineup Builder")
st.caption(f"{year} {sport} — {school_name}")

if sport != "Track":
    st.info("Lineup builder is for Track meets. Switch sport in the sidebar.")
    st.stop()

meets = db.get_meets(season_id)

if not meets:
    st.info("No meets on the schedule yet.")
    st.page_link("pages/2_Schedule.py", label="Add a meet on the Schedule page →")
    st.stop()

with st.container(border=True):
    meet_options = {f"{m['meet_date']} · {m['name']}": m["id"] for m in meets}
    selected_meet_label = st.selectbox("Meet", list(meet_options.keys()))
    selected_meet_id = meet_options[selected_meet_label]
    selected_meet = db.get_meet(selected_meet_id)
    st.caption(f"Location: {selected_meet['location']}  ·  "
               f"Host: {selected_meet['host_name']}")

MAX_PER_INDIVIDUAL = 3
MAX_PER_RELAY = 5
MAX_PER_ATHLETE = 4


def max_for_event(event: dict) -> int:
    """Return the max entries allowed for an event."""
    return MAX_PER_RELAY if event.get("event_type") == "relay" else MAX_PER_INDIVIDUAL


# Load current lineup as set of (athlete_id, event_id) tuples
saved_lineup = db.get_lineup(selected_meet_id)
saved_set = {(e["athlete_id"], e["event_id"]) for e in saved_lineup}

# Session state for working lineup (before save)
lineup_key = f"lineup_{selected_meet_id}"
if lineup_key not in st.session_state:
    st.session_state[lineup_key] = saved_set

working_set: set = set(st.session_state[lineup_key])


def _clear_checkbox_keys():
    """Clear all lu_ checkbox keys so Streamlit picks up new values."""
    keys_to_clear = [k for k in st.session_state if k.startswith(f"lu_{selected_meet_id}_")]
    for k in keys_to_clear:
        del st.session_state[k]


# Action buttons
col_suggest, col_save, col_clear, col_export = st.columns([2, 2, 2, 2])

if col_suggest.button("Auto-suggest lineup", type="secondary"):
    suggestion = db.auto_suggest_lineup(
        selected_meet_id, season_id,
        max_per_individual=MAX_PER_INDIVIDUAL,
        max_per_relay=MAX_PER_RELAY,
        max_per_athlete=MAX_PER_ATHLETE,
    )
    st.session_state[lineup_key] = {
        (e["athlete_id"], e["event_id"]) for e in suggestion["entries"]
    }
    _clear_checkbox_keys()

    if suggestion["conflicts"]:
        for c in suggestion["conflicts"]:
            gender_label = "Boys" if c["gender"] == "M" else "Girls"
            st.warning(
                f"⚠ {c['event_name']} ({gender_label}): only "
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
    _clear_checkbox_keys()
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
    with st.spinner("Generating PDF…"):
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
                label="⬇ Download lineup PDF",
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

# ---------------------------------------------------------------------------
# Shared data
# ---------------------------------------------------------------------------

# Compute live event counts from working set
athlete_counts: dict[int, int] = {}
for aid, eid in working_set:
    athlete_counts[aid] = athlete_counts.get(aid, 0) + 1

# Season bests for seed display
season_bests_map = db.get_season_best_per_event(season_id)

# Roster lookup
roster_all = db.get_roster(season_id)
roster_by_id = {a["id"]: a for a in roster_all}

# Batch-fetch all event assignments (avoids N+1 queries)
all_event_assignments = db.get_all_athlete_events(season_id)

# All events
all_events = db.get_track_events()
events_by_id = {e["id"]: e for e in all_events}

# Map relay events to corresponding individual event IDs for season best lookup
# e.g. "4x100 Relay" (gender M) → find the event_id for "100m" (gender M)
RELAY_TO_INDIVIDUAL = {"4x100 Relay": "100m", "4x200 Relay": "200m", "4x400 Relay": "400m"}
relay_sb_event_map: dict[int, int] = {}  # relay_event_id → individual_event_id
for e in all_events:
    if e["event_type"] == "relay" and e["name"] in RELAY_TO_INDIVIDUAL:
        indiv_name = RELAY_TO_INDIVIDUAL[e["name"]]
        for ie in all_events:
            if ie["name"] == indiv_name and ie["gender"] == e["gender"]:
                relay_sb_event_map[e["id"]] = ie["id"]
                break

# Build mapping: event_id → list of athlete first names in working set
event_athletes: dict[int, list[str]] = {}
for aid, eid in working_set:
    a = roster_by_id.get(aid)
    if a:
        event_athletes.setdefault(eid, []).append(a["first_name"])

# Total unique athletes in the lineup
unique_athletes = set(aid for aid, eid in working_set)

# ---------------------------------------------------------------------------
# Top summary: Total athletes + Athlete event totals (moved from bottom)
# ---------------------------------------------------------------------------

mc1, mc2 = st.columns([1, 3])
mc1.metric("Total Athletes", len(unique_athletes))

# ---------------------------------------------------------------------------
# Athlete event totals (was at the bottom of each gender tab)
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.caption("Athlete event totals")
    for gender_val, gender_label in [("M", "Boys"), ("F", "Girls")]:
        gender_roster = [
            a for a in roster_all
            if a["gender"] == gender_val and a["status"] == "active"
        ]
        summary_athletes = [
            a for a in gender_roster
            if athlete_counts.get(a["id"], 0) > 0
        ]
        if not summary_athletes:
            continue

        st.markdown(f"**{gender_label}**")
        # Display in columns for compactness
        cols = st.columns(min(len(summary_athletes), 4))
        for i, athlete in enumerate(sorted(
            summary_athletes,
            key=lambda a: -athlete_counts.get(a["id"], 0)
        )):
            aid = athlete["id"]
            cnt = athlete_counts.get(aid, 0)
            bar = "█" * cnt + "░" * (MAX_PER_ATHLETE - cnt)
            warning = " ⚠" if cnt >= MAX_PER_ATHLETE else ""
            cols[i % 4].caption(
                f"{athlete['first_name']} {athlete['last_name']}\n"
                f"{bar} {cnt}/{MAX_PER_ATHLETE}{warning}"
            )

# ---------------------------------------------------------------------------
# Lineup progress (with names)
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.caption("Lineup progress")
    for gender_val, gender_label in [("M", "Boys"), ("F", "Girls")]:
        gender_events_prog = [
            e for e in all_events
            if e["gender"] == gender_val
        ]
        event_counts = {}
        for aid, eid in working_set:
            a = roster_by_id.get(aid)
            if a and a["gender"] == gender_val:
                event_counts[eid] = event_counts.get(eid, 0) + 1

        total_slots = sum(max_for_event(e) for e in gender_events_prog)
        filled_slots = sum(event_counts.values())

        st.markdown(
            f"**{gender_label}** — {filled_slots}/{total_slots} slots"
        )

        row_size = 5
        for i in range(0, len(gender_events_prog), row_size):
            bcols = st.columns(row_size)
            for j, e in enumerate(gender_events_prog[i:i + row_size]):
                n = event_counts.get(e["id"], 0)
                mx = max_for_event(e)
                icon = "🟢" if n == mx else (
                    "🟡" if n > 0 else "🔴"
                )
                names = event_athletes.get(e["id"], [])
                names_str = ", ".join(sorted(names)) if names else "—"
                bcols[j].caption(f"{icon} **{e['name']}** {n}/{mx}")
                bcols[j].caption(f"  {names_str}")

st.divider()

# ---------------------------------------------------------------------------
# Event-by-event grid (collapsible)
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
            mx = max_for_event(event)
            is_relay = event["event_type"] == "relay"

            if is_relay:
                # Relays: show ALL active athletes, sorted by corresponding
                # individual event SB (e.g. 4x100 → 100m times)
                eligible_athletes = gender_roster
                sb_event_id = relay_sb_event_map.get(eid, eid)
            else:
                # Individual events: only show athletes assigned to this event
                eligible_athletes = [
                    a for a in gender_roster
                    if any(
                        ev["id"] == eid
                        for ev in all_event_assignments.get(a["id"], [])
                    )
                ]
                sb_event_id = eid

            if not eligible_athletes:
                continue

            event_selected = [
                aid for aid, e in working_set if e == eid
            ]
            count_label = f"{len(event_selected)}/{mx}"
            over_limit = len(event_selected) > mx

            header_color = "🔴" if over_limit else (
                "🟢" if len(event_selected) == mx else "⚪"
            )

            with st.expander(
                f"{header_color}  **{event['name']}** — {count_label} entered",
                expanded=len(event_selected) < mx
            ):
                if is_relay:
                    indiv_name = RELAY_TO_INDIVIDUAL.get(event["name"], "")
                    st.caption(f"Sorted by {indiv_name} season best")

                for athlete in sorted(
                    eligible_athletes,
                    key=lambda a: (
                        season_bests_map.get((a["id"], sb_event_id)) is None,
                        season_bests_map.get((a["id"], sb_event_id), "z")
                    )
                ):
                    aid = athlete["id"]
                    key = (aid, eid)
                    is_checked = key in working_set
                    sb = season_bests_map.get((aid, sb_event_id), "—")
                    total_events = athlete_counts.get(aid, 0)
                    at_limit = total_events >= MAX_PER_ATHLETE and not is_checked

                    sb_label = f"{indiv_name}: {sb}" if is_relay else f"SB: {sb}"
                    label = (
                        f"{athlete['last_name']}, {athlete['first_name']} "
                        f"· Gr. {athlete['grade']} · {sb_label}"
                    )
                    if total_events >= MAX_PER_ATHLETE:
                        label += f" ⚠ {total_events}/{MAX_PER_ATHLETE} events"

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
