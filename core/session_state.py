import streamlit as st

DEFAULTS = {
    "google_creds": None,

    # generate
    "generated_items": [],
    "generated_report": [],
    "mark_idx": set(),
    "form_result_generate": None,
    "export_init_generate": None,        # ✅ 新增，供 app.py 管理 export 全選旗標
    "_export_panel_rendered_generate": False,

    # import
    "imported_items": [],
    "imported_report": [],
    "imported_text": "",
    "form_result_import": None,
    "export_init_import": None,          # ✅ 新增
    "_export_panel_rendered_import": False,

    # scroll
    "current_section": None,
}

def init_session_state():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v
