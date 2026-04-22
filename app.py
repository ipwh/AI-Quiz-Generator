# =========================================================
# app.py — FINAL 穩定完整版（已鎖定縮排 / 無隱性字元）
#
# 功能：
# - 完整 Sidebar（API / Fast Mode / 科目 / 難度）
# - 生成新題目 + 匯入現有題目
# - 多格式輸入（DOCX / PDF / XLSX / PPTX / 圖片）
# - OCR / Vision fallback
# - 教師選擇教學重點（只用選定內容出題）
# - needs_review 題目提示
#
# 使用方法：
# - 整份覆蓋原 app.py
# - streamlit run app.py
# =========================================================

import io
import traceback
import streamlit as st
import pandas as pd
from docx import Document

from services.llm_service import generate_questions, assist_import_questions
from services.vision_service import vision_generate_questions, file_to_data_url, supports_vision

# =========================================================
# 基本設定
# =========================================================

st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

SS = st.session_state
if "items" not in SS:
    SS.items = None

# =========================================================
# 工具函式
# =========================================================

def show_exception(msg, e):
    st.error(msg)
    with st.expander("🔎 技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

def split_paragraphs(text):
    return [p.strip() for p in text.split("\n\n") if p.strip()]

def extract_text_and_images(files):
    texts = []
    images = []

    for f in files:
        data = f.read()
        name = f.name.lower()

        if name.endswith(".docx"):
            doc = Document(io.BytesIO(data))
            for p in doc.paragraphs:
                if p.text.strip():
                    texts.append(p.text.strip())

        elif name.endswith(".xlsx"):
            try:
                xls = pd.ExcelFile(io.BytesIO(data))
                for s in xls.sheet_names:
                    df = xls.parse(s, header=None)
                    for row in df.astype(str).fillna("").values.tolist():
                        line = " ".join(v for v in row if v and v != "nan").strip()
                        if line:
                            texts.append(line)
            except Exception:
                pass

        elif name.endswith(".pptx"):
            try:
                from pptx import Presentation
                prs = Presentation(io.BytesIO(data))
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            texts.append(shape.text.strip())
            except Exception:
                pass

        elif name.endswith(".pdf"):
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(data))
                has_text = False
                for page in reader.pages:
                    t = page.extract_text()
                    if t and t.strip():
                        texts.append(t.strip())
                        has_text = True
                if not has_text:
                    images.append(file_to_data_url(data, f.name))
            except Exception:
                images.append(file_to_data_url(data, f.name))

        elif name.endswith((".png", ".jpg", ".jpeg")):
            images.append(file_to_data_url(data, f.name))

    return "\n\n".join(texts), images

# =========================================================
# Sidebar — AI 設定
# =========================================================

st.sidebar.header("🔌 AI 設定")

preset = st.sidebar.selectbox("模型類型", ["OpenAI", "DeepSeek", "Grok"])
api_key = st.sidebar.text_input("API Key", type="password")
fast_mode = st.sidebar.checkbox("⚡ 快速模式", value=True)

if preset == "OpenAI":
    cfg = {"api_key": api_key, "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}
elif preset == "DeepSeek":
    cfg = {"api_key": api_key, "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"}
else:
    cfg = {"api_key": api_key, "base_url": "https://api.x.ai/v1", "model": "grok-4-latest"}

st.sidebar.divider()

st.sidebar.header("📘 教學設定")

subject = st.sidebar.selectbox(
    "科目",
    [
        "中國語文", "英國語文", "數學", "公民與社會發展",
        "科學", "物理", "化學", "生物",
        "地理", "歷史", "中國歷史",
        "資訊及通訊科技（ICT）",
        "經濟", "企業、會計與財務概論", "旅遊與款待"
    ]
)

level_label = st.sidebar.radio(
    "難度",
    ["基礎（理解）", "標準（應用）", "進階（分析）", "混合"],
    index=1
)

level_map = {
    "基礎（理解）": "easy",
    "標準（應用）": "medium",
    "進階（分析）": "hard",
    "混合": "mixed"
}

level = level_map[level_label]
question_count = st.sidebar.selectbox("題目數目", [5, 8, 10, 12, 15])

# =========================================================
# Tabs
# =========================================================

tab_gen, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# =========================================================
# 生成新題目
# =========================================================

with tab_gen:
    st.header("① 上傳教材（多格式）")
    uploads = st.file_uploader(
        "支援 Word / PDF / Excel / PPTX / 圖片",
        type=["docx", "pdf", "xlsx", "pptx", "png", "jpg"],
        accept_multiple_files=True
    )

    extracted_text = ""
    vision_images = []

    if uploads:
        extracted_text, vision_images = extract_text_and_images(uploads)

    st.header("② 選擇教學重點")
    paragraphs = split_paragraphs(extracted_text)
    selected = []

    for i, p in enumerate(paragraphs, 1):
        if st.checkbox(f"使用第 {i} 段"):
            selected.append(p)
        st.markdown(p)

    st.header("③ 生成題目")

    if st.button("生成"):
        try:
            if selected:
                SS.items = generate_questions(
                    cfg,
                    "\n\n".join(selected),
                    subject,
                    level,
                    question_count,
                    fast_mode=fast_mode
                )
                st.success("✅ 已根據選定內容生成題目")
            elif vision_images and supports_vision(cfg):
                SS.items = vision_generate_questions(
                    cfg,
                    "",
                    vision_images,
                    subject,
                    level,
                    question_count
                )
                st.success("✅ 已使用 Vision 生成題目")
            else:
                st.warning("請先選擇內容或上傳可 OCR 的教材")
        except Exception as e:
            show_exception("生成失敗", e)

    if isinstance(SS.items, list) and SS.items:
        st.header("④ 生成結果")
        for i, q in enumerate(SS.items, 1):
            with st.expander(f"第 {i} 題", expanded=True):
                st.markdown(q.get("question", ""))
                for idx, opt in enumerate(q.get("options", []), 1):
                    st.markdown(f"{idx}. {opt}")
                st.markdown("答案：" + ",".join(q.get("correct", [])))
                if q.get("needs_review"):
                    st.warning("⚠️ 此題需要教師確認")

# =========================================================
# 匯入現有題目
# =========================================================

with tab_import:
    st.header("① 上傳題目檔案（多格式）")
    uploads2 = st.file_uploader(
        "Word / PDF / Excel / PPTX / 圖片",
        type=["docx", "pdf", "xlsx", "pptx", "png", "jpg"],
        accept_multiple_files=True,
        key="import"
    )

    raw_text = ""
    if uploads2:
        raw_text, _ = extract_text_and_images(uploads2)

    raw_text = st.text_area("② 擷取後文字（可編輯）", value=raw_text, height=200)

    if st.button("③ 使用 AI 整理"):
        try:
            SS.items = assist_import_questions(cfg, raw_text, subject)
            st.success("✅ 已整理成標準題目")
        except Exception as e:
            show_exception("整理失敗", e)
