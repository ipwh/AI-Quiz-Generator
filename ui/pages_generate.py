import streamlit as st

from extractors.extract import extract_payload
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
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


def _reset_highlight_state(paras_len: int):
    st.session_state["mark_idx"] = set(range(paras_len))
    # also reset checkbox widget states so UI updates immediately
    for i in range(paras_len):
        st.session_state[f"gen_mark_{i}"] = True


def _clear_highlight_state(paras_len: int):
    st.session_state["mark_idx"] = set()
    for i in range(paras_len):
        st.session_state[f"gen_mark_{i}"] = False


def render_generate_tab(ctx: dict):
    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)

    ocr_mode = ctx.get("ocr_mode", "📄 純文字（一般文件，最快）")
    vision_pdf_max_pages = int(ctx.get("vision_pdf_max_pages", 3) or 3)

    st.markdown("## ① 上載教材")

    file = st.file_uploader(
        "上載教材",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="gen_source_file",
    )

    raw_text = ""
    images = []

    # progress UI
    prog = st.progress(0)
    status = st.empty()

    if file:
        status.info("正在抽取教材內容…")
        prog.progress(10)

        try:
            payload = extract_payload(
                file,
                enable_ocr=(ocr_mode.startswith("🔬")),
                enable_vision=(ocr_mode.startswith("🤖")),
                vision_pdf_max_pages=vision_pdf_max_pages,
            )
        except TypeError:
            payload = extract_payload(file)

        raw_text = payload.get("text", "") or ""
        images = payload.get("images", []) or []

        prog.progress(25)

        # show extract length and limit by fast_mode
        limit = 8000 if fast_mode else 12000
        st.caption(f"已擷取文字：{len(raw_text)} 字（上限約 {limit}；{'快速' if fast_mode else '一般'}模式）")

        # reset highlight state when content changes
        sig = f"{len(raw_text)}|{hash(raw_text)}|{len(images)}"
        if st.session_state.get("_gen_sig") != sig:
            st.session_state["_gen_sig"] = sig
            st.session_state.pop("gen_mark_initialized", None)
            st.session_state.pop("mark_idx", None)
            # clear old checkbox keys to prevent pollution
            for k in list(st.session_state.keys()):
                if isinstance(k, str) and k.startswith("gen_mark_"):
                    st.session_state.pop(k, None)

        prog.progress(35)
        status.success("教材抽取完成")

    prog.progress(40)

    # ② Highlight
    st.markdown("## ② 標記重點段落（可選）")
    paras = _split_paragraphs(raw_text)

    with st.expander("📌 重點段落選擇（預設全選）", expanded=False):
        if paras and not st.session_state.get("gen_mark_initialized"):
            _reset_highlight_state(len(paras))
            st.session_state["gen_mark_initialized"] = True

        c1, c2, c3 = st.columns([1, 1, 2])
        if c1.button("✅ 全選", key="btn_gen_mark_all"):
            _reset_highlight_state(len(paras))
            st.rerun()
        if c2.button("❌ 取消全選", key="btn_gen_mark_none"):
            _clear_highlight_state(len(paras))
            st.rerun()

        marked = set(st.session_state.get("mark_idx", set()))
        st.caption(f"已選 {len(marked)} / 共 {len(paras)} 段")

        for i, p in enumerate(paras):
            label = p.replace("\n", " ")
            label = (label[:160] + "…") if len(label) > 160 else label
            checked = bool(st.session_state.get(f"gen_mark_{i}", i in marked))
            if st.checkbox(label, value=checked, key=f"gen_mark_{i}"):
                marked.add(i)
            else:
                marked.discard(i)
        st.session_state["mark_idx"] = marked

    prog.progress(55)

    # ③ Generate
    st.markdown("## ③ 生成題目")

    if not can_call_ai(cfg):
        st.warning("⚠️ 請先在左側輸入 API Key。")

    disabled = (not raw_text.strip() and not images) or (not can_call_ai(cfg))

    if st.button("🪄 生成題目", disabled=disabled, key="btn_generate_questions"):
        # show progress bar during generation
        status.info("正在準備出題資料…")
        prog.progress(60)

        text_for_ai = _build_text_with_highlights(raw_text, st.session_state.get("mark_idx", set()), 10000)
        prog.progress(70)

        status.info("🧠 AI 出題中…")
        with st.spinner("AI 出題中…"):
            data = generate_questions(
                cfg=cfg,
                text=text_for_ai,
                subject=subject,
                level=level_code,
                question_count=question_count,
                fast_mode=fast_mode,
            )
        prog.progress(90)

        status.info("正在檢查題目格式…")
        items = dicts_to_items(data, subject=subject, source="generate")
        report = validate_questions(items)
        st.session_state["generated_items"] = items
        st.session_state["generated_report"] = report

        prog.progress(100)
        status.success("✅ 已完成")

    # ④ Editor + export
    if st.session_state.get("generated_items"):
        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(st.session_state["generated_items"], report=st.session_state.get("generated_report", []))
        edited_df, selected_df = render_editor(df, key="editor_generate")
        edited_items = editor_df_to_items(edited_df, default_subject=subject, source="generate")
        st.session_state["generated_items"] = edited_items
        st.session_state["generated_report"] = validate_questions(edited_items)

        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        render_export_panel(selected_df, subject, st.session_state.get("google_creds"), prefix="generate")
