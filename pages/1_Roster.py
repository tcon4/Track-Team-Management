"""Roster & Events page."""

import streamlit as st
import db
import shared

season_id = shared.setup()

year = st.session_state.current_year
sport = st.session_state.sport
school = db.get_school(st.session_state.school_id)
school_name = school["name"] if school else "—"

st.title("Roster")
st.caption(f"{year} {sport} — {school_name}")

gender_filter = st.radio("View", ["All", "Boys (M)", "Girls (F)"],
                         horizontal=True)
gender_map = {"All": None, "Boys (M)": "M", "Girls (F)": "F"}
selected_gender = gender_map[gender_filter]

roster = db.get_roster(season_id)
season_bests = db.get_season_bests(season_id) if sport == "XC" else {}
all_event_assignments = db.get_all_athlete_events(season_id) if sport == "Track" else {}

if selected_gender:
    roster = [a for a in roster if a["gender"] == selected_gender]

# Stats
stats = db.get_roster_stats(season_id)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total", stats["total"])
c2.metric("Active", stats["active"])
c3.metric("Injured", stats["injured"])
c4.metric("Inactive", stats["inactive"])

st.divider()

# ---------------------------------------------------------------------------
# Roster list
# ---------------------------------------------------------------------------

if not roster:
    st.info("No athletes on the roster yet. Use one of the options below to add athletes individually, import a CSV, or upload a tryout spreadsheet.")
else:
    for athlete in roster:
        aid = athlete["id"]
        sb = season_bests.get(aid, "—")
        gender_label = "Boys" if athlete["gender"] == "M" else "Girls"
        status = athlete["status"]
        status_icon = {"active": "\U0001f7e2", "injured": "\U0001f7e1",
                       "inactive": "\u26ab"}.get(status, "\u26aa")

        if sport == "Track":
            events = all_event_assignments.get(aid, [])
            event_str = ", ".join(e["name"] for e in events) if events else "—"
        else:
            event_str = sb

        col_name, col_edit = st.columns([5, 1])
        is_profile_open = st.session_state.get("profile_athlete") == aid
        with col_name:
            if st.button(
                f"**{athlete['last_name']}, {athlete['first_name']}**",
                key=f"profile_{aid}", use_container_width=True
            ):
                st.session_state.profile_athlete = None if is_profile_open else aid
                st.rerun()
            st.caption(f"Gr. {athlete['grade']} \u00b7 {gender_label} \u00b7 {status_icon}")

        is_editing = st.session_state.editing_athlete == aid
        btn_label = "\u2715" if is_editing else "Edit"
        if col_edit.button(btn_label, key=f"edit_{aid}"):
            st.session_state.editing_athlete = None if is_editing else aid
            st.rerun()

        # ---- Athlete profile panel ----
        if is_profile_open and sport == "Track":
            with st.container(border=True):
                profile = db.get_athlete_profile(aid, season_id)
                bests = profile["season_bests"]
                history = profile["history"]

                st.caption(
                    f"{athlete['first_name']} {athlete['last_name']} \u00b7 "
                    f"Gr. {athlete['grade']} \u00b7 {gender_label} \u00b7 "
                    f"{status_icon} {status.capitalize()}"
                )
                if event_str != "—":
                    st.caption(f"Events: {event_str}")

                if bests:
                    st.markdown("**Season bests**")
                    for ev, data in bests.items():
                        pr_flag = " \u2713 PR" if data["has_pr"] else ""
                        st.write(f"{ev}: **{data['result_value']}**{pr_flag}")
                else:
                    st.caption("No results recorded yet this season.")

                if history:
                    st.markdown("**Meet history**")
                    for h in history:
                        pr_flag = " \u2713 PR" if h["is_pr"] else ""
                        place_str = f" \u00b7 {shared.format_place(h['place'])}" if h["place"] else ""
                        st.caption(
                            f"{h['meet_date']} — {h['meet_name']} \u00b7 "
                            f"{h['event_name']} \u00b7 "
                            f"{h['result_value']}{place_str}{pr_flag}"
                        )

                if st.button("Close profile", key=f"close_profile_{aid}"):
                    st.session_state.profile_athlete = None
                    st.rerun()

        # ---- Inline edit panel ----
        if is_editing:
            with st.container(border=True):
                st.caption(f"Editing: {athlete['first_name']} {athlete['last_name']}")

                with st.form(f"edit_form_{aid}"):
                    ec1, ec2 = st.columns(2)
                    new_first = ec1.text_input("First name", value=athlete["first_name"])
                    new_last = ec2.text_input("Last name", value=athlete["last_name"])
                    ec3, ec4, ec5 = st.columns(3)
                    new_grade = ec3.selectbox("Grade", [6, 7, 8],
                                             index=[6, 7, 8].index(athlete["grade"]))
                    new_gender = ec4.selectbox("Gender", ["M", "F"],
                                              index=["M", "F"].index(athlete["gender"]))
                    new_status = ec5.selectbox(
                        "Status", ["active", "injured", "inactive"],
                        index=["active", "injured", "inactive"].index(athlete["status"])
                    )
                    s_col, c_col, r_col = st.columns(3)
                    save = s_col.form_submit_button("Save changes", type="primary")
                    cancel = c_col.form_submit_button("Cancel")
                    remove = r_col.form_submit_button("Remove from roster")

                if save:
                    db.update_athlete(aid, new_first, new_last,
                                      new_grade, new_gender, new_status)
                    st.session_state.editing_athlete = None
                    st.success(f"Saved {new_first} {new_last}.")
                    st.rerun()
                if cancel:
                    st.session_state.editing_athlete = None
                    st.rerun()
                if remove:
                    db.remove_from_roster(season_id, aid)
                    st.session_state.editing_athlete = None
                    st.success("Removed from roster.")
                    st.rerun()

                # Event assignment (Track only)
                if sport == "Track":
                    st.markdown("**Event assignments**")
                    all_events = db.get_track_events(gender=athlete["gender"])
                    current_events = db.get_athlete_events(aid, season_id)
                    current_ids = {e["id"] for e in current_events}

                    selected_ids = []
                    running = [e for e in all_events if e["event_type"] == "running"]
                    field = [e for e in all_events if e["event_type"] == "field"]
                    relay = [e for e in all_events if e["event_type"] == "relay"]

                    for section_label, section_events in [
                        ("Running", running), ("Field", field), ("Relays", relay)
                    ]:
                        if section_events:
                            st.caption(section_label)
                            ev_cols = st.columns(min(len(section_events), 4))
                            for i, ev in enumerate(section_events):
                                checked = ev_cols[i % 4].checkbox(
                                    ev["name"],
                                    value=ev["id"] in current_ids,
                                    key=f"ev_{aid}_{ev['id']}"
                                )
                                if checked:
                                    selected_ids.append(ev["id"])

                    if len(selected_ids) > 4:
                        st.warning(
                            f"4 events max per meet — you've selected {len(selected_ids)}. "
                            "Fine for season planning, just watch per-meet entries."
                        )

                    if st.button("Save event assignments", type="primary",
                                 key=f"save_ev_{aid}"):
                        db.set_athlete_events(aid, season_id, selected_ids)
                        st.success("Event assignments saved.")
                        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Add athlete manually
# ---------------------------------------------------------------------------

with st.expander("+ Add a single athlete"):
    with st.form("add_athlete_form", clear_on_submit=True):
        ac1, ac2 = st.columns(2)
        first = ac1.text_input("First name", placeholder="e.g. Jane")
        last = ac2.text_input("Last name", placeholder="e.g. Smith")
        ac3, ac4 = st.columns(2)
        grade = ac3.selectbox("Grade", [6, 7, 8])
        gender = ac4.selectbox("Gender", ["M", "F"],
                               format_func=lambda x: "Boys (M)" if x == "M" else "Girls (F)")
        submitted = st.form_submit_button("Add to roster", type="primary")

    if submitted:
        if not first.strip() or not last.strip():
            st.error("First and last name are required.")
        else:
            aid = db.add_athlete(first, last, grade, gender,
                                 st.session_state.school_id)
            db.add_to_roster(season_id, aid)
            st.success(f"Added {first} {last}.")
            st.rerun()

# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

with st.expander("\u2b06 Import from CSV file"):
    st.caption(
        "Your CSV needs columns: `first_name`, `last_name`, `grade`, `gender`. "
        "Other column names are fine too — see the template."
    )

    template = db.generate_csv_template()
    st.download_button(
        "Download CSV template",
        data=template,
        file_name="roster_template.csv",
        mime="text/csv",
    )

    uploaded = st.file_uploader("Upload roster CSV", type=["csv"])

    if uploaded:
        file_bytes = uploaded.read()
        rows, errors = db.parse_roster_csv(file_bytes)

        if errors:
            for e in errors:
                st.error(e)

        if rows:
            st.success(f"Preview: {len(rows)} athletes ready to import.")
            preview_data = [
                {
                    "First": r["first_name"],
                    "Last": r["last_name"],
                    "Grade": r["grade"],
                    "Gender": "Boys" if r["gender"] == "M" else "Girls",
                }
                for r in rows
            ]
            st.dataframe(preview_data, use_container_width=True, hide_index=True)
            st.session_state.csv_preview_rows = rows

    if st.session_state.csv_preview_rows:
        if st.button("Confirm import", type="primary"):
            result = db.import_roster_from_rows(
                st.session_state.csv_preview_rows,
                st.session_state.school_id,
                season_id,
            )
            st.session_state.csv_preview_rows = None
            st.success(
                f"Imported: {result['added']} added, "
                f"{result['skipped']} already existed."
            )
            st.rerun()

# ---------------------------------------------------------------------------
# Tryout spreadsheet import
# ---------------------------------------------------------------------------

with st.expander("\u2b06 Import from tryout spreadsheet (.xlsx)"):
    st.caption(
        "Upload your tryout spreadsheet. Tabs should be named by grade/gender "
        "(e.g. **6th Girls**, **7th Boys**). "
        "Cut athletes (y in Cut? column) are skipped entirely. "
        "Non-empty time columns auto-assign events and import as Tryouts meet results."
    )
    tryout_file = st.file_uploader("Upload tryout spreadsheet", type=["xlsx"],
                                   key="tryout_upload")
    if tryout_file:
        preview, errors = db.parse_tryout_spreadsheet(tryout_file.read())
        if errors:
            for e in errors:
                st.warning(e)
        if preview:
            added_count = len([r for r in preview if not r.get("cut")])
            cut_count = len([r for r in preview if r.get("cut")])
            result_count = sum(len(r.get("results", [])) for r in preview)
            st.success(
                f"Found **{added_count}** athletes to import \u00b7 "
                f"{cut_count} cuts skipped \u00b7 "
                f"{result_count} tryout results"
            )
            preview_rows = [
                {
                    "First": r["first_name"],
                    "Last": r["last_name"],
                    "Gr.": r["grade"],
                    "Gender": "Boys" if r["gender"] == "M" else "Girls",
                    "Events": ", ".join(r.get("events", [])) or "—",
                }
                for r in preview if not r.get("cut")
            ]
            st.dataframe(preview_rows, use_container_width=True, hide_index=True)
            st.session_state["tryout_preview"] = preview

    if st.session_state.get("tryout_preview"):
        if st.button("Import tryout data", type="primary"):
            result = db.import_tryout_data(
                st.session_state["tryout_preview"],
                st.session_state.school_id,
                season_id,
            )
            st.session_state["tryout_preview"] = None
            st.success(
                f"Imported {result['athletes']} athletes \u00b7 "
                f"{result['results']} tryout results \u00b7 "
                f"{result['assignments']} event assignments."
            )
            st.rerun()
