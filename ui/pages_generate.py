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

NL = chr(10)
DNL = chr(10) * 2


def _split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split(DNL) if p.strip()]


def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]

    parts = []
    if highlights:
        parts.append("【重點段落（老師標記）】")
        parts.append(DNL.join(highlights))
    parts.append("【其餘教材】")
    parts.append(DNL.join(others))

    return DNL.join(parts)[:limit]


def render_generate_tab(ctx: dict):
    """生成新題目頁。

    ctx 必須包含：
      - api_config(): dict
      - can_call_ai(cfg): bool
      - generate_questions(...) callable
      - subject, level_code, level_label, question_count, fast_mode
    """
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF/DOCX/TXT/PPTX/XLSX/PNG/JPG。掃描/截圖可選擇啟用 LLM 讀圖 OCR（較慢，要選用Grok或ChatGPT等LLM，DeepSeek暫不支援）。")

    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]

    files = st.file_uploader(
        "上載教材檔案",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="files_generate",
    )

    raw_text = ""
    if files:
        with st.spinner("📄 正在擷取文字…"):
            raw_text = "".join(extract_text(f) for f in files)
        st.info(f"✅ 已擷取 {len(raw_text)} 字")

        # ② 重點段落標記（可選）— 注意：不依賴 OCR checkbox
        st.markdown("## ② 重點段落標記（可選）")
        st.caption("勾選後會把重點段落放到最前面，提高貼題度。")

        paras = _split_paragraphs(raw_text)
        with st.expander("⭐ 打開段落清單（最多顯示 80 段）", expanded=False):
            st.caption(f"段落數：{len(paras)}（以空行分段）")

            cA, cB = st.columns(2)
            with cA:
                if st.button("✅ 全選重點段落", key="btn_mark_all"):
                    st.session_state.mark_idx = set(range(len(paras)))
            with cB:
                if st.button("⛔ 全不選", key="btn_mark_none"):
                    st.session_state.mark_idx = set()

            for i, p in enumerate(paras[:80]):
                checked = i in st.session_state.mark_idx
                new_checked = st.checkbox(f"第 {i+1} 段", value=checked, key=f"para_{i}")
                if new_checked:
                    st.session_state.mark_idx.add(i)
                else:
                    st.session_state.mark_idx.discard(i)
                st.write(p[:200] + ("…" if len(p) > 200 else ""))

    st.markdown("## ③ 生成題目")
    st.caption("按下後呼叫 AI 生成題目；若你選『混合』難度，系統會分層生成再混合。")

    limit = 8000 if ctx.get("fast_mode") else 10000

    if st.button(
        "🪄 生成題目",
        disabled=not (can_call_ai(cfg) and bool(raw_text.strip())),
        key="btn_generate",
    ):
        used_text = _build_text_with_highlights(raw_text, st.session_state.mark_idx, limit)

        with st.spinner("🤖 正在生成…"):
            data = ctx["generate_questions"](
                cfg,
                used_text,
                ctx["subject"],
                ctx["level_code"],
                ctx["question_count"],
                fast_mode=ctx.get("fast_mode", False),
                qtype="single",
            )

        items = dicts_to_items(data, subject=ctx["subject"], source="generate")
        report = validate_questions(items)
        st.session_state.generated_items = items
        st.session_state.generated_report = report

    if st.session_state.get("generated_items"):
        report = st.session_state.get("generated_report", [])
        bad_count = len([x for x in report if not x.get("ok")])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查（建議先修正再匯出）")

        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(st.session_state.generated_items)

        if HAS_EDITOR_COMPONENT and render_editor is not None:
            edited, selected = render_editor(df, key="editor_generate")
        else:
            edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="editor_generate")
            selected = edited[edited["export"] == True].copy() if "export" in edited.columns else edited.copy()

        edited_items = editor_df_to_items(edited, default_subject=ctx["subject"], source="generate")
        st.session_state.generated_items = edited_items

        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        export_items = editor_df_to_items(selected, default_subject=ctx["subject"], source="generate")
        export_df = items_to_export_df(export_items)

        if HAS_EXPORT_COMPONENT and render_export_panel is not None:
            render_export_panel(export_df, ctx["subject"], st.session_state.get("google_creds"), prefix="generate")
        else:
            st.info("（尚未接入 ui/components_export.py，暫時只顯示可匯出題目表格）")
            st.dataframe(export_df, use_container_width=True)
