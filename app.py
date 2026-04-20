# =========================
# app.py — Final Stable Version
# =========================

import io
import traceback
import hashlib
import streamlit as st
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
from services.cache_service import load_cache, save_cache
from extractors.extract import extract_text, extract_images_for_llm_ocr
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    credentials_from_dict,
)
from services.google_forms_api import create_quiz_form
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# -------------------------
# Session State Init
# -------------------------
if "generated_items" not in st.session_state:
    st.session_state.generated_items = []
if "imported_items" not in st.session_state:
    st.session_state.imported_items = []

for k, v in {
    "google_creds": None,
    "mark_idx": set(),
    "form_result_generate": None,
    "form_result_import": None,
}.items():
    st.session_state.setdefault(k, v)

# -------------------------
# Helpers
# -------------------------
def show_exception(user_msg: str, e: Exception):
    st.error(user_msg)
    with st.expander("🔎 技術細節（維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

def drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def upload_bytes_to_drive(creds, filename, mimetype, data_bytes):
    service = drive_service(creds)
    media = MediaIoBaseUpload(
        io.BytesIO(data_bytes),
        mimetype=mimetype,
        resumable=False,
    )
    meta = {"name": filename}
    return service.files().create(
        body=meta,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

def share_file_to_emails(creds, file_id, emails):
    service = drive_service(creds)
    for email in emails:
        body = {
            "type": "user",
            "role": "reader",
            "emailAddress": email,
        }
        service.permissions().create(
            fileId=file_id,
            body=body,
            sendNotificationEmail=True,
        ).execute()

# -------------------------
# ✅ Export & Share Panel (FINAL)
# -------------------------
def export_and_share_panel(selected_df: pd.DataFrame, subject_name: str, prefix: str):
    """
    FINAL STABLE EXPORT PANEL
    - Excel / Word / Google Forms / Drive Email Share
    - Render-guarded (no duplicate key)
    - Stable button keys
    """

    # ✅ Render guard (critical)
    guard_key = f"_export_panel_rendered_{prefix}"
    if st.session_state.get(guard_key):
        return
    st.session_state[guard_key] = True

    if selected_df is None or selected_df.empty:
        st.warning("⚠️ 尚未選擇任何題目（請勾選『匯出』）。")
        return

    panel_id = f"export_{prefix}"

    kahoot_bytes = export_kahoot_excel(selected_df)
    docx_bytes = export_wayground_docx(selected_df, subject_name)

    st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")

    # --------- Download ----------
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Kahoot Excel",
            data=kahoot_bytes,
            file_name=f"{subject_name}_kahoot.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_kahoot_{panel_id}",
        )
    with c2:
        st.download_button(
            "⬇️ Wayground DOCX",
            data=docx_bytes,
            file_name=f"{subject_name}_wayground.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key=f"dl_wayground_{panel_id}",
        )

    # --------- Google Form ----------
    st.markdown("### 🟦 Google Forms")
    if st.session_state.get("google_creds"):
        if st.button("🟦 一鍵建立 Google Form Quiz", key=f"btn_form_{panel_id}"):
            try:
                with st.spinner("🟦 正在建立 Google Form…"):
                    creds = credentials_from_dict(st.session_state.google_creds)
                    result = create_quiz_form(
                        creds,
                        f"{subject_name} Quiz",
                        selected_df,
                    )
                st.session_state[f"form_result_{prefix}"] = result
                st.success("✅ 已成功建立 Google Form")
            except Exception as e:
                show_exception("⚠️ 建立 Google Form 失敗。", e)

        result = st.session_state.get(f"form_result_{prefix}")
        if result:
            st.markdown(f"🔗 **編輯連結：** {result.get('editUrl')}")
            st.markdown(f"👥 **作答連結：** {result.get('responderUrl')}")

    else:
        st.info("請先在左側登入 Google。")

    # --------- Drive Email Share ----------
    st.markdown("### 📧 一鍵電郵分享匯出檔（Google Drive）")
    if not st.session_state.get("google_creds"):
        st.info("請先登入 Google 才可使用電郵分享。")
        return

    emails_text = st.text_input(
        "收件人電郵（多個用逗號分隔）",
        key=f"emails_{panel_id}",
    )
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    cA, cB = st.columns(2)

    with cA:
        if st.button("📧 分享 Kahoot Excel", key=f"btn_share_kahoot_{panel_id}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(st.session_state.google_creds)
                    uploaded = upload_bytes_to_drive(
                        creds,
                        f"{subject_name}_kahoot.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        kahoot_bytes,
                    )
                    share_file_to_emails(creds, uploaded["id"], emails)
                    st.success("✅ 已成功以電郵分享 Kahoot Excel")
                    st.markdown(f"🔗 **檔案連結：** {uploaded.get('webViewLink')}")
                except Exception as e:
                    show_exception("⚠️ 電郵分享失敗。", e)

    with cB:
        if st.button("📧 分享 Wayground DOCX", key=f"btn_share_docx_{panel_id}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(st.session_state.google_creds)
                    uploaded = upload_bytes_to_drive(
                        creds,
                        f"{subject_name}_wayground.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        docx_bytes,
                    )
                    share_file_to_emails(creds, uploaded["id"], emails)
                    st.success("✅ 已成功以電郵分享 Wayground DOCX")
                    st.markdown(f"🔗 **檔案連結：** {uploaded.get('webViewLink')}")
                except Exception as e:
                    show_exception("⚠️ 電郵分享失敗。", e)

# -------------------------
# Page config + session
# -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")


for k, v in {
    "google_creds": None,
    "generated_data": None,
    "imported_data": None,
    "imported_text": "",
    "mark_idx": set(),
    "form_result_generate": None,
    "form_result_import": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

    
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
# Sidebar: Google connect
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
# Sidebar: AI API config
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
def _detect_xai_model_cached(k: str, u: str) -> str:
    return get_xai_default_model(k, u)


if preset == "Grok (xAI)" and auto_xai and api_key:
    detected = _detect_xai_model_cached(api_key, base_url)
    if detected and detected != model:
        model = detected
        st.sidebar.caption(f"✅ 已自動選用：{model}")


def api_config():
    if preset == "Azure OpenAI":
        return {"type": "azure", "api_key": api_key, "endpoint": azure_endpoint, "deployment": azure_deployment, "api_version": azure_api_version}
    return {"type": "openai_compat", "api_key": api_key, "base_url": base_url, "model": model}


def can_call_ai(cfg: dict):
    if not cfg.get("api_key"):
        return False
    if cfg.get("type") == "azure":
        return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
    return bool(cfg.get("base_url")) and bool(cfg.get("model"))


# API test
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
            st.sidebar.success(f"✅ 成功：{r.get('latency_ms', 0)} ms；回覆：{r.get('output','')}")
        else:
            st.sidebar.error("❌ 失敗：請檢查 Key/Endpoint/Model 或服務狀態")
            st.sidebar.code(r.get("error", ""))

st.sidebar.divider()

# Teaching settings
st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox(
    "科目",
    ["中國語文","英國語文","數學","公民與社會發展","科學","公民、經濟及社會","物理","化學","生物","地理","歷史","中國歷史","宗教",
     "資訊及通訊科技（ICT）","經濟","企業、會計與財務概論","旅遊與款待"],
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
# Main: flow guide + tabs
# -------------------------
with st.expander("🧭 使用流程（建議）", expanded=True):
    st.markdown(
        """
**🪄 生成新題目（推薦）**
1. 左側完成：Google 登入（可選）＋設定 AI API
2. 選科目、難度、題目數目
3. 上載教材 →（可選）標記重點段落
4. 按「生成題目」→ 在表格內微調題幹/選項/答案
5. 勾選要匯出的題目 → 匯出 Kahoot/Wayground、建立 Google Form、或用電郵分享

**📄 匯入現有題目**
1. 上載/貼上題目內容 →（可選）啟用 AI 協助整理
2. 按「整理並轉換」→ 在表格內校對答案
3. 匯出 / 建 Google Form / 電郵分享
        """
    )

tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])


# =========================
# Tab 1: Generate
# =========================
with tab_generate:
    st.markdown("## ① 上載教材")
    st.caption("上載教材後由 AI 生成題目。")

    cfg = api_config()

    reset_generation = st.checkbox(
        "🧹 清除上一輪生成記憶（切換課題時建議勾選）",
        value=False,
        help="清空上一輪生成的題目與快取，確保新一輪出題不受影響。",
    )

    files = st.file_uploader(
        "上載教材檔案",
        accept_multiple_files=True,
        type=["pdf", "docx", "txt", "pptx", "xlsx"],
        key="files_generate",
    )

    raw_text = ""
    if files:
        with st.spinner("📄 正在擷取文字…"):
            raw_text = "".join(extract_text(f) for f in files)

        st.info(f"✅ 已擷取 {len(raw_text)} 字")

    # ===== ③ 生成題目 =====
    st.markdown("## ③ 生成題目")

    limit = 8000 if fast_mode else 10000

    if st.button(
        "🪄 生成題目",
        disabled=not (can_call_ai(cfg) and bool(raw_text.strip())),
        key="btn_generate",
    ):
        try:
            if reset_generation:
                st.session_state.generated_items = []
                try:
                    save_cache({})
                except Exception:
                    pass

            used_text = build_text_with_highlights(
                raw_text, st.session_state.mark_idx, limit
            )

            with st.spinner("🤖 正在生成…"):
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
                st.session_state.generated_items = dicts_to_items(
                    data,
                    subject=subject,
                    source="generate",
                )
                st.success(f"✅ 成功生成 {len(st.session_state.generated_items)} 題")

        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)

    # =================================================
    # ④＋⑤ 檢視、匯出（共用 panel）
    # =================================================
    if st.session_state.generated_items:
        items = st.session_state.generated_items

        # 題目品質摘要
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

        # ✅ 第一次顯示時，預設全選匯出（避免匯出區永遠不顯示）
        if "export_init_generate" not in st.session_state:
            df["export"] = True
            st.session_state.export_init_generate = True

        edited = st.data_editor(
            df,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "export": st.column_config.CheckboxColumn("匯出", width="small"),
                "correct": st.column_config.SelectboxColumn(
                    "正確答案（1–4）",
                    options=["1", "2", "3", "4"],
                    width="small",
                ),
                "needs_review": st.column_config.CheckboxColumn(
                    "需教師確認",
                    width="small",
                ),
            },
            disabled=["subject", "qtype"],
            key="editor_generate",
        )

        selected = edited[edited["export"] == True].copy()

        export_and_share_panel(
            selected,
            subject,
            prefix="import",
        )

# =========================
# Tab 2: Import
# =========================
with tab_import:
    st.markdown("## ① 匯入現有題目")
    st.caption("貼上或上載題目，整理成標準單選題。")

    import_text = st.text_area(
        "貼上題目內容",
        height=280,
        key="import_text",
    )

    import_files = st.file_uploader(
        "上載 DOCX / TXT / PDF",
        type=["docx", "txt", "pdf"],
        accept_multiple_files=True,
        key="files_import",
    )

    raw_import_text = import_text.strip()
    if import_files:
        with st.spinner("📄 正在擷取文字…"):
            raw_import_text += "\n\n" + "".join(
                extract_text(f) for f in import_files
            )

    # ✅ AI assist toggle
    use_ai_assist = st.checkbox(
        "🤖（可選）啟用 AI 協助整理題目",
        value=True,
        help="關閉後只使用本地規則拆題，不會呼叫 AI。",
    )

    st.markdown("## ② 整理並轉換")

    cfg = api_config()

    if st.button(
        "✨ 整理並轉換",
        disabled=not raw_import_text.strip(),
        key="btn_import_parse",
    ):
        try:
            with st.spinner("🧠 正在整理題目…"):
                if use_ai_assist and can_call_ai(cfg):
                    data = assist_import_questions(
                        cfg,
                        raw_import_text,
                        subject,
                        fast_mode=fast_mode,
                        qtype="single",
                    )
                else:
                    data = parse_import_questions_locally(
                        raw_import_text,
                    )

            if not data:
                st.error("❌ 無法解析任何題目")
            else:
                st.session_state.imported_items = dicts_to_items(
                    data,
                    subject=subject,
                    source="import",
                )
                st.success(f"✅ 成功整理 {len(st.session_state.imported_items)} 題")

        except Exception as e:
            show_exception("⚠️ 整理並轉換失敗。", e)

    # =================================================
    # ④＋⑤（匯入）
    # =================================================
    if st.session_state.imported_items:
        items = st.session_state.imported_items

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

        # ✅ 第一次顯示時，預設全選匯出（避免匯出區永遠不顯示）
        if "export_init_import" not in st.session_state:
            df["export"] = True
            st.session_state.export_init_import = True

        edited = st.data_editor(
            df,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "export": st.column_config.CheckboxColumn("匯出", width="small"),
                "correct": st.column_config.SelectboxColumn(
                    "正確答案（1–4）",
                    options=["1", "2", "3", "4"],
                    width="small",
                ),
                "needs_review": st.column_config.CheckboxColumn(
                    "需教師確認",
                    width="small",
                ),
            },
            disabled=["subject", "qtype"],
            key="editor_import",
        )

        selected = edited[edited["export"] == True].copy()

        export_and_share_panel(
            selected,
            subject,
            prefix="import",
        )
