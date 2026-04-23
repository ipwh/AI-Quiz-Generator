import streamlit as st
from extractors.extract import extract_payload
from core.question_mapper import (
    dicts_to_items,
    items_to_editor_df,
    editor_df_to_items,
)
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from services.llm_service import (
    generate_questions,
    llm_ocr_extract_text,
)

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


def render_generate_tab(ctx: dict):
    st.markdown("## ① 上載教材")
    file = st.file_uploader("上載教材", type=["pdf","docx","txt","pptx","xlsx","png","jpg"])
    raw_text = ""
    images = []
    if file:
        payload = extract_payload(
            file,
            enable_ocr=(st.session_state.get("ocr_mode") == "🔬 本地 OCR（掃描 PDF/圖片，離線）"),
            enable_vision=(st.session_state.get("ocr_mode") == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）"),
            vision_pdf_max_pages=st.session_state.get("vision_pdf_max_pages",3),
        )
        raw_text = payload.get("text","")
        images = payload.get("images",[])

    st.markdown("## ② 標記重點段落（可選）")
    paras = _split_paragraphs(raw_text)
    for i,p in enumerate(paras):
        if st.checkbox(p[:120], key=f"mark_{i}"):
            st.session_state.mark_idx.add(i)

    st.markdown("## ③ 生成題目")
    if st.button("🪄 生成題目", disabled=not raw_text):
        with st.spinner("AI 出題中…"):
            text_for_ai = _build_text_with_highlights(raw_text, st.session_state.mark_idx, 9000)
            if images:
                data = llm_ocr_extract_text(
                    ctx["api_config"](),
                    text_for_ai,
                    images,
                    ctx["subject"],
                    ctx["level_code"],
                    ctx["question_count"],
                    fast_mode=ctx.get("fast_mode",True),
                )
            else:
                data = generate_questions(
                    ctx["api_config"](),
                    text_for_ai,
                    ctx["subject"],
                    ctx["level_code"],
                    ctx["question_count"],
                    fast_mode=ctx.get("fast_mode",True),
                )
            items = dicts_to_items(data, subject=ctx["subject"], source="generate")
            report = validate_questions(items)
            st.session_state.generated_items = items
            st.session_state.generated_report = report

    if st.session_state.get("generated_items"):
        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(st.session_state.generated_items, st.session_state.generated_report)
        edited, selected = render_editor(df, key="editor_generate")
        items2 = editor_df_to_items(edited, default_subject=ctx["subject"], source="generate")
        st.session_state.generated_items = items2
        st.session_state.generated_report = validate_questions(items2)

        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        render_export_panel(selected, ctx["subject"], st.session_state.get("google_creds"), prefix="generate")
