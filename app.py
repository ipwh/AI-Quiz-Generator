import streamlit as st

# ─────────────────────────────────────────────────────────────
# Robust imports (support both "root files" and "package folders")
# ─────────────────────────────────────────────────────────────
try:
    from session_state import init_session_state  # root/session_state.py
except Exception:
    try:
        from core.session_state import init_session_state  # core/session_state.py
    except Exception:
        def init_session_state():
            # 最小備援（避免因 init 失敗而整個 app 起唔到）
            defaults = {
                "google_creds": None,
                "generated_items": [],
                "generated_report": [],
                "mark_idx": set(),
                "form_result_generate": None,
                "_export_panel_rendered_generate": False,
                "imported_items": [],
                "imported_report": [],
                "imported_text": "",
                "form_result_import": None,
                "_export_panel_rendered_import": False,
                "current_section": None,
            }
            for k, v in defaults.items():
                if k not in st.session_state:
                    st.session_state[k] = v

try:
    from sidebar import render_sidebar  # root/sidebar.py
except Exception:
    from ui.sidebar import render_sidebar  # ui/sidebar.py

try:
    from pages_generate import render_generate_tab
except Exception:
    from ui.pages_generate import render_generate_tab

try:
    from pages_import import render_import_tab
except Exception:
    from ui.pages_import import render_import_tab

from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)

# ─────────────────────────────────────────────────────────────
# Page init
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")
init_session_state()

# ─────────────────────────────────────────────────────────────
# OAuth callback (Google)
# ─────────────────────────────────────────────────────────────
params = st.query_params
if oauth_is_configured() and "code" in params and not st.session_state.get("google_creds"):
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list):
            code = code[0]
        if isinstance(state, list):
            state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state["google_creds"] = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        st.error("Google 登入失敗。請重新按『連接 Google（登入）』一次。")
        st.exception(e)
        st.stop()

# ─────────────────────────────────────────────────────────────
# Sidebar (AI settings) + Google connect
# ─────────────────────────────────────────────────────────────
ctx = render_sidebar()

st.sidebar.header("🟦 Google 連接（Forms / Drive 分享）")
if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth（Secrets: google_oauth_client + APP_URL）")
else:
    if st.session_state.get("google_creds"):
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google", key="btn_logout_google"):
            st.session_state["google_creds"] = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())

# ─────────────────────────────────────────────────────────────
# Main tabs
# ─────────────────────────────────────────────────────────────
tab_g, tab_i = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])
with tab_g:
    render_generate_tab(ctx)
with tab_i:
    render_import_tab(ctx)
