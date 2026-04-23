import streamlit as st
from extractors.extract import extract_payload, extract_images_for_llm_ocr
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from services.llm_service import generate_questions
import requests

DNL = chr(10) * 2

# ---------- helpers ----------
def _split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split(DNL) if p.strip()]


def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]
    blocks = []
    if highlights:
        blocks.append("[FOCUS]")
        blocks.extend(highlights)
    if others:
        blocks.append("[OTHER]")
        blocks.extend(others)
    text = DNL.join(blocks)
    return text[:limit] if limit else text


def _vision_ocr_text(cfg: dict, images_data_urls: list, fast_mode: bool = True) -> str:
    """Best‑effort Vision OCR. Returns empty string on any failure."""
    if not images_data_urls or not isinstance(cfg, dict):
        return ""
    prompt = (
        "你是一個 OCR 文字抽取器。請從圖片中抽取所有可辨識文字，只輸出純文字。\n"
        "- 不要解釋、不要總結、不要加入推測\n"
        "- 盡量保留段落與換行\n"
    )
    content = [{"type": "text", "text": prompt}]
    for url in images_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
    temperature = 0.0
    max_tokens = 1200 if fast_mode else 2000
    timeout = 90 if fast_mode else 140
    try:
        if cfg.get("type") == "azure":
            endpoint = (cfg.get("endpoint") or "").rstrip("/")
            deployment = cfg.get("deployment")
            api_version = cfg.get("api_version") or "2024-02-15-preview"
            if not endpoint or not deployment:
                return ""
            url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
            headers = {"api-key": cfg.get("api_key", ""), "Content-Type": "application/json"}
            payload = {"messages": [{"role": "user", "content": content}], "temperature": temperature, "max_tokens": max_tokens}
        else:
            base_url = (cfg.get("base_url") or "").rstrip("/")
            model = cfg.get("model")
            if not base_url or not model:
                return ""
            url = f"{base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {cfg.get('api_key','')}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": temperature, "max_tokens": max_tokens}
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        out = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content", "")
        return (out or "").strip()
    except Exception:
        return ""


# ---------- page ----------
def render_generate_tab(ctx: dict):
    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)
    ocr_mode = ctx.get("ocr_mode")
    vision_pdf_max_pages = int(ctx.get("vision_pdf_max_pages", 3))

    # Cache control
    st.markdown("## ⚙️ 工具")
    if st.button("🧹 清除本頁快取（切換教材/科目前建議）"):
        for k in ["generated_items", "generated_report", "mark_idx", "gen_mark_initialized"]:
            st.session_state.pop(k, None)
        st.success("已清除本頁快取")
        st.rerun()

    # Upload
    st.markdown("## ① 上載教材")
    file = st.file_uploader("上載教材", type=["pdf","docx","txt","pptx","xlsx","png","jpg","jpeg"], key="gen_source_file")
    raw_text, images = "", []

    if file:
        try:
            payload = extract_payload(file, enable_ocr=(ocr_mode=="🔬 本地 OCR（掃描 PDF/圖片，離線）"), enable_vision=(ocr_mode=="🤖 Vision OCR（把圖片轉文字，較準）"), vision_pdf_max_pages=vision_pdf_max_pages)
        except TypeError:
            payload = extract_payload(file)
        raw_text = payload.get("text", "") or ""
        images = payload.get("images", []) or []
        if ocr_mode == "🤖 Vision OCR（把圖片轉文字，較準）" and not images:
            try:
                images = extract_images_for_llm_ocr(file, pdf_max_pages=vision_pdf_max_pages)
            except Exception:
                images = []

        # text length hint
        limit = 8000 if fast_mode else 12000
        st.info(f"已擷取文字約 {len(raw_text)} 字；系統上限 {limit} 字（{'快速' if fast_mode else '一般'}模式）")

    # Highlight
    st.markdown("## ② 標記重點段落（可選）")
    paras = _split_paragraphs(raw_text)
    with st.expander("📌 重點段落選擇（預設全選）", expanded=False):
        if paras and not st.session_state.get("gen_mark_initialized"):
            st.session_state["mark_idx"] = set(range(len(paras)))
            st.session_state["gen_mark_initialized"] = True
        col1, col2 = st.columns(2)
        if col1.button("✅ 全選"):
            st.session_state["mark_idx"] = set(range(len(paras)))
            st.rerun()
        if col2.button("❌ 取消全選"):
            st.session_state["mark_idx"] = set()
            st.rerun()
        marked = set(st.session_state.get("mark_idx", set()))
        st.caption(f"已選 {len(marked)} / 共 {len(paras)} 段")
        for i, p in enumerate(paras):
            label = p.replace("\n"," ")[:160]
            if st.checkbox(label, value=(i in marked), key=f"gen_mark_{i}"):
                marked.add(i)
            else:
                marked.discard(i)
        st.session_state["mark_idx"] = marked

    # Generate
    st.markdown("## ③ 生成題目")
    if not can_call_ai(cfg):
        st.warning("請先在左側填妥 AI API 設定並測試連線。")
    disabled = (not raw_text.strip() and not images) or (not can_call_ai(cfg))
    if st.button("🪄 生成題目", disabled=disabled):
        with st.spinner("出題中…"):
            text_for_ai = _build_text_with_highlights(raw_text, st.session_state.get("mark_idx", set()), 10000)
            if ocr_mode == "🤖 Vision OCR（把圖片轉文字，較準）" and images:
                ocr_text = _vision_ocr_text(cfg, images, fast_mode)
                if ocr_text:
                    text_for_ai = (text_for_ai + DNL + ocr_text).strip()
            data = generate_questions(cfg=cfg, text=text_for_ai, subject=subject, level=level_code, question_count=question_count, fast_mode=fast_mode)
            items = dicts_to_items(data, subject=subject, source="generate")
            report = validate_questions(items)
            st.session_state["generated_items"] = items
            st.session_state["generated_report"] = report

    # Review & export
    if st.session_state.get("generated_items"):
        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(st.session_state["generated_items"], report=st.session_state.get("generated_report", []))
        edited_df, selected_df = render_editor(df, key="editor_generate")
        edited_items = editor_df_to_items(edited_df, default_subject=subject, source="generate")
        st.session_state["generated_items"] = edited_items
        st.session_state["generated_report"] = validate_questions(edited_items)
        st.markdown("## ⑤ 匯出")
        render_export_panel(selected_df, subject, st.session_state.get("google_creds"), prefix="generate")
