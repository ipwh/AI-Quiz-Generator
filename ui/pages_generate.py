import re
import streamlit as st

from extractors.extract import extract_text
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
from core.validators import validate_questions

from ui.components_editor import render_editor
from ui.components_export import render_export_panel

DNL = "\n\n"


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", DNL, text)
    return text.strip()


def _split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split(DNL) if p.strip()]


def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlighted = [p for i, p in enumerate(paras) if i in marked_idx]
    others = [p for i, p in enumerate(paras) if i not in marked_idx]

    combined = []
    if highlighted:
        combined.append("【重點段落】")
        combined.extend(highlighted)
    if others:
        combined.append("【其餘內容】")
        combined.extend(others)

    out = DNL.join(combined)
    if limit and len(out) > limit:
        out = out[:limit]
    return out


def _normalize_llm_dicts(data: list):
    """強化：確保 correct 為 1..4；options 必有 4 個；並剔除題幹中的『根據教材/根據文本』等字眼。"""
    out = []
    for q in (data or []):
        qq = dict(q)

        # clean question meta
        qtext = str(qq.get("question", ""))
        qtext = re.sub(r"^(根據|根據以下|根據上述|根據教材|根據文本|根據文章|根據資料)(.{0,15})([，,:：\s]+)", "", qtext)
        qq["question"] = qtext.strip()

        # options
        opts = qq.get("options", [])
        if not isinstance(opts, list):
            opts = []
        opts = [str(x) if x is not None else "" for x in opts]
        opts = (opts + ["", "", "", ""])[:4]
        qq["options"] = opts

        # correct
        corr = qq.get("correct", [])
        if isinstance(corr, str):
            corr = [c.strip() for c in corr.split(",") if c.strip()]
        if isinstance(corr, int):
            corr = [str(corr)]
        if not isinstance(corr, list):
            corr = []
        corr = [str(x).strip() for x in corr]
        corr = [c for c in corr if c in {"1", "2", "3", "4"}]
        qq["correct"] = corr[:1]

        if "needs_review" not in qq:
            qq["needs_review"] = False

        out.append(qq)
    return out


def _extract_multi_files(files) -> str:
    parts = []
    for f in files:
        try:
            t = extract_text(f) or ""
        except Exception:
            t = ""
        t = _clean_text(t)
        if t:
            parts.append(t)
    return _clean_text(DNL.join(parts))


def _ensure_default_select_all(text: str, idx_key: str, hash_key: str):
    h = str(hash(text or ""))
    if st.session_state.get(hash_key) != h:
        paras = _split_paragraphs(text)
        st.session_state[idx_key] = set(range(len(paras)))
        st.session_state[hash_key] = h


def _enforce_question_count(ctx, cfg, used_text, target_n, fast_mode):
    """嚴格匹配題數：若不足，追加生成；若過多，截斷。"""
    # first call
    data = ctx["generate_questions"](
        cfg,
        used_text,
        ctx["subject"],
        ctx["level_code"],
        target_n,
        fast_mode=fast_mode,
        qtype="single",
    )

    if not isinstance(data, list):
        data = []

    # if too many
    if len(data) > target_n:
        return data[:target_n]

    # if too few: try one more time to top up
    remaining = target_n - len(data)
    if remaining > 0:
        data2 = ctx["generate_questions"](
            cfg,
            used_text,
            ctx["subject"],
            ctx["level_code"],
            remaining,
            fast_mode=fast_mode,
            qtype="single",
        )
        if isinstance(data2, list):
            data.extend(data2)

    return data[:target_n]


def render_generate_tab(ctx: dict):
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG；可配合 OCR 或 Vision 讀圖。")

    cfg = ctx["api_config"]()
    can_call_ai = ctx["can_call_ai"]

    uploads = st.file_uploader(
        "上載教材（可多檔）",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="gen_files",
    )

    extracted_text = ""
    if uploads:
        with st.status("正在擷取教材內容…", expanded=False) as status:
            status.update(state="running")
            extracted_text = _extract_multi_files(uploads)
            status.update(label="教材內容擷取完成", state="complete")

    st.session_state["gen_extracted_text"] = extracted_text

    st.markdown("## ② 老師勾選重點段落（只用勾選內容出題）")

    limit = 8000 if ctx.get("fast_mode", True) else 10000
    _ensure_default_select_all(extracted_text, idx_key="mark_idx_generate", hash_key="gen_text_hash")

    with st.expander("② 重點段落選擇（預設摺疊）", expanded=False):
        paras = _split_paragraphs(extracted_text)
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ 全選", key="btn_gen_select_all"):
                st.session_state.mark_idx_generate = set(range(len(paras)))
                st.rerun()
        with c2:
            if st.button("⬜ 全不選", key="btn_gen_select_none"):
                st.session_state.mark_idx_generate = set()
                st.rerun()
        with c3:
            st.caption("預設已全選。可按需要取消。")

        mark_idx = st.session_state.get("mark_idx_generate", set())
        new_set = set(mark_idx)
        for i, p in enumerate(paras):
            checked = (i in new_set)
            new_checked = st.checkbox(f"段落 {i+1}", value=checked, key=f"gen_para_{i}")
            st.markdown(p)
            if new_checked:
                new_set.add(i)
            else:
                new_set.discard(i)
        st.session_state.mark_idx_generate = new_set

    used_text = _build_text_with_highlights(extracted_text, st.session_state.get("mark_idx_generate", set()), limit)

    st.info(
        f"已從文本擷取 {len(extracted_text)} 字；送入 AI（重點合併後）{len(used_text)} 字（上限 {limit}；快速模式={'開' if ctx.get('fast_mode', True) else '關'}）"
    )

    with st.expander("🔎 已選內容預覽（將送入 AI）", expanded=False):
        st.text(used_text[:5000] + ("\n…（已截斷）" if len(used_text) > 5000 else ""))

    st.markdown("## ③ 生成題目")

    if st.button("🪄 生成題目", disabled=not can_call_ai(cfg), key="btn_generate_questions"):
        try:
            progress = st.progress(0)
            with st.spinner("AI 生成題目中…"):
                progress.progress(20)
                data = _enforce_question_count(
                    ctx,
                    cfg,
                    used_text,
                    ctx["question_count"],
                    fast_mode=ctx.get("fast_mode", True),
                )
                progress.progress(70)

            data = _normalize_llm_dicts(data)
            items = dicts_to_items(data, subject=ctx["subject"], source="generate")
            report = validate_questions(items)

            st.session_state.generated_items = items
            st.session_state.generated_report = report
            progress.progress(100)
            st.success("✅ 題目生成完成")

        except Exception as e:
            st.exception(e)

    if st.session_state.get("generated_items"):
        report = st.session_state.get("generated_report", [])
        bad_count = len([x for x in report if not x.get("ok")])
        if bad_count:
            st.warning(f"⚠️ 有 {bad_count} 題需要教師檢查（建議先修正再匯出）")

        st.markdown("## ④ 結果（可直接編輯題目與答案）")
        df = items_to_editor_df(st.session_state.generated_items, report=report)
        edited, selected = render_editor(df, key="editor_generate")

        edited_items = editor_df_to_items(edited, default_subject=ctx["subject"], source="generate")
        edited_report = validate_questions(edited_items)

        st.session_state.generated_items = edited_items
        st.session_state.generated_report = edited_report

        st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
        render_export_panel(selected, ctx["subject"], st.session_state.get("google_creds"), prefix="generate")
