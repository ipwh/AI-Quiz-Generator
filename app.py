import streamlit as st
import pandas as pd
import requests

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
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


def to_editor_df(data):
    rows = []
    for q in data or []:
        opts = q.get("options", [])
        if not isinstance(opts, list):
            opts = []
        opts = [str(x) for x in opts][:4]
        while len(opts) < 4:
            opts.append("")

        corr = q.get("correct", ["1"])
        corr_val = str(corr[0]) if isinstance(corr, list) and corr else "1"

        rows.append(
            {
                "type": q.get("type", "single"),
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


EDITOR_COLUMN_CONFIG = {
    "correct": st.column_config.SelectboxColumn(
        "正確答案（1-4）",
        help="1=option_1, 2=option_2, 3=option_3, 4=option_4",
        options=["1", "2", "3", "4"],
        required=True,
        width="small",
    ),
    "needs_review": st.column_config.CheckboxColumn(
        "需教師確認",
        help="AI 推測答案或內容不確定時會標示（匯出不會顯示）",
        width="small",
    ),
    "type": st.column_config.TextColumn(
        "題型",
        help="single=單選題（系統內部用）",
        width="small",
    ),
}

st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫  AI 題目生成器（生成檔案匯入Kahoot / Wayground｜直接生成Google Form）")

# session init
if "google_creds" not in st.session_state:
    st.session_state.google_creds = None
if "imported_text" not in st.session_state:
    st.session_state.imported_text = ""
if "imported_data" not in st.session_state:
    st.session_state.imported_data = None
if "generated_data" not in st.session_state:
    st.session_state.generated_data = None

# ✅ 先處理 OAuth callback（code/state）
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
        st.error("Google 登入失敗：" + str(e))
        st.info("請回到左側重新按『連接 Google（登入）』一次（建議使用無痕視窗，避免多分頁干擾）。")
        st.stop()

# =========================
# Sidebar：Google Forms 連接（按鈕）
# =========================
st.sidebar.header("🟦 Google Forms 連接")

if not oauth_is_configured():
    st.sidebar.warning("⚠️ 尚未設定 Google OAuth（請在 Streamlit Secrets 設定 google_oauth_client 及 APP_URL）。")
else:
    if st.session_state.google_creds:
        st.sidebar.success("✅ 已連接 Google（可一鍵建立 Google Form Quiz）")
        if st.sidebar.button("🔒 登出 Google"):
            st.session_state.google_creds = None
            st.rerun()
    else:
        auth_url = get_auth_url()
        st.sidebar.link_button("🔐 連接 Google（登入）", auth_url)
        st.sidebar.caption("提示：避免多分頁登入；建議用同一分頁/無痕視窗完成授權。")

st.sidebar.divider()

# =========================
# Sidebar：AI API 設定（你可保留原本版本；此處保持簡化）
# =========================
fast_mode = st.sidebar.checkbox("⚡ 快速模式（更快但較保守）", value=True)
st.sidebar.header("🔌 AI API 設定")
preset = st.sidebar.selectbox("快速選擇（簡易）", ["DeepSeek", "OpenAI", "Azure OpenAI", "自訂（OpenAI 相容）"])
api_key = st.sidebar.text_input("API Key", type="password")

if preset == "DeepSeek（推薦）":
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
elif preset == "OpenAI":
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
else:
    base_url = st.sidebar.text_input("Base URL（含 /v1）", value="")
    model = st.sidebar.text_input("Model", value="")

azure_endpoint = ""
azure_deployment = ""
azure_api_version = "2024-02-15-preview"
if preset == "Azure OpenAI":
    with st.sidebar.expander("⚙️ Azure 設定", expanded=True):
        azure_endpoint = st.text_input("Azure Endpoint", value="")
        azure_deployment = st.text_input("Deployment name", value="")
        azure_api_version = st.text_input("API version", value="2024-02-15-preview")

st.sidebar.divider()

mode = st.sidebar.radio("📂 試題來源模式", ["🪄 AI 生成新題目", "📄 匯入現有題目（AI 協助）"])
subject = st.sidebar.selectbox(
    "📘 科目",
    ["中國語文","英國語文","數學","公民與社會發展","科學","物理","化學","生物",
     "資訊及通訊科技（ICT）","地理","歷史","公民、經濟及社會","中國歷史","宗教","經濟"]
)

def api_config():
    if preset == "Azure OpenAI":
        return {"type":"azure","api_key":api_key,"endpoint":azure_endpoint,"deployment":azure_deployment,"api_version":azure_api_version}
    return {"type":"openai_compat","api_key":api_key,"base_url":base_url,"model":model}

def can_call_ai(cfg: dict):
    if not cfg.get("api_key"):
        return False
    if cfg.get("type") == "azure":
        return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
    return bool(cfg.get("base_url")) and bool(cfg.get("model"))

# =========================
# 模式一：AI 生成
# =========================
if mode == "🪄 AI 生成新題目":
    question_count = st.sidebar.selectbox("🧮 題目數目", [5, 8, 10, 12, 15, 20], index=2)
    level_label = st.sidebar.radio("🎯 難度", ["基礎（理解與記憶）","標準（應用與理解）","進階（分析與思考）","混合（課堂活動建議）"])
    level_map = {"基礎（理解與記憶）":"easy","標準（應用與理解）":"medium","進階（分析與思考）":"hard","混合（課堂活動建議）":"mixed"}
    level_code = level_map[level_label]

    files = st.file_uploader("上載教材（支援PDF/DOCX/TXT/PPTX/XLSX）", accept_multiple_files=True,
                             type=["pdf","docx","txt","pptx","xlsx"])

    cfg = api_config()
    if st.button("生成題目", disabled=not (can_call_ai(cfg) and bool(files))):
        text = "".join(extract_text(f) for f in files)[:5000]
        cache = load_cache()
        key = str(hash(text + subject + level_code + str(question_count)))
        if key in cache:
            st.session_state.generated_data = cache[key]
        else:
            with st.spinner("🤖 生成中..."):
                st.session_state.generated_data = generate_questions(cfg, text, subject, level_code, question_count, fast_mode=fast_mode)
            cache[key] = st.session_state.generated_data
            save_cache(cache)

    if st.session_state.generated_data:
        df = to_editor_df(st.session_state.generated_data)
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", column_config=EDITOR_COLUMN_CONFIG, disabled=["type"])

        st.download_button("⬇️ Kahoot Excel", export_kahoot(edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX", export_wayground_docx(edited, subject), "wayground.docx")

        if st.session_state.google_creds:
            if st.button("🟦 一鍵建立 Google Form Quiz"):
                creds = credentials_from_dict(st.session_state.google_creds)
                result = create_quiz_form(creds, f"{subject} Quiz", edited)
                st.success("✅ 已建立 Google Form Quiz")
                st.write("編輯連結：", result.get("editUrl"))
                st.write("發佈連結：", result.get("responderUrl"))
        else:
            st.info("先在左側登入 Google，才可一鍵建立。")

# =========================
# 模式二：匯入現有題目
# =========================
if mode == "📄 匯入現有題目（AI 協助）":
    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""
        st.session_state.imported_data = None

    st.file_uploader("上載 DOCX/TXT（自動載入）", type=["docx","txt"], key="import_file", on_change=load_import_file_to_textbox)
    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True)
    st.text_area("貼上題目內容", height=320, key="imported_text")

    cfg = api_config()
    if st.button("✨ 整理並轉換", disabled=not (bool(st.session_state.imported_text.strip()) and (not use_ai_assist or can_call_ai(cfg)))):
        raw = st.session_state.imported_text.strip()
        with st.spinner("🧠 整理中..."):
            if use_ai_assist:
                st.session_state.imported_data = assist_import_questions(cfg, raw, subject, allow_guess=True, fast_mode=fast_mode)
            else:
                st.session_state.imported_data = parse_import_questions_locally(raw)

    if st.session_state.imported_data:
        df = to_editor_df(st.session_state.imported_data)
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", column_config=EDITOR_COLUMN_CONFIG, disabled=["type"])

        st.download_button("⬇️ Kahoot Excel", export_kahoot(edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX", export_wayground_docx(edited, subject), "wayground.docx")

        if st.session_state.google_creds:
            if st.button("🟦 一鍵建立 Google Form Quiz"):
                creds = credentials_from_dict(st.session_state.google_creds)
                result = create_quiz_form(creds, f"{subject} Quiz", edited)
                st.success("✅ 已建立 Google Form Quiz")
                st.write("編輯連結：", result.get("editUrl"))
                st.write("發佈連結：", result.get("responderUrl"))
        else:
            st.info("先在左側登入 Google，才可一鍵建立。")
