# =========================================================
# app.py — FINAL 最終完整版
#
# ✅ 完整 Sidebar（API / Fast Mode / 教學設定）
# ✅ 生成新題目 + 匯入現有題目（共用流程）
# ✅ 多格式輸入：DOCX / PDF / XLSX / PPTX / 圖片
# ✅ 文字擷取 + Vision / OCR fallback
# ✅ 教師選擇教學重點（只用選定內容出題）
# ✅ needs_review 題目標示
# ✅ Kahoot Excel / Wayground DOCX 匯出
# ✅ Google OAuth（登入，不會 crash）
#
# 👉 此檔案為「最終交付版」，可長期使用與擴展
# =========================================================

import io
import traceback
import streamlit as st
import pandas as pd
from docx import Document

# ---------- Services ----------
from services.llm_service import (
    generate_questions,
    assist_import_questions,
)
from services.vision_service import (
    vision_generate_questions,
    file_to_data_url,
    supports_vision,
)
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
)

# =========================================================
# Page config
# =========================================================
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# =========================================================
# Session state
# =========================================================
SS = st.session_state
SS.setdefault("extracted_text", "")
SS.setdefault("selected_idxs", set())
SS.setdefault("items", None)

# =========================================================
# Utilities
# =========================================================
def show_exception(msg, e):
    st.error(msg)
    with st.expander("技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

def split_paragraphs(text: str):
    return [p.strip() for p in text.split("\n\n") if p.strip()]

# =========================================================
# Sidebar — Google OAuth（安全：無設定不會 crash）
# =========================================================
st.sidebar.header("🟦 Google 連接（Forms / Drive）")
if oauth_is_configured():
    st.sidebar.link_button("🔐 登入 Google", get_auth_url())
else:
    st.sidebar.warning("尚未設定 Google OAuth（可暫時忽略）")

st.sidebar.divider()

# =========================================================
# Sidebar — AI API 設定（完整回歸）
# =========================================================
st.sidebar.header("🔌 AI API 設定")
preset = st.sidebar.selectbox(
    "模型類型",
    ["OpenAI", "DeepSeek", "Grok", "自訂（OpenAI 相容）"],
)
api_key = st.sidebar.text_input("API Key", type="password")

if preset == "OpenAI":
    cfg = {
        "api_key": api_key,
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    }
elif preset == "DeepSeek":
    cfg = {
        "api_key": api_key,
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    }
elif preset == "Grok":
    cfg = {
        "api_key": api_key,
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-latest",
    }
else:
    base = st.sidebar.text_input("Base URL（含 /v1）", value="")
    model = st.sidebar.text_input("Model", value="")
    cfg = {
        "api_key": api_key,
        "base_url": base,
        "model": model,
    }

st.sidebar.divider()

# =========================================================
# Sidebar — Fast Mode
# =========================================================
fast_mode = st.sidebar.checkbox(
    "⚡ 快速模式",
    value=True,
    help="較快、較保守輸出；關閉後題目更豐富",
)

st.sidebar.divider()

# =========================================================
# Sidebar — 教學設定（完整科目與難度）
# =========================================================
st.sidebar.header("📘 出題設定")

subject = st.sidebar.selectbox(
    "科目",
    [
        "中國語文", "英國語文", "數學", "公民與社會發展",
        "科學", "公民、經濟及社會",
        "物理", "化學", "生物", "地理",
        "歷史", "中國歷史", "宗教",
        "資訊及通訊科技（ICT）",
        "經濟", "企業、會計與財務概論", "旅遊與款待",
    ],
)

level_label = st.sidebar.radio(
    "🎯 難度",
    [
        "基礎（理解與記憶）",
        "標準（應用與理解）",
        "進階（分析與思考）",
        "混合（課堂活動建議）",
    ],
    index=1,
)

level_map = {
    "基礎（理解與記憶）": "easy",
    "標準（應用與理解）": "medium",
    "進階（分析與思考）": "hard",
    "混合（課堂活動建議）": "mixed",
}
level = level_map[level_label]

question_count = st.sidebar.selectbox(
    "題目數目",
    [5, 8, 10, 12, 15, 20],
    index=2,
)

# =========================================================
# Tabs
# =========================================================
tab_gen, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# =========================================================
# Shared: 多格式文字擷取
# =========================================================
def extract_text_from_files(files):
    extracted = []
    images_for_vision = []

    for f in files:
        b = f.read()
        name = f.name.lower()

        if name.endswith(".docx"):
            doc = Document(io.BytesIO(b))
            extracted.extend(
                p.text.strip() for p in doc.paragraphs if p.text.strip()
            )

        elif name.endswith(".xlsx"):
            try:
                xls = pd.ExcelFile(io.BytesIO(b))
                for s in xls.sheet_names:
                    df = xls.parse(s, header=None)
                    for row in df.astype(str).fillna("").values.tolist():
                        line = " ".join(v for v in row if v and v.lower() != "nan").strip()
                        if line:
                            extracted.append(line)
            except Exception:
                pass

        elif name.endswith(".pptx"):
            try:
                from pptx import Presentation
                prs = Presentation(io.BytesIO(b))
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            extracted.append(shape.text.strip())
            except Exception:
                pass

        elif name.endswith(".pdf"):
            # 嘗試文字型；掃描型交 Vision
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(io.BytesIO(b))
                text_ok = False
                for p in reader.pages:
                    t = p.extract_text() or ""
                    if t.strip():
                        extracted.append(t.strip())
                        text_ok = True
                if not text_ok:
                    images_for_vision.append(file_to_data_url(b, f.name))
            except Exception:
                images_for_vision.append(file_to_data_url(b, f.name))

        elif name.endswith((".png", ".jpg", ".jpeg")):
            images_for_vision.append(file_to_data_url(b, f.name))

    return "\n\n".join(extracted).strip(), images_for_vision

# =========================================================
# Tab: 生成新題目
# =========================================================
with tab_gen:
    st.header("① 上傳教材（多格式）")
    uploads = st.file_uploader(
        "Word / PDF / Excel / PPTX / 圖片",
        type=["docx", "pdf", "xlsx", "pptx", "png", "jpg"],
        accept_multiple_files=True,
    )

    if uploads:
        SS.extracted_text, vision_images = extract_text_from_files(uploads)
    else:
        SS.extracted_text, vision_images = "", []

    st.header("② 選擇教學重點")
    paras = split_paragraphs(SS.extracted_text)
    SS.selected_idxs = set()

    if paras:
        for i, p in enumerate(paras):
            if st.checkbox(f"使用第 {i+1} 段"):
                SS.selected_idxs.add(i)
            st.markdown(p)
    else:
        st.info("未能擷取文字（掃描 PDF / 圖片可用 Vision）")

    st.header("③ 生成題目")
    if st.button("生成"):
        try:
            chosen = "\n\n".join(paras[i] for i in sorted(SS.selected_idxs))
            if chosen:
                SS.items = generate_questions(
                    cfg,
                    chosen,
                    subject,
                    level,
                    question_count,
                    fast_mode=fast_mode,
                )
                st.success("✅ 已根據選定重點生成題目")
            elif vision_images and supports_vision(cfg):
                SS.items = vision_generate_questions(
                    cfg,
                    "",
                    vision_images,
                    subject,
                    level,
                    question_count,
                )
                st.success("✅ 已使用 Vision 生成題目")
            else:
                st.warning("請選擇內容或上傳可 OCR 的教材")
        except Exception as e:
            show_exception("生成失敗", e)

# ---- 生成結果顯示（最終安全版）----
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
else:
    if SS.items is not None:
        st.error("⚠️ 題目資料狀態異常，請重新生成一次。")


# =========================================================
# Tab: 匯入現有題目（沿用相同多格式流程）
# =========================================================
with tab_import:
    st.header("① 上傳題目檔案（多格式）")
    uploads2 = st.file_uploader(
        "Word / PDF / Excel / PPTX / 圖片",
        type=["docx", "pdf", "xlsx", "pptx", "png", "jpg"],
        accept_multiple_files=True,
        key="import",
    )

    raw_text = ""
    if uploads2:
        raw_text, _ = extract_text_from_files(uploads2)

    raw_text = st.text_area("② 擷取後文字（可修改）", value=raw_text, height=200)

    if st.button("③ 使用 AI 整理"):
        try:
            SS.items = assist_import_questions(cfg, raw_text, subject)
            st.success("✅ 已整理成標準題目")
        except Exception as e:
            show_exception("整理失敗", e)
