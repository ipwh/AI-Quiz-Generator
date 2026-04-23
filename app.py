import streamlit as st

# ============================================================
# App entry (single source of truth, ASCII-only)
# ============================================================

# Session state init (root or core)
try:
    from session_state import init_session_state
except Exception:
    from core.session_state import init_session_state

# Sidebar settings renderer
from ui.sidebar import render_sidebar

# Pages (single source)
from ui.pages_generate import render_generate_tab
from ui.pages_import import render_import_tab

# Google OAuth helpers
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)

# ------------------------------------------------------------
# Page init
# ------------------------------------------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")
init_session_state()

# ------------------------------------------------------------
# OAuth callback (Google)
# ------------------------------------------------------------
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
        st.error("Google 登入失敗，請重新嘗試。")
        st.exception(e)
        st.stop()

# ------------------------------------------------------------
# Sidebar (Google login ALWAYS at top)
# ------------------------------------------------------------
st.sidebar.header("🟦 Google 連接（Forms / Drive 分享）")
if not oauth_is_configured():
    st.sidebar.warning("尚未設定 Google OAuth（Secrets: google_oauth_client + APP_URL）")
else:
    if st.session_state.get("google_creds"):
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google", key="btn_logout_google"):
            st.session_state["google_creds"] = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())

# ------------------------------------------------------------
# Sidebar (AI / subject settings BELOW Google login)
# ------------------------------------------------------------
ctx = render_sidebar()

# ------------------------------------------------------------
# Main tabs
# ------------------------------------------------------------
tab_g, tab_i = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])
with tab_g:
    render_generate_tab(ctx)
with tab_i:
    render_import_tab(ctx)
