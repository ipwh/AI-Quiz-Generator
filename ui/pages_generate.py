import streamlit as st
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items, items_to_export_df
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from extractors.extract import extract_text


def render_generate_tab(ctx: dict):
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF/DOCX/TXT/PPTX/XLSX/PNG/JPG。掃描/截圖可選擇啟用 LLM 讀圖 OCR（較慢，要選用Grok或ChatGPT等LLM，DeepSeek暫不支援）。")

    cfg = ctx"api_config"
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

        st.markdown("## ② 重點段落標記（可選）")
        st.caption("勾選後會把重點段落放到最前面，提高貼題度。")

        paras = [p.strip() for p in (raw_text or "").split("\n\n") if p.strip()]
        with st.expander("⭐ 打開段落清單（最多顯示 80 段）", expanded=False):
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
    limit = 8000 if ctx["fast_mode"] else 10000

    def build_text_with_highlights():
        paras = [p.strip() for p in (raw_text or "").split("\n\n") if p.strip()]
        highlights = [paras[i] for i in range(len(paras)) if i in st.session_state.mark_idx]
        others = [paras[i] for i in range(len(paras)) if i not in st.session_state.mark_idx]
        out = ""
        if highlights:
            out += "【重點段落（老師標記）】\n" + "\n\n".join(highlights) + "\n\n"
        out += "【其餘教材】\n" + "\n\n".join(others)
        return out[:limit]

    if st.button("🪄 生成題目", disabled=not (can_call_ai(cfg) and bool(raw_text.strip())), key="btn_generate"):
        used_text = build_text_with_highlights()

        with st.spinner("🤖 正在生成…"):
            data = ctxcfg,
                used_text,
                ctx["subject"],
                ctx["level_code"],
                ctx["question_count"],
                fast_mode=ctx["fast_mode"],
                qtype="single",
            

        items = dicts_to_items(data, subject=ctx["subject"], source="generate")
        report = validate_questions(items)

        st.session_state.generated_items = items
        st.session_state.generated_report = report

    if st.session_state.generated_items:
        report = st.session_state.generated_report or []
        bad_count = len([x for x in report if not x["ok"]])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查（請在表格內修正）。")

        df = items_to_editor_df(st.session_state.generated_items)
        edited, selected = render_editor(df, key="editor_generate")

        # 轉回 items（供 validator/export）
        edited_items = editor_df_to_items(edited, default_subject=ctx["subject"], source="generate")
        st.session_state.generated_items = edited_items

        # 匯出前再跑一次 validator（保護匯出）
        report2 = validate_questions(edited_items)
        bad2 = len([x for x in report2 if not x["ok"]])
        if bad2:
            st.info(f"提醒：匯出前仍有 {bad2} 題存在問題（可繼續匯出，但建議先修正）。")

        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        export_df = items_to_export_df(editor_df_to_items(selected, default_subject=ctx['subject'], source='generate'))
        render_export_panel(export_df, ctx["subject"], st.session_state.google_creds, prefix="generate")