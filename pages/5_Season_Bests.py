"""Season Bests page."""

import streamlit as st
import db
import shared

season_id = shared.setup()

year = st.session_state.current_year
sport = st.session_state.sport
school = db.get_school(st.session_state.school_id)
school_name = school["name"] if school else "—"

st.header(f"{year} {sport} Season Bests — {school_name}")

if sport != "Track":
    st.info("XC season bests coming soon.")
    st.stop()

bests = db.get_season_bests_track(season_id)

if not bests:
    st.info("No results recorded yet. Enter some in the Results tab.")
    st.stop()

gender_tab_b, gender_tab_g = st.tabs(["Boys", "Girls"])

for gender_val, tab in [("M", gender_tab_b), ("F", gender_tab_g)]:
    with tab:
        filtered = [b for b in bests if b["gender"] == gender_val]
        if not filtered:
            st.info("No results yet.")
            continue

        events_seen = {}
        for b in filtered:
            events_seen.setdefault(b["event_name"], []).append(b)

        for event_name, event_bests in events_seen.items():
            st.subheader(event_name)
            st.dataframe(
                [{
                    "Athlete": f"{b['last_name']}, {b['first_name']}",
                    "Season best": b["season_best"],
                    "PR": "\u2713" if b.get("is_pr") else "",
                } for b in event_bests],
                use_container_width=True,
                hide_index=True,
            )
