"""
app.py — XC / Track Athletics App
Run with: streamlit run app.py

This is the landing page. Navigation pages are in the pages/ directory.
"""

import shared

season_id = shared.setup()

import streamlit as st

st.markdown(
    "Select a page from the sidebar to get started: "
    "**Roster**, **Schedule**, **Lineup Builder**, **Results**, or **Season Bests**."
)
