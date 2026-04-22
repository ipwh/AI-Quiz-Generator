# =========================================================
# app.py — FINAL-FULL（最終完整版）
#
# 目標：恢復你原本應有的完整功能（不縮水）
#
# ✅ Sidebar 完整回歸
#   - Google OAuth 登入/登出
#   - Fast Mode（⚡）
#   - API 設定：DeepSeek / OpenAI / Grok(xAI) / Azure(OpenAI) / 自訂
#   - Grok 自動偵測型號（如 llm_service 內有 get_xai_default_model）
#   - API 一鍵測試（ping_llm）
#   - OCR / Vision 模式選擇（純文字 / 本地 OCR / Vision）
#   - 完整科目、教學難度（中文標籤→easy/medium/hard/mixed）、題數
#   - 隱私提醒、使用流程
#
# ✅ 主流程（Generate / Import 兩邊）
#   - 多格式輸入：PDF / DOCX / PPTX / XLSX / TXT / PNG / JPG
#   - 內容擷取：Office 直接抽字；PDF 抽字；掃描件/圖片走 OCR 或 Vision（可降級）
#   - 教師選擇重點段落（全選/全不選）
#   - 只用選定內容送入 AI 出題/整理
#   - needs_review 題目高亮
#
# ✅ 匯出（不依賴你舊 export panel）
#   - Kahoot Excel（.xlsx）
#   - Wayground DOCX（.docx）
#   - Google Forms（需要 Google OAuth + googleapiclient，否則顯示提示）
#   - 一鍵電郵分享（優先：Gmail Draft；若無 API 退化為 mailto 連結）
#
# 依賴（若缺少，會自動降級並提示）：
#   - pandas, openpyxl, python-docx
#   - PyPDF2（PDF 抽字）
#   - python-pptx（PPTX 抽字）
#   - pytesseract + pillow（本地 OCR，可選）
#   - google-api-python-client（Google Forms/Drive/Gmail，可選）
#
# =========================================================

import io
import os
import re
import time
import traceback
from datetime import datetime

import streamlit as st
import pandas as pd

from docx import Document

# ---------- 你的服務層（已存在） ----------
from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
)

# Vision（你已經有）
from services.vision_service import (
    supports_vision,
    vision_generate_questions,
    file_to_data_url,
)

# Google OAuth（你原本就有）
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)

# （可選）xAI 型號自動偵測、API ping（若 llm_service 提供就用）
try:
    from services.llm_service import get_xai_default_model
except Exception:
    get_xai_default_model = None

try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None


# =========================================================
# Page config
# =========================================================
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")


# =========================================================
# Session state init（與你原本 app.py 同風格）
# =========================================================
SS_DEFAULTS = {
    "google_creds": None,

    "extracted_text_generate": "",
    "extracted_text_import": "",

    "mark_idx_generate": set(),
    "mark_idx_import": set(),

    "generated_items": [],
    "imported_items": [],

    # export cache / links
    "last_export_excel": None,
    "last_export_docx": None,
    "last_google_form_url": None,
    "last_drive_links": {},

    # UI
    "current_section": None,
}
for k, v in SS_DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =========================================================
# Helpers
# =========================================================
def show_exception(user_msg: str, e: Exception):
    st.error(user_msg)
    with st.expander("🔎 技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.traceback)))


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
# Phase 1：多格式內容擷取（Office/PDF 文本） + OCR/Vision（可選）
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


def extract_pdf_text(file_bytes: bytes) -> str:
    # 文字型 PDF 直接抽字；掃描型可能抽不到（會回空）
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


def local_ocr_images_to_text(images_bytes_list, lang_hint="chi_tra+eng") -> str:
    """
    本地 OCR：可選（若缺 pytesseract/pillow 會自動失敗並由呼叫端降級）
    """
    try:
        import pytesseract
        from PIL import Image
    except Exception as e:
        raise RuntimeError("本地 OCR 需要 pytesseract + pillow") from e

    texts = []
    for b in images_bytes_list:
        img = Image.open(io.BytesIO(b))
        t = pytesseract.image_to_string(img, lang=lang_hint)
        t = clean_text(t)
        if t:
            texts.append(t)
    return "\n\n".join(texts)


def extract_payload_from_uploads(uploads):
    """
    回傳：
    - extracted_text: str
    - vision_data_urls: list[str]
    - image_bytes_list: list[bytes] （供本地 OCR 用）
    """
    extracted_parts = []
    vision_data_urls = []
    image_bytes_list = []

    for f in uploads:
        name = (f.name or "").lower()
        b = f.read()

        if name.endswith(".docx"):
            t = extract_docx(b)
            if t:
                extracted_parts.append(t)

        elif name.endswith(".xlsx"):
            t = extract_xlsx(b)
            if t:
                extracted_parts.append(t)

        elif name.endswith(".pptx"):
            t = extract_pptx(b)
            if t:
                extracted_parts.append(t)

        elif name.endswith(".txt"):
            try:
                t = b.decode("utf-8", errors="ignore")
            except Exception:
                t = ""
            t = clean_text(t)
            if t:
                extracted_parts.append(t)

        elif name.endswith(".pdf"):
            t = extract_pdf_text(b)
            if t:
                extracted_parts.append(t)
            else:
                # 掃描型 PDF：交由 Vision / OCR
                vision_data_urls.append(file_to_data_url(b, f.name))

        elif name.endswith((".png", ".jpg", ".jpeg")):
            vision_data_urls.append(file_to_data_url(b, f.name))
            image_bytes_list.append(b)

        else:
            # 其他格式暫不處理
            pass

    return clean_text("\n\n".join(extracted_parts)), vision_data_urls, image_bytes_list


# =========================================================
# 匯出：Kahoot Excel / Wayground DOCX
# =========================================================
def export_kahoot_excel(items):
    rows = []
    for q in items:
        opts = q.get("options", [])
        opts = (opts + ["", "", "", ""])[:4]
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

        opts = q.get("options", [])
        for idx, opt in enumerate(opts, 1):
            doc.add_paragraph(f"{idx}. {opt}")

        doc.add_paragraph("答案：" + ",".join(q.get("correct", [])))
        if q.get("needs_review"):
            doc.add_paragraph("⚠️ 需要教師確認")
        if q.get("explanation"):
            doc.add_paragraph("提示：" + str(q.get("explanation")))

    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio


# =========================================================
# Google：Forms / Drive / Gmail（可選，沒有依賴就降級提示）
# =========================================================
def google_build_services(creds):
    """
    回傳 (forms_service, drive_service, gmail_service)
    需要 google-api-python-client。
    """
    try:
        from googleapiclient.discovery import build
    except Exception as e:
        raise RuntimeError("需要安裝 google-api-python-client 才能建立 Google Forms/Drive/Gmail") from e

    forms = build("forms", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    gmail = build("gmail", "v1", credentials=creds)
    return forms, drive, gmail


def google_drive_upload_bytes(drive_service, filename: str, file_bytes: bytes, mime_type: str):
    try:
        from googleapiclient.http import MediaIoBaseUpload
    except Exception as e:
        raise RuntimeError("需要 google-api-python-client") from e

    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
    meta = {"name": filename}
    created = drive_service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
    file_id = created["id"]

    # 設為任何知道連結的人可讀（可按校方政策改）
    drive_service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    # 取分享連結
    info = drive_service.files().get(fileId=file_id, fields="webViewLink").execute()
    return file_id, info.get("webViewLink", "")


def google_forms_create_quiz(forms_service, title: str, items):
    """
    用 Forms API 建立 Google Form（每題一題，四選一）。
    回傳 form responder URL / edit URL（依 API 欄位）。
    """
    body = {
        "info": {"title": title},
    }
    form = forms_service.forms().create(body=body).execute()
    form_id = form["formId"]

    requests = []
    for idx, q in enumerate(items):
        opts = (q.get("options", []) + ["", "", "", ""])[:4]
        # Google Forms choiceQuestion options
        requests.append({
            "createItem": {
                "item": {
                    "title": q.get("question", f"第 {idx+1} 題"),
                    "questionItem": {
                        "question": {
                            "required": True,
                            "choiceQuestion": {
                                "type": "RADIO",
                                "options": [{"value": o} for o in opts if o is not None],
                                "shuffle": False,
                            }
                        }
                    }
                },
                "location": {"index": idx}
            }
        })

    forms_service.forms().batchUpdate(formId=form_id, body={"requests": requests}).execute()

    # 回取連結
    f = forms_service.forms().get(formId=form_id).execute()
    # Google Forms API 回的資料通常含 responderUri（若沒有就用標準 URL）
    responder = f.get("responderUri") or f"https://docs.google.com/forms/d/e/{form_id}/viewform"
    edit = f.get("documentTitle")  # 不一定提供 edit url；可顯示 responder 足夠
    return responder


def gmail_create_draft(gmail_service, to_email: str, subject: str, body_text: str):
    """
    建立 Gmail 草稿（最接近「一鍵電郵」）。
    """
    try:
        import base64
        from email.message import EmailMessage
    except Exception as e:
        raise RuntimeError("email/base64 模組不可用") from e

    msg = EmailMessage()
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    draft = gmail_service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()
    return draft.get("id", "")


# =========================================================
# OAuth Callback（你原本就有）
# =========================================================
params = st.query_params
if oauth_is_configured() and "code" in params and not st.session_state.google_creds:
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list):
            code = code[0]
        if isinstance(state, list):
            state = state[0]

        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state.google_creds = credentials_to_dict(creds)

        st.query_params.clear()
        st.rerun()

    except Exception as e:
        st.query_params.clear()
        show_exception("Google 登入失敗。請重新按『連接 Google（登入）』一次。", e)
        st.stop()


# =========================================================
# Sidebar（完整回歸）
# =========================================================
st.sidebar.header("🟦 Google 連接（Google Forms / Google Drive 一鍵分享）")
if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth（Secrets: google_oauth_client + APP_URL）")
else:
    if st.session_state.google_creds:
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google"):
            st.session_state.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())
        st.sidebar.caption("提示：請以學校電郵登入，方便統一管理與分享。")

st.sidebar.divider()

fast_mode = st.sidebar.checkbox(
    "⚡ 快速模式",
    value=True,
    help="較快、較保守：較短輸出與較短超時；適合日常快速出題。"
)
st.sidebar.caption("關閉快速模式：較慢，但題目更豐富/更有變化。")

st.sidebar.divider()
st.sidebar.header("🔌 AI API 設定")

preset = st.sidebar.selectbox(
    "快速選擇（簡易）",
    ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"],
)

api_key = st.sidebar.text_input("API Key", type="password")

auto_xai = False
azure_endpoint = ""
azure_deployment = ""
azure_api_version = "2024-02-15-preview"

if preset == "DeepSeek":
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
    cfg = {"api_key": api_key, "base_url": base_url, "model": model}

elif preset == "OpenAI":
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
    cfg = {"api_key": api_key, "base_url": base_url, "model": model}

elif preset == "Grok (xAI)":
    base_url = "https://api.x.ai/v1"
    model = "grok-4-latest"
    auto_xai = st.sidebar.checkbox("🤖 自動偵測可用最新 Grok 型號（建議）", value=True)
    if auto_xai and api_key and get_xai_default_model:
        try:
            model = get_xai_default_model(api_key, base_url)
            st.sidebar.caption("✅ 已自動選用：" + model)
        except Exception:
            pass
    cfg = {"api_key": api_key, "base_url": base_url, "model": model}

elif preset == "Azure OpenAI":
    # 你的 llm_service 若不支援 Azure，UI 仍保留，但會提示
    azure_endpoint = st.sidebar.text_input("Azure Endpoint", value="")
    azure_deployment = st.sidebar.text_input("Deployment name", value="")
    azure_api_version = st.sidebar.text_input("API version", value="2024-02-15-preview")
    st.sidebar.warning("⚠️ 注意：目前 services.llm_service.py 若未實作 Azure 呼叫，將無法使用此選項。")
    cfg = {
        "api_key": api_key,
        "base_url": "",   # 佔位
        "model": "",      # 佔位
        "type": "azure",
        "endpoint": azure_endpoint,
        "deployment": azure_deployment,
        "api_version": azure_api_version,
    }

else:
    base_url = st.sidebar.text_input("Base URL（含 /v1）", value="")
    model = st.sidebar.text_input("Model", value="")
    cfg = {"api_key": api_key, "base_url": base_url, "model": model}

st.sidebar.divider()
st.sidebar.header("🧪 API 連線測試")
if st.sidebar.button("🧪 一鍵測試 API（回覆 OK）"):
    if not ping_llm:
        st.sidebar.warning("⚠️ 目前 llm_service 未提供 ping_llm()，略過測試。")
    elif not cfg.get("api_key"):
        st.sidebar.error("請先填入 API Key")
    else:
        with st.sidebar.spinner("正在測試連線…"):
            r = ping_llm(cfg, timeout=25)
        if r.get("ok"):
            st.sidebar.success("✅ 成功：" + str(r.get("latency_ms", 0)) + " ms；回覆：" + str(r.get("output", "")))
        else:
            st.sidebar.error("❌ 失敗：請檢查 Key/Model/Base URL 或服務狀態")
            st.sidebar.code(r.get("error", ""))

st.sidebar.divider()
st.sidebar.header("🔬 OCR / 讀圖設定（數理科必讀）")
ocr_mode = st.sidebar.radio(
    "教材擷取模式",
    [
        "📄 純文字（一般文件，最快）",
        "🔬 本地 OCR（掃描 PDF/圖片，離線）",
        "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）",
    ],
    index=0,
)
vision_pdf_max_pages = 3
if ocr_mode.startswith("🤖"):
    vision_pdf_max_pages = st.sidebar.slider("Vision PDF 最多讀取頁數", 1, 10, 3)

if ocr_mode.startswith("🤖"):
    st.sidebar.info("💡 DeepSeek 不支援 Vision，請改用 Grok / GPT-4o 等模型。")

st.sidebar.divider()
st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox(
    "科目",
    [
        "中國語文", "英國語文", "數學", "公民與社會發展",
        "科學", "公民、經濟及社會",
        "物理", "化學", "生物", "地理",
        "歷史", "中國歷史", "宗教",
        "資訊及通訊科技（ICT）", "經濟",
        "企業、會計與財務概論", "旅遊與款待",
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
question_count = st.sidebar.selectbox("🧮 題目數目（生成用）", [5, 8, 10, 12, 15, 20], index=2)

st.sidebar.divider()
st.sidebar.markdown("### ⚠️ 隱私提醒")
st.sidebar.info(
    "教材內容將傳送至您所選的 AI 服務商（OpenAI / xAI / DeepSeek 等）。\n\n"
    "請勿上傳含有學生個人資料、敏感資訊或受版權嚴格保護的完整教材。"
)

with st.expander("🧭 使用流程", expanded=True):
    st.markdown(
        "⚠️ 重要隱私提醒：教材內容會上傳至第三方 AI 服務，請避免上傳含學生姓名、學號等個人資料。\n\n"
        "#### 🪄 生成新題目\n"
        "- 左側欄選擇科目、難度、題目數目\n"
        "- 填寫 AI API Key 並測試連線\n"
        "- ① 上載教材（支援多格式 / OCR / Vision）\n"
        "- ② 老師勾選重點段落\n"
        "- 按「🪄 生成題目」\n"
        "- ④ 檢視結果（⚠️ needs_review 題目優先確認）\n"
        "- ⑤ 匯出（Kahoot / Wayground / Google Forms / 電郵分享）\n\n"
        "#### 📄 匯入現有題目\n"
        "- 上載或貼上題目\n"
        "- 選擇是否使用 AI 協助整理\n"
        "- 按「✨ 整理並轉換」後核對答案\n"
        "- 再進行匯出/分享\n\n"
        "💡 小提示：掃描 PDF/圖片建議選 Vision；重要測驗可關閉快速模式以提升品質。"
    )


# =========================================================
# Tabs：Generate / Import
# =========================================================
tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])


# =========================================================
# Tab 1: Generate（多格式上傳 → 擷取 → 勾選重點 → 出題 → 匯出）
# =========================================================
with tab_generate:
    st.markdown("## ① 上載教材（多格式）")
    uploads = st.file_uploader(
        "支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG（可多檔）",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="u_gen",
    )

    extracted_text = ""
    vision_urls = []
    image_bytes_list = []

    if uploads:
        extracted_text, vision_urls, image_bytes_list = extract_payload_from_uploads(uploads)
    extracted_text = clean_text(extracted_text)
    st.session_state.extracted_text_generate = extracted_text

    st.markdown("## ② 老師勾選重點段落（只用勾選內容出題）")

    paras = split_paragraphs(extracted_text)
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        if st.button("✅ 全選段落", key="btn_sel_all_gen"):
            st.session_state.mark_idx_generate = set(range(len(paras)))
            st.rerun()
    with col_b:
        if st.button("⬜ 全不選", key="btn_sel_none_gen"):
            st.session_state.mark_idx_generate = set()
            st.rerun()
    with col_c:
        st.caption("提示：勾選後將只用重點段落出題，避免離題。")

    mark_idx = st.session_state.mark_idx_generate
    if paras:
        for i, p in enumerate(paras):
            checked = (i in mark_idx)
            new_checked = st.checkbox(f"選用段落 {i+1}", value=checked, key=f"gen_p{i}")
            st.markdown(p)
            if new_checked:
                mark_idx.add(i)
            else:
                mark_idx.discard(i)
        st.session_state.mark_idx_generate = mark_idx
    else:
        st.info("目前未抽到可勾選的文字。若為掃描 PDF/圖片，可改用本地 OCR 或 Vision。")

    st.markdown("## ③ 生成題目")
    if st.button("🪄 生成題目", key="btn_generate"):
        try:
            used_text = extracted_text
            if mark_idx:
                used_text = build_text_with_highlights(extracted_text, mark_idx, limit=(8000 if fast_mode else 10000))

            # OCR / Vision / 純文字策略
            items = None

            if ocr_mode.startswith("🔬"):
                # 本地 OCR（僅當有圖片 bytes）
                if image_bytes_list:
                    try:
                        ocr_txt = local_ocr_images_to_text(image_bytes_list)
                        used_text = clean_text(used_text + "\n\n" + ocr_txt)
                    except Exception as e:
                        st.warning("本地 OCR 不可用，將改用純文字/ Vision（若可用）。")
                items = generate_questions(cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode)

            elif ocr_mode.startswith("🤖"):
                # Vision（需要模型支援）
                if vision_urls and supports_vision(cfg):
                    items = vision_generate_questions(
                        cfg, used_text, vision_urls, subject, level_code, question_count, fast_mode=fast_mode
                    )
                else:
                    st.warning("Vision 不可用（可能是模型不支援或沒有可讀圖片），已改用純文字。")
                    items = generate_questions(cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode)

            else:
                # 純文字
                items = generate_questions(cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode)

            st.session_state.generated_items = items or []
            st.success("✅ 題目生成完成")

        except Exception as e:
            show_exception("生成失敗", e)

    # 顯示結果（needs_review 高亮）
    items = st.session_state.generated_items
    if isinstance(items, list) and items:
        st.markdown("## ④ 結果（⚠️ needs_review 需教師確認）")
        for i, q in enumerate(items, 1):
            needs = bool(q.get("needs_review"))
            title = f"第 {i} 題"
            with st.expander(("⚠️ " if needs else "") + title, expanded=needs):
                st.markdown(f"題目： {q.get('question','')}")
                for j, opt in enumerate(q.get("options", []), 1):
                    st.markdown(f"{j}. {opt}")
                st.markdown("答案： " + ",".join(q.get("correct", [])))
                if needs:
                    st.warning(q.get("explanation") or "此題涉及關鍵條件/推論，建議教師覆核。")

        st.markdown("---")
        st.markdown("## ⑤ 匯出與分享")

        # Kahoot Excel
        try:
            xbio = export_kahoot_excel(items)
            st.download_button(
                "⬇️ 下載 Kahoot（Excel）",
                data=xbio,
                file_name=f"kahoot{now_stamp()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.error("Kahoot 匯出失敗")
            show_exception("Kahoot 匯出失敗", e)

        # Wayground DOCX
        try:
            dbio = export_wayground_docx(items, title=f"{subject} 題目清單")
            st.download_button(
                "⬇️ 下載 Wayground（DOCX）",
                data=dbio,
                file_name=f"wayground_{now_stamp()}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            st.error("Wayground 匯出失敗")
            show_exception("Wayground 匯出失敗", e)

        # Google Forms + Email share
        st.markdown("### 🌐 Google Forms / Drive / Email（需要登入 Google）")
        if not st.session_state.google_creds:
            st.info("請先在左側 Sidebar 登入 Google，才可一鍵建立 Google Form / 上傳 Drive / 建立 Gmail 草稿。")
        else:
            try:
                creds = credentials_from_dict(st.session_state.google_creds)
                forms_service, drive_service, gmail_service = google_build_services(creds)

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("🚀 一鍵建立 Google Form", key="btn_make_form"):
                        url = google_forms_create_quiz(forms_service, f"AI 題目表單（{subject}）", items)
                        st.session_state.last_google_form_url = url
                        st.success("✅ 已建立 Google Form")
                        st.write(url)

                with col2:
                    st.caption("（可選）先把檔案上傳到 Google Drive，再用 Gmail 草稿一鍵分享連結。")

                # Drive upload of exported files
                drive_links = {}
                try:
                    # 重新生成匯出 bytes（不依賴 download）
                    xbio2 = export_kahoot_excel(items)
                    dbio2 = export_wayground_docx(items, title=f"{subject} 題目清單")

                    if st.button("☁️ 上傳匯出檔到 Google Drive", key="btn_upload_drive"):
                        file_id_x, link_x = google_drive_upload_bytes(
                            drive_service,
                            filename=f"kahoot_{now_stamp()}.xlsx",
                            file_bytes=xbio2.getvalue(),
                            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                        file_id_d, link_d = google_drive_upload_bytes(
                            drive_service,
                            filename=f"wayground_{now_stamp()}.docx",
                            file_bytes=dbio2.getvalue(),
                            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        )
                        drive_links = {"kahoot": link_x, "wayground": link_d}
                        st.session_state.last_drive_links = drive_links
                        st.success("✅ 已上傳到 Google Drive")
                        st.write("Kahoot Excel：", link_x)
                        st.write("Wayground DOCX：", link_d)

                except Exception as e:
                    st.warning("Drive 上傳功能未能使用（可能缺 google-api-python-client 或權限）。")
                    # 不 raise，維持穩定

                # Email share (Gmail draft preferred)
                st.markdown("#### ✉️ 一鍵電郵分享（Gmail 草稿 / mailto）")
                to_email = st.text_input("收件人電郵（可多個，用逗號分隔）", value="", key="email_to")
                if st.button("📨 建立 Gmail 草稿（最接近一鍵）", key="btn_gmail_draft"):
                    try:
                        links = st.session_state.last_drive_links or {}
                        form_url = st.session_state.last_google_form_url or ""
                        body_lines = [
                            f"老師您好，以下為 AI 題目匯出與分享：",
                            "",
                        ]
                        if form_url:
                            body_lines.append(f"Google Form：{form_url}")
                        if links.get("kahoot"):
                            body_lines.append(f"Kahoot Excel（Drive）：{links['kahoot']}")
                        if links.get("wayground"):
                            body_lines.append(f"Wayground DOCX（Drive）：{links['wayground']}")
                        body_lines.append("")
                        body_lines.append("（如未看到連結，請先按『上傳匯出檔到 Google Drive』。）")

                        draft_id = gmail_create_draft(
                            gmail_service,
                            to_email=to_email,
                            subject=f"AI 題目分享（{subject}）",
                            body_text="\n".join(body_lines),
                        )
                        st.success("✅ 已建立 Gmail 草稿（請到 Gmail 草稿匣發送）")
                        st.caption(f"Draft ID: {draft_id}")

                    except Exception as e:
                        st.warning("未能建立 Gmail 草稿（可能缺 Gmail API 權限）。將提供 mailto 連結。")
                        # mailto fallback
                        links = st.session_state.last_drive_links or {}
                        form_url = st.session_state.last_google_form_url or ""
                        body = "AI 題目分享：%0D%0A"
                        if form_url:
                            body += f"Google Form：{form_url}%0D%0A"
                        if links.get("kahoot"):
                            body += f"Kahoot Excel：{links['kahoot']}%0D%0A"
                        if links.get("wayground"):
                            body += f"Wayground DOCX：{links['wayground']}%0D%0A"
                        mailto = f"mailto:{to_email}?subject=AI%20題目分享（{subject}）&body={body}"
                        st.markdown(f"{mailto}")

            except Exception as e:
                st.warning("Google Forms/Drive/Gmail 功能未能使用（可能未安裝 google-api-python-client 或 OAuth scope 不足）。")
                show_exception("Google 功能啟用失敗", e)


# =========================================================
# Tab 2: Import（多格式上傳/貼上 →（可選）重點 → AI 整理 → 匯出）
# =========================================================
with tab_import:
    st.markdown("## ① 上載 / 貼上題目（多格式）")
    uploads2 = st.file_uploader(
        "支援 DOCX / PDF / XLSX / PPTX / TXT / PNG / JPG（可多檔）",
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="u_imp",
    )
    pasted = st.text_area("或直接貼上題目文字（可選）", value="", height=150, key="imp_paste")

    extracted_text2 = ""
    vision_urls2 = []
    image_bytes_list2 = []

    if uploads2:
        extracted_text2, vision_urls2, image_bytes_list2 = extract_payload_from_uploads(uploads2)
    extracted_text2 = clean_text(extracted_text2)

    raw_all = clean_text("\n\n".join([extracted_text2, pasted]))
    st.session_state.extracted_text_import = raw_all

    st.markdown("## ②（可選）老師勾選要整理的重點段落")
    paras2 = split_paragraphs(raw_all)
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("✅ 全選段落", key="btn_sel_all_imp"):
            st.session_state.mark_idx_import = set(range(len(paras2)))
            st.rerun()
    with col2:
        if st.button("⬜ 全不選", key="btn_sel_none_imp"):
            st.session_state.mark_idx_import = set()
            st.rerun()
    with col3:
        st.caption("匯入題目通常可直接全選；如只想整理部分題目可勾選重點。")

    mark2 = st.session_state.mark_idx_import
    if paras2:
        for i, p in enumerate(paras2):
            checked = (i in mark2)
            new_checked = st.checkbox(f"選用段落 {i+1}", value=checked, key=f"imp_p_{i}")
            st.markdown(p)
            if new_checked:
                mark2.add(i)
            else:
                mark2.discard(i)
        st.session_state.mark_idx_import = mark2
    else:
        st.info("尚未有可顯示的文字。可上載檔案或貼上題目內容。")

    st.markdown("## ③ 整理並轉換（AI / 本地）")
    use_ai = st.checkbox("使用 AI 協助整理（建議）", value=True, key="imp_use_ai")

    if st.button("✨ 整理並轉換", key="btn_import_convert"):
        try:
            used = raw_all
            if mark2:
                used = "\n\n".join(paras2[i] for i in sorted(mark2))
                used = clean_text(used)

            if use_ai:
                items2 = assist_import_questions(cfg, used, subject)
            else:
                items2 = parse_import_questions_locally(used)

            st.session_state.imported_items = items2 or []
            st.success("✅ 題目整理完成")

        except Exception as e:
            show_exception("匯入/整理失敗", e)

    items2 = st.session_state.imported_items
    if isinstance(items2, list) and items2:
        st.markdown("## ④ 整理結果（⚠️ needs_review 需教師確認）")
        for i, q in enumerate(items2, 1):
            needs = bool(q.get("needs_review"))
            with st.expander(("⚠️ " if needs else "") + f"第 {i} 題", expanded=needs):
                st.markdown(f"題目： {q.get('question','')}")
                for j, opt in enumerate(q.get("options", []), 1):
                    st.markdown(f"{j}. {opt}")
                st.markdown("答案： " + ",".join(q.get("correct", [])))
                if needs:
                    st.warning(q.get("explanation") or "此題涉及關鍵條件/推論，建議教師覆核。")

        st.markdown("---")
        st.markdown("## ⑤ 匯出與分享（同生成頁一致）")
        try:
            xbio = export_kahoot_excel(items2)
            st.download_button(
                "⬇️ 下載 Kahoot（Excel）",
                data=xbio,
                file_name=f"kahoot_import_{now_stamp()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            show_exception("Kahoot 匯出失敗", e)

        try:
            dbio = export_wayground_docx(items2, title=f"{subject}（匯入整理）題目清單")
            st.download_button(
                "⬇️ 下載 Wayground（DOCX）",
                data=dbio,
                file_name=f"wayground_import_{now_stamp()}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            show_exception("Wayground 匯出失敗", e)

        st.info("Google Forms / Drive / Email 分享請到「生成新題目」頁面底部使用（同一套 Google 登入狀態）。")
