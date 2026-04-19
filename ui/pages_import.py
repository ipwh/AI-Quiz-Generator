import streamlit as st
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items, items_to_export_df
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from extractors.extract import extract_text


def render_import_tab(ctx: dict):
    st.markdown("## ① 上載 / 貼上題目")
    cfg = ctx"api_config"
    can_call_ai = ctx["can_call_ai"]

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""
        st.session_state.imported_items = []
        st.session_state.imported_report = []

    st.file_uploader(
        "上載 DOCX/TXT（自動載入到文字框）",
        type=["docx", "txt"],
        key="import_file",
        on_change=load_import_file_to_textbox,
    )

    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True, key="use_ai_assist")
    st.text_area("貼上題目內容", height=320, key="imported_text")

    st.markdown("## ② 整理並轉換")
    if st.button(
        "✨ 整理並轉換",
        disabled=not (bool(st.session_state.imported_text.strip()) and (not use_ai_assist or can_call_ai(cfg))),
        key="btn_import_parse",
    ):
        raw = st.session_state.imported_text.strip()
        try:
            with st.spinner("🧠 正在整理…"):
                if use_ai_assist:
                    data = ctxcfg,
                        raw,
                        ctx["subject"],
                        allow_guess=True,
                        fast_mode=ctx["fast_mode"],
                        qtype="single",
                    
                else:
                    data = ctxraw

            items = dicts_to_items(data, subject=ctx["subject"], source="import")
            report = validate_questions(items)
            st.session_state.imported_items = items
            st.session_state.imported_report = report

        except Exception as e:
            st.warning("⚠️ AI 整理失敗，改用本地拆題作備援，請老師核對答案。")
            data = ctxraw
            items = dicts_to_items(data, subject=ctx["subject"], source="local")
            report = validate_questions(items)
            st.session_state.imported_items = items
            st.session_state.imported_report = report
            st.exception(e)

    if st.session_state.imported_items:
        report = st.session_state.imported_report or []
        bad_count = len([x for x in report if not x["ok"]])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查（請在表格內修正）。")

        df = items_to_editor_df(st.session_state.imported_items)
        edited, selected = render_editor(df, key="editor_import")

        edited_items = editor_df_to_items(edited, default_subject=ctx["subject"], source="import")
        st.session_state.imported_items = edited_items

        st.markdown("## ④ 匯出 / Google Form / 電郵分享")
        export_df = items_to_export_df(editor_df_to_items(selected, default_subject=ctx['subject'], source='import'))
        render_export_panel(export_df, ctx["subject"], st.session_state.google_creds, prefix="import")