import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
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
        with st.expander("技術細節"):
            st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
        st.stop()

# ------------------------- Sidebar -------------------------
ctx = render_sidebar()   # 回傳包含 fast_mode, api_config, can_call_ai, subject 等資訊的 dict

# ------------------------- 使用流程 + 隱私提醒 -------------------------
with st.expander("🧭 使用流程", expanded=True):
    st.markdown("""
**⚠️ 重要隱私提醒**  
教材內容會上傳至第三方 AI 服務（OpenAI / xAI / DeepSeek 等），  
**請勿上傳含有學生個人資料、敏感資訊或受版權嚴格保護的完整教材。**

### 🪄 生成新題目
1. 左側欄設定科目、難度、題目數目與 API  
2. **① 上載教材**（支援 Vision 讀圖）  
3. **② 重點段落標記**（可選，提高貼題度）  
4. 按「🪄 生成題目」  
5. 檢視與微調（特別留意 `⚠️ 需教師確認` 的題目）  
6. 勾選匯出 → 一鍵匯出 Kahoot / Wayground / Google Forms / 電郵分享

### 📄 匯入現有題目
1. 貼上或上載題目  
2. 可開啟 AI 協助整理  
3. 整理後核對答案與驗證報告  
4. 勾選匯出

**💡 小提示**：數理科強烈建議開啟 **Vision 模式**；重要測驗請關閉快速模式。
""")

tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# ========================= Tab 1: Generate =========================
with tab_generate:
    render_generate_tab(ctx)

# ========================= Tab 2: Import =========================
with tab_import:
    render_import_tab(ctx)

# 保留 Google 登入成功後的 rerender 處理
if st.session_state.get("google_creds") and "code" in st.query_params:
    st.query_params.clear()
    st.rerun()
