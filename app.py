# =========================================================
# app.py
# ✅ 完整最終版（單一檔案）
# ✅ 已補回：完整科目清單 + 教學難度 UI + Fast Mode
# ✅ 已整合：Google 登入、Generate / Import、Vision、needs_review 高亮
# ✅ 相容：乾淨重寫版 llm_service.py
# ---------------------------------------------------------
# 使用方式：直接以此檔案完整覆蓋你的 app.py，然後重啟 Streamlit
# =========================================================

import streamlit as st
import traceback

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
)
from services.vision_service import (
    vision_generate_questions,
    file_to_data_url,
    supports_vision,
)
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
)

# =========================================================
# Page config
# =========================================================

st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# =========================================================
# Session state
# =========================================================

if "google_creds" not in st.session_state:
    st.session_state.google_creds = None

# =========================================================
# Helper
# =========================================================

def show_exception(msg, e):
    st.error(msg)
    with st.expander("技術細節"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

# =========================================================
# Google OAuth callback
# =========================================================

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
        show_exception("Google 登入失敗", e)
        st.stop()

# =========================================================
# Sidebar — Google Login
# =========================================================

st.sidebar.header("🟦 Google 連接（Google Forms / Drive）")
if not oauth_is_configured():
    st.sidebar.warning("尚未設定 Google OAuth secrets")
else:
    if st.session_state.google_creds:
        st.sidebar.success("✅ 已登入 Google")
        if st.sidebar.button("🔒 登出 Google"):
            st.session_state.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 登入 Google", get_auth_url())

st.sidebar.divider()

# =========================================================
# Sidebar — Fast Mode
# =========================================================

fast_mode = st.sidebar.checkbox(
    "⚡ 快速模式",
    value=True,
    help="較快、較保守輸出；適合日常出題。關閉後題目更豐富。",
)

st.sidebar.divider()

# =========================================================
# Sidebar — AI API 設定
# =========================================================

st.sidebar.header("🔌 AI API 設定")
preset = st.sidebar.selectbox("API 類型", ["DeepSeek", "OpenAI", "Grok", "自訂"])
api_key = st.sidebar.text_input("API Key", type="password")

if preset == "DeepSeek":
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
elif preset == "OpenAI":
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
elif preset == "Grok":
    base_url = "https://api.x.ai/v1"
    model = "grok-4-latest"
else:
    base_url = st.sidebar.text_input("Base URL", value="")
    model = st.sidebar.text_input("Model", value="")

cfg = {
    "api_key": api_key,
    "base_url": base_url,
    "model": model,
}

if st.sidebar.button("🧪 測試 API"):
    r = ping_llm(cfg)
    if r.get("ok"):
        st.sidebar.success("API 正常")
    else:
        st.sidebar.error("API 失敗")
        st.sidebar.code(r.get("error"))

# =========================================================
# Sidebar — 教學設定（完整回歸）
# =========================================================

st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox(
    "科目",
    [
        "中國語文", "英國語文", "數學", "公民與社會發展",
        "科學", "公民、經濟及社會",
        "物理", "化學", "生物", "地理",
        "歷史", "中國歷史", "宗教",
        "資訊及通訊科技（ICT）", "經濟",
        "企業、會計與財務概論", "旅遊與款待",
    ],
)

level_label = st.sidebar.radio(
    "🎯 難度",
    [
        "基礎（理解與記憶）",
        "標準（應用與理解）",
        "進階（分析與思考）",
        "混合（課堂活動建議）",
    ],
    index=1,
)

level_map = {
    "基礎（理解與記憶）": "easy",
    "標準（應用與理解）": "medium",
    "進階（分析與思考）": "hard",
    "混合（課堂活動建議）": "mixed",
}
level = level_map[level_label]

question_count = st.sidebar.selectbox("題目數目", [5, 8, 10, 12, 15, 20], index=2)

st.sidebar.header("🔬 OCR / Vision")
ocr_mode = st.sidebar.radio("教材擷取模式", ["純文字", "Vision"], index=0)

# =========================================================
# Tabs
# =========================================================

tab_gen, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# =========================================================
# Tab 1 — Generate
# =========================================================

with tab_gen:
    text = st.text_area("貼上教材內容")
    images = st.file_uploader("（可選）圖片", type=["png", "jpg"], accept_multiple_files=True)

    if st.button("生成題目"):
        try:
            if ocr_mode == "Vision" and images and supports_vision(cfg):
                image_urls = [file_to_data_url(f.read(), f.name) for f in images]
                items = vision_generate_questions(
                    cfg, text, image_urls, subject, level, question_count, fast_mode=fast_mode
                )
            else:
                items = generate_questions(
                    cfg, text, subject, level, question_count, fast_mode=fast_mode
                )

            st.success("✅ 題目生成完成")

            for i, q in enumerate(items, start=1):
                needs_review = bool(q.get("needs_review"))
                title = f"第 {i} 題"

                if needs_review:
                    with st.expander(f"⚠️ {title}（需要教師確認）", expanded=True):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        for idx, opt in enumerate(q.get('options', []), start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**建議答案：** {','.join(q.get('correct', []))}")
                        reason = q.get('explanation') or "此題涉及關鍵條件／推論，建議教師覆核。"
                        st.warning(f"需要確認原因：{reason}")
                else:
                    with st.expander(title, expanded=False):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        for idx, opt in enumerate(q.get('options', []), start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**答案：** {','.join(q.get('correct', []))}")
        except Exception as e:
            show_exception("生成失敗", e)

# =========================================================
# Tab 2 — Import
# =========================================================

with tab_import:
    raw = st.text_area("貼上現有題目")
    use_ai = st.checkbox("使用 AI 整理", value=True)

    if st.button("整理並轉換"):
        try:
            if use_ai:
                items = assist_import_questions(cfg, raw, subject)
            else:
                items = parse_import_questions_locally(raw)

            st.success("✅ 題目整理完成")

            for i, q in enumerate(items, start=1):
                needs_review = bool(q.get("needs_review"))
                title = f"第 {i} 題"

                if needs_review:
                    with st.expander(f"⚠️ {title}（需要教師確認）", expanded=True):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        for idx, opt in enumerate(q.get('options', []), start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**建議答案：** {','.join(q.get('correct', []))}")
                        reason = q.get('explanation') or "此題涉及關鍵條件／推論，建議教師覆核。"
                        st.warning(f"需要確認原因：{reason}")
                else:
                    with st.expander(title, expanded=False):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        for idx, opt in enumerate(q.get('options', []), start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**答案：** {','.join(q.get('correct', []))}")
        except Exception as e:
            show_exception("匯入失敗", e)
