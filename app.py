import streamlit as st
from ui.sidebar import render_sidebar
from session_state import init_session_state
from pages_generate import render_generate_tab
from pages_import import render_import_tab
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)

# ---------------- Init ----------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")
init_session_state()

# ---------------- OAuth callback ----------------
params = st.query_params
if oauth_is_configured() and "code" in params and not st.session_state.get("google_creds"):
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list): code = code[0]
        if isinstance(state, list): state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state["google_creds"] = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        st.error("Google 登入失敗，請重新嘗試")
        st.exception(e)
        st.stop()

# ---------------- Sidebar ----------------
ctx = render_sidebar()

st.sidebar.header("🟦 Google 連接")
if not oauth_is_configured():
    st.sidebar.warning("尚未設定 Google OAuth")
else:
    if st.session_state.get("google_creds"):
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google"):
            st.session_state["google_creds"] = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google", get_auth_url())

# ---------------- Tabs ----------------
tab_g, tab_i = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])
with tab_g:
    render_generate_tab(ctx)
with tab_i:
    render_import_tab(ctx)
