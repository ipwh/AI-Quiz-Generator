import streamlit as st
import pandas as pd
import traceback
import hashlib

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
from services.google_drive_bank import (
    create_bank_file,
    load_bank,
    append_questions,
    share_bank_with_emails,
)

# ---------- helpers ----------
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
            corr_val = ",".join([str(x) for x in corr])
        else:
            corr_val = str(corr)

        rows.append({
            "export": True,
            "subject": subject,
            "qtype": q.get("qtype", "single"),
            "question": q.get("question", ""),
            "option_1": opts[0],
            "option_2": opts[1],
            "option_3": opts[2],
            "option_4": opts[3],
            "correct": corr_val,
            "explanation": q.get("explanation", ""),
            "needs_review": bool(q.get("needs_review", False)),
        })
    return pd.DataFrame(rows)

def _split_paragraphs(text: str):
    # 以空行分段
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return parts

def _build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = _split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]

    out = ""
    if highlights:
        out += "【重點段落（老師標記）】\n" + "\n\n".join(highlights) + "\n\n"
    out += "【其餘教材】\n" + "\n\n".join(others)
    return out[:limit]

# ---------- Streamlit ----------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器（Kahoot / Wayground / Google Form｜題庫共享 School Mode）")

# session
if "google_creds" not in st.session_state:
    st.session_state.google_creds = None
if "imported_text" not in st.session_state:
    st.session_state.imported_text = ""
if "imported_data" not in st.session_state:
    st.session_state.imported_data = None
if "generated_data" not in st.session_state:
    st.session_state.generated_data = None
if "mark_idx" not in st.session_state:
    st.session_state.mark_idx = set()
if "bank_file_id" not in st.session_state:
    st.session_state.bank_file_id = None

# OAuth callback
params = st.query_params
if oauth_is_configured() and "code" in params and not st.session_state.google_creds:
    try:
        code = params.get("code")
        state = params.get("state")
        if isinstance(code, list): code = code[0]
        if isinstance(state, list): state = state[0]
        creds = exchange_code_for_credentials(code=code, returned_state=state)
        st.session_state.google_creds = credentials_to_dict(creds)
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.query_params.clear()
        show_exception("Google 登入失敗。請重新按『連接 Google（登入）』一次。", e)
        st.stop()

# ---------- School Mode secrets ----------
SCHOOL_MODE = str(st.secrets.get("SCHOOL_MODE", "false")).lower() in {"1", "true", "yes"}
SCHOOL_API_KEY = st.secrets.get("SCHOOL_API_KEY", "")
SCHOOL_PRESET = st.secrets.get("SCHOOL_LLM_PRESET", "")  # e.g. "Grok (xAI)" / "OpenAI" / "DeepSeek"
SCHOOL_BASE_URL = st.secrets.get("SCHOOL_BASE_URL", "")
SCHOOL_MODEL = st.secrets.get("SCHOOL_MODEL", "")
SCHOOL_BANK_FILE_ID = st.secrets.get("SCHOOL_BANK_FILE_ID", "")

# ---------- Sidebar: Google ----------
st.sidebar.header("🟦 Google Forms / 題庫")
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

st.sidebar.divider()

# ---------- Sidebar: AI config ----------
fast_mode = st.sidebar.checkbox("⚡ 快速模式", value=True)
st.sidebar.header("🔌 AI API 設定")

preset_options = ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"]

if SCHOOL_MODE and SCHOOL_PRESET in preset_options:
    preset = SCHOOL_PRESET
    st.sidebar.info(f"🏫 學校模式：已鎖定供應商：{preset}")
else:
    preset = st.sidebar.selectbox("快速選擇（簡易）", preset_options)

# API key
if SCHOOL_MODE and SCHOOL_API_KEY:
    api_key = SCHOOL_API_KEY
    st.sidebar.caption("🏫 學校模式：API Key 已由系統提供（教師無需輸入）")
else:
    api_key = st.sidebar.text_input("API Key", type="password")

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
    auto_xai = st.sidebar.checkbox("🤖 自動偵測可用最新 Grok 型號（建議）", value=True)

elif preset == "Azure OpenAI":
    base_url = ""
    model = ""

else:
    base_url = st.sidebar.text_input("Base URL（含 /v1）", value=SCHOOL_BASE_URL if SCHOOL_MODE else "")
    model = st.sidebar.text_input("Model", value=SCHOOL_MODEL if SCHOOL_MODE else "")

azure_endpoint = ""
azure_deployment = ""
azure_api_version = "2024-02-15-preview"
if preset == "Azure OpenAI":
    with st.sidebar.expander("⚙️ Azure 設定", expanded=True):
        azure_endpoint = st.text_input("Azure Endpoint", value=str(st.secrets.get("SCHOOL_AZURE_ENDPOINT", "")) if SCHOOL_MODE else "")
        azure_deployment = st.text_input("Deployment name", value=str(st.secrets.get("SCHOOL_AZURE_DEPLOYMENT", "")) if SCHOOL_MODE else "")
        azure_api_version = st.text_input("API version", value=str(st.secrets.get("SCHOOL_AZURE_API_VERSION", "2024-02-15-preview")) if SCHOOL_MODE else "2024-02-15-preview")

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

# ---------- Sidebar: API test ----------
st.sidebar.divider()
st.sidebar.header("🧪 API 連線測試")
cfg_test = api_config()
if st.sidebar.button("🧪 一鍵測試 API（回覆 OK）"):
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

# ---------- Sidebar: mode / subject / qtype ----------
mode = st.sidebar.radio("📂 試題來源模式", ["🪄 AI 生成新題目", "📄 匯入現有題目（AI 協助）", "📚 題庫（學校版/共享）"])
subject = st.sidebar.selectbox(
    "📘 科目",
    ["中國語文","英國語文","數學","公民與社會發展","科學","公民、經濟及社會","物理","化學","生物","地理","歷史","中國歷史","宗教",
     "資訊及通訊科技（ICT）","經濟","企業、會計與財務概論","旅遊與款待"]
)

qtype_label = st.sidebar.selectbox("🧩 題型", ["單選 (single)", "多選 (multiple)", "是非 (true_false)"])
qtype_map = {"單選 (single)": "single", "多選 (multiple)": "multiple", "是非 (true_false)": "true_false"}
qtype = qtype_map[qtype_label]

# ---------- Editor config ----------
EDITOR_COLUMN_CONFIG = {
    "export": st.column_config.CheckboxColumn("匯出", help="勾選：匯出到 Kahoot/Wayground/Google Form/題庫", width="small"),
    "subject": st.column_config.TextColumn("科目", width="small"),
    "qtype": st.column_config.SelectboxColumn("題型", options=["single", "multiple", "true_false"], width="small"),
    "correct": st.column_config.TextColumn("正確答案", help="single/true_false：1；multiple：1,3（逗號分隔）", width="small"),
    "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
}

# ========== Mode 1: Generate ==========
if mode == "🪄 AI 生成新題目":
    question_count = st.sidebar.selectbox("🧮 題目數目", [5, 8, 10, 12, 15, 20], index=2)
    level_label = st.sidebar.radio("🎯 難度", ["easy", "medium", "hard", "mixed"])
    cfg = api_config()

    files = st.file_uploader("上載教材（PDF/DOCX/TXT/PPTX/XLSX）", accept_multiple_files=True, type=["pdf","docx","txt","pptx","xlsx"])

    raw_text = ""
    if files:
        with st.spinner("📄 正在擷取文字…"):
            raw_text = "".join(extract_text(f) for f in files)
        st.info(f"✅ 已擷取 {len(raw_text)} 字（可用重點段落標記加強貼題）")

        with st.expander("⭐ 重點段落標記（勾選後會優先送入AI）", expanded=False):
            paras = _split_paragraphs(raw_text)
            st.caption(f"段落數：{len(paras)}（以空行分段）")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 全選重點段落"):
                    st.session_state.mark_idx = set(range(len(paras)))
            with c2:
                if st.button("⛔ 全不選"):
                    st.session_state.mark_idx = set()

            for i, p in enumerate(paras[:80]):  # 顯示最多 80 段（避免 UI 太重）
                checked = i in st.session_state.mark_idx
                new_checked = st.checkbox(f"第 {i+1} 段", value=checked, key=f"para_{i}")
                if new_checked:
                    st.session_state.mark_idx.add(i)
                else:
                    st.session_state.mark_idx.discard(i)
                st.write(p[:200] + ("…" if len(p) > 200 else ""))

    limit = 8000 if fast_mode else 10000

    if st.button("生成題目", disabled=not (can_call_ai(cfg) and bool(raw_text))):
        try:
            marked = st.session_state.mark_idx
            used_text = _build_text_with_highlights(raw_text, marked, limit)
            st.info(f"✅ 送入 AI：{len(used_text)} 字（上限 {limit}）｜題型：{qtype}")

            cache = load_cache()
            key = stable_key(used_text, subject, level_label, question_count, fast_mode, preset, model, base_url, qtype)

            if key in cache:
                st.success("✅ 已從快取讀取")
                st.session_state.generated_data = cache[key]
            else:
                with st.spinner("🤖 正在呼叫 AI，請稍候 10–30 秒…"):
                    st.session_state.generated_data = generate_questions(cfg, used_text, subject, level_label, question_count, fast_mode=fast_mode, qtype=qtype)
                cache[key] = st.session_state.generated_data
                save_cache(cache)

        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)
            st.stop()

    if st.session_state.generated_data:
        df = to_editor_df(st.session_state.generated_data, subject)
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ 全選匯出"):
                df["export"] = True
        with c2:
            if st.button("⛔ 全不選匯出"):
                df["export"] = False

        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", column_config=EDITOR_COLUMN_CONFIG)
        selected = edited[edited["export"] == True].copy()

        st.download_button("⬇️ Kahoot Excel（已選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX（已選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

        if st.session_state.google_creds and not selected.empty:
            if st.button("🟦 一鍵建立 Google Form Quiz（已選）"):
                try:
                    with st.spinner("🟦 正在建立 Google Form…"):
                        creds = credentials_from_dict(st.session_state.google_creds)
                        result = create_quiz_form(creds, f"{subject} Quiz", selected)
                    st.success("✅ 已建立 Google Form")
                    st.write("編輯連結：", result.get("editUrl"))
                    st.write("發佈連結：", result.get("responderUrl") or "（未提供 responderUri）")
                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗。", e)

# ========== Mode 2: Import ==========
if mode == "📄 匯入現有題目（AI 協助）":
    cfg = api_config()

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""
        st.session_state.imported_data = None

    st.file_uploader("上載 DOCX/TXT（自動載入）", type=["docx","txt"], key="import_file", on_change=load_import_file_to_textbox)
    use_ai_assist = st.checkbox("啟用 AI 協助整理", value=True)
    st.text_area("貼上題目內容", height=320, key="imported_text")

    if st.button("✨ 整理並轉換", disabled=not (bool(st.session_state.imported_text.strip()) and (not use_ai_assist or can_call_ai(cfg)))):
        try:
            raw = st.session_state.imported_text.strip()
            with st.spinner("🧠 正在整理…"):
                if use_ai_assist:
                    st.session_state.imported_data = assist_import_questions(cfg, raw, subject, allow_guess=True, fast_mode=fast_mode, qtype=qtype)
                else:
                    st.session_state.imported_data = parse_import_questions_locally(raw)
        except Exception as e:
            show_exception("⚠️ 整理失敗。", e)

    if st.session_state.imported_data:
        df = to_editor_df(st.session_state.imported_data, subject)
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", column_config=EDITOR_COLUMN_CONFIG)
        selected = edited[edited["export"] == True].copy()

        st.download_button("⬇️ Kahoot Excel（已選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX（已選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

        # ✅ 匯入模式也可輸出 Google Form
        if st.session_state.google_creds and not selected.empty:
            if st.button("🟦 一鍵建立 Google Form Quiz（已選）"):
                try:
                    with st.spinner("🟦 正在建立 Google Form…"):
                        creds = credentials_from_dict(st.session_state.google_creds)
                        result = create_quiz_form(creds, f"{subject} Quiz", selected)
                    st.success("✅ 已建立 Google Form")
                    st.write("編輯連結：", result.get("editUrl"))
                    st.write("發佈連結：", result.get("responderUrl") or "（未提供 responderUri）")
                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗。", e)

# ========== Mode 3: Shared Bank ==========
if mode == "📚 題庫（學校版/共享）":
    if not st.session_state.google_creds:
        st.warning("請先在左側登入 Google，才可使用題庫共享。")
        st.stop()

    creds = credentials_from_dict(st.session_state.google_creds)

    # 決定 bank fileId（school secrets 優先）
    if SCHOOL_BANK_FILE_ID:
        st.session_state.bank_file_id = SCHOOL_BANK_FILE_ID

    st.subheader("📚 題庫（Drive JSON）")

    if not st.session_state.bank_file_id:
        st.info("尚未指定題庫檔案。你可以建立一個新的題庫檔（Drive 內 JSON）。")
        if st.button("➕ 建立題庫檔（Drive）"):
            try:
                fid = create_bank_file(creds, name="AI Quiz Bank.json")
                st.session_state.bank_file_id = fid
                st.success(f"✅ 已建立題庫檔：{fid}")
                st.info("如要全校共用：請把這個 fileId 寫入 Streamlit Secrets：SCHOOL_BANK_FILE_ID")
            except Exception as e:
                show_exception("⚠️ 建立題庫檔失敗。", e)
                st.stop()

    if st.session_state.bank_file_id:
        fid = st.session_state.bank_file_id

        colA, colB = st.columns(2)
        with colA:
            if st.button("🔄 重新載入題庫"):
                pass
        with colB:
            emails = st.text_input("📧 以電郵分享題庫（輸入多個 email，用逗號分隔）", value="")
            if st.button("📧 分享（Drive 權限）"):
                try:
                    ems = [e.strip() for e in emails.split(",") if e.strip()]
                    share_bank_with_emails(creds, fid, ems, role="writer")
                    st.success("✅ 已分享（Google 會寄出通知電郵）")
                except Exception as e:
                    show_exception("⚠️ 分享失敗。", e)

        bank = load_bank(creds, fid)
        st.caption(f"題庫共有：{len(bank)} 題")

        # 題庫轉成 DataFrame（可勾選匯出）
        bank_rows = []
        for item in bank:
            if not isinstance(item, dict):
                continue
            opts = item.get("options", ["", "", "", ""])
            if not isinstance(opts, list):
                opts = ["", "", "", ""]
            while len(opts) < 4:
                opts.append("")
            corr = item.get("correct", ["1"])
            corr_val = ",".join(corr) if isinstance(corr, list) else str(corr)
            bank_rows.append({
                "export": False,
                "subject": item.get("subject", ""),
                "qtype": item.get("qtype", "single"),
                "question": item.get("question", ""),
                "option_1": opts[0],
                "option_2": opts[1],
                "option_3": opts[2],
                "option_4": opts[3],
                "correct": corr_val,
                "explanation": item.get("explanation", ""),
                "needs_review": bool(item.get("needs_review", False)),
            })

        bank_df = pd.DataFrame(bank_rows)
        if not bank_df.empty:
            edited = st.data_editor(bank_df, use_container_width=True, num_rows="dynamic", column_config=EDITOR_COLUMN_CONFIG)
            selected = edited[edited["export"] == True].copy()

            st.download_button("⬇️ Kahoot Excel（題庫已選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
            st.download_button("⬇️ Wayground DOCX（題庫已選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

            if not selected.empty:
                if st.button("🟦 用題庫已選建立 Google Form Quiz"):
                    try:
                        with st.spinner("🟦 建立 Google Form…"):
                            result = create_quiz_form(creds, f"{subject} Quiz", selected)
                        st.success("✅ 已建立 Google Form")
                        st.write("編輯連結：", result.get("editUrl"))
                        st.write("發佈連結：", result.get("responderUrl") or "（未提供 responderUri）")
                    except Exception as e:
                        show_exception("⚠️ 建立 Google Form 失敗。", e)
        else:
            st.info("題庫目前為空。你可以在生成/匯入模式把題目加入題庫。")

    # 入口提示：在生成/匯入頁面把題目加入題庫
    st.info("提示：請在『生成』或『匯入』模式完成後，選中題目，再用『加入題庫』功能（下方按鈕）。")