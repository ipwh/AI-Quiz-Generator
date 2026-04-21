import streamlit as st
from extractors.extract import extract_text
from core.question_mapper import dicts_to_items, items_to_editor_df
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel


def render_import_tab(ctx: dict):
    st.markdown("## ① 上載 / 貼上題目")
    st.caption("支援 DOCX / TXT 或直接貼上。匯入模式固定為單選（4 選 1）。")

    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]
    subject = ctx["subject"]
    fast_mode = ctx.get("fast_mode", True)

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None: return
        st.session_state.imported_text = extract_text(f) or ""

    st.file_uploader(
        "上載 DOCX / TXT（自動載入到文字框）",
        type=["docx", "txt"],
        key="import_file",
        on_change=load_import_file_to_textbox,
    )

    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True, key="use_ai_assist")
    st.text_area("貼上題目內容", height=320, key="imported_text")

    st.markdown("## ② 整理並轉換")
    import_has_text = bool(st.session_state.get("imported_text", "").strip())
    import_can_run = import_has_text and (not use_ai_assist or can_call_ai(cfg))

    if st.button("✨ 整理並轉換", disabled=not import_can_run, key="btn_import_parse"):
        raw = st.session_state.get("imported_text", "").strip()
        try:
            with st.spinner("🧠 正在整理…"):
                from services.llm_service import assist_import_questions, parse_import_questions_locally
                if use_ai_assist:
                    data = assist_import_questions(cfg, raw, subject, allow_guess=True, fast_mode=fast_mode)
                else:
                    data = parse_import_questions_locally(raw)

            items = dicts_to_items(data, subject=subject, source="import")
            report = validate_questions(items)
            st.session_state.imported_items = items
            st.session_state.imported_report = report
            st.session_state.pop("export_init_import", None)
            st.success(f"✅ 已整理 {len(items)} 題")
        except Exception as e:
            st.warning("⚠️ AI 整理失敗，已改用本地拆題，請老師核對答案。")
            data = parse_import_questions_locally(raw)
            items = dicts_to_items(data, subject=subject, source="local")
            report = validate_questions(items)
            st.session_state.imported_items = items
            st.session_state.imported_report = report
            st.exception(e)

    if st.session_state.get("imported_items"):
        report = st.session_state.get("imported_report", [])
        bad_count = len([x for x in report if not x.get("ok")])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查")

        st.markdown("## ③ 檢視與微調")
        df = items_to_editor_df(st.session_state.imported_items, report=report)

        if "export_init_import" not in st.session_state:
            df["export"] = True
            st.session_state.export_init_import = True

        edited, selected = render_editor(df, key="editor_import")

        st.markdown('<div id="export_anchor_import"></div>', unsafe_allow_html=True)
        render_export_panel(selected, subject, st.session_state.get("google_creds"), prefix="import")
