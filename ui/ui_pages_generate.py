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

from services.llm_service import generate_questions

# Vision OCR（安全：若函數不存在，會自動停用 Vision OCR）
try:
    from services.llm_service import llm_ocr_extract_text_only
except Exception:
    llm_ocr_extract_text_only = None

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


def _sync_mark_checkboxes(paras_len: int, value: bool):
    # 將所有 checkbox 的 state 同步（Streamlit checkbox 用 key 儲存 state）
    for i in range(paras_len):
        st.session_state[f"gen_mark_{i}"] = value


def render_generate_tab(ctx: dict):
    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)

    ocr_mode = st.session_state.get("ocr_mode", "📄 純文字（一般文件，最快）")
    vision_pdf_max_pages = int(st.session_state.get("vision_pdf_max_pages", 3) or 3)

    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG；可選 Vision OCR。")

    file = st.file_uploader(
        "上載教材",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="gen_source_file",
    )

    raw_text = ""
    images = []

    if file:
        # 安全呼叫：舊版 extract_payload 可能不支援 enable_vision / vision_pdf_max_pages
        try:
            payload = extract_payload(
                file,
                enable_ocr=(ocr_mode == "🔬 本地 OCR（掃描 PDF/圖片，離線）"),
                enable_vision=(ocr_mode == "🤖 Vision OCR（先讀圖抽字，再用文字出題）"),
                vision_pdf_max_pages=vision_pdf_max_pages,
            )
        except TypeError:
            payload = extract_payload(file)

        raw_text = (payload.get("text", "") or "")
        images = payload.get("images", []) or []

        if ocr_mode.startswith("🤖") and llm_ocr_extract_text_only is None:
            st.warning("⚠️ 此版本未提供 llm_ocr_extract_text_only，已自動改用純文字模式。")
            images = []

    st.markdown("## ② 標記重點段落（可選）")

    paras = _split_paragraphs(raw_text)
    sig = f"{len(paras)}|{hash(raw_text)}"

    # 初次 / 教材變更：預設全選
    if st.session_state.get("gen_paras_sig") != sig:
        st.session_state.gen_paras_sig = sig
        st.session_state.mark_idx = set(range(len(paras)))
        _sync_mark_checkboxes(len(paras), True)

    with st.expander("📌 重點段落選擇（預設全選）", expanded=False):
        c1, c2, c3 = st.columns([1, 1, 2])
        if c1.button("✅ 全選", key="gen_mark_all"):
            st.session_state.mark_idx = set(range(len(paras)))
            _sync_mark_checkboxes(len(paras), True)
            st.rerun()
        if c2.button("❌ 取消全選", key="gen_mark_none"):
            st.session_state.mark_idx = set()
            _sync_mark_checkboxes(len(paras), False)
            st.rerun()

        st.caption(f"已選 {len(st.session_state.get('mark_idx', set()))} / 共 {len(paras)} 段")

        marked = set(st.session_state.get("mark_idx", set()))
        for i, p in enumerate(paras):
            label = p.replace("\n", " ")
            if len(label) > 160:
                label = label[:160] + "…"
            # 不傳 value；完全由 session_state key 控制
            checked = st.checkbox(label, key=f"gen_mark_{i}")
            if checked:
                marked.add(i)
            else:
                marked.discard(i)
        st.session_state.mark_idx = marked

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

            # Vision OCR：先抽字，再用文字出題（安全退化）
            if images and llm_ocr_extract_text_only is not None:
                try:
                    ocr_text = llm_ocr_extract_text_only(
                        cfg=cfg,
                        images_data_urls=images,
                        fast_mode=fast_mode,
                    )
                except Exception:
                    ocr_text = ""
                combined_text = (text_for_ai + DNL + (ocr_text or "")).strip()
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
