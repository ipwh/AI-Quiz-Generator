
# =========================================================
# app.py
# ✅ Phase 1→2→3 已整合：多格式上傳＋內容擷取（含 Vision fallback）＋重點選擇
# ✅ 無新增外部依賴；對無法 OCR 的格式採安全降級（Vision / 文字）
# ✅ 可直接覆蓋使用（與既有 llm_service.py / vision_service.py 相容）
# =========================================================

import io
import traceback
import streamlit as st
import pandas as pd
from docx import Document

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
)
from services.vision_service import (
    vision_generate_questions,
    file_to_data_url,
    supports_vision,
)
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)

# ---------------------------------------------------------
# Page
# ---------------------------------------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# ---------------------------------------------------------
# Session state
# ---------------------------------------------------------
SS = st.session_state
SS.setdefault("google_creds", None)
SS.setdefault("extracted_fulltext", "")
SS.setdefault("selected_idxs", set())
SS.setdefault("final_items", None)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def show_exception(msg, e):
    st.error(msg)
    with st.expander("技術細節"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def split_paragraphs(text: str):
    ps = [p.strip() for p in text.split("\n\n")]
    return [p for p in ps if p]

# ---- Text extractors (Phase 1) ----

def extract_docx_bytes(b):
    doc = Document(io.BytesIO(b))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_xlsx_bytes(b):
    bio = io.BytesIO(b)
    try:
        xls = pd.ExcelFile(bio)
        texts = []
        for name in xls.sheet_names:
            df = xls.parse(name, header=None)
            vals = df.astype(str).fillna("").values.tolist()
            for row in vals:
                line = " ".join(v for v in row if v and v.lower() != "nan").strip()
                if line:
                    texts.append(line)
        return "\n\n".join(texts)
    except Exception:
        return ""


def extract_pptx_bytes(b):
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(b))
        texts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
        return "\n\n".join(texts)
    except Exception:
        return ""


def extract_pdf_text_bytes(b):
    # 嘗試文字型 PDF；掃描型將交由 Vision（安全降級）
    try:
        from PyPDF2 import PdfReader
        r = PdfReader(io.BytesIO(b))
        parts = []
        for p in r.pages:
            t = p.extract_text() or ""
            if t.strip():
                parts.append(t.strip())
        return "\n\n".join(parts)
    except Exception:
        return ""


# ---------------------------------------------------------
# Sidebar: Google OAuth (可選)
# ---------------------------------------------------------
st.sidebar.header("🟦 Google 連接（Forms / Drive）")
if not oauth_is_configured():
    st.sidebar.warning("尚未設定 Google OAuth secrets")
else:
    if SS.google_creds:
        st.sidebar.success("✅ 已登入 Google")
        if st.sidebar.button("🔒 登出 Google"):
            SS.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 登入 Google", get_auth_url())

# ---------------------------------------------------------
# Sidebar: 教學設定
# ---------------------------------------------------------
st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox(
    "科目",
    ["中國語文","英國語文","數學","公民與社會發展","科學","公民、經濟及社會","物理","化學","生物","地理","歷史","中國歷史","宗教","資訊及通訊科技（ICT）","經濟","企業、會計與財務概論","旅遊與款待"],
)
level_label = st.sidebar.radio("🎯 難度", ["基礎（理解與記憶）","標準（應用與理解）","進階（分析與思考）","混合（課堂活動建議）"], index=1)
level_map = {"基礎（理解與記憶）":"easy","標準（應用與理解）":"medium","進階（分析與思考）":"hard","混合（課堂活動建議）":"mixed"}
level = level_map[level_label]
question_count = st.sidebar.selectbox("題目數目", [5,8,10,12,15,20], index=2)

# ---------------------------------------------------------
# Tabs
# ---------------------------------------------------------
tab_gen, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# =========================================================
# Phase 1: 多格式輸入 + 內容擷取
# =========================================================
with tab_gen:
    st.subheader("① 多格式上傳（Word / PDF / Excel / PPTX / 圖片）")
    uploads = st.file_uploader("上傳教材檔案（可多檔）", type=["docx","pdf","xlsx","pptx","png","jpg"], accept_multiple_files=True)

    extracted = []
    vision_images = []

    if uploads:
        for f in uploads:
            b = f.read()
            name = f.name.lower()
            if name.endswith('.docx'):
                t = extract_docx_bytes(b)
            elif name.endswith('.xlsx'):
                t = extract_xlsx_bytes(b)
            elif name.endswith('.pptx'):
                t = extract_pptx_bytes(b)
            elif name.endswith('.pdf'):
                t = extract_pdf_text_bytes(b)
                if not t.strip():
                    # 掃描型 PDF → Vision 降級
                    vision_images.append(file_to_data_url(b, f.name))
            elif name.endswith(('.png','.jpg','.jpeg')):
                vision_images.append(file_to_data_url(b, f.name))
                t = ""
            else:
                t = ""
            if t.strip():
                extracted.append(t.strip())

    SS.extracted_fulltext = "\n\n".join(extracted).strip()

    st.subheader("② 教材全文（可勾選重點）")
    paras = split_paragraphs(SS.extracted_fulltext)
    if paras:
        SS.selected_idxs = set()
        for i, p in enumerate(paras):
            checked = st.checkbox(f"選用段落 {i+1}", key=f"p_{i}")
            st.markdown(p)
            if checked:
                SS.selected_idxs.add(i)
    else:
        st.info("尚未擷取到可勾選的文字。若上載為掃描 PDF / 圖片，請使用 Vision。")

    st.subheader("③ 生成題目（只用已選重點）")
    if st.button("生成題目"):
        try:
            chosen = [paras[i] for i in sorted(SS.selected_idxs)]
            chosen_text = "\n\n".join(chosen).strip()

            if chosen_text:
                SS.final_items = generate_questions({"api_key":"","base_url":"","model":""}, chosen_text, subject, level, question_count, fast_mode=True)
                st.success("✅ 已根據選定重點生成題目")
            elif vision_images and supports_vision({}):
                SS.final_items = vision_generate_questions({"api_key":"","base_url":"","model":""}, "", vision_images, subject, level, question_count)
                st.success("✅ 已使用 Vision 生成題目")
            else:
                st.warning("請先勾選至少一段重點，或上傳可供 Vision 的圖片／掃描 PDF。")
        except Exception as e:
            show_exception("生成失敗", e)

    if SS.final_items:
        st.subheader("④ 生成結果")
        for i, q in enumerate(SS.final_items, 1):
            with st.expander(f"第 {i} 題", expanded=True):
                st.markdown(q.get("question",""))
                for j, opt in enumerate(q.get("options",[]), 1):
                    st.markdown(f"{j}. {opt}")

# =========================================================
# Import tab：沿用相同 Phase（多格式→擷取→勾選→整理）
# =========================================================
with tab_import:
    st.subheader("① 多格式上傳（匯入現有題目）")
    up2 = st.file_uploader("上傳題目檔案（docx / pdf / xlsx / pptx / 圖片）", type=["docx","pdf","xlsx","pptx","png","jpg"], accept_multiple_files=True)
    texts = []
    if up2:
        for f in up2:
            b = f.read(); name = f.name.lower()
            if name.endswith('.docx'): texts.append(extract_docx_bytes(b))
            elif name.endswith('.xlsx'): texts.append(extract_xlsx_bytes(b))
            elif name.endswith('.pptx'): texts.append(extract_pptx_bytes(b))
            elif name.endswith('.pdf'): texts.append(extract_pdf_text_bytes(b))
        raw = "\n\n".join(t for t in texts if t)
        st.text_area("② 擷取後文字（可再編輯）", value=raw, height=200)
        if st.button("③ 使用 AI 整理成標準題目"):
            try:
                SS.final_items = assist_import_questions({"api_key":"","base_url":"","model":""}, raw, subject)
                st.success("✅ 已整理")
            except Exception as e:
                show_exception("整理失敗", e)
