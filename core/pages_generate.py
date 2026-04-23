import streamlit as st

# ============================================================
# 嚴格使用唯一正確的 import（純文字版本，確保 0 隱形字元）
# ============================================================
from extractors.extract import extract_payload
from core.question_mapper import (
    dicts_to_items,
    items_to_editor_df,
    editor_df_to_items,
)
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from services.llm_service import generate_questions


DNL = chr(10) * 2


def _split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split(DNL) if p.strip()]


def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]

    blocks = []
    if highlights:
        blocks.append("【重點段落】")
        blocks.extend(highlights)
    if others:
        blocks.append("【其餘內容】")
        blocks.extend(others)

    text = DNL.join(blocks)
    return text[:limit] if limit else text


# ============================================================
# Generate Page（最終穩定版，不含 Vision OCR）
# ============================================================

def render_generate_tab(ctx: dict):
    """生成新題目頁面（最終穩定版；避免所有隱形字元與不存在函數）"""


    # --------------------------------------------------------
    # ctx helpers（唯一正確寫法）
    # --------------------------------------------------------
    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)

    # --------------------------------------------------------
    # ① 上載教材
    # --------------------------------------------------------
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG")


    file = st.file_uploader(
        "上載教材",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="gen_source_file",
    )

    raw_text = ""

    if file:
        payload = extract_payload(file)
        raw_text = payload.get("text", "") or ""
        if not raw_text.strip():
            st.warning("⚠️ 未能從檔案抽取到文字內容。若為掃描件，請先轉成可選取文字的 PDF。")


    # --------------------------------------------------------
    # ② 標記重點段落（可選）
    # --------------------------------------------------------
    st.markdown("## ② 標記重點段落（可選）")

    paras = _split_paragraphs(raw_text)

    with st.expander("📌 展開／摺疊重點段落選擇", expanded=False):
        col_a, col_b = st.columns(2)
        if col_a.button("✅ 全選", key="gen_mark_all"):
            st.session_state.mark_idx = set(range(len(paras)))
        if col_b.button("❌ 取消全選", key="gen_mark_none"):
            st.session_state.mark_idx = set()

        marked = set(st.session_state.get("mark_idx", set()))

        for i, p in enumerate(paras):
            label = p.replace("\n", " ")
            if len(label) > 160:
                label = label[:160] + "…"
            if st.checkbox(label, value=(i in marked), key=f"gen_mark_{i}"):
                marked.add(i)
            else:
                marked.discard(i)

        st.session_state.mark_idx = marked

    # --------------------------------------------------------
    # ③ 生成題目
    # --------------------------------------------------------
    st.markdown("## ③ 生成題目")

    if not can_call_ai(cfg):
        st.warning("⚠️ 請先在左側填妥 AI API 設定並測試連線。")

    disabled_generate = (not raw_text.strip()) or (not can_call_ai(cfg))


    if st.button("🪄 生成題目", disabled=disabled_generate, key="btn_generate_questions"):
        with st.spinner("🧠 AI 出題中…"):
            text_for_ai = _build_text_with_highlights(
                raw_text,
                st.session_state.get("mark_idx", set()),
                10000,
            )

            data = generate_questions(
                cfg=cfg,
                text=text_for_ai,
                subject=subject,
                level=level_code,
                question_count=question_count,
                fast_mode=fast_mode,
            )

            items = dicts_to_items(data, subject=subject, source="generate")
            report = validate_questions(items)

            st.session_state.generated_items = items
            st.session_state.generated_report = report

    # --------------------------------------------------------
    # ④ 檢視與微調
    # --------------------------------------------------------
    if st.session_state.get("generated_items"):
        st.markdown("## ④ 檢視與微調")

        report = st.session_state.get("generated_report", [])
        df = items_to_editor_df(st.session_state.generated_items, report=report)

        edited_df, selected_df = render_editor(df, key="editor_generate")

        edited_items = editor_df_to_items(
            edited_df,
            default_subject=subject,
            source="generate",
        )

        st.session_state.generated_items = edited_items
        st.session_state.generated_report = validate_questions(edited_items)

        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        render_export_panel(
            selected_df,
            subject,
            st.session_state.get("google_creds"),
            prefix="generate",
        )
