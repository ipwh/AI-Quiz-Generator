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

# ✅ 題庫功能（如檔案未加入，會自動降級）
BANK_ENABLED = True
try:
    from services.google_drive_bank import (
        create_bank_file,
        load_bank,
        append_questions,
        share_bank_with_emails,
    )
except Exception:
    BANK_ENABLED = False


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
                "qtype": q.get("qtype", "single"),
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


def df_to_bank_items(df: pd.DataFrame):
    """
    把 editor df 轉成題庫 dict list：
    - qtype
    - question
    - options list（4）
    - correct list（"1"~"4"）
    - explanation
    - needs_review
    - subject
    """
    out = []
    if df is None or df.empty:
        return out

    for _, r in df.iterrows():
        qtype = str(r.get("qtype", "single")).strip() or "single"
        question = str(r.get("question", "")).strip()
        if not question:
            continue

        if qtype == "true_false":
            options = ["對", "錯", "", ""]
        else:
            options = [
                str(r.get("option_1", "")).strip(),
                str(r.get("option_2", "")).strip(),
                str(r.get("option_3", "")).strip(),
                str(r.get("option_4", "")).strip(),
            ]
            while len(options) < 4:
                options.append("")

        corr_raw = r.get("correct", "1")
        corr_list = []
        if isinstance(corr_raw, list):
            corr_list = [str(x).strip() for x in corr_raw]
        else:
            corr_list = [x.strip() for x in str(corr_raw).split(",") if x.strip()]

        # only keep valid 1-4
        corr_list = [c for c in corr_list if c in {"1", "2", "3", "4"}]
        if qtype == "true_false":
            corr_list = [c for c in corr_list if c in {"1", "2"}]
            corr_list = [corr_list[0]] if corr_list else ["1"]
        elif qtype == "multiple":
            # de-dup keep order
            seen = set()
            tmp = []
            for c in corr_list:
                if c not in seen:
                    seen.add(c)
                    tmp.append(c)
            corr_list = tmp if tmp else ["1"]
        else:
            corr_list = [corr_list[0]] if corr_list else ["1"]

        out.append({
            "subject": str(r.get("subject", "")).strip(),
            "qtype": qtype,
            "question": question,
            "options": options[:4],
            "correct": corr_list,
            "explanation": str(r.get("explanation", "")).strip(),
            "needs_review": bool(r.get("needs_review", False)),
        })
    return out


def split_paragraphs(text: str):
    parts = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    return parts


def build_text_with_highlights(raw_text: str, marked_idx: set, limit: int):
    paras = split_paragraphs(raw_text)
    highlights = [paras[i] for i in range(len(paras)) if i in marked_idx]
    others = [paras[i] for i in range(len(paras)) if i not in marked_idx]

    out = ""
    if highlights:
        out += "【重點段落（老師標記）】\n" + "\n\n".join(highlights) + "\n\n"
    out += "【其餘教材】\n" + "\n\n".join(others)
    return out[:limit]


# -------------------------
# Streamlit UI
# -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器（題型選擇｜重點段落｜Kahoot/Wayground/Google Form｜題庫共享）")

# session init
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
# Sidebar：Google Forms + 題庫
# -------------------------
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

# -------------------------
# Sidebar：AI 設定
# -------------------------
fast_mode = st.sidebar.checkbox("⚡ 快速模式", value=True)
st.sidebar.header("🔌 AI API 設定")

preset = st.sidebar.selectbox("快速選擇（簡易）", ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"])
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

# -------------------------
# Sidebar：API 測試
# -------------------------
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

# -------------------------
# Sidebar：模式/科目/題型/難度
# -------------------------
mode = st.sidebar.radio("📂 試題來源模式", ["🪄 AI 生成新題目", "📄 匯入現有題目（AI 協助）", "📚 題庫（共享）"])
subject = st.sidebar.selectbox(
    "📘 科目",
    ["中國語文","英國語文","數學","公民與社會發展","科學","公民、經濟及社會","物理","化學","生物","地理","歷史","中國歷史","宗教",
     "資訊及通訊科技（ICT）","經濟","企業、會計與財務概論","旅遊與款待"]
)

qtype_label = st.sidebar.selectbox("🧩 題型", ["單選 (single)", "多選 (multiple)", "是非 (true_false)"])
qtype_map = {"單選 (single)": "single", "多選 (multiple)": "multiple", "是非 (true_false)": "true_false"}
qtype = qtype_map[qtype_label]

# ✅ 難度：用清晰中文（你要求）
level_label = st.sidebar.radio(
    "🎯 難度",
    ["基礎（理解與記憶）", "標準（應用與理解）", "進階（分析與思考）", "混合（課堂活動建議）"],
    index=1
)
level_map = {
    "基礎（理解與記憶）": "easy",
    "標準（應用與理解）": "medium",
    "進階（分析與思考）": "hard",
    "混合（課堂活動建議）": "mixed",
}
level_code = level_map[level_label]
st.sidebar.caption(
    "說明：\n"
    "- 基礎：偏重定義、關鍵詞、直接理解\n"
    "- 標準：情境應用、簡單推論\n"
    "- 進階：分析、比較、判斷與推理\n"
    "- 混合：同時包含不同層次題目"
)

# Editor columns
EDITOR_COLUMN_CONFIG = {
    "export": st.column_config.CheckboxColumn("匯出", help="勾選：匯出到 Kahoot/Wayground/Google Form/題庫", width="small"),
    "subject": st.column_config.TextColumn("科目", width="small"),
    "qtype": st.column_config.SelectboxColumn("題型", options=["single", "multiple", "true_false"], width="small"),
    "correct": st.column_config.TextColumn("正確答案", help="single/true_false：1；multiple：1,3（逗號分隔）", width="small"),
    "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
}

# -------------------------
# 題庫快捷按鈕區（生成/匯入頁面用）
# -------------------------
def bank_quick_panel(selected_df: pd.DataFrame):
    """
    在生成/匯入頁面直接提供：
    - 建立題庫檔（Drive）
    - 加入題庫（已選）
    """
    if not BANK_ENABLED:
        st.info("（題庫模組尚未加入：未啟用題庫按鈕）")
        return

    if not st.session_state.google_creds:
        st.info("（未登入 Google：題庫功能需要登入）")
        return

    creds = credentials_from_dict(st.session_state.google_creds)

    with st.expander("📚 題庫快捷（生成/匯入頁面）", expanded=False):
        st.caption("你可以在此直接建立題庫檔，或把已勾選題目加入題庫（Drive JSON）。")

        if not st.session_state.bank_file_id:
            st.warning("尚未有題庫檔案（bank_file_id）。")
            if st.button("➕ 建立題庫檔（Drive）"):
                try:
                    fid = create_bank_file(creds, name="AI Quiz Bank.json")
                    st.session_state.bank_file_id = fid
                    st.success(f"✅ 已建立題庫檔：{fid}")
                except Exception as e:
                    show_exception("⚠️ 建立題庫檔失敗。", e)
                    return
        else:
            st.success(f"已使用題庫檔：{st.session_state.bank_file_id}")

        if st.session_state.bank_file_id and selected_df is not None and not selected_df.empty:
            if st.button("📥 加入題庫（已勾選匯出）"):
                try:
                    items = df_to_bank_items(selected_df)
                    added = append_questions(creds, st.session_state.bank_file_id, items, subject=subject)
                    st.success(f"✅ 已加入題庫：{added} 題")
                except Exception as e:
                    show_exception("⚠️ 加入題庫失敗。", e)

        st.caption("提示：題庫頁可以檢視/選題/再匯出/以電郵分享。")

# =========================
# Mode 1: 生成
# =========================
if mode == "🪄 AI 生成新題目":
    question_count = st.sidebar.selectbox("🧮 題目數目", [5, 8, 10, 12, 15, 20], index=2)
    cfg = api_config()

    files = st.file_uploader("上載教材（PDF/DOCX/TXT/PPTX/XLSX）", accept_multiple_files=True, type=["pdf","docx","txt","pptx","xlsx"])

    raw_text = ""
    if files:
        with st.spinner("📄 正在擷取文字…"):
            raw_text = "".join(extract_text(f) for f in files)
        st.info(f"✅ 已擷取 {len(raw_text)} 字（可用重點段落標記加強貼題）")

        with st.expander("⭐ 重點段落標記（勾選後會優先送入AI）", expanded=False):
            paras = split_paragraphs(raw_text)
            st.caption(f"段落數：{len(paras)}（以空行分段）")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 全選重點段落"):
                    st.session_state.mark_idx = set(range(len(paras)))
            with c2:
                if st.button("⛔ 全不選"):
                    st.session_state.mark_idx = set()

            for i, p in enumerate(paras[:80]):  # 顯示最多 80 段
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
            used_text = build_text_with_highlights(raw_text, st.session_state.mark_idx, limit)
            st.info(f"✅ 送入 AI：{len(used_text)} 字（上限 {limit}）｜題型：{qtype}｜難度：{level_label}")

            cache = load_cache()
            key = stable_key(used_text, subject, level_code, question_count, fast_mode, preset, model, base_url, qtype)

            if key in cache:
                st.success("✅ 已從快取讀取")
                st.session_state.generated_data = cache[key]
            else:
                with st.spinner("🤖 正在呼叫 AI，請稍候 10–30 秒…"):
                    st.session_state.generated_data = generate_questions(
                        cfg, used_text, subject, level_code, question_count, fast_mode=fast_mode, qtype=qtype
                    )
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

        st.caption(f"✅ 已選擇匯出 {len(selected)} 題（共 {len(edited)} 題）")

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

        # ✅ 你要求：生成頁面直接加按鈕（題庫快捷）
        bank_quick_panel(selected)

# =========================
# Mode 2: 匯入
# =========================
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

        st.caption(f"✅ 已選擇匯出 {len(selected)} 題（共 {len(edited)} 題）")

        st.download_button("⬇️ Kahoot Excel（已選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
        st.download_button("⬇️ Wayground DOCX（已選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

        # ✅ 你要求：匯入模式也要輸出 Google Form（已做）
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

        # ✅ 你要求：匯入頁面直接加按鈕（題庫快捷）
        bank_quick_panel(selected)

# =========================
# Mode 3: 題庫頁
# =========================
if mode == "📚 題庫（共享）":
    st.subheader("📚 題庫（Drive JSON）")

    if not BANK_ENABLED:
        st.warning("題庫模組未加入（services/google_drive_bank.py）。請先加入再使用。")
        st.stop()

    if not st.session_state.google_creds:
        st.warning("請先在左側登入 Google 才可使用題庫。")
        st.stop()

    creds = credentials_from_dict(st.session_state.google_creds)

    if not st.session_state.bank_file_id:
        st.info("尚未指定題庫檔案。你可在此建立一個新的題庫檔（Drive JSON）。")
        if st.button("➕ 建立題庫檔（Drive）"):
            try:
                fid = create_bank_file(creds, name="AI Quiz Bank.json")
                st.session_state.bank_file_id = fid
                st.success(f"✅ 已建立題庫檔：{fid}")
            except Exception as e:
                show_exception("⚠️ 建立題庫檔失敗。", e)
                st.stop()

    if st.session_state.bank_file_id:
        fid = st.session_state.bank_file_id
        st.success(f"目前題庫檔：{fid}")

        # 分享（以電郵）
        emails = st.text_input("📧 以電郵分享題庫（逗號分隔，多個 email）", value="")
        if st.button("📧 分享題庫（Drive 權限 + 通知電郵）"):
            try:
                ems = [e.strip() for e in emails.split(",") if e.strip()]
                share_bank_with_emails(creds, fid, ems, role="writer")
                st.success("✅ 已分享（Google 會寄出通知電郵）")
            except Exception as e:
                show_exception("⚠️ 分享失敗。", e)

        bank = load_bank(creds, fid)
        st.caption(f"題庫共有：{len(bank)} 題")

        # 顯示題庫（簡化：只顯示前 200 題）
        rows = []
        for item in bank[:200]:
            if not isinstance(item, dict):
                continue
            opts = item.get("options", ["", "", "", ""])
            if not isinstance(opts, list):
                opts = ["", "", "", ""]
            while len(opts) < 4:
                opts.append("")
            corr = item.get("correct", ["1"])
            corr_val = ",".join(corr) if isinstance(corr, list) else str(corr)

            rows.append({
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

        if rows:
            df = pd.DataFrame(rows)
            edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", column_config=EDITOR_COLUMN_CONFIG)
            selected = edited[edited["export"] == True].copy()

            st.download_button("⬇️ Kahoot Excel（題庫已選）", export_kahoot(selected if not selected.empty else edited), "kahoot.xlsx")
            st.download_button("⬇️ Wayground DOCX（題庫已選）", export_wayground_docx(selected if not selected.empty else edited, subject), "wayground.docx")

            if st.session_state.google_creds and not selected.empty:
                if st.button("🟦 用題庫已選建立 Google Form Quiz"):
                    try:
                        with st.spinner("🟦 正在建立 Google Form…"):
                            result = create_quiz_form(creds, f"{subject} Quiz", selected)
                        st.success("✅ 已建立 Google Form")
                        st.write("編輯連結：", result.get("editUrl"))
                        st.write("發佈連結：", result.get("responderUrl") or "（未提供 responderUri）")
                    except Exception as e:
                        show_exception("⚠️ 建立 Google Form 失敗。", e)
        else:
            st.info("題庫目前為空。你可以在『生成/匯入』頁面用『加入題庫』按鈕加入題目。")
