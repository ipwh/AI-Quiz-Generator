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
    except ValueError as e:
        st.sidebar.error(f"❌ OAuth 認證失敗：無效的狀態參數。詳情：{str(e)}")
        st.query_params.clear()
    except KeyError as e:
        st.sidebar.error(f"❌ OAuth 認證失敗：缺少必要參數 {str(e)}")
        st.query_params.clear()
    except Exception as e:
        st.sidebar.error(f"❌ Google 連接錯誤：{str(e)[:100]}")
        st.query_params.clear()


# ------------------------- Page -------------------------
st.set_page_config(page_title="AI 多項選擇題題目生成器", layout="wide")
st.title("🏫 AI 多項選擇題題目生成器，支援Kahoot / Wayground / Google Forms / 一鍵分享檔案")

with st.expander("👣 使用流程", expanded=True):
    st.markdown("""
1. **（可選）連接 Google**：左側最上方點「🔐 連接 Google（登入）」，之後可一鍵建立 Google Forms／Drive 分享／電郵分享。
2. **設定 AI（必需）**：學校已預設使用DeepSeek，無需設定即可開始。老師亦可在自行選擇其他LLM並輸入 AI API Key。
3. **選科目與難度**：選擇科目、題目難度、題目數量及題目困難程度。
4. **上載教材**：到「🪄 生成新題目」上載 PDF/DOCX/PPTX/圖片等；掃描件可在左側選「本地 OCR」或「Vision OCR」。
5. **（可選）標記重點段落**：展開「重點段落選擇」，保留想出的部分；預設已全選。
6. **生成與微調**：按「🪄 生成題目」，完成後可在表格內改題幹／選項／答案，再勾選要匯出的題目。
7. **匯出／分享**：選 Kahoot、Wayground、Google Forms 或下載檔案；已連接 Google 的話可直接建立表單並分享。
""")



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
        st.sidebar.caption("提示：請以學校電郵登入，以建立Google Forms及分享檔案。")

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
