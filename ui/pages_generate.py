# ui/pages_generate.py

from __future__ import annotations
import streamlit as st

from extractors.extract import extract_payload
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from services.llm_service import generate_questions
from services.vision_service import vision_ocr_extract_text  # 新增：Vision OCR

DNL = chr(10) * 2

# =========================================================
# 清除工作區（換課題用）
# =========================================================

_GEN_KEYS = [
    "generated_items", "generated_report",
    "_gen_sig", "gen_mark_initialized", "mark_idx",
    "export_quiz_mode", "export_quiz_points", "export_quiz_show_exp",
    "form_result_generate", "_is_generating",
    "_gen_raw_text", "_gen_images",
]

def _clear_generate_state():
    for k in _GEN_KEYS:
        st.session_state.pop(k, None)
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and (
            k.startswith("gen_mark_") or k.startswith("editor_generate")
        ):
            st.session_state.pop(k, None)
    st.session_state["_gen_uploader_key"] = (
        st.session_state.get("_gen_uploader_key", 0) + 1
    )

# =========================================================
# Helpers
# =========================================================

def _split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split(DNL) if p.strip()]


def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]
    blocks = []
    if highlights:
        blocks.append("[Key Paragraphs]")
        blocks.extend(highlights)
    if others:
        blocks.append("[Other Content]")
        blocks.extend(others)
    text = DNL.join(blocks)
    return text[:limit] if limit else text


def _reset_highlight_state(paras_len: int):
    st.session_state["mark_idx"] = set(range(paras_len))
    for i in range(paras_len):
        st.session_state[f"gen_mark_{i}"] = True


def _clear_highlight_state(paras_len: int):
    st.session_state["mark_idx"] = set()
    for i in range(paras_len):
        st.session_state[f"gen_mark_{i}"] = False

# =========================================================
# Vision 模式警告
# =========================================================

_VISION_UNSUPPORTED_MODELS = {"deepseek-chat", "deepseek-reasoner"}

def _warn_if_vision_unsupported(ocr_mode: str, model: str):
    if ocr_mode.startswith("🤖") and model in _VISION_UNSUPPORTED_MODELS:
        st.warning(
            f"⚠️ 目前模型 `{model}` 不支援 Vision 讀圖。"
            "圖片將被忽略，只使用文字出題。\n\n"
            "如需 Vision 出題，請在「進階設定」切換至 **Grok** 或 **GPT-4o** 等支援 Vision 的模型。"
        )
        return True
    return False

# =========================================================
# Main render
# =========================================================

def render_generate_tab(ctx: dict):
    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    level_code = ctx["level_code"]
    question_count = ctx["question_count"]
    fast_mode = ctx.get("fast_mode", True)
    ocr_mode = ctx.get("ocr_mode", "📄 純文字（一般文件，最快）")
    vision_pdf_max_pages = int(ctx.get("vision_pdf_max_pages", 3) or 3)
    current_model = ctx.get("model", "deepseek-chat")

    # --------------------------------------------------
    # Header + 清除工作區
    # --------------------------------------------------
    col_title, col_clear = st.columns([5, 1])
    with col_title:
        st.markdown("## 1  上載教材")
    with col_clear:
        st.markdown("<div style='padding-top:0.6rem'></div>", unsafe_allow_html=True)
        if st.button(
            "🗑️ 清除工作區",
            key="btn_clear_workspace",
            help="換課題時點此清除上次的教材、題目及所有設定，重新開始。",
        ):
            _clear_generate_state()
            st.rerun()

    if st.session_state.get("generated_items"):
        st.info("💡 目前工作區有上次生成的題目。若要換課題，請先點「🗑️ 清除工作區」再上載新教材。")

    uploader_key = f"gen_source_file_{st.session_state.get('_gen_uploader_key', 0)}"

    file = st.file_uploader(
        "上載教材",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key=uploader_key,
    )

    raw_text = ""
    images = []
    prog = st.progress(0)
    status = st.empty()

    if file:
        status.info("⏳ 正在抽取教材內容...")
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
        images = payload.get("images", []) or ""

        # ── Vision OCR 預提取文字（新增）──
        vision_mode = ocr_mode.startswith("🤖")
        vision_unsupported = _warn_if_vision_unsupported(ocr_mode, current_model)
        if vision_mode and images and not vision_unsupported:
            with st.status("🤖 正在用 Vision 辨識圖片文字…", expanded=True) as vs:
                try:
                    ocr_text = vision_ocr_extract_text(
                        cfg=cfg,
                        image_data_urls=images,
                        lang_hint="zh-Hant" if subject not in {"英國語文", "English Language"} else "en"
                    )
                    if ocr_text.strip():
                        raw_text = (raw_text + "\n\n" + ocr_text).strip()
                        vs.update(label="✅ Vision 辨識完成", state="complete")
                    else:
                        vs.update(label="⚠️ Vision 未擷取到文字", state="complete")
                except Exception as e:
                    vs.update(label=f"❌ Vision 辨識失敗：{e}", state="error")

        # 快取供生成鎖使用
        st.session_state["_gen_raw_text"] = raw_text
        st.session_state["_gen_images"] = images

        prog.progress(25)

        limit = 8000 if fast_mode else 12000
        img_info = f"　｜　圖片：{len(images)} 頁" if images else ""
        st.caption(
            f"已擷取文字：{len(raw_text)} 字（上限約 {limit}；"
            f"{'快速' if fast_mode else '一般'}模式）{img_info}"
        )

        sig = f"{len(raw_text)}|{hash(raw_text)}|{len(images)}"
        if st.session_state.get("_gen_sig") != sig:
            st.session_state["_gen_sig"] = sig
            st.session_state.pop("gen_mark_initialized", None)
            st.session_state.pop("mark_idx", None)
            for k in list(st.session_state.keys()):
                if isinstance(k, str) and k.startswith("gen_mark_"):
                    st.session_state.pop(k, None)

        prog.progress(35)
        status.success("✅ 教材抽取完成")
        prog.progress(40)

    # --------------------------------------------------
    # Step 2: Highlight paragraphs
    # --------------------------------------------------
    st.markdown("## 2  標記重點段落（可選）")
    paras = _split_paragraphs(raw_text)

    with st.expander("📌 重點段落選擇（預設全選）", expanded=False):
        if paras and not st.session_state.get("gen_mark_initialized"):
            _reset_highlight_state(len(paras))
            st.session_state["gen_mark_initialized"] = True

        c1, c2, _ = st.columns([1, 1, 2])
        if c1.button("全選", key="btn_gen_mark_all"):
            _reset_highlight_state(len(paras))
            st.rerun()
        if c2.button("取消全選", key="btn_gen_mark_none"):
            _clear_highlight_state(len(paras))
            st.rerun()

        marked = set(st.session_state.get("mark_idx", set()))
        st.caption(f"已選 {len(marked)} / 共 {len(paras)} 段")

        for i, p in enumerate(paras):
            label = p.replace("\n", " ")
            label = (label[:160] + "...") if len(label) > 160 else label
            checked = bool(st.session_state.get(f"gen_mark_{i}", i in marked))
            if st.checkbox(label, value=checked, key=f"gen_mark_{i}"):
                marked.add(i)
            else:
                marked.discard(i)
        st.session_state["mark_idx"] = marked

    prog.progress(55)

    # --------------------------------------------------
    # Step 3: Generate（防重複生成鎖 + Vision 串接）
    # --------------------------------------------------
    st.markdown("## 3  生成題目")

    is_generating = st.session_state.get("_is_generating", False)

    if not can_call_ai(cfg):
        st.warning("請先在左側「進階設定」填入 API Key，或聯絡 IT 設定校內預設 Key。")

    # Vision 模式提示
    vision_mode = ocr_mode.startswith("🤖")
    vision_unsupported = _warn_if_vision_unsupported(ocr_mode, current_model)

    cached_images = st.session_state.get("_gen_images", [])
    if vision_mode and cached_images and not vision_unsupported:
        st.info(f"🤖 Vision 模式：已載入 {len(cached_images)} 頁圖片，將連同文字一起傳送給 AI 出題。")

    btn_disabled = (
        (not raw_text.strip() and not cached_images)
        or (not can_call_ai(cfg))
        or is_generating
    )

    if st.button(
        "⏳ 生成中，請稍候…" if is_generating else "✨ AI 生成題目",
        disabled=btn_disabled,
        key="btn_generate_questions",
    ):
        st.session_state["_is_generating"] = True
        st.rerun()

    # 生成鎖啟動後執行實際生成
    if st.session_state.get("_is_generating"):
        status.info("⏳ 正在準備出題資料...")
        prog.progress(60)

        # 從快取取得教材（rerun 後 file 已消失）
        cached_raw = st.session_state.get("_gen_raw_text", raw_text)
        cached_imgs = st.session_state.get("_gen_images", images)

        text_for_ai = _build_text_with_highlights(
            cached_raw, st.session_state.get("mark_idx", set()), 10000
        )
        prog.progress(70)

        # 決定是否傳入 images（Vision 模式且模型支援）
        images_for_ai = (
            cached_imgs
            if (vision_mode and cached_imgs and not vision_unsupported)
            else []
        )

        mode_label = "Vision 讀圖" if images_for_ai else "純文字"
        status.info(f"🤖 AI 出題中（{mode_label}，共 {question_count} 題），請勿重複按…")

        try:
            with st.spinner(f"AI 正在生成 {question_count} 題（{mode_label}模式），請稍候…"):
                data = generate_questions(
                    cfg=cfg,
                    text=text_for_ai,
                    subject=subject,
                    level=level_code,
                    question_count=question_count,
                    fast_mode=fast_mode,
                    images=images_for_ai,   # ← 串接 Vision images
                )
        finally:
            st.session_state["_is_generating"] = False

        prog.progress(90)
        status.info("🔍 正在整理輸出...")

        items = dicts_to_items(data, subject=subject, source="generate")
        report = validate_questions(items)
        st.session_state["generated_items"] = items
        st.session_state["generated_report"] = report

        prog.progress(100)

        total = len(items)
        needs_review = sum(1 for r in report if not r.get("ok"))
        if needs_review:
            status.warning(
                f"✅ 已生成 {total} 題　｜　⚠️ 有 {needs_review} 題需要教師檢查"
            )
        else:
            status.success(f"✅ 已生成 {total} 題，全部通過檢查")

        st.rerun()

    # --------------------------------------------------
    # Step 4: Editor
    # --------------------------------------------------
    if st.session_state.get("generated_items"):
        st.markdown("## 4  檢視與微調")
        df = items_to_editor_df(
            st.session_state["generated_items"],
            report=st.session_state.get("generated_report", []),
        )
        edited_df, selected_df = render_editor(df, key="editor_generate")
        edited_items = editor_df_to_items(
            edited_df, default_subject=subject, source="generate"
        )
        st.session_state["generated_items"] = edited_items
        st.session_state["generated_report"] = validate_questions(edited_items)

        # --------------------------------------------------
        # Step 5: Export
        # --------------------------------------------------
        st.markdown("## 5  匯出 / Google Form / 電郵分享")

        google_creds = st.session_state.get("google_creds")

        if google_creds:
            st.markdown("### Google Form 匯出設定")
            col1, col2 = st.columns(2)

            with col1:
                form_mode = st.radio(
                    "匯出模式",
                    ["測驗模式（Quiz）", "普通問卷（Survey）"],
                    index=0,
                    key="google_form_mode",
                    help=(
                        "測驗模式：含正確答案、評分及解釋說明，學生提交後可即時查閱成績。\n"
                        "普通問卷：只有題目和選項，不設答案評分。"
                    ),
                )
                quiz_mode = form_mode.startswith("測驗")

            with col2:
                if quiz_mode:
                    points = st.number_input(
                        "每題分數", min_value=1, max_value=10, value=1,
                        key="google_form_points",
                    )
                    show_exp = st.checkbox(
                        "答錯時顯示解釋",
                        value=True,
                        key="google_form_show_exp",
                        help="勾選後，學生答錯時會看到 AI 生成的解釋說明。",
                    )
                else:
                    points = 1
                    show_exp = False

            st.session_state["export_quiz_mode"] = quiz_mode
            st.session_state["export_quiz_points"] = points
            st.session_state["export_quiz_show_exp"] = show_exp

        render_export_panel(
            selected_df,
            subject,
            google_creds,
            prefix="generate",
        )