# =================================================
# Imports
# =================================================
import io
import hashlib
import traceback
import streamlit as st
import pandas as pd

from core.question_mapper import dicts_to_items, items_to_editor_df
from extractors.extract import extract_text
from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
)
from services.cache_service import load_cache, save_cache
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    credentials_from_dict,
)
from services.google_forms_api import create_quiz_form

from exporters.export_kahoot import export_kahoot_excel
from exporters.export_wayground_docx import export_wayground_docx


# =================================================
# Session state init (一次就夠)
# =================================================
if "generated_items" not in st.session_state:
    st.session_state.generated_items = []

if "imported_items" not in st.session_state:
    st.session_state.imported_items = []

if "form_result_generate" not in st.session_state:
    st.session_state.form_result_generate = None

if "form_result_import" not in st.session_state:
    st.session_state.form_result_import = None

if "mark_idx" not in st.session_state:
    st.session_state.mark_idx = set()


# =================================================
# Helpers
# =================================================
def show_exception(user_msg: str, e: Exception):
    st.error(user_msg)
    with st.expander("🔎 技術細節（供維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


def build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]

    parts = []
    if highlights:
        parts.append("【重點段落】")
        parts.append("\n\n".join(highlights))
    parts.append("【其餘內容】")
    parts.append("\n\n".join(others))

    return "\n\n".join(parts)[:limit]


def api_config():
    return {
        "type": "openai_compat",
        "api_key": st.session_state.get("api_key", ""),
        "base_url": st.session_state.get("base_url", ""),
        "model": st.session_state.get("model", ""),
    }


def can_call_ai(cfg: dict):
    return bool(cfg.get("api_key")) and bool(cfg.get("base_url")) and bool(cfg.get("model"))


# =================================================
# Export & Share Panel（唯一匯出入口）
# =================================================
def export_and_share_panel(selected_df: pd.DataFrame, subject_name: str, prefix: str):
    if selected_df is None or selected_df.empty:
        st.info("請先在上方表格勾選要匯出的題目。")
        return

    st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")

    # -------- Kahoot Excel --------
    kahoot_bytes = export_kahoot_excel(selected_df)
    st.download_button(
        "⬇️ Kahoot Excel",
        kahoot_bytes,
        file_name="kahoot.xlsx",
        key=f"dl_kahoot_{prefix}",
    )

    # -------- Wayground DOCX --------
    docx_bytes = export_wayground_docx(selected_df, subject_name)
    st.download_button(
        "⬇️ Wayground DOCX",
        docx_bytes,
        file_name="wayground.docx",
        key=f"dl_wayground_{prefix}",
    )

    # -------- Google Form --------
    if oauth_is_configured() and st.session_state.get("google_creds"):
        if st.button("🟦 一鍵建立 Google Form Quiz", key=f"btn_form_{prefix}"):
            try:
                with st.spinner("🟦 正在建立 Google Form…"):
                    creds = credentials_from_dict(st.session_state.google_creds)
                    result = create_quiz_form(
                        creds,
                        f"{subject_name} Quiz",
                        selected_df,
                    )
                st.session_state[f"form_result_{prefix}"] = result
                st.success("✅ 已建立 Google Form")
            except Exception as e:
                show_exception("⚠️ 建立 Google Form 失敗。", e)

        result = st.session_state.get(f"form_result_{prefix}")
        if result:
            st.write("編輯連結：", result.get("editUrl"))
            st.write("發佈連結：", result.get("responderUrl"))


# =================================================
# Page config
# =================================================
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器（最終穩定版）")


# =================================================
# Sidebar: API 設定（簡化示例）
# =================================================
st.sidebar.header("🔌 AI API 設定")
st.session_state.api_key = st.sidebar.text_input("API Key", type="password")
st.session_state.base_url = st.sidebar.text_input("Base URL", value="https://api.deepseek.com/v1")
st.session_state.model = st.sidebar.text_input("Model", value="deepseek-chat")

fast_mode = st.sidebar.checkbox("⚡ 快速模式", value=True)

subject = st.sidebar.selectbox(
    "科目",
    ["中國歷史", "歷史", "公民與社會發展", "地理", "經濟", "ICT"],
)

question_count = st.sidebar.selectbox("題目數目", [5, 8, 10, 12], index=2)


# =================================================
# Tabs
# =================================================
tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])


# =================================================
# Tab 1: Generate
# =================================================
with tab_generate:
    st.markdown("## ① 上載教材")

    reset_generation = st.checkbox(
        "🧹 清除上一輪生成記憶（切換課題時建議勾選）",
        value=False,
    )

    files = st.file_uploader(
        "上載教材檔案",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt"],
    )

    raw_text = ""
    if files:
        with st.spinner("📄 正在擷取文字…"):
            raw_text = "".join(extract_text(f) for f in files)
        st.info(f"✅ 已擷取 {len(raw_text)} 字")

    st.markdown("## ③ 生成題目")

    cfg = api_config()
    limit = 8000 if fast_mode else 10000

    if st.button(
        "🪄 生成題目",
        disabled=not (can_call_ai(cfg) and raw_text.strip()),
    ):
        try:
            if reset_generation:
                st.session_state.generated_items = []
                save_cache({})

            used_text = build_text_with_highlights(raw_text, st.session_state.mark_idx, limit)

            with st.spinner("🤖 正在生成…"):
                data = generate_questions(
                    cfg,
                    used_text,
                    subject,
                    "medium",
                    question_count,
                    fast_mode=fast_mode,
                    qtype="single",
                )

            st.session_state.generated_items = dicts_to_items(
                data,
                subject=subject,
                source="generate",
            )
            st.success(f"✅ 成功生成 {len(st.session_state.generated_items)} 題")

        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)

    if st.session_state.generated_items:
        items = st.session_state.generated_items

        st.markdown("## ✅ 題目品質摘要")
        review_count = sum(1 for q in items if q.needs_review)
        st.metric("✅ 通過題目", len(items) - review_count)
        st.metric("⚠️ 需教師留意", review_count)

        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(items)

        edited = st.data_editor(
            df,
            width="stretch",
            num_rows="dynamic",
            key="editor_generate",
        )

        selected = edited[edited["export"] == True].copy()
        export_and_share_panel(selected, subject, prefix="generate")


# =================================================
# Tab 2: Import
# =================================================
with tab_import:
    st.markdown("## ① 匯入現有題目")

    import_text = st.text_area("貼上題目內容", height=300)

    use_ai_assist = st.checkbox(
        "🤖（可選）啟用 AI 協助整理",
        value=True,
    )

    st.markdown("## ② 整理並轉換")

    if st.button("✨ 整理並轉換", disabled=not import_text.strip()):
        try:
            cfg = api_config()
            with st.spinner("🧠 正在整理題目…"):
                if use_ai_assist and can_call_ai(cfg):
                    data = assist_import_questions(
                        cfg,
                        import_text,
                        subject,
                        fast_mode=fast_mode,
                        qtype="single",
                    )
                else:
                    data = parse_import_questions_locally(import_text)

            st.session_state.imported_items = dicts_to_items(
                data,
                subject=subject,
                source="import",
            )
            st.success(f"✅ 成功整理 {len(st.session_state.imported_items)} 題")

        except Exception as e:
            show_exception("⚠️ 整理並轉換失敗。", e)

    if st.session_state.imported_items:
        items = st.session_state.imported_items

        st.markdown("## ✅ 題目品質摘要")
        review_count = sum(1 for q in items if q.needs_review)
        st.metric("✅ 通過題目", len(items) - review_count)
        st.metric("⚠️ 需教師留意", review_count)

        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(items)

        edited = st.data_editor(
            df,
            width="stretch",
            num_rows="dynamic",
            key="editor_import",
        )

        selected = edited[edited["export"] == True].copy()
        export_and_share_panel(selected, subject, prefix="import")
