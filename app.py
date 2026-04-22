# =========================================================
# app.py — FINAL-FULL v2026-04-22.4
#
# ✅ 修正（依你回報）：
# 1) 文字型 PDF（可複製文字）仍抽不到內容：新增更強的 PDF 抽字鏈
#    - 優先 PyMuPDF(fitz) get_text
#    - 其次 pdfplumber
#    - 再次 PyPDF2
#    - 若仍為空：在「純文字模式」也會提示並提供一鍵改用 OCR（不再默默 0 字）
# 2) 明確顯示「每個檔案抽取字數」+ 合併後字數 + 上限（8000/10000，跟 fast_mode）
# 3) ④ 結果預設「一眼睇晒」；可切換折疊 / 表格編輯（如 core.question_mapper 存在）
#
# ✅ 保留原本功能：Google OAuth、API 設定、Fast Mode、OCR/Vision、多格式、Kahoot/Wayground、(可選)Export Panel
#
# 注意：全檔 4 spaces 縮排，無 NBSP。
# =========================================================

import io
import re
import shutil
import traceback
from datetime import datetime

import streamlit as st
import pandas as pd
from docx import Document

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
)
from services.vision_service import (
    supports_vision,
    vision_generate_questions,
    file_to_data_url,
)
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)

try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None

try:
    from services.llm_service import get_xai_default_model
except Exception:
    get_xai_default_model = None

try:
    from core.question_mapper import dicts_to_items, items_to_editor_df, editor_df_to_items
    _HAS_EDITOR = True
except Exception:
    _HAS_EDITOR = False

try:
    from ui.components_export import render_export_panel
    _HAS_EXPORT_PANEL = True
except Exception:
    _HAS_EXPORT_PANEL = False


# =========================================================
# Page
# =========================================================

st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")
st.caption("FINAL-FULL v2026-04-22.4（PDF 抽字強化 / 字數提示 / 結果一眼睇晒）")


# =========================================================
# Session state
# =========================================================

SS = st.session_state
DEFAULTS = {
    "google_creds": None,

    "extracted_text_generate": "",
    "extracted_text_import": "",

    "file_extract_report_generate": [],
    "file_extract_report_import": [],

    "pdf_scan_bytes_generate": [],
    "pdf_scan_bytes_import": [],

    "image_bytes_generate": [],
    "image_bytes_import": [],

    "vision_urls_generate": [],
    "vision_urls_import": [],

    "mark_idx_generate": set(),
    "mark_idx_import": set(),

    "generated_items": [],
    "imported_items": [],

    "display_mode_generate": "full",
    "display_mode_import": "full",
}
for k, v in DEFAULTS.items():
    if k not in SS:
        SS[k] = v


# =========================================================
# Helpers
# =========================================================

def show_exception(msg: str, e: Exception):
    st.error(msg)
    with st.expander("🔎 技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


def build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    if not raw_text:
        return ""
    paragraphs = split_paragraphs(raw_text)
    highlighted = [p for i, p in enumerate(paragraphs) if i in marked_idx]
    others = [p for i, p in enumerate(paragraphs) if i not in marked_idx]

    combined = []
    if highlighted:
        combined.append("【重點段落】")
        combined.extend(highlighted)
    if others:
        combined.append("【其餘內容】")
        combined.extend(others)

    out = "\n\n".join(combined)
    if limit and len(out) > limit:
        out = out[:limit]
    return out


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M")


# =========================================================
# OCR readiness
# =========================================================

def check_local_ocr_ready():
    try:
        import pytesseract  # noqa
        from PIL import Image  # noqa
    except Exception:
        return False, "未安裝 pytesseract 或 pillow"

    if shutil.which("tesseract") is None:
        return False, "找不到 tesseract 執行檔（未安裝或不在 PATH）"

    try:
        import pytesseract
        _ = pytesseract.get_tesseract_version()
    except Exception:
        return True, "pytesseract 可用，但無法讀取版本（仍可嘗試）"

    return True, "✅ 本地 OCR（Tesseract）可用"


def local_ocr_images_to_text(images_bytes_list, lang_hint="chi_tra+eng") -> str:
    import pytesseract
    from PIL import Image

    texts = []
    for b in images_bytes_list:
        img = Image.open(io.BytesIO(b))
        t = pytesseract.image_to_string(img, lang=lang_hint)
        t = clean_text(t)
        if t:
            texts.append(t)
    return "\n\n".join(texts)


# =========================================================
# Extractors
# =========================================================

def extract_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    return "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text and p.text.strip())


def extract_xlsx(file_bytes: bytes) -> str:
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        lines = []
        for s in xls.sheet_names:
            df = xls.parse(s, header=None)
            for row in df.astype(str).fillna("").values.tolist():
                line = " ".join(v for v in row if v and v.lower() != "nan").strip()
                if line:
                    lines.append(line)
        return "\n\n".join(lines)
    except Exception:
        return ""


def extract_pptx(file_bytes: bytes) -> str:
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(file_bytes))
        lines = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text and shape.text.strip():
                    lines.append(shape.text.strip())
        return "\n\n".join(lines)
    except Exception:
        return ""


def extract_pdf_text_strong(file_bytes: bytes) -> str:
    """更強的 PDF 抽字：PyMuPDF(fitz) → pdfplumber → PyPDF2。"""
    # 0) PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        parts = []
        for i in range(len(doc)):
            t = doc.load_page(i).get_text("text") or ""
            if t.strip():
                parts.append(t.strip())
        doc.close()
        out = "\n\n".join(parts)
        if out.strip():
            return out
    except Exception:
        pass

    # 1) pdfplumber
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t.strip())
        out = "\n\n".join(parts)
        if out.strip():
            return out
    except Exception:
        pass

    # 2) PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for p in reader.pages:
            t = p.extract_text() or ""
            if t.strip():
                parts.append(t.strip())
        return "\n\n".join(parts)
    except Exception:
        return ""


def extract_payload_from_uploads(uploads):
    extracted_parts = []
    vision_urls = []
    image_bytes = []
    pdf_scan_bytes = []
    report = []

    for f in uploads:
        name = (f.name or "").lower()
        b = f.read()

        extracted = ""
        kind = ""

        if name.endswith(".docx"):
            kind = "DOCX"
            extracted = extract_docx(b)

        elif name.endswith(".xlsx"):
            kind = "XLSX"
            extracted = extract_xlsx(b)

        elif name.endswith(".pptx"):
            kind = "PPTX"
            extracted = extract_pptx(b)

        elif name.endswith(".txt"):
            kind = "TXT"
            try:
                extracted = b.decode("utf-8", errors="ignore")
            except Exception:
                extracted = ""
            extracted = clean_text(extracted)

        elif name.endswith(".pdf"):
            kind = "PDF"
            extracted = extract_pdf_text_strong(b)
            if not extracted.strip():
                pdf_scan_bytes.append(b)
                vision_urls.append(file_to_data_url(b, f.name))

        elif name.endswith((".png", ".jpg", ".jpeg")):
            kind = "IMG"
            image_bytes.append(b)
            vision_urls.append(file_to_data_url(b, f.name))

        if extracted.strip():
            extracted_parts.append(extracted.strip())

        report.append({
            "file": f.name,
            "type": kind,
            "chars": len(extracted),
            "note": "OK" if len(extracted) > 0 else ("掃描/抽字失敗" if kind == "PDF" else "")
        })

    return clean_text("\n\n".join(extracted_parts)), vision_urls, image_bytes, pdf_scan_bytes, report


# =========================================================
# Export helpers
# =========================================================

def export_kahoot_excel(items):
    rows = []
    for q in items:
        opts = (q.get("options", []) + ["", "", "", ""])[:4]
        corr = q.get("correct", [""])[0] if q.get("correct") else ""
        rows.append({
            "Question": q.get("question", ""),
            "Answer 1": opts[0],
            "Answer 2": opts[1],
            "Answer 3": opts[2],
            "Answer 4": opts[3],
            "Correct Answer": corr,
        })
    df = pd.DataFrame(rows)
    bio = io.BytesIO()
    df.to_excel(bio, index=False, engine="openpyxl")
    bio.seek(0)
    return bio


def export_wayground_docx(items, title="題目清單"):
    doc = Document()
    doc.add_heading(title, 0)
    for i, q in enumerate(items, 1):
        doc.add_heading(f"第 {i} 題", level=1)
        doc.add_paragraph(q.get("question", ""))
        for idx, opt in enumerate(q.get("options", []), 1):
            doc.add_paragraph(f"{idx}. {opt}")
        doc.add_paragraph("答案：" + ",".join(q.get("correct", [])))
        if q.get("needs_review"):
            doc.add_paragraph("⚠️ 需要教師確認")
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio


# =========================================================
# OAuth callback
# =========================================================
params = st.query_params
if oauth_is_configured() and "code" in params and not SS.google_creds:
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list):
            code = code[0]
        if isinstance(state, list):
            state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        SS.google_creds = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        show_exception("Google 登入失敗。", e)
        st.stop()


# =========================================================
# Sidebar
# =========================================================

st.sidebar.header("🟦 Google 連接")
if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth")
else:
    if SS.google_creds:
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google"):
            SS.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())

st.sidebar.divider()

fast_mode = st.sidebar.checkbox("⚡ 快速模式", value=True)

st.sidebar.divider()

st.sidebar.header("🔌 AI API 設定")
preset = st.sidebar.selectbox(
    "快速選擇",
    ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"],
)
api_key = st.sidebar.text_input("API Key", type="password")

if preset == "DeepSeek":
    cfg = {"api_key": api_key, "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"}
elif preset == "OpenAI":
    cfg = {"api_key": api_key, "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}
elif preset == "Grok (xAI)":
    base_url = "https://api.x.ai/v1"
    model = "grok-4-latest"
    if get_xai_default_model and api_key:
        try:
            model = get_xai_default_model(api_key, base_url)
        except Exception:
            pass
    cfg = {"api_key": api_key, "base_url": base_url, "model": model}
elif preset == "Azure OpenAI":
    st.sidebar.warning("⚠️ 此 FINAL 版本以 openai_compat 為主；如你 llm_service 有 Azure 版本，才可用。")
    cfg = {"api_key": api_key, "base_url": "", "model": ""}
else:
    base_url = st.sidebar.text_input("Base URL（含 /v1）", value="")
    model = st.sidebar.text_input("Model", value="")
    cfg = {"api_key": api_key, "base_url": base_url, "model": model}

if ping_llm and st.sidebar.button("🧪 測試 API"):
    if not cfg.get("api_key"):
        st.sidebar.error("請先輸入 API Key")
    else:
        r = ping_llm(cfg, timeout=25)
        if r.get("ok"):
            st.sidebar.success("✅ OK")
        else:
            st.sidebar.error("❌ 失敗")
            st.sidebar.code(r.get("error", ""))

st.sidebar.divider()

st.sidebar.header("🔬 OCR / 讀圖")
ocr_mode = st.sidebar.radio(
    "教材擷取模式",
    ["📄 純文字", "🔬 本地 OCR", "🤖 Vision"],
    index=0,
)
ocr_ok, ocr_msg = check_local_ocr_ready()
if ocr_mode.startswith("🔬"):
    st.sidebar.info(ocr_msg)

st.sidebar.divider()

st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox(
    "科目",
    [
        "中國語文", "英國語文", "數學", "公民與社會發展", "科學", "公民、經濟及社會",
        "物理", "化學", "生物", "地理", "歷史", "中國歷史", "宗教",
        "資訊及通訊科技（ICT）", "經濟", "企業、會計與財務概論", "旅遊與款待",
    ],
)
level_label = st.sidebar.radio(
    "🎯 難度",
    ["基礎（理解與記憶）", "標準（應用與理解）", "進階（分析與思考）", "混合（課堂活動建議）"],
    index=1,
)
level_map = {
    "基礎（理解與記憶）": "easy",
    "標準（應用與理解）": "medium",
    "進階（分析與思考）": "hard",
    "混合（課堂活動建議）": "mixed",
}
level_code = level_map[level_label]
question_count = st.sidebar.selectbox("題目數目", [5, 8, 10, 12, 15, 20], index=2)


# =========================================================
# UI components
# =========================================================

def render_paragraph_picker(raw_text: str, mark_idx_key: str, limit: int):
    paras = split_paragraphs(raw_text)
    mark_idx = SS.get(mark_idx_key, set())

    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("✅ 全選段落", key=f"all_{mark_idx_key}"):
            SS[mark_idx_key] = set(range(len(paras)))
            st.rerun()
    with c2:
        if st.button("⬜ 全不選", key=f"none_{mark_idx_key}"):
            SS[mark_idx_key] = set()
            st.rerun()
    with c3:
        st.caption("只會把已勾選段落送入 AI（更貼題）")

    new_set = set(mark_idx)
    for i, p in enumerate(paras):
        checked = (i in new_set)
        new_checked = st.checkbox(f"選用段落 {i+1}", value=checked, key=f"{mark_idx_key}_{i}")
        st.markdown(p)
        if new_checked:
            new_set.add(i)
        else:
            new_set.discard(i)

    SS[mark_idx_key] = new_set
    used = build_text_with_highlights(raw_text, new_set, limit=limit)
    return used


def render_results_one_glance(items: list, title: str, mode_key: str):
    if not isinstance(items, list) or not items:
        return items

    st.markdown(f"## {title}")

    mode = st.radio(
        "顯示模式",
        ["一眼睇晒（建議）", "折疊（簡潔）", "表格編輯（如可用）"],
        index=0,
        horizontal=True,
        key=f"radio_{mode_key}",
    )

    if mode.startswith("表格") and _HAS_EDITOR:
        try:
            df = items_to_editor_df(dicts_to_items(items))
            edited = st.data_editor(df, use_container_width=True, num_rows="dynamic")
            items2 = [it.to_dict() for it in editor_df_to_items(edited)]
            return items2
        except Exception:
            st.warning("表格編輯暫不可用，已回退到『一眼睇晒』。")

    if mode.startswith("折疊"):
        for i, q in enumerate(items, 1):
            needs = bool(q.get("needs_review"))
            with st.expander(("⚠️ " if needs else "") + f"第 {i} 題", expanded=needs):
                st.markdown(q.get("question", ""))
                for j, opt in enumerate(q.get("options", []), 1):
                    st.markdown(f"{j}. {opt}")
                st.markdown("**答案：** " + ",".join(q.get("correct", [])))
                if needs:
                    st.warning(q.get("explanation") or "此題需要教師確認")
        return items

    # default: one-glance
    for i, q in enumerate(items, 1):
        needs = bool(q.get("needs_review"))
        with st.container(border=True):
            st.markdown(f"### {'⚠️ ' if needs else ''}第 {i} 題")
            st.markdown(q.get("question", ""))
            for j, opt in enumerate(q.get("options", []), 1):
                st.markdown(f"{j}. {opt}")
            st.markdown("**答案：** " + ",".join(q.get("correct", [])))
            if needs:
                st.warning(q.get("explanation") or "此題需要教師確認")
    return items


# =========================================================
# Tabs
# =========================================================

tab_gen, tab_imp = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])


# =========================================================
# Generate
# =========================================================
with tab_gen:
    st.markdown("## ① 上載教材（多格式）")
    uploads = st.file_uploader(
        "PDF / DOCX / XLSX / PPTX / TXT / 圖片",
        type=["pdf", "docx", "xlsx", "pptx", "txt", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="up_gen",
    )

    if uploads:
        with st.status("正在擷取教材內容…", expanded=False) as s:
            s.update(label="正在擷取教材內容…", state="running")
            text, v_urls, img_bytes, pdf_scan, report = extract_payload_from_uploads(uploads)
            SS.extracted_text_generate = text
            SS.vision_urls_generate = v_urls
            SS.image_bytes_generate = img_bytes
            SS.pdf_scan_bytes_generate = pdf_scan
            SS.file_extract_report_generate = report
            s.update(label="擷取完成", state="complete")

        with st.expander("📄 擷取報告（每檔抽取字數）", expanded=False):
            st.dataframe(pd.DataFrame(SS.file_extract_report_generate), use_container_width=True)

    st.markdown("## ② 老師勾選重點段落（只用勾選內容出題）")
    limit = 8000 if fast_mode else 10000
    used = render_paragraph_picker(SS.extracted_text_generate, "mark_idx_generate", limit=limit)

    st.info(f"已從文字層擷取 {len(SS.extracted_text_generate)} 字；送入 AI（重點合併後）{len(used)} 字（上限 {limit}；快速模式={'開' if fast_mode else '關'}）")

    if len(SS.extracted_text_generate) == 0 and any(r.get('type') == 'PDF' for r in SS.file_extract_report_generate):
        st.warning(
            "⚠️ 你上載的 PDF 雖然可複製文字，但程式抽字仍為 0。\n"
            "已加強抽字鏈（fitz/pdfplumber/PyPDF2），若仍為 0，通常是 PDF 字型/編碼特殊。\n"
            "你可暫時改用：\n"
            "- 🔬 本地 OCR（會把 PDF 轉圖再 OCR；需要 PyMuPDF fitz 已安裝）或\n"
            "- 🤖 Vision（若模型支援）。"
        )

    with st.expander("🔎 已選內容預覽（將送入 AI）", expanded=False):
        st.text(used[:5000] + ("\n…（已截斷）" if len(used) > 5000 else ""))

    st.markdown("## ③ 生成題目")
    if st.button("🪄 生成題目", key="btn_gen"):
        if not cfg.get("api_key"):
            st.error("請先在左側輸入 API Key")
        else:
            try:
                prog = st.progress(0)
                prog.progress(10)

                used_for_ai = used

                # 若抽字失敗但 PDF 是文字型：允許在本地 OCR 模式下強制 OCR
                if ocr_mode.startswith("🔬") and ocr_ok:
                    with st.spinner("本地 OCR 處理中（掃描 PDF/圖片 或 抽字失敗的 PDF）…"):
                        prog.progress(30)
                        ocr_images = list(SS.image_bytes_generate)
                        # 對所有 pdf_scan 做 OCR 轉圖
                        for b in SS.pdf_scan_bytes_generate:
                            try:
                                pages = []
                                import fitz
                                doc = fitz.open(stream=b, filetype="pdf")
                                n = min(len(doc), 3)
                                for i in range(n):
                                    pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                                    pages.append(pix.tobytes("png"))
                                doc.close()
                                ocr_images.extend(pages)
                            except Exception:
                                pass

                        if ocr_images:
                            ocr_text = local_ocr_images_to_text(ocr_images)
                            used_for_ai = clean_text(used_for_ai + "\n\n" + ocr_text)
                        prog.progress(55)

                if ocr_mode.startswith("🤖") and SS.vision_urls_generate:
                    with st.spinner("Vision 讀圖/讀 PDF 中…"):
                        prog.progress(65)
                        if supports_vision(cfg):
                            items = vision_generate_questions(
                                cfg,
                                used_for_ai,
                                SS.vision_urls_generate,
                                subject,
                                level_code,
                                question_count,
                                fast_mode=fast_mode,
                            )
                        else:
                            items = generate_questions(cfg, used_for_ai, subject, level_code, question_count, fast_mode=fast_mode)
                        prog.progress(90)
                else:
                    with st.spinner("AI 生成題目中…"):
                        prog.progress(70)
                        items = generate_questions(cfg, used_for_ai, subject, level_code, question_count, fast_mode=fast_mode)
                        prog.progress(90)

                SS.generated_items = items or []
                prog.progress(100)
                st.success("✅ 題目生成完成")

            except Exception as e:
                show_exception("生成失敗", e)

    SS.generated_items = render_results_one_glance(SS.generated_items, "④ 結果", "display_mode_generate") or SS.generated_items

    if isinstance(SS.generated_items, list) and SS.generated_items:
        st.markdown("## ⑤ 匯出")
        if _HAS_EXPORT_PANEL:
            try:
                render_export_panel(items=SS.generated_items, subject=subject, google_creds=SS.google_creds, mode="generate")
            except Exception:
                st.warning("內建 Export Panel 暫不可用，已用保底匯出")

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️ Kahoot（Excel）",
                data=export_kahoot_excel(SS.generated_items),
                file_name=f"kahoot_{now_stamp()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.download_button(
                "⬇️ Wayground（DOCX）",
                data=export_wayground_docx(SS.generated_items, title=f"{subject} 題目清單"),
                file_name=f"wayground_{now_stamp()}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )


# =========================================================
# Import
# =========================================================
with tab_imp:
    st.markdown("## ① 上載 / 貼上題目")
    uploads = st.file_uploader(
        "DOCX / PDF / XLSX / PPTX / TXT / 圖片",
        type=["pdf", "docx", "xlsx", "pptx", "txt", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="up_imp",
    )
    pasted = st.text_area("或直接貼上題目文字", value="", height=150)

    if uploads:
        with st.status("正在擷取題目內容…", expanded=False) as s:
            s.update(label="正在擷取題目內容…", state="running")
            text, v_urls, img_bytes, pdf_scan, report = extract_payload_from_uploads(uploads)
            SS.extracted_text_import = clean_text(text + "\n\n" + pasted)
            SS.vision_urls_import = v_urls
            SS.image_bytes_import = img_bytes
            SS.pdf_scan_bytes_import = pdf_scan
            SS.file_extract_report_import = report
            s.update(label="擷取完成", state="complete")

        with st.expander("📄 擷取報告（每檔抽取字數）", expanded=False):
            st.dataframe(pd.DataFrame(SS.file_extract_report_import), use_container_width=True)
    else:
        SS.extracted_text_import = clean_text(pasted)

    st.markdown("## ②（可選）勾選要整理的重點段落")
    limit = 8000 if fast_mode else 10000
    used = render_paragraph_picker(SS.extracted_text_import, "mark_idx_import", limit=limit)
    st.info(f"送入 AI（重點合併後）{len(used)} 字（上限 {limit}）")

    st.markdown("## ③ 整理並轉換")
    use_ai = st.checkbox("使用 AI 協助整理（建議）", value=True)

    if st.button("✨ 整理並轉換", key="btn_imp"):
        if use_ai and not cfg.get("api_key"):
            st.error("請先在左側輸入 API Key")
        else:
            try:
                prog = st.progress(0)
                prog.progress(20)

                used_for_ai = used
                if ocr_mode.startswith("🔬") and ocr_ok:
                    with st.spinner("本地 OCR 處理中…"):
                        prog.progress(40)
                        ocr_images = list(SS.image_bytes_import)
                        for b in SS.pdf_scan_bytes_import:
                            try:
                                pages = []
                                import fitz
                                doc = fitz.open(stream=b, filetype="pdf")
                                n = min(len(doc), 3)
                                for i in range(n):
                                    pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                                    pages.append(pix.tobytes("png"))
                                doc.close()
                                ocr_images.extend(pages)
                            except Exception:
                                pass
                        if ocr_images:
                            ocr_text = local_ocr_images_to_text(ocr_images)
                            used_for_ai = clean_text(used_for_ai + "\n\n" + ocr_text)
                        prog.progress(60)

                if use_ai:
                    with st.spinner("AI 正在整理題目…"):
                        prog.progress(80)
                        SS.imported_items = assist_import_questions(cfg, used_for_ai, subject) or []
                else:
                    SS.imported_items = parse_import_questions_locally(used_for_ai) or []

                prog.progress(100)
                st.success("✅ 題目整理完成")

            except Exception as e:
                show_exception("整理失敗", e)

    SS.imported_items = render_results_one_glance(SS.imported_items, "④ 整理結果", "display_mode_import") or SS.imported_items

    if isinstance(SS.imported_items, list) and SS.imported_items:
        st.markdown("## ⑤ 匯出")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️ Kahoot（Excel）",
                data=export_kahoot_excel(SS.imported_items),
                file_name=f"kahoot_import_{now_stamp()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with c2:
            st.download_button(
                "⬇️ Wayground（DOCX）",
                data=export_wayground_docx(SS.imported_items, title=f"{subject}（匯入）題目清單"),
                file_name=f"wayground_import_{now_stamp()}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
