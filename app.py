# app.py — 極簡主程式（已修正 Google 登入 UI）

import streamlit as st
import streamlit.components.v1 as components
import traceback

from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)
from ui.sidebar import render_sidebar
from ui.pages_generate import render_generate_tab
from ui.pages_import import render_import_tab

# ------------------------- Session State Init -------------------------
_SS_DEFAULTS = {
    "google_creds": None,
    "generated_items": [],
    "generated_items_df": None,
    "imported_items": [],
    "generated_report": [],
    "imported_report": [],
    "mark_idx": set(),
    "imported_text": "",
    "form_result_generate": None,
    "form_result_import": None,
    "export_init_generate": None,
    "export_init_import": None,
    "current_section": None,
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ------------------------- Page Config -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# ------------------------- OAuth Callback -------------------------
params = st.query_params
if oauth_is_configured() and "code" in params and not st.session_state.google_creds:
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list): code = code[0]
        if isinstance(state, list): state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state.google_creds = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        st.error("Google 登入失敗。請重新按『連接 Google（登入）』一次。")
        with st.expander("🔎 技術細節"):
            st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        st.stop()

# ------------------------- Sidebar：Google 登入 + 出題設定 -------------------------
# Google 登入區塊（固定在最上方）
st.sidebar.header("🟦 Google 連接")
if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth（需在 Secrets 中設定 google_oauth_client + APP_URL）")
else:
    if st.session_state.google_creds:
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google", key="btn_logout_google"):
            st.session_state.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())
        st.sidebar.caption("建議使用學校電郵登入，方便使用 Google Forms 與 Drive 分享")

st.sidebar.divider()

# 出題設定與 API 設定（由 sidebar.py 處理）
ctx = render_sidebar()

# ------------------------- 使用流程 + 隱私提醒 -------------------------
with st.expander("🧭 使用流程", expanded=True):
    st.markdown("""
**⚠️ 重要隱私提醒**  
教材內容會上傳至第三方 AI 服務，請避免上傳含學生個人資料的文件。

### 🪄 生成新題目
1. 左側欄登入 Google（可選，但推薦）  
2. 設定科目、難度、API  
3. 上載教材 → 重點段落標記 → 生成題目  
4. 檢視微調後匯出（Kahoot / Wayground / Google Forms）

### 📄 匯入現有題目
貼上題目 → AI 整理 → 核對 → 匯出

**💡 小提示**：數理科請開啟 **Vision 模式**。
""")

tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

with tab_generate:
    render_generate_tab(ctx)

with tab_import:
    render_import_tab(ctx)

# 清理 query params
if "code" in st.query_params:
    st.query_params.clear()
