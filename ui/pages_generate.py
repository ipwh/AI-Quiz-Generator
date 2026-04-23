# ui/pages_generate.py

from __future__ import annotations
import streamlit as st

from extractors.extract import extract_payload
from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
from core.validators import validate_questions
from ui.components_editor import render_editor
from ui.components_export import render_export_panel
from services.llm_service import generate_questions

DNL = chr(10) * 2

# =========================================================
# 清除所有生成頁面的 session_state（換課題用）
# =========================================================

_GEN_KEYS = [
    "generated_items", "generated_report",
    "_gen_sig", "gen_mark_initialized", "mark_idx",
    "export_quiz_mode", "export_quiz_points", "export_quiz_show_exp",
    "form_result_generate",
]

def _clear_generate_state():
    for k in _GEN_KEYS:
        st.session_state.pop(k, None)
    # 清除所有段落勾選狀態
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and (k.startswith("gen_mark_") or k.startswith("editor_generate")):
            st.session_state.pop(k, None)
    # 重置 file_uploader（透過 key 更換強制清除）
    st.session_state["_gen_uploader_key"] = st.session_state.get("_gen_uploader_key", 0) + 1


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


de
