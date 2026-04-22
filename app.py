# =========================================================
# app.py (FINAL-FULL, modular, strict old-behavior)
# - 主入口：根目錄 app.py
# - Google OAuth callback + Google 連接區塊（在 sidebar 最上方）
# - 呼叫 ui/sidebar.py 建 ctx
# - Tabs 呼叫 ui/pages_generate.py, ui/pages_import.py
# =========================================================

import streamlit as st

from ui.sidebar import render_sidebar
from ui.pages_generate import render_generate_tab
from ui.pages_import import render_import_tab

from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
)


def _adapt_kwargs(fn, **kwargs):
    """Call fn with only supported kwargs (signature-safe)."""
    try:
        import inspect
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        filtered = {k: v for k, v in kwargs.items() if k in allowed}
        return fn(**filtered)
    except Exception:
        return fn(**kwargs)


# ------------------------- Session -------------------------
if "google_creds" not in st.session_state:
    st.session_state.google_creds = None


# ------------------------- OAuth callback -------------------------
params = st.query_params
if oauth_is_configured() and "code" in params and not st.session_state.google_creds:
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list):
            code = code[0]
        if isinstance(state, list):
            state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state.google_creds = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()
    except Exception:
        st.query_params.clear()


# ------------------------- Page -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")


# ------------------------- Google connect (sidebar top) -------------------------
st.sidebar.header("🟦 Google 連接（Google Forms / Google Drive / 電郵分享）")
if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth（Secrets: google_oauth_client + APP_URL）")
else:
    if st.session_state.google_creds:
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google", key="btn_logout_google"):
            st.session_state.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())
        st.sidebar.caption("提示：請以學校電郵登入，方便統一管理與分享。")

st.sidebar.divider()


# ------------------------- Sidebar ctx -------------------------
ctx = render_sidebar()


# ------------------------- Inject services (保持舊版介面) -------------------------
ctx.update({
    "generate_questions": lambda cfg, text, subject, level_code, question_count, **kw: _adapt_kwargs(
        generate_questions,
        cfg=cfg,
        text=text,
        subject=subject,
        level=level_code,
        question_count=question_count,
        fast_mode=kw.get("fast_mode", True),
        qtype=kw.get("qtype", "single"),
    ),
    "assist_import_questions": lambda cfg, raw, subject, **kw: _adapt_kwargs(
        assist_import_questions,
        cfg=cfg,
        raw_text=raw,
        subject=subject,
        fast_mode=kw.get("fast_mode", True),
    ),
    "parse_import_questions_locally": parse_import_questions_locally,
})


# ------------------------- Tabs -------------------------
tab1, tab2 = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])
with tab1:
    render_generate_tab(ctx)
with tab2:
    render_import_tab(ctx)
