# =========================================================
# app.py — 修正後可執行版
# ✅ 修正 Vision import 錯誤
# ✅ 加入 Vision 能力判斷與安全 fallback
# ✅ 匯入（Import）流程完整可用
# =========================================================

import io
import traceback
import streamlit as st
import pandas as pd

# ---------------------------------------------------------
# ✅ Vision 服務（穩定版）
# ---------------------------------------------------------
# 注意：vision_service 只在「真正需要 Vision」時使用
from services.vision_service import vision_generate_questions, file_to_data_url, supports_vision

# ---------------------------------------------------------
# ✅ 核心 LLM 服務（純文字）
# ---------------------------------------------------------
from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
)

from core.question_mapper import dicts_to_items, items_to_editor_df
from services.cache_service import save_cache

# ---------------------------------------------------------
# Page Config
# ---------------------------------------------------------

st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def show_exception(user_msg, e):
    st.error(user_msg)
    with st.expander("🔎 技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def build_text_with_highlights(raw_text, marked_idx, limit):
    if not raw_text:
        return ""
    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    highlighted = [p for i, p in enumerate(paragraphs) if i in marked_idx]
    others = [p for i, p in enumerate(paragraphs) if i not in marked_idx]

    combined = []
    if highlighted:
        combined.append("【重點段落】")
        combined.extend(highlighted)
    if others:
        combined.append("【其餘內容】")
        combined.extend(others)

    final_text = "\n\n".join(combined)
    if limit and len(final_text) > limit:
        final_text = final_text[:limit]
    return final_text

# ---------------------------------------------------------
# Sidebar — API Settings
# ---------------------------------------------------------

st.sidebar.header("🔌 AI API 設定")

preset = st.sidebar.selectbox(
    "快速選擇",
    ["DeepSeek", "OpenAI", "Grok (xAI)", "自訂（OpenAI 相容）"],
)

api_key = st.sidebar.text_input("API Key", type="password")

if preset == "DeepSeek":
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
elif preset == "OpenAI":
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
elif preset == "Grok (xAI)":
    base_url = "https://api.x.ai/v1"
    model = "grok-4-latest"
else:
    base_url = st.sidebar.text_input("Base URL（含 /v1）", value="")
    model = st.sidebar.text_input("Model", value="")

cfg = {
    "type": "openai_compat",
    "api_key": api_key,
    "base_url": base_url,
    "model": model,
}

# ---------------------------------------------------------
# API 測試
# ---------------------------------------------------------

st.sidebar.divider()
if st.sidebar.button("🧪 測試 API"):
    if not api_key or not base_url or not model:
        st.sidebar.error("請先填妥 API Key / Base URL / Model")
    else:
        r = ping_llm(cfg)
        if r.get("ok"):
            st.sidebar.success("✅ API 正常")
        else:
            st.sidebar.error("❌ API 失敗")
            st.sidebar.code(r.get("error"))

# ---------------------------------------------------------
# OCR / Vision 模式
# ---------------------------------------------------------

st.sidebar.header("🔬 教材擷取模式")
ocr_mode = st.sidebar.radio(
    "",
    [
        "📄 純文字",
        "🤖 LLM Vision 讀圖（圖表／方程式）",
    ],
)

if ocr_mode.startswith("🤖"):
    st.sidebar.info("💡 Vision 僅支援 GPT‑4o / Grok。DeepSeek 將自動 fallback。")

# ---------------------------------------------------------
# 出題設定
# ---------------------------------------------------------

subject = st.sidebar.selectbox("科目", ["中國語文", "數學", "科學", "經濟", "歷史"]) 
level = st.sidebar.selectbox("難度", ["easy", "medium", "hard", "mixed"])
question_count = st.sidebar.selectbox("題目數目", [5, 8, 10, 15, 20])

# ---------------------------------------------------------
# Tabs
# ---------------------------------------------------------

tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# =========================================================
# Tab 1: Generate
# =========================================================

with tab_generate:
    uploaded_files = st.file_uploader(
        "上載教材（圖片 / PDF / TXT）",
        accept_multiple_files=True,
    )

    raw_text = st.text_area("或直接貼上教材內容")

    if st.button("🪄 生成題目"):
        try:
            if ocr_mode.startswith("🤖") and uploaded_files and supports_vision(cfg):
                image_urls = [file_to_data_url(f.read(), f.name) for f in uploaded_files]
                items = vision_generate_questions(
                    cfg,
                    raw_text,
                    image_urls,
                    subject,
                    level,
                    question_count,
                )
            else:
                # ✅ 純文字 fallback（包括 DeepSeek）
                items = generate_questions(
                    cfg,
                    raw_text,
                    subject,
                    level,
                    question_count,
                )

            st.success("✅ 題目生成完成")

            for i, q in enumerate(items, start=1):
                needs_review = bool(q.get("needs_review"))
                title = f"第 {i} 題"
            
                if needs_review:
                    with st.expander(f"⚠️ {title}（需要教師確認）", expanded=True):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        opts = q.get('options', [])
                        for idx, opt in enumerate(opts, start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**建議答案：** {','.join(q.get('correct', []))}")
                        reason = q.get('explanation') or "此題涉及關鍵條件／推論，建議教師覆核。"
                        st.warning(f"需要確認原因：{reason}")
                else:
                    with st.expander(title, expanded=False):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        opts = q.get('options', [])
                        for idx, opt in enumerate(opts, start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**答案：** {','.join(q.get('correct', []))}")


        except Exception as e:
            show_exception("題目生成失敗", e)

# =========================================================
# Tab 2: Import
# =========================================================

with tab_import:
    imported_text = st.text_area("貼上現有題目")
    use_ai = st.checkbox("使用 AI 協助整理", value=True)

    if st.button("✨ 整理並轉換"):
        try:
            if use_ai:
                items = assist_import_questions(cfg, imported_text, subject)
            else:
                items = parse_import_questions_locally(imported_text)

            st.success("✅ 題目生成完成")

            for i, q in enumerate(items, start=1):
                needs_review = bool(q.get("needs_review"))
                title = f"第 {i} 題"
            
                if needs_review:
                    with st.expander(f"⚠️ {title}（需要教師確認）", expanded=True):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        opts = q.get('options', [])
                        for idx, opt in enumerate(opts, start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**建議答案：** {','.join(q.get('correct', []))}")
                        reason = q.get('explanation') or "此題涉及關鍵條件／推論，建議教師覆核。"
                        st.warning(f"需要確認原因：{reason}")
                else:
                    with st.expander(title, expanded=False):
                        st.markdown(f"**題目：** {q.get('question','')}")
                        opts = q.get('options', [])
                        for idx, opt in enumerate(opts, start=1):
                            st.markdown(f"{idx}. {opt}")
                        st.markdown(f"**答案：** {','.join(q.get('correct', []))}")


        except Exception as e:
            show_exception("匯入題目失敗", e)
