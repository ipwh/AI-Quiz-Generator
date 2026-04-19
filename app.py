import io
import traceback
import hashlib
import streamlit as st
import pandas as pd

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
    get_xai_default_model,
)
from services.cache_service import load_cache, save_cache
from extractors.extract import extract_text
from exporters.export_kahoot import export_kahoot
from exporters.export_wayground_docx import export_wayground_docx

from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)
from services.google_forms_api import create_quiz_form


def stable_key(*parts) -> str:
    raw = "||".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def show_exception(user_msg: str, e: Exception):
    st.error(user_msg)
    with st.expander("🔎 技術細節（供維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


def to_editor_df(data, subject: str):
    rows = []
    for q in data or []:
        opts = q.get("options", [])
        if not isinstance(opts, list):
            opts = []
        opts = [str(x) for x in opts][:4]
        while len(opts) < 4:
            opts.append("")

        corr = q.get("correct", ["1"])
        if isinstance(corr, list):
            corr_val = ",".join([str(x).strip() for x in corr if str(x).strip()])
        else:
            corr_val = str(corr).strip() or "1"

        rows.append(
            {
                "export": True,
                "subject": subject,
                "qtype": "single",  # ✅ 固定 single
                "question": q.get("question", ""),
                "option_1": opts[0],
                "option_2": opts[1],
                "option_3": opts[2],
                "option_4": opts[3],
                "correct": corr_val,
                "explanation": q.get("explanation", ""),
                "needs_review": bool(q.get("needs_review", False)),
            }
        )
    return pd.DataFrame(rows)


def split_paragraphs(text: str):
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


def build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]
    out = ""
    if highlights:
        out += "【重點段落（老師標記）】\n" + "\n\n".join(highlights) + "\n\n"
    out += "【其餘教材】\n" + "\n\n".join(others)
    return out[:limit]


def drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_bytes_to_drive(creds, filename: str, mimetype: str, data_bytes: bytes) -> dict:
    service = drive_service(creds)
    media = MediaIoBaseUpload(io.BytesIO(data_bytes), mimetype=mimetype, resumable=False)
    meta = {"name": filename}
    f = service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()
    return f


def share_file_to_emails(creds, file_id: str, emails: list, role: str = "reader"):
    service = drive_service(creds)
    for email in emails:
        email = str(email).strip()
        if not email:
            continue
        body = {"type": "user", "role": role, "emailAddress": email}
        service.permissions().create(
            fileId=file_id,
            body=body,
            sendNotificationEmail=True,
        ).execute()


# -------------------------
# Streamlit Config
# -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器（Kahoot / Wayground / Google Form｜一鍵電郵分享匯出檔）")

# session init
if "google_creds" not in st.session_state:
    st.session_state.google_creds = None

if "generated_data" not in st.session_state:
    st.session_state.generated_data = None
if "imported_data" not in st.session_state:
    st.session_state.imported_data = None
if "imported_text" not in st.session_state:
    st.session_state.imported_text = ""

if "mark_idx" not in st.session_state:
    st.session_state.mark_idx = set()

if "edited_generate_df" not in st.session_state:
    st.session_state.edited_generate_df = None
if "edited_import_df" not in st.session_state:
    st.session_state.edited_import_df = None

if "form_result_generate" not in st.session_state:
    st.session_state.form_result_generate = None
if "form_result_import" not in st.session_state:
    st.session_state.form_result_import = None

# OAuth callback
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

# Sidebar: Google connect
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
        st.sidebar.caption(""提示：請以學校電郵登入（例如：xxx@pochiu.edu.hk）")

st.sidebar.divider()

# Sidebar: AI API config
fast_mode = st.sidebar.checkbox(
    "⚡ 快速模式",
    value=True,
    help="較快、較保守：會用較短的AI輸出與較短超時；適合日常快速出題。"
)
st.sidebar.caption("快速模式：速度較快但題目較保守；關閉後較慢但可生成更豐富/更有變化的題目。")
st.sidebar.header("🔌 AI API 設定")

preset = st.sidebar.selectbox(
    "快速選擇（簡易）",
    ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"],
    key="preset"
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

# Sidebar: API test
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

# Sidebar: mode / subject / difficulty
mode = st.sidebar.radio(
    "📂 試題來源模式",
    ["🪄 AI 生成新題目", "📄 匯入現有題目（AI 協助）"],
    key="mode"
)

subject = st.sidebar.selectbox(
    "📘 科目",
    ["中國語文","英國語文","數學","公民與社會發展","科學","公民、經濟及社會","物理","化學","生物","地理","歷史","中國歷史","宗教",
     "資訊及通訊科技（ICT）","經濟","企業、會計與財務概論","旅遊與款待"],
    key="subject"
)

level_label = st.sidebar.radio(
    "🎯 難度",
    ["基礎（理解與記憶）", "標準（應用與理解）", "進階（分析與思考）", "混合（課堂活動建議）"],
    index=1,
    key="level_label"
)
level_map = {
    "基礎（理解與記憶）": "easy",
    "標準（應用與理解）": "medium",
    "進階（分析與思考）": "hard",
    "混合（課堂活動建議）": "mixed",
}
level_code = level_map[level_label]

# Editor config（qtype 不再提供選擇）
EDITOR_COLUMN_CONFIG = {
    "export": st.column_config.CheckboxColumn("匯出", help="勾選：匯出/建Form/分享檔案", width="small"),
    "correct": st.column_config.SelectboxColumn("正確答案（1-4）", options=["1","2","3","4"], width="small"),
    "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
}


def export_and_share_panel(selected_df: pd.DataFrame, subject_name: str, prefix: str):
    if selected_df is None or selected_df.empty:
        st.warning("⚠️ 尚未選擇任何題目（請勾選『匯出』欄）。")
        return

    kahoot_bytes = export_kahoot(selected_df)
    docx_bytes = export_wayground_docx(selected_df, subject_name)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Kahoot Excel", kahoot_bytes, "kahoot.xlsx", key=f"dl_kahoot_{prefix}")
    with c2:
        st.download_button("⬇️ Wayground DOCX", docx_bytes, "wayground.docx", key=f"dl_docx_{prefix}")

    st.markdown("### 📧 一鍵電郵分享匯出檔（需要先登入 Google）")
    if not st.session_state.google_creds:
        st.info("請先在左側登入 Google，才可用電郵分享檔案。")
        return

    emails_text = st.text_input("收件人電郵（多個用逗號分隔）", value="", key=f"emails_{prefix}")
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    share_col1, share_col2 = st.columns(2)
    with share_col1:
        if st.button("📧 分享 Kahoot Excel", key=f"btn_share_kahoot_{prefix}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(st.session_state.google_creds)
                    uploaded = upload_bytes_to_drive(
                        creds,
                        filename=f"{subject_name}_kahoot.xlsx",
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        data_bytes=kahoot_bytes,
                    )
                    share_file_to_emails(creds, uploaded["id"], emails, role="reader")
                    st.success("✅ 已分享 Kahoot 檔案（Google 會寄出通知電郵）")
                    st.write("Drive 連結：", uploaded.get("webViewLink"))
                except Exception as e:
                    show_exception("⚠️ 分享 Kahoot 檔案失敗。", e)

    with share_col2:
        if st.button("📧 分享 Wayground DOCX", key=f"btn_share_docx_{prefix}"):
            if not emails:
                st.warning("請先輸入至少一個電郵。")
            else:
                try:
                    creds = credentials_from_dict(st.session_state.google_creds)
                    uploaded = upload_bytes_to_drive(
                        creds,
                        filename=f"{subject_name}_wayground.docx",
                        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        data_bytes=docx_bytes,
                    )
                    share_file_to_emails(creds, uploaded["id"], emails, role="reader")
                    st.success("✅ 已分享 Wayground 檔案（Google 會寄出通知電郵）")
                    st.write("Drive 連結：", uploaded.get("webViewLink"))
                except Exception as e:
                    show_exception("⚠️ 分享 DOCX 檔案失敗。", e)


# =========================
# Mode 1: Generate (固定 single)
# =========================
if mode == "🪄 AI 生成新題目":
    st.subheader("🪄 AI 生成新題目（固定單選 4 選 1）")

    question_count = st.sidebar.selectbox("🧮 題目數目", [5, 8, 10, 12, 15, 20], index=2, key="question_count")
    cfg = api_config()

    files = st.file_uploader(
        "上載教材（PDF/DOCX/TXT/PPTX/XLSX）",
        accept_multiple_files=True,
        type=["pdf","docx","txt","pptx","xlsx"],
        key="files_generate"
    )

    raw_text = ""
    if files:
        with st.spinner("📄 正在擷取文字…"):
            raw_text = "".join(extract_text(f) for f in files)
        st.info(f"✅ 已擷取 {len(raw_text)} 字（可用重點段落標記加強貼題）")

        with st.expander("⭐ 重點段落標記（勾選後優先送入AI）", expanded=False):
            paras = split_paragraphs(raw_text)
            st.caption(f"段落數：{len(paras)}（以空行分段）")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 全選重點段落", key="btn_mark_all"):
                    st.session_state.mark_idx = set(range(len(paras)))
            with c2:
                if st.button("⛔ 全不選", key="btn_mark_none"):
                    st.session_state.mark_idx = set()

            for i, p in enumerate(paras[:80]):
                checked = i in st.session_state.mark_idx
                new_checked = st.checkbox(f"第 {i+1} 段", value=checked, key=f"para_g_{i}")
                if new_checked:
                    st.session_state.mark_idx.add(i)
                else:
                    st.session_state.mark_idx.discard(i)
                st.write(p[:200] + ("…" if len(p) > 200 else ""))

    limit = 8000 if fast_mode else 10000
    qtype = "single"

    if st.button("生成題目", disabled=not (can_call_ai(cfg) and bool(raw_text)), key="btn_generate"):
        try:
            used_text = build_text_with_highlights(raw_text, st.session_state.mark_idx, limit)
            st.info(f"✅ 送入 AI：{len(used_text)} 字（上限 {limit}）｜難度：{level_label}")

            cache = load_cache()
            key = stable_key(used_text, subject, level_code, question_count, fast_mode, preset, model, base_url, qtype)

            if key in cache:
                st.success("✅ 已從快取讀取")
                st.session_state.generated_data = cache[key]
            else:
                with st.spinner("🤖 正在呼叫 AI，請稍候 10–30 秒…"):
                    st.session_state.generated_data = generate_questions(
                        cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode, qtype="single"
                    )
                cache[key] = st.session_state.generated_data
                save_cache(cache)

            st.session_state.form_result_generate = None

        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)
            st.stop()

    if st.session_state.generated_data:
        df = to_editor_df(st.session_state.generated_data, subject)

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ 全選匯出", key="btn_export_all_generate"):
                df["export"] = True
        with c2:
            if st.button("全部取消匯出", key="btn_export_none_generate"):
                df["export"] = False

        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config=EDITOR_COLUMN_CONFIG,
            disabled=["qtype", "subject"],
            key="editor_generate"
        )

        st.session_state.edited_generate_df = edited
        selected = edited[edited["export"] == True].copy()
        st.caption(f"✅ 已選擇匯出 {len(selected)} 題（共 {len(edited)} 題）")

        if st.session_state.google_creds and not selected.empty:
            if st.button("🟦 一鍵建立 Google Form Quiz", key="btn_form_generate"):
                try:
                    with st.spinner("🟦 正在建立 Google Form…"):
                        creds = credentials_from_dict(st.session_state.google_creds)
                        result = create_quiz_form(creds, f"{subject} Quiz", selected)
                    st.session_state.form_result_generate = result
                    st.success("✅ 已建立 Google Form")
                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗。", e)

        if st.session_state.form_result_generate:
            st.write("編輯連結：", st.session_state.form_result_generate.get("editUrl"))
            st.write("發佈連結：", st.session_state.form_result_generate.get("responderUrl") or "（未提供 responderUri）")

        export_and_share_panel(selected, subject, prefix="generate")


# =========================
# Mode 2: Import (固定 single)
# =========================
if mode == "📄 匯入現有題目（AI 協助）":
    st.subheader("📄 匯入現有題目（AI 協助）")
    st.info("📌 匯入模式固定為「單選 single（4選1）」；若原文無答案，AI 會推測並標示需教師確認。")

    cfg = api_config()
    import_qtype = "single"

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""
        st.session_state.imported_data = None

    st.file_uploader("上載 DOCX/TXT（自動載入）", type=["docx", "txt"], key="import_file", on_change=load_import_file_to_textbox)
    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True, key="use_ai_assist")
    st.text_area("貼上題目內容", height=320, key="imported_text")

    if st.button("✨ 整理並轉換", disabled=not (bool(st.session_state.imported_text.strip()) and (not use_ai_assist or can_call_ai(cfg))), key="btn_import_parse"):
        try:
            raw = st.session_state.imported_text.strip()
            st.info(f"✅ 已載入/貼上 {len(raw)} 字。")

            with st.spinner("🧠 正在整理（可能需 10–30 秒，慢時 1–3 分鐘）…"):
                if use_ai_assist:
                    st.session_state.imported_data = assist_import_questions(
                        cfg, raw, subject, allow_guess=True, fast_mode=fast_mode, qtype=import_qtype
                    )
                else:
                    st.session_state.imported_data = parse_import_questions_locally(raw)

            st.session_state.form_result_import = None

        except Exception as e:
            st.warning("⚠️ AI 整理暫時失敗（可能服務繁忙或網絡超時）。系統已改用本地拆題作備援，請老師核對答案。")
            try:
                st.session_state.imported_data = parse_import_questions_locally(st.session_state.imported_text.strip())
            except Exception as e2:
                show_exception("⚠️ 本地拆題亦失敗，請檢查貼上的格式。", e2)
                st.stop()
            with st.expander("🔎 AI 失敗技術細節"):
                st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

    if st.session_state.imported_data:
        df = to_editor_df(st.session_state.imported_data, subject)

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ 全選匯出", key="btn_export_all_import"):
                df["export"] = True
        with c2:
            if st.button("全部取消匯出", key="btn_export_none_import"):
                df["export"] = False

        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config=EDITOR_COLUMN_CONFIG,
            disabled=["qtype", "subject"],
            key="editor_import"
        )

        st.session_state.edited_import_df = edited
        selected = edited[edited["export"] == True].copy()
        st.caption(f"✅ 已選擇匯出 {len(selected)} 題（共 {len(edited)} 題）")

        if st.session_state.google_creds and not selected.empty:
            if st.button("🟦 一鍵建立 Google Form Quiz", key="btn_form_import"):
                try:
                    with st.spinner("🟦 正在建立 Google Form…"):
                        creds = credentials_from_dict(st.session_state.google_creds)
                        result = create_quiz_form(creds, f"{subject} Quiz", selected)
                    st.session_state.form_result_import = result
                    st.success("✅ 已建立 Google Form")
                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗。", e)

        if st.session_state.form_result_import:
            st.write("編輯連結：", st.session_state.form_result_import.get("editUrl"))
            st.write("發佈連結：", st.session_state.form_result_import.get("responderUrl") or "（未提供 responderUri）")

        export_and_share_panel(selected, subject, prefix="import")
