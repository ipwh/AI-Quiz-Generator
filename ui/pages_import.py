import streamlit as st

from extractors.extract import extract_text
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items, items_to_export_df
from core.validators import validate_questions

try:
    from ui.components_editor import render_editor
    HAS_EDITOR_COMPONENT = True
except Exception:
    render_editor = None
    HAS_EDITOR_COMPONENT = False

try:
    from ui.components_export import render_export_panel
    HAS_EXPORT_COMPONENT = True
except Exception:
    render_export_panel = None
    HAS_EXPORT_COMPONENT = False


def render_import_tab(ctx: dict):
    st.markdown("## ① 上載 / 貼上題目")
    st.caption("支援 DOCX/TXT 或直接貼上。匯入模式固定為單選（4選1）。")

    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""

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
        disabled=not (bool(st.session_state.get("imported_text", "").strip()) and (not use_ai_assist or can_call_ai(cfg))),
        key="btn_import_parse",
    ):
        raw = st.session_state.get("imported_text", "").strip()

        try:
            with st.spinner("🧠 正在整理…"):
                if use_ai_assist:
                    data = ctx["assist_import_questions"](
                        cfg,
                        raw,
                        ctx["subject"],
                        allow_guess=True,
                        fast_mode=ctx.get("fast_mode", False),
                        qtype="single",
                    )
                else:
                    data = ctx["parse_import_questions_locally"](raw)

            items = dicts_to_items(data, subject=ctx["subject"], source="import")
            st.session_state.imported_items = items
            st.session_state.imported_report = validate_questions(items)

        except Exception as e:
            st.warning("⚠️ AI 整理失敗，改用本地拆題作備援，請老師核對答案。")
            data = ctx["parse_import_questions_locally"](raw)
            items = dicts_to_items(data, subject=ctx["subject"], source="local")
            st.session_state.imported_items = items
            st.session_state.imported_report = validate_questions(items)
            st.exception(e)

    if st.session_state.get("imported_items"):
        report = st.session_state.get("imported_report", [])
        bad_count = len([x for x in report if not x.get("ok")])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查（建議先修正再匯出）")

        st.markdown("## ③ 檢視與微調")
        df = items_to_editor_df(st.session_state.imported_items)

        if HAS_EDITOR_COMPONENT and render_editor is not None:
            edited, selected = render_editor(df, key="editor_import")
        else:
            edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="editor_import")
            selected = edited[edited["export"] == True].copy() if "export" in edited.columns else edited.copy()

        edited_items = editor_df_to_items(edited, default_subject=ctx["subject"], source="import")
        st.session_state.imported_items = edited_items

        st.markdown("## ④ 匯出 / Google Form / 電郵分享")
        export_items = editor_df_to_items(selected, default_subject=ctx["subject"], source="import")
        export_df = items_to_export_df(export_items)

        if HAS_EXPORT_COMPONENT and render_export_panel is not None:
            render_export_panel(export_df, ctx["subject"], st.session_state.get("google_creds"), prefix="import")
        else:
            st.info("（尚未接入 ui/components_export.py，暫時只顯示可匯出題目表格）")
            st.dataframe(export_df, use_container_width=True)
