import streamlit as st
from extractors.extract import extract_payload
from core.question_mapper import dicts_to_items, items_to_editor_df
from services.cache_service import save_cache
from ui.components_editor import render_editor
from ui.components_export import render_export_panel


def build_text_with_highlights(raw_text: str, marked_idx: set, limit: int) -> str:
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
    return final_text[:limit] if limit else final_text


def render_generate_tab(ctx: dict):
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG；數理科建議使用 Vision 模式。")

    cfg = ctx["api_config"]()
    fast_mode = ctx.get("fast_mode", True)
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]

    reset_generation = st.checkbox("🧹 清除上一輪生成記憶（切換課題時建議勾選）", value=False)

    files = st.file_uploader(
        "上載教材檔案（可多檔）",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="files_generate",
    )

    raw_text = ""
    vision_images = []

    if files:
        use_local_ocr = st.session_state.get("ocr_mode") == "🔬 本地 OCR（掃描 PDF/圖片，離線）"
        use_vision = st.session_state.get("ocr_mode") == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）"
        vision_max_pages = st.session_state.get("vision_pdf_max_pages", 3)

        with st.spinner("📄 正在擷取教材…"):
            for f in files:
                payload = extract_payload(
                    f,
                    enable_ocr=use_local_ocr,
                    enable_vision=use_vision,
                    vision_pdf_max_pages=vision_max_pages,
                )
                if payload.get("text"):
                    raw_text += payload["text"] + "\n\n"
                if payload.get("images"):
                    vision_images.extend(payload["images"])
        raw_text = raw_text.strip()

        c1, c2 = st.columns(2)
        with c1: st.info(f"✅ 已擷取 {len(raw_text)} 字")
        with c2:
            if vision_images:
                st.success(f"🖼️ 已讀取 {len(vision_images)} 張圖像")

        if use_vision and vision_images:
            with st.expander("🖼️ 預覽已讀取圖像（前 3 張）"):
                for i, img in enumerate(vision_images[:3]):
                    st.image(img, caption=f"第 {i+1} 張", use_container_width=True)

    # 重點段落標記
    st.markdown("## ② 重點段落標記（可選）")
    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    with st.expander("⭐ 打開段落清單（最多顯示 80 段）"):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ 全選重點段落", key="mark_all_btn"):
                st.session_state.mark_idx = set(range(len(paragraphs)))
        with c2:
            if st.button("⛔ 全不選", key="mark_none_btn"):
                st.session_state.mark_idx = set()

        for i, p in enumerate(paragraphs[:80]):
            checked = i in st.session_state.mark_idx
            new_checked = st.checkbox(f"第 {i+1} 段", value=checked, key=f"para_{i}")
            if new_checked:
                st.session_state.mark_idx.add(i)
            else:
                st.session_state.mark_idx.discard(i)
            st.write(p[:200] + ("…" if len(p) > 200 else ""))

    # 生成按鈕
    st.markdown("## ③ 生成題目")
    limit = 8000 if fast_mode else 10000
    can_generate = bool(raw_text.strip() or vision_images) and ctx["can_call_ai"](cfg)

    if st.button("🪄 生成題目", disabled=not can_generate, key="btn_generate"):
        try:
            if reset_generation:
                st.session_state.generated_items = []
                save_cache({})

            used_text = build_text_with_highlights(raw_text, st.session_state.mark_idx, limit)

            with st.spinner("🤖 正在生成題目（約需 10–40 秒）…"):
                vision_used = False
                from services.llm_service import llm_ocr_extract_text, generate_questions

                if vision_images and st.session_state.get("ocr_mode") == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）":
                    try:
                        data = llm_ocr_extract_text(
                            cfg, used_text, vision_images, subject, level_code, question_count, fast_mode
                        )
                        vision_used = True
                    except Exception:
                        st.warning("⚠️ Vision 模式執行失敗，已自動回退至純文字模式。")
                        data = generate_questions(cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode)
                else:
                    data = generate_questions(cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode)

                if st.session_state.get("ocr_mode") == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）" and not vision_used:
                    st.info(
                        "ℹ️ **Vision 模式已回退至純文字出題**\n\n"
                        "原因：目前模型不支援圖像輸入（例如 DeepSeek）或處理失敗。\n"
                        "建議改用 Grok 或 GPT-4o 系列模型以獲得最佳圖表/方程式辨識效果。"
                    )

            st.session_state.generated_items = dicts_to_items(data, subject=subject, source="generate")
            st.session_state.pop("export_init_generate", None)
            st.success(f"✅ 成功生成 {len(st.session_state.generated_items)} 題")

        except Exception as e:
            st.error("⚠️ 生成題目失敗。")
            with st.expander("技術細節"):
                st.code(traceback.format_exc())

    # 檢視與微調 + 匯出
    if st.session_state.get("generated_items"):
        from core.validators import validate_questions
        items = st.session_state.generated_items
        report = validate_questions(items)

        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(items, report=report)
        if "export_init_generate" not in st.session_state:
            df["export"] = True
            st.session_state.export_init_generate = True

        edited, selected = render_editor(df, key="editor_generate")

        # 更新 session state
        st.session_state.generated_items = edited  # 這裡可再轉回 items，若需要

        st.markdown('<div id="export_anchor_generate"></div>', unsafe_allow_html=True)
        render_export_panel(selected, subject, st.session_state.get("google_creds"), prefix="generate")
