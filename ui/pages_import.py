import streamlit as st

from extractors.extract import extract_text
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
from core.validators import validate_questions

from ui.components_editor import render_editor
from ui.components_export import render_export_panel


def render_import_tab(ctx: dict):
    st.markdown("## ① 上載 / 貼上題目")
    st.caption("支援 PDF/DOCX/TXT/PPTX/XLSX 或直接貼上。匯入模式固定為單選（4選1）。")

    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]

    def load_import_files_to_text():
        files = st.session_state.get("import_files")
        if not files:
            return
        parts = []
        for f in files:
            try:
                t = extract_text(f) or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(t.strip())
        st.session_state.imported_text = "\n\n".join(parts)

    st.file_uploader(
        "上載題目檔案（自動載入到文字框）",
        type=["pdf", "docx", "txt", "pptx", "xlsx"],
        accept_multiple_files=True,
        key="import_files",
        on_change=load_import_files_to_text,
    )

    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True, key="use_ai_assist")
    st.text_area("貼上題目內容", height=320, key="imported_text")

    st.markdown("## ② 整理並轉換")

    raw = (st.session_state.get("imported_text", "") or "").strip()
    disabled = not bool(raw)
    if use_ai_assist:
        disabled = disabled or (not can_call_ai(cfg))

    if st.button("✨ 整理並轉換", disabled=disabled, key="btn_import_parse"):
        try:
            with st.spinner("🧠 正在整理…"):
                if use_ai_assist:
                    data = ctx["assist_import_questions"](
                        cfg,
                        raw,
                        ctx["subject"],
                        allow_guess=True,
                        fast_mode=ctx.get("fast_mode", True),
                        qtype="single",
                    )
                else:
                    data = ctx["parse_import_questions_locally"](raw)

            items = dicts_to_items(data, subject=ctx["subject"], source="import")
            report = validate_questions(items)
            st.session_state.imported_items = items
            st.session_state.imported_report = report

        except Exception as e:
            st.error("匯入/整理失敗")
            st.exception(e)

    if st.session_state.get("imported_items"):
        report = st.session_state.get("imported_report", [])
        bad_count = len([x for x in report if not x.get("ok")])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查（建議先修正再匯出）")

        st.markdown("## ③ 檢視與微調")
        df = items_to_editor_df(st.session_state.imported_items, report=report)
        edited, selected = render_editor(df, key="editor_import")

        edited_items = editor_df_to_items(edited, default_subject=ctx["subject"], source="import")
        edited_report = validate_questions(edited_items)
        st.session_state.imported_items = edited_items
        st.session_state.imported_report = edited_report

        st.markdown("## ④ 匯出 / Google Form / 電郵分享")
        render_export_panel(selected, ctx["subject"], st.session_state.get("google_creds"), prefix="import")
