import streamlit as st

DEFAULTS = {
    "google_creds": None,

    # generate
    "generated_items": [],
    "generated_report": [],
    "mark_idx": set(),
    "form_result_generate": None,

    # import
    "imported_items": [],
    "imported_report": [],
    "imported_text": "",
    "form_result_import": None,
}


def init_session_state():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v