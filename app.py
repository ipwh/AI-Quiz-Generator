import streamlit as st
import pandas as pd
import traceback
import hashlib

from services.llm_service import (
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,  # ✅ 新增
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
                "export": True,  # ✅ 新增：預設全選匯出
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
    "export": st.column_config.CheckboxColumn(
        "匯出",
        help="✅ 勾選：會匯出到 Kahoot/Wayground/Google Form；取消：不匯出此題",
        width="small",
    ),
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
        show_exception("Google 登入失敗。請回到左側重新按『連接 Google（登入）』一次（建議無痕視窗）。", e)
        st.stop()

# =========================
# Sidebar：Google Forms 連接
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
        st.sidebar.caption("提示：若不用生成Google Form，則不用理會")

st.sidebar.divider()

# =========================
# Sidebar：AI API 設定
# =========================
fast_mode = st.sidebar.checkbox("⚡ 快速模式（更快但較保守）", value=True)
st.sidebar.header("🔌 AI API 設定")
preset = st.sidebar.selectbox("快速選擇（簡易）", ["DeepSeek", "OpenAI", "Azure OpenAI", "自訂（OpenAI 相容）"])
api_key = st.sidebar.text_input("API Key", type="password")

if preset == "DeepSeek":
    base_url = "https://api.deepseek.com/v1"
    model = "deepseek-chat"
elif preset == "OpenAI":
    base_url = "https://api.openai.com/v1"
    model = "gpt-4o-mini"
elif preset == "Azure OpenAI":
    base_url = ""
    model = ""
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


def api_config():
    if preset == "Azure OpenAI":
        return {
            "type": "azure",
            "api_key": api_key,
            "endpoint": azure_endpoint,
            "deployment": azure_deployment,
            "api_version": azure_api_version,
        }
    return {"type": "openai_compat", "api_key": api_key, "base_url": base_url, "model": model}


def can_call_ai(cfg: dict):
    if not cfg.get("api_key"):
        return False
    if cfg.get("type") == "azure":
        return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
    return bool(cfg.get("base_url")) and bool(cfg.get("model"))


# ✅ 一鍵測試 API
st.sidebar.divider()
st.sidebar.header("🧪 API 連線測試")
cfg_test = api_config()

if st.sidebar.button("🧪 一鍵測試 API"):
    if not can_call_ai(cfg_test):
        st.sidebar.error("請先填妥 API Key／Base URL／Model（Azure 要 Endpoint + Deployment）。")
    else:
        with st.sidebar.spinner("正在測試連線（通常 2–10 秒；慢時 10–30 秒）…"):
            r = ping_llm(cfg_test, timeout=25)

    if r["ok"]:
        ms = r["latency_ms"]
        st.sidebar.success(f"✅ 連線成功：{ms} ms")
        if ms >= 15000:
            st.sidebar.warning("⚠️ 服務偏慢（可能對方繁忙或網絡不穩）")

        out_text = (r["output"] or "").strip()
        if out_text == "OK":
            st.sidebar.caption("回覆：OK")
    else:
            st.sidebar.warning("⚠️ 已連線，但回覆未完全按指令（仍可視作可用）")
            st.sidebar.caption(f"回覆：{out_text[:80]}")
    else:
            st.sidebar.error("❌ 連線失敗：請檢查 Key/Endpoint/Model 或服務狀態")
            st.sidebar.code(r["error"])


st.sidebar.divider()

mode = st.sidebar.radio("📂 試題來源模式", ["🪄 AI 生成新題目", "📄 匯入現有題目（AI 協助）"])
subject = st.sidebar.selectbox(
    "📘 科目",
    [
        "中國語文","英國語文","數學","公民與社會發展","科學","公民、經濟及社會","物理","化學","生物","地理","歷史","中國歷史","宗教",
        "資訊及通訊科技（ICT）","經濟","企業、會計與財務概論","旅遊與款待"
    ],
)

# =========================
# 模式一：AI 生成
# =========================
if mode == "🪄 AI 生成新題目":
    question_count = st.sidebar.selectbox("🧮 題目數目", [5, 8, 10, 12, 15, 20], index=2)
    level_label = st.sidebar.radio("🎯 難度", ["基礎（理解與記憶）","標準（應用與理解）","進階（分析與思考）","混合（課堂活動建議）"])
    level_map = {"基礎（理解與記憶）":"easy","標準（應用與理解）":"medium","進階（分析與思考）":"hard","混合（課堂活動建議）":"mixed"}
    level_code = level_map[level_label]

    files = st.file_uploader(
        "上載教材（支援PDF/DOCX/TXT/PPTX/XLSX）",
        accept_multiple_files=True,
        type=["pdf","docx","txt","pptx","xlsx"],
    )

    cfg = api_config()
    if st.button("生成題目", disabled=not (can_call_ai(cfg) and bool(files))):
        try:
            with st.spinner("📄 正在擷取文字…"):
                raw_text = "".join(extract_text(f) for f in files)

            used_text = raw_text[:6000]
            st.info(f"✅ 已擷取 {len(raw_text)} 字；送入 AI 上限 {len(used_text)} 字。")

            cache = load_cache()
            key = stable_key(used_text, subject, level_code, question_count, fast_mode, preset, model, base_url)

            if key in cache:
                st.success("✅ 已從快取讀取（節省時間與額度）")
                st.session_state.generated_data = cache[key]
            else:
                with st.spinner("🤖 正在呼叫 AI，請稍候 10–30 秒…"):
                    st.session_state.generated_data = generate_questions(
                        cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode
                    )
                cache[key] = st.session_state.generated_data
                save_cache(cache)

        except Exception as e:
            show_exception("⚠️ 生成題目失敗（可能是網絡逾時、API Key/Model 設定問題或對方服務繁忙）。", e)
            st.stop()

    if st.session_state.generated_data:
        df = to_editor_df(st.session_state.generated_data)

        # ✅ 加兩個快捷鍵：全選/全不選匯出
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ 全選匯出"):
                df["export"] = True
        with c2:
            if st.button("⛔ 全不選匯出"):
                df["export"] = False

        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config=EDITOR_COLUMN_CONFIG,
            disabled=["type"],
        )

        selected = edited[edited["export"] == True].copy()
        if selected.empty:
            st.warning("⚠️ 你未選擇任何題目匯出。請先勾選『匯出』欄。")
        else:
            st.caption(f"✅ 已選擇匯出 {len(selected)} 題（共 {len(edited)} 題）")

        st.download_button("⬇️ Kahoot Excel（只匯出已勾選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX（只匯出已勾選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

        if st.session_state.google_creds:
            if st.button("🟦 一鍵建立 Google Form Quiz（只匯出已勾選）"):
                try:
                    if selected.empty:
                        st.warning("⚠️ 未選擇任何題目匯出，已取消建立 Google Form。")
                    else:
                        with st.spinner("🟦 正在建立 Google Form（通常 5–20 秒）…"):
                            creds = credentials_from_dict(st.session_state.google_creds)
                            result = create_quiz_form(creds, f"{subject} Quiz", selected)

                        st.success("✅ 已建立 Google Form Quiz")
                        st.write("編輯連結：", result.get("editUrl"))
                        st.write("發佈連結：", result.get("responderUrl") or "（Google API 未提供 responderUri，可於表單右上角『傳送』取得）")

                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗（常見：配額用盡/權限不足/未啟用 Forms API）。", e)
                    st.stop()
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
        try:
            raw = st.session_state.imported_text.strip()
            st.info(f"✅ 已載入/貼上 {len(raw)} 字。")

            with st.spinner("🧠 正在整理（可能需 10–30 秒）…"):
                if use_ai_assist:
                    st.session_state.imported_data = assist_import_questions(cfg, raw, subject, allow_guess=True, fast_mode=fast_mode)
                else:
                    st.session_state.imported_data = parse_import_questions_locally(raw)

        except Exception as e:
            show_exception("⚠️ 整理並轉換失敗（可能是AI連線問題或輸入格式過於混亂）。", e)
            st.stop()

    if st.session_state.imported_data:
        df = to_editor_df(st.session_state.imported_data)

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("✅ 全選匯出（匯入）"):
                df["export"] = True
        with c2:
            if st.button("⛔ 全不選匯出（匯入）"):
                df["export"] = False

        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config=EDITOR_COLUMN_CONFIG,
            disabled=["type"],
        )

        selected = edited[edited["export"] == True].copy()
        if selected.empty:
            st.warning("⚠️ 你未選擇任何題目匯出。請先勾選『匯出』欄。")
        else:
            st.caption(f"✅ 已選擇匯出 {len(selected)} 題（共 {len(edited)} 題）")

        st.download_button("⬇️ Kahoot Excel（只匯出已勾選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX（只匯出已勾選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

        if st.session_state.google_creds:
            if st.button("🟦 一鍵建立 Google Form Quiz（只匯出已勾選）"):
                try:
                    if selected.empty:
                        st.warning("⚠️ 未選擇任何題目匯出，已取消建立 Google Form。")
                    else:
                        with st.spinner("🟦 正在建立 Google Form（通常 5–20 秒）…"):
                            creds = credentials_from_dict(st.session_state.google_creds)
                            result = create_quiz_form(creds, f"{subject} Quiz", selected)

                        st.success("✅ 已建立 Google Form Quiz")
                        st.write("編輯連結：", result.get("editUrl"))
                        st.write("發佈連結：", result.get("responderUrl") or "（Google API 未提供 responderUri，可於表單右上角『傳送』取得）")

                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗（常見：配額用盡/權限不足/未啟用 Forms API）。", e)
                    st.stop()
        else:
            st.info("先在左側登入 Google，才可一鍵建立。")
