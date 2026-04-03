"""
shared.py — Common sidebar, session state, and bootstrap logic.
Every page calls setup() at the top to get the sidebar and season_id.
"""

import streamlit as st
from datetime import date
import db


def setup() -> int:
    """
    Bootstrap the app: init DB, render sidebar, resolve season.
    Returns the current season_id.
    """
    st.set_page_config(
        page_title="Athletics",
        page_icon="\U0001f3c3",
        layout="wide",
    )

    db.init_db()

    # Session state defaults
    if "school_id" not in st.session_state:
        schools = db.get_schools()
        st.session_state.school_id = schools[0]["id"] if schools else None

    if "sport" not in st.session_state:
        st.session_state.sport = "Track"

    if "current_year" not in st.session_state:
        st.session_state.current_year = date.today().year

    for key in ("editing_athlete", "editing_meet", "profile_athlete",
                "ms_matched", "csv_preview_rows"):
        if key not in st.session_state:
            st.session_state[key] = None

    # Sidebar
    with st.sidebar:
        _sport_label = st.session_state.get("sport", "Athletics")
        st.title(f"🏃 {_sport_label} Manager")

        schools = db.get_schools()
        if not schools:
            st.error("No schools found in database. Check your database connection.")
            st.stop()
        school_names = [s["name"] for s in schools]
        selected_school_name = st.selectbox("School", school_names)
        school = next(s for s in schools if s["name"] == selected_school_name)
        st.session_state.school_id = school["id"]

        sport = st.radio("Sport", ["Track", "XC"], horizontal=True)
        st.session_state.sport = sport

        year = st.selectbox(
            "Season",
            options=list(range(date.today().year, date.today().year - 5, -1)),
        )
        st.session_state.current_year = year

        st.divider()

        with st.expander("Edit school name"):
            with st.form("school_form"):
                new_name = st.text_input("School name", value=school["name"])
                new_city = st.text_input("City", value=school["city"])
                if st.form_submit_button("Save"):
                    db.update_school(school["id"], new_name, new_city)
                    st.rerun()

    # Resolve season
    season_id = db.get_or_create_season(
        year=st.session_state.current_year,
        sport=st.session_state.sport,
        school_id=st.session_state.school_id,
    )

    return season_id


def format_place(place: int | None) -> str:
    """Format a place number as '1st', '2nd', '3rd', '4th', etc."""
    if place is None:
        return "\u2014"
    if place == 1:
        return "1st"
    if place == 2:
        return "2nd"
    if place == 3:
        return "3rd"
    return f"{place}th"
