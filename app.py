# app.py — Full stable version with OCR / Vision mode

import io
import traceback
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from core.question_mapper import dicts_to_items, items_to_editor_df
from exporters.export_kahoot import export_kahoot_excel
from exporters.export_wayground_docx import export_wayground_docx
from services.llm_service import (
    xai_pick_vision_model,
    llm_ocr_extract_text,
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
    get_xai_default_model,
)
from services.cache_service import save_cache
from extractors.extract import extract_text, extract_payload, extract_images_for_llm_ocr
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)
from services.google_forms_api import create_quiz_form
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# -------------------------
# Session State Init
# -------------------------
_SS_DEFAULTS = {
    "google_creds": None,
    "generated_items": [],
    "imported_items": [],
    "generated_report": [],
    "imported_report": [],
    "mark_idx": set(),
    "imported_text": "",
    "form_result_generate": None,
    "form_result_import": None,
    "export_init_generate": None,
    "export_init_import": None,
    "_export_panel_rendered_generate": False,
    "_export_panel_rendered_import": False,
    "current_section": None,
}
for _k, _v in _SS_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

st.session_state["_export_panel_rendered_generate"] = False
st.session_state["_export_panel_rendered_import"] = False

# -------------------------
# Helpers
# -------------------------
def build_text_with_highlights(raw_text, marked_idx, limit):
    if not raw_text:
        return ""
    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    highlighted = []
    others = []
    for idx, p in enumerate(paragraphs):
        if idx in marked_idx:
            highlighted.append(p)
        else:
            others.append(p)
    combined = []
    if highlighted:
        combined.append("【重點段落】")
        combined.extend(highlighted)
    if others:
        combined.append("【其餘內容】")
        combined.extend(others)
    final_text = "\n\n".join(combined)
    if limit and len(final_text) > limit:
        final_text = final_text[:limit]
    return final_text


def show_exception(user_msg, e):
    st.error(user_msg)
    with st.expander("🔎 技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_bytes_to_drive(creds, filename, mimetype, data_bytes):
    service = drive_service(creds)
    media = MediaIoBaseUpload(io.BytesIO(data_bytes), mimetype=mimetype, resumable=False)
    meta = {"name": filename}
    return service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()


def share_file_to_emails(creds, file_id, emails):
    service = drive_service(creds)
    for email in emails:
        body = {"type": "user", "role": "reader", "emailAddress": email}
        service.permissions().create(fileId=file_id, body=body, sendNotificationEmail=True).execute()


# -------------------------
# Export & Share Panel
# -------------------------
def export_and_share_panel(selected_df, subject_name, prefix):
    guard_key = "_export_panel_rendered_" + prefix
    if st.session_state.get(guard_key):
        return
    st.session_state[guard_key] = True
    st.session_state.current_section = "export"

    st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")

    if selected_df is None or selected_df.empty:
        st.warning("⚠️ 尚未選擇任何題目（請勾選『匯出』）。")
        return

    panel_id = "export_" + prefix
    kahoot_bytes = export_kahoot_excel(selected_df)
    docx_bytes = export_wayground_docx(selected_df, subject_name)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Kahoot Excel",
            data=kahoot_bytes,
            file_name=subject_name + "_kahoot.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_kahoot_" + panel_id,
        )
    with c2:
        st.download_button(
            "⬇️ Wayground DOCX",
            data=docx_bytes,
            file_name=subject_name + "_wayground.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="dl_wayground_" + panel_id,
        )

    st.markdown("### 🟦 Google Forms")
    if st.session_state.get("google_creds"):
        if st.button("🟦 一鍵建立 Google Form Quiz", key="btn_form_" + panel_id):
            try:
                with st.spinner("🟦 正在建立 Google Form…"):
                    creds = credentials_from_dict(st.session_state.google_creds)
                    result = create_quiz_form(creds, subject_name + " Quiz", selected_df)
                    st.session_state["form_result_" + prefix] = result
                    st.success("✅ 已成功建立 Google Form")
            except Exception as e:
                show_exception("⚠️ 建立 Google Form 失敗。", e)
        result = st.session_state.get("form_result_" + prefix)
        if result:
            st.markdown("🔗 **編輯連結：** " + str(result.get("editUrl")))
            st.markdown("👥 **作答連結：** " + str(result.get("responderUrl")))
    else:
        st.info("請先在左側登入 Google。")

    st.markdown("### 📧 一鍵電郵分享匯出檔（Google Drive）")
    if not st.session_state.get("google_creds"):
        st.info("請先登入 Google 才可使用電郵分享。")
        return

    emails_text = st.text_input("收件人電郵（多個用逗號分隔）", key="emails_" + panel_id)
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    cA, cB = st.columns(2)
    with cA:
        if st.button("📧 分享 Kahoot Excel", key="btn_share_kahoot_" + panel_id):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(st.session_state.google_creds)
                    uploaded = upload_bytes_to_drive(
                        creds,
                        subject_name + "_kahoot.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        kahoot_bytes,
                    )
                    share_file_to_emails(creds, uploaded["id"], emails)
                    st.success("✅ 已成功以電郵分享 Kahoot Excel")
                    st.markdown("🔗 **檔案連結：** " + str(uploaded.get("webViewLink")))
                except Exception as e:
                    show_exception("⚠️ 電郵分享失敗。", e)
    with cB:
        if st.button("📧 分享 Wayground DOCX", key="btn_share_docx_" + panel_id):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(st.session_state.google_creds)
                    uploaded = upload_bytes_to_drive(
                        creds,
                        subject_name + "_wayground.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        docx_bytes,
                    )
                    share_file_to_emails(creds, uploaded["id"], emails)
                    st.success("✅ 已成功以電郵分享 Wayground DOCX")
                    st.markdown("🔗 **檔案連結：** " + str(uploaded.get("webViewLink")))
                except Exception as e:
                    show_exception("⚠️ 電郵分享失敗。", e)


# -------------------------
# Page config
# -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# -------------------------
# OAuth callback
# -------------------------
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

# -------------------------
# Sidebar: Google
# -------------------------
st.sidebar.header("🟦 Google 連接（Google Forms / Google Drive 一鍵分享檔案）")
if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth（Secrets: google_oauth_client + APP_URL）")
else:
    if st.session_state.google_creds:
        st.sidebar.success("✅ 已連接 Google")
        if st.sidebar.button("🔒 登出 Google", key="btn_logout_google"):
            st.session_state.google_creds = None
            st.rerun()
    else:
        st.sidebar.link_button("🔐 連接 Google（登入）", get_auth_url())
        st.sidebar.caption("提示：請以學校電郵登入，方便統一管理與分享。")

st.sidebar.divider()

# -------------------------
# Sidebar: AI API
# -------------------------
fast_mode = st.sidebar.checkbox(
    "⚡ 快速模式",
    value=True,
    help="較快、較保守：較短輸出與較短超時；適合日常快速出題。",
)
st.sidebar.caption("關閉快速模式：較慢，但題目更豐富/更有變化。")

st.sidebar.header("🔌 AI API 設定")
preset = st.sidebar.selectbox(
    "快速選擇（簡易）",
    ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"],
    key="preset",
)
api_key = st.sidebar.text_input("API Key", type="password", key="api_key")

auto_xai = False
if preset == "DeepSeek":
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
elif preset == "OpenAI":
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
elif preset == "Grok (xAI)":
    base_url = "https://api.x.ai/v1"
    model = "grok-4-latest"
    auto_xai = st.sidebar.checkbox("🤖 自動偵測可用最新 Grok 型號（建議）", value=True, key="auto_xai")
elif preset == "Azure OpenAI":
    base_url = ""
    model = ""
else:
    base_url = st.sidebar.text_input("Base URL（含 /v1）", value="", key="custom_base_url")
    model = st.sidebar.text_input("Model", value="", key="custom_model")

azure_endpoint = ""
azure_deployment = ""
azure_api_version = "2024-02-15-preview"
if preset == "Azure OpenAI":
    with st.sidebar.expander("⚙️ Azure 設定", expanded=True):
        azure_endpoint = st.text_input("Azure Endpoint", value="", key="azure_endpoint")
        azure_deployment = st.text_input("Deployment name", value="", key="azure_deployment")
        azure_api_version = st.text_input("API version", value="2024-02-15-preview", key="azure_api_version")


@st.cache_data(ttl=600, show_spinner=False)
def _detect_xai_model_cached(k, u):
    return get_xai_default_model(k, u)


if preset == "Grok (xAI)" and auto_xai and api_key:
    detected = _detect_xai_model_cached(api_key, base_url)
    if detected and detected != model:
        model = detected
        st.sidebar.caption("✅ 已自動選用：" + model)


def api_config():
    if preset == "Azure OpenAI":
        return {
            "type": "azure",
            "api_key": api_key,
            "endpoint": azure_endpoint,
            "deployment": azure_deployment,
            "api_version": azure_api_version,
        }
    return {
        "type": "openai_compat",
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def can_call_ai(cfg):
    if not cfg.get("api_key"):
        return False
    if cfg.get("type") == "azure":
        return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
    return bool(cfg.get("base_url")) and bool(cfg.get("model"))


st.sidebar.divider()
st.sidebar.header("🧪 API 連線測試")
cfg_test = api_config()
if st.sidebar.button("🧪 一鍵測試 API（回覆 OK）", key="btn_ping_api"):
    if not can_call_ai(cfg_test):
        st.sidebar.error("請先填妥 API Key／Base URL／Model（Azure 要 Endpoint + Deployment）。")
    else:
        with st.sidebar.spinner("正在測試連線…"):
            r = ping_llm(cfg_test, timeout=25)
            if r.get("ok"):
                st.sidebar.success("✅ 成功：" + str(r.get("latency_ms", 0)) + " ms；回覆：" + str(r.get("output", "")))
            else:
                st.sidebar.error("❌ 失敗：請檢查 Key/Endpoint/Model 或服務狀態")
                st.sidebar.code(r.get("error", ""))

st.sidebar.divider()

# -------------------------
# Sidebar: OCR / Vision
# -------------------------
st.sidebar.header("🔬 OCR / 讀圖設定（數理科必讀）")
st.sidebar.caption(
    "若教材含圖表、方程式、掃描頁面，"
    "建議開啟『LLM Vision 讀圖』讓 AI 直接理解圖像內容再出題。"
)

ocr_mode = st.sidebar.radio(
    "教材擷取模式",
    [
        "📄 純文字（一般文件，最快）",
        "🔬 本地 OCR（掃描 PDF/圖片，離線）",
        "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）",
    ],
    index=0,
    key="ocr_mode",
)

vision_pdf_max_pages = 3
if ocr_mode == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）":
    vision_pdf_max_pages = st.sidebar.slider(
        "Vision PDF 最多讀取頁數",
        min_value=1,
        max_value=10,
        value=3,
        key="vision_pdf_max_pages",
        help="頁數越多越準確，但耗時及費用也越高。",
    )
    st.sidebar.info(
        "💡 此模式需要支援圖像輸入的模型，DeepSeek不支援相關功能，請改用 GPT-4o、Grok 等視覺模型；"
        "如模型不支援，程式會自動回退至純文字出題。"
    )

st.sidebar.divider()
st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox(
    "科目",
    [
        "中國語文", "英國語文", "數學", "公民與社會發展", "科學", "公民、經濟及社會",
        "物理", "化學", "生物", "地理", "歷史", "中國歷史", "宗教",
        "資訊及通訊科技（ICT）", "經濟", "企業、會計與財務概論", "旅遊與款待",
    ],
    key="subject",
)
level_label = st.sidebar.radio(
    "🎯 難度",
    ["基礎（理解與記憶）", "標準（應用與理解）", "進階（分析與思考）", "混合（課堂活動建議）"],
    index=1,
    key="level_label",
)
level_map = {
    "基礎（理解與記憶）": "easy",
    "標準（應用與理解）": "medium",
    "進階（分析與思考）": "hard",
    "混合（課堂活動建議）": "mixed",
}
level_code = level_map[level_label]
question_count = st.sidebar.selectbox("🧮 題目數目（生成用）", [5, 8, 10, 12, 15, 20], index=2, key="question_count")

# -------------------------
# Flow guide
# -------------------------
with st.expander("🧭 使用流程", expanded=False):
    st.markdown("""
### 🪄 生成新題目
1. **左側欄** 選擇科目、難度、題目數目
2. **左側欄** 填寫 AI API Key 並按「🧪 測試 API」確認連線
3. **① 上載教材**：支援 PDF、DOCX、TXT、PPTX、XLSX、PNG、JPG
   - 掃描 PDF 或圖片：可勾選「🖼️ 啟用 LLM Vision 讀圖」直接由 AI 讀圖出題
4. **② 重點段落標記**（可選）：勾選重要段落，AI 會優先參考這些內容出題
5. 按「🪄 生成題目」→ 等待約 10–30 秒
6. **④ 檢視與微調**：在表格內直接修改題幹、選項或答案；`⚠️ 需教師確認` 的題目請優先核對
7. 勾選「匯出」欄 → **⑤ 匯出**：
   - ⬇️ 下載 Kahoot Excel（直接匯入 Kahoot）
   - ⬇️ 下載 Wayground DOCX（校本試卷格式）
   - 🟦 一鍵建立 Google Forms Quiz（需先登入 Google）
   - 📧 電郵分享至指定收件人（需先登入 Google）

---

### 📄 匯入現有題目
1. **貼上**題目內容，或**上載** DOCX / TXT / PDF 檔案
2. 選擇是否啟用「✨ AI 協助整理」（建議開啟，自動補全答案格式）
3. 按「✨ 整理並轉換」
4. 在表格內核對答案（特別留意 `⚠️ 需教師確認` 的題目）
5. 勾選「匯出」欄 → 同上匯出至 Kahoot / DOCX / Google Forms / 電郵

---

### 💡 小提示
- **⚡ 快速模式**：節省 API Token，適合日常快速出題；關閉則輸出更詳細
- **混合難度**：系統自動按 40% 基礎 / 40% 標準 / 20% 進階分配
- **Google 登入**（左側欄）：啟用後才能使用 Google Forms 建立及電郵分享功能
- 切換課題前建議勾選「🧹 清除上一輪生成記憶」，避免舊題目混入
""")

tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# =========================
# Tab 1: Generate
# =========================
with tab_generate:
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG；可配合 OCR 或 Vision 讀圖。")

    cfg = api_config()

    reset_generation = st.checkbox(
        "🧹 清除上一輪生成記憶（切換課題時建議勾選）",
        value=False,
        help="清空上一輪生成的題目與快取，確保新一輪出題不受影響。",
    )

    files = st.file_uploader(
        "上載教材檔案（可多檔）",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt", "pptx", "xlsx", "png", "jpg", "jpeg"],
        key="files_generate",
    )
    
    raw_text = ""
    vision_images = []

    if files:
        use_local_ocr = (ocr_mode == "🔬 本地 OCR（掃描 PDF/圖片，離線）")
        use_vision = (ocr_mode == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）")

        with st.spinner("📄 正在擷取教材…"):
            for f in files:
                payload = extract_payload(
                    f,
                    enable_ocr=use_local_ocr,
                    enable_vision=use_vision,
                    vision_pdf_max_pages=vision_pdf_max_pages,
                )
                if payload.get("text"):
                    raw_text += payload["text"] + "\n\n"
                if payload.get("images"):
                    vision_images.extend(payload["images"])
        raw_text = raw_text.strip()

        c1, c2 = st.columns(2)
        with c1:
            st.info("✅ 已擷取 " + str(len(raw_text)) + " 字")
        with c2:
            if vision_images:
                st.success("🖼️ 已讀取 " + str(len(vision_images)) + " 張圖像")
            elif use_vision:
                st.caption("Vision 模式未讀到圖像，將以文字內容為主。")

        if use_vision and vision_images:
            with st.expander("🖼️ 預覽已讀取圖像（前 3 張）"):
                for i, img in enumerate(vision_images[:3]):
                    st.image(img, caption="第 " + str(i + 1) + " 張／頁", use_container_width=True)

        if use_local_ocr and not raw_text:
            st.warning("⚠️ 本地 OCR 未能擷取文字；如教材含複雜圖表或方程式，建議改用 Vision 模式。")

    st.markdown("## ② 重點段落標記（可選）")
    st.caption("勾選後會把重點段落放到最前面，提高貼題度。")

    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    with st.expander("⭐ 打開段落清單（最多顯示 80 段）"):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ 全選重點段落", key="mark_all_btn"):
                st.session_state.mark_idx = set(range(len(paragraphs)))
        with c2:
            if st.button("⛔ 全不選", key="mark_none_btn"):
                st.session_state.mark_idx = set()

        for i, p in enumerate(paragraphs[:80]):
            checked = i in st.session_state.mark_idx
            new_checked = st.checkbox("第 " + str(i + 1) + " 段", value=checked, key="para_" + str(i))
            if new_checked:
                st.session_state.mark_idx.add(i)
            else:
                st.session_state.mark_idx.discard(i)
            st.write(p[:200] + ("…" if len(p) > 200 else ""))

    st.markdown("## ③ 生成題目")
    limit = 8000 if fast_mode else 10000
    can_generate = can_call_ai(cfg) and (bool(raw_text.strip()) or bool(vision_images))

    if st.button("🪄 生成題目", disabled=(not can_generate), key="btn_generate"):
        try:
            if reset_generation:
                st.session_state.generated_items = []
                try:
                    save_cache({})
                except Exception:
                    pass

            used_text = build_text_with_highlights(raw_text, st.session_state.mark_idx, limit)

            with st.spinner("🤖 正在生成題目（約需 10–40 秒）…"):
                if vision_images and ocr_mode == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）":
                    data = llm_ocr_extract_text(
                        cfg,
                        text=used_text,
                        images=vision_images,
                        subject=subject,
                        level=level_code,
                        count=question_count,
                        fast_mode=fast_mode,
                    )
                else:
                    data = generate_questions(
                        cfg,
                        used_text,
                        subject,
                        level_code,
                        question_count,
                        fast_mode=fast_mode,
                        qtype="single",
                    )

            if not data:
                st.error("❌ AI 沒有回傳任何題目")
            else:
                st.session_state.generated_items = dicts_to_items(data, subject=subject, source="generate")
                st.session_state.pop("export_init_generate", None)
                st.success("✅ 成功生成 " + str(len(st.session_state.generated_items)) + " 題")
        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)

    if st.session_state.generated_items:
        items = st.session_state.generated_items
        total_count = len(items)
        review_count = sum(1 for q in items if q.needs_review)
        ok_count = total_count - review_count

        st.markdown("## ✅ 題目品質摘要")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("✅ 通過題目", ok_count)
        with c2:
            st.metric("⚠️ 需教師留意", review_count)

        st.markdown("## ④ 檢視與微調")
        df = items_to_editor_df(items)
        if "export_init_generate" not in st.session_state:
            df["export"] = True
            st.session_state.export_init_generate = True

        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "export": st.column_config.CheckboxColumn("匯出", width="small"),
                "correct": st.column_config.SelectboxColumn("正確答案（1–4）", options=["1", "2", "3", "4"], width="small"),
                "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
            },
            disabled=["subject", "qtype"],
            key="editor_generate",
        )

        selected = edited[edited["export"] == True].copy()
        st.markdown('<div id="export_anchor_generate"></div>', unsafe_allow_html=True)
        export_and_share_panel(selected, subject, prefix="generate")

        if st.session_state.get("current_section") == "export":
            components.html(
                '<script>var el=document.getElementById("export_anchor_generate");if(el){el.scrollIntoView({behavior:"smooth"});}</script>',
                height=0,
            )

# =========================
# Tab 2: Import
# =========================
with tab_import:
    st.markdown("## ① 上載 / 貼上題目")
    st.caption("支援 DOCX / TXT 或直接貼上。匯入模式固定為單選（4 選 1）。")

    cfg = api_config()

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""

    st.file_uploader(
        "上載 DOCX / TXT（自動載入到文字框）",
        type=["docx", "txt"],
        key="import_file",
        on_change=load_import_file_to_textbox,
    )

    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True, key="use_ai_assist")
    st.text_area("貼上題目內容", height=320, key="imported_text")

    st.markdown("## ② 整理並轉換")
    import_has_text = bool(st.session_state.get("imported_text", "").strip())
    import_ai_ready = (not use_ai_assist) or can_call_ai(cfg)
    import_can_run = import_has_text and import_ai_ready

    if st.button("✨ 整理並轉換", disabled=(not import_can_run), key="btn_import_parse"):
        raw = st.session_state.get("imported_text", "").strip()
        try:
            with st.spinner("🧠 正在整理…"):
                if use_ai_assist:
                    data = assist_import_questions(cfg, raw, subject, allow_guess=True, fast_mode=fast_mode, qtype="single")
                else:
                    data = parse_import_questions_locally(raw)
            items = dicts_to_items(data, subject=subject, source="import")
            st.session_state.imported_items = items
            st.session_state.imported_report = []
            st.session_state.pop("export_init_import", None)
            st.success("✅ 已整理 " + str(len(items)) + " 題")
        except Exception as e:
            st.warning("⚠️ AI 整理失敗，改用本地拆題作備援，請老師核對答案。")
            data = parse_import_questions_locally(raw)
            items = dicts_to_items(data, subject=subject, source="local")
            st.session_state.imported_items = items
            st.session_state.imported_report = []
            st.exception(e)

    if st.session_state.imported_items:
        st.markdown("## ③ 檢視與微調")
        df = items_to_editor_df(st.session_state.imported_items)

        if "export_init_import" not in st.session_state:
            df["export"] = True
            st.session_state.export_init_import = True

        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "export": st.column_config.CheckboxColumn("匯出", width="small"),
                "correct": st.column_config.SelectboxColumn("正確答案（1–4）", options=["1", "2", "3", "4"], width="small"),
                "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
            },
            disabled=["subject", "qtype"],
            key="editor_import",
        )

        selected = edited[edited["export"] == True].copy()
        st.markdown('<div id="export_anchor_import"></div>', unsafe_allow_html=True)
        export_and_share_panel(selected, subject, prefix="import")

        if st.session_state.get("current_section") == "export":
            components.html(
                '<script>var el=document.getElementById("export_anchor_import");if(el){el.scrollIntoView({behavior:"smooth"});}</script>',
                height=0,
            )
