import streamlit as st

# ─────────────────────────────────────────────────────────────
# Robust imports（支援 root / package 兩種結構）
# ─────────────────────────────────────────────────────────────
try:
    from extractors.extract import extract_payload
except Exception:
    from extract import extract_payload

try:
    from core.question_mapper import (
        dicts_to_items,
        items_to_editor_df,
        editor_df_to_items,
    )
except Exception:
    from question_mapper import (
        dicts_to_items,
        items_to_editor_df,
        editor_df_to_items,
    )

try:
    from core.validators import validate_questions
except Exception:
    from validators import validate_questions

try:
    from ui.components_editor import render_editor
except Exception:
    from components_editor import render_editor

try:
    from ui.components_export import render_export_panel
except Exception:
    from components_export import render_export_panel

# ✅ 正確：你現有 llm_service.py 入面有嘅 function
try:
    from services.llm_service import (
        generate_questions,
        llm_ocr_extract_text_only,
    )
except Exception:
    from llm_service import (
        generate_questions,
        llm_ocr_extract_text_only,
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
    """生成新題目頁面（與 pages_import.py 對稱）"""

    # ctx helpers
    cfg = ctx["api_config``
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)

    # ─────────────────────────────────────────────────────────
    # ① 上載教材
    # ─────────────────────────────────────────────────────────
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG；可配合 OCR 或 Vision 讀圖。")

    file = st.file_uploader(
        "上載教材",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="gen_source_file",
    )

    raw_text = ""
    images = []

    if file:
        # Sidebar 使用 key="ocr_mode" 及 "vision_pdf_max_pages"
        ocr_mode = st.session_state.get("ocr_mode", "📄 純文字（一般文件，最快）")
        enable_ocr = (ocr_mode == "🔬 本地 OCR（掃描 PDF/圖片，離線）")
        enable_vision = (ocr_mode == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）")
        vision_pdf_max_pages = int(st.session_state.get("vision_pdf_max_pages", 3) or 3)

        payload = extract_payload(
            file,
            enable_ocr=enable_ocr,
            enable_vision=enable_vision,
            vision_pdf_max_pages=vision_pdf_max_pages,
        )
        raw_text = payload.get("text", "") or ""
        images = payload.get("images", []) or []

        if not raw_text.strip() and not images:
            st.warning("⚠️ 未能從檔案抽取到文字／圖片，請嘗試切換 OCR / Vision 模式。")

    # ─────────────────────────────────────────────────────────
    # ② 標記重點段落
    # ─────────────────────────────────────────────────────────
    st.markdown("## ② 標記重點段落（可選）")
    paras = _split_paragraphs(raw_text)

    marked = set()
    if paras:
        st.caption("勾選後，AI 會優先根據『重點段落』出題。")
        for i, p in enumerate(paras):
            label = p.replace("\n", " ")
            label = (label[:160] + "…") if len(label) > 160 else label
            if st.checkbox(label, key=f"gen_mark_{i}"):
                marked.add(i)
    else:
        st.info("提示：若教材是掃描件，請切換到『本地 OCR』或『LLM Vision』。")

    st.session_state.mark_idx = marked

    # ─────────────────────────────────────────────────────────
    # ③ 生成題目
    # ─────────────────────────────────────────────────────────
    st.markdown("## ③ 生成題目")

    if not can_call_ai(cfg):
        st.warning("⚠️ 請先在左側填妥 AI API 設定並測試連線。")

    disabled_generate = (not raw_text.strip() and not images) or (not can_call_ai(cfg))

    if st.button("🪄 生成題目", disabled=disabled_generate, key="btn_generate_questions"):
        with st.spinner("🧠 AI 出題中…"):
            text_for_ai = _build_text_with_highlights(
                raw_text,
                st.session_state.get("mark_idx", set()),
                10000,
            )

            # ✅ Vision / OCR：先抽文字，再交俾 generate_questions
            if images:
                ocr_text = llm_ocr_extract_text_only(
                    cfg=cfg,
                    images_data_urls=images,
                    fast_mode=fast_mode,
                )
                combined_text = (text_for_ai + DNL + ocr_text).strip()
            else:
                combined_text = text_for_ai

            data = generate_questions(
                cfg=cfg,
                text=combined_text,
                subject=subject,
                level=level_code,
                question_count=question_count,
                fast_mode=fast_mode,
            )

            items = dicts_to_items(data, subject=subject, source="generate")
            report = validate_questions(items)

            st.session_state.generated_items = items
            st.session_state.generated_report = report

    # ─────────────────────────────────────────────────────────
    # ④ 檢視與微調
    # ─────────────────────────────────────────────────────────
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

        # ─────────────────────────────────────────────────────────
        # ⑤ 匯出
        # ─────────────────────────────────────────────────────────
        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        render_export_panel(
            selected_df,
            subject,
            st.session_state.get("google_creds"),
            prefix="generate",
        )
