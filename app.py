import io
import traceback
import hashlib
import streamlit as st
import pandas as pd

from core.question_mapper import dicts_to_items, items_to_editor_df
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from exporters.export_kahoot import export_kahoot_excel
from exporters.export_wayground_docx import export_wayground_docx


from services.llm_service import (
    xai_pick_vision_model, llm_ocr_extract_text,
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
    get_xai_default_model,
)
from services.cache_service import load_cache, save_cache
from extractors.extract import extract_text
from extractors.extract import extract_images_for_llm_ocr
from exporters.export_kahoot import export_kahoot_excel
from exporters.export_wayground_docx import export_wayground_docx
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)
from services.google_forms_api import create_quiz_form


# -------------------------
# Helpers
# -------------------------
def stable_key(*parts) -> str:
    raw = "||".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def show_exception(user_msg: str, e: Exception):
    st.error(user_msg)
    with st.expander("🔎 技術細節（供維護用）"):
        st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))


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
                "qtype": "single",
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


def drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_bytes_to_drive(creds, filename: str, mimetype: str, data_bytes: bytes) -> dict:
    service = drive_service(creds)
    media = MediaIoBaseUpload(io.BytesIO(data_bytes), mimetype=mimetype, resumable=False)
    meta = {"name": filename}
    return service.files().create(body=meta, media_body=media, fields="id, webViewLink").execute()


def share_file_to_emails(creds, file_id: str, emails: list, role: str = "reader"):
    service = drive_service(creds)
    for email in emails:
        email = str(email).strip()
        if not email:
            continue
        body = {"type": "user", "role": role, "emailAddress": email}
        service.permissions().create(fileId=file_id, body=body, sendNotificationEmail=True).execute()


def export_and_share_panel(selected_df: pd.DataFrame, subject_name: str, prefix: str):
    """匯出 Kahoot/Wayground +（可選）用 Google Drive 一鍵電郵分享。"""
    if selected_df is None or selected_df.empty:
        st.warning("⚠️ 尚未選擇任何題目（請在表格中勾選『匯出』欄）。")
        return

    kahoot_bytes = export_kahoot_excel(selected_df)
    docx_bytes = export_wayground_docx(selected_df, subject_name)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Kahoot Excel", kahoot_bytes, "kahoot.xlsx", key=f"dl_kahoot_{prefix}")
        st.caption("用途：匯入 Kahoot / Quiz 平台（只包含已勾選題目）")
    with c2:
        st.download_button("⬇️ Wayground DOCX", docx_bytes, "wayground.docx", key=f"dl_docx_{prefix}")
        st.caption("用途：Wayground / 校內工作紙（只包含已勾選題目）")

    st.markdown("### 📧 一鍵電郵分享匯出檔（Google Drive）")
    st.caption("會先把檔案上載到你的 Google Drive，然後分享並寄出通知電郵。")

    if not st.session_state.google_creds:
        st.info("請先在左側登入 Google，才可用電郵分享檔案。")
        return

    emails_text = st.text_input("收件人電郵（多個用逗號分隔）", value="", key=f"emails_{prefix}")
    emails = [e.strip() for e in emails_text.split(",") if e.strip()]

    colA, colB = st.columns(2)
    with colA:
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

    with colB:
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


# -------------------------
# Page config + session
# -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器（新版介面）")
st.caption("UI版本：UI-REDESIGN 2026-04-19 v1 ✅（見到呢句＝你已成功換到新版）")

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
# Session state init
# -------------------------
if "generated_items" not in st.session_state:
    st.session_state.generated_items = []

if "form_result_generate" not in st.session_state:
    st.session_state.form_result_generate = None
    
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
    st.caption("支援 PDF/DOCX/TXT/PPTX/XLSX。系統會抽取文字後交給 AI 出題。")

    # ✅ 只定義一次 cfg（非常重要）
    cfg = api_config()

    enable_llm_ocr = st.checkbox(
        "🖼️ 啟用 LLM 讀圖 OCR（適合掃描/截圖/圖表/幾何；較慢）",
        value=False,
        help=(
            "當抽取到的文字太少或品質差，會把圖片/掃描 PDF 前幾頁交給 "
            "Grok 或其他 LLM 讀圖抽字（DeepSeek 欠缺 OCR，不可用）。"
        ),
    )
    llm_ocr_pdf_pages = st.selectbox(
        "LLM OCR PDF頁數（只取前幾頁）", [1, 2, 3, 4, 5], index=2
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

        # ===== OCR 補強（不包住生成按鈕）=====
        if enable_llm_ocr and can_call_ai(cfg) and len(raw_text.strip()) < 200:
            if preset == "Grok (xAI)":
                vision_model = xai_pick_vision_model(api_key, base_url)
                if vision_model:
                    cfg2 = dict(cfg)
                    cfg2["model"] = vision_model
                else:
                    st.warning("⚠️ 找不到支援圖片輸入的 Grok 型號，已略過 LLM OCR。")
                    cfg2 = None
            else:
                cfg2 = cfg

            if cfg2:
                images = []
                for f in files:
                    images.extend(
                        extract_images_for_llm_ocr(
                            f,
                            pdf_max_pages=llm_ocr_pdf_pages,
                            pdf_zoom=2.0,
                        )
                    )

                if images:
                    with st.spinner("🖼️ 正在用 LLM 讀圖抽取文字…"):
                        ocr_text = llm_ocr_extract_text(
                            cfg2,
                            images,
                            lang_hint="zh-Hant",
                            fast_mode=fast_mode,
                        )
                    if ocr_text and len(ocr_text) > len(raw_text):
                        raw_text = (ocr_text + "\n\n" + raw_text).strip()

        st.info(f"✅ 已擷取 {len(raw_text)} 字")

        # ===== ② 重點段落標記 =====
        st.markdown("## ② 重點段落標記（可選）")
        st.caption("勾選後會把重點段落放在最前面，提高貼題度。")

        with st.expander("⭐ 打開段落清單（最多顯示 80 段）", expanded=False):
            paras = split_paragraphs(raw_text)
            st.caption(f"段落數：{len(paras)}（以空行分段）")

            cA, cB = st.columns(2)
            with cA:
                if st.button("✅ 全選重點段落", key="btn_mark_all"):
                    st.session_state.mark_idx = set(range(len(paras)))
            with cB:
                if st.button("⛔ 全不選", key="btn_mark_none"):
                    st.session_state.mark_idx = set()

            for i, p in enumerate(paras[:80]):
                checked = i in st.session_state.mark_idx
                new_checked = st.checkbox(
                    f"第 {i+1} 段", value=checked, key=f"para_{i}"
                )
                if new_checked:
                    st.session_state.mark_idx.add(i)
                else:
                    st.session_state.mark_idx.discard(i)
                st.write(p[:200] + ("…" if len(p) > 200 else ""))

    # ===== ③ 生成題目 =====
    st.markdown("## ③ 生成題目")
    st.caption("按下後呼叫 AI 生成題目；完成後會自動跳到題目編輯區。")

    limit = 8000 if fast_mode else 10000

    if st.button(
        "🪄 生成題目",
        disabled=not (can_call_ai(cfg) and bool(raw_text.strip())),
        key="btn_generate",
    ):
        try:
            used_text = build_text_with_highlights(
                raw_text,
                st.session_state.mark_idx,
                limit,
            )

            with st.spinner("🤖 正在生成…"):
                items = generate_questions(
                    cfg,
                    used_text,
                    subject,
                    level_code,
                    question_count,
                    fast_mode=fast_mode,
                    qtype="single",
                )

            if not items:
                st.error("❌ AI 沒有回傳任何題目")
            else:
                st.session_state.generated_items = dicts_to_items(
                    items,
                    subject=subject,
                    source="import",
                )

                st.session_state.imported_items = items
                
                # ✅ 自動 scroll 到 ④
                st.markdown(
                    """
                    <script>
                    const el = document.getElementById("section-review");
                    if (el) {
                        el.scrollIntoView({behavior: "smooth"});
                    }
                    </script>
                    """,
                    unsafe_allow_html=True,
                )

        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)

            cache = load_cache()
            PROMPT_VERSION = "fmtquota_v1"
            qtype = "single"
            cache_key = stable_key(
                used_text,
                subject,
                level_code,
                question_count,
                fast_mode,
                preset,
                model,
                base_url,
                qtype,
                PROMPT_VERSION,
            )

            if cache_key in cache:
                st.success("✅ 已從快取讀取（節省時間與額度）")
                st.session_state.generated_data = cache[cache_key]
            else:
                with st.spinner("🤖 正在生成…"):
                    st.session_state.generated_data = generate_questions(
                        cfg,
                        used_text,
                        subject,
                        level_code,
                        question_count,
                        fast_mode=fast_mode,
                        qtype=qtype,
                    )
                cache[cache_key] = st.session_state.generated_data
                save_cache(cache)

            st.session_state.form_result_generate = None

        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)

items = st.session_state.generated_items

total_count = len(items)
review_count = sum(1 for q in items if q.needs_review)
ok_count = total_count - review_count

# =================================================
# ④ 檢視與微調（題目品質摘要 + 編輯）
# =================================================
if st.session_state.get("generated_items"):
    items = st.session_state.generated_items

    # -------- 題目品質摘要 --------
    total_count = len(items)
    review_count = sum(1 for q in items if q.needs_review)
    ok_count = total_count - review_count

    st.markdown("## ✅ 題目品質摘要")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("✅ 通過題目", ok_count)
    with c2:
        st.metric("⚠️ 需教師留意", review_count)

    if review_count > 0:
        with st.expander("⚠️ 查看需教師留意的題目"):
            for i, q in enumerate(items, start=1):
                if q.needs_review:
                    st.write(f"第 {i} 題：{q.question[:80]}…")

    # -------- 題目編輯區 --------
    st.markdown("## ④ 檢視與微調")
    st.caption("你可以在表格內直接修改題幹、選項及正確答案，並勾選是否匯出。")

    df = items_to_editor_df(items)

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("✅ 全選匯出", key="btn_export_all_generate"):
            df["export"] = True
    with c2:
        if st.button("全部取消匯出", key="btn_export_none_generate"):
            df["export"] = False

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

    st.success(
        f"✅ 已生成 {len(edited)} 題；"
        f"已選擇匯出 {len(selected)} 題"
    )

    # =================================================
    # ⑤ 匯出 / Google Form / 電郵分享
    # =================================================
    st.markdown("## ⑤ 匯出 / Google Form / 電郵分享")
    st.caption("先勾選要匯出的題目，然後使用以下功能。")

    if selected.empty:
        st.info("請先在上方表格勾選要匯出的題目。")
    else:
        
        # -------- Google Form Quiz --------
        if st.session_state.google_creds:
            if st.button("🟦 一鍵建立 Google Form Quiz", key="btn_form_generate"):
                try:
                    with st.spinner("🟦 正在建立 Google Form…"):
                        creds = credentials_from_dict(
                            st.session_state.google_creds
                        )
                        result = create_quiz_form(
                            creds,
                            f"{subject} Quiz",
                            selected,
                        )
                    st.session_state.form_result_generate = result
                    st.success("✅ 已建立 Google Form")
                except Exception as e:
                    show_exception("⚠️ 建立 Google Form 失敗。", e)

        if st.session_state.form_result_generate:
            st.write(
                "編輯連結：",
                st.session_state.form_result_generate.get("editUrl"),
            )
            st.write(
                "發佈連結：",
                st.session_state.form_result_generate.get("responderUrl")
                or "（未提供 responderUri）",
            )

        # -------- Google Drive 一鍵分享 --------
        export_and_share_panel(
            selected,
            subject,
            prefix="generate",
        )


# =========================
# Tab 2: Import
# =========================
with tab_import:
    st.markdown("## ① 上載 / 貼上題目")
    st.caption("支援 DOCX/TXT 或直接貼上。匯入模式固定為單選（4選1）。")

    cfg = api_config()

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None:
            return
        st.session_state.imported_text = extract_text(f) or ""
        st.session_state.imported_data = None

    st.file_uploader(
        "上載 DOCX/TXT（自動載入到文字框）",
        type=["docx", "txt"],
        key="import_file",
        on_change=load_import_file_to_textbox,
    )

    use_ai_assist = st.checkbox("啟用 AI 協助整理（建議）", value=True, key="use_ai_assist")
    st.text_area("貼上題目內容", height=320, key="imported_text")

    st.markdown("## ② 整理並轉換")
    st.caption("啟用 AI 協助：會拆出題幹/選項/答案；若原文無答案，AI 會推測並標記『需教師確認』。")

    if st.button(
        "✨ 整理並轉換",
        disabled=not (bool(st.session_state.imported_text.strip()) and (not use_ai_assist or can_call_ai(cfg))),
        key="btn_import_parse",
    ):
        try:
            raw = st.session_state.imported_text.strip()
            with st.spinner("🧠 正在整理…"):
                if use_ai_assist:
                    st.session_state.imported_data = assist_import_questions(
                        cfg,
                        raw,
                        subject,
                        allow_guess=True,
                        fast_mode=fast_mode,
                        qtype="single",
                    )
                else:
                    st.session_state.imported_data = parse_import_questions_locally(raw)
            st.session_state.form_result_import = None
        except Exception as e:
            st.warning("⚠️ AI 整理失敗，改用本地拆題作備援，請老師核對答案。")
            try:
                st.session_state.imported_data = parse_import_questions_locally(st.session_state.imported_text.strip())
            except Exception as e2:
                show_exception("⚠️ 本地拆題亦失敗，請檢查貼上的格式。", e2)
                st.stop()
            with st.expander("🔎 AI 失敗技術細節"):
                st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))

    if st.session_state.imported_data:
        st.markdown("## ③ 檢視與微調")
        st.caption("在表格內校對題幹、選項與答案，並勾選是否匯出。")

# =================================================
# ✅ 題目品質摘要（匯入現有題目）
# =================================================
if st.session_state.get("imported_items"):
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

    if review_count > 0:
        with st.expander("⚠️ 查看需教師留意的題目"):
            for i, q in enumerate(items, start=1):
                if q.needs_review:
                    st.write(f"第 {i} 題：{q.question[:80]}…")
        
        df = to_editor_df(st.session_state.imported_data, subject)

        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("✅ 全選匯出", key="btn_export_all_import"):
                df["export"] = True
        with c2:
            if st.button("全部取消匯出", key="btn_export_none_import"):
                df["export"] = False

        edited = st.data_editor(
            df,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "export": st.column_config.CheckboxColumn("匯出", width="small"),
                "correct": st.column_config.SelectboxColumn("正確答案（1-4）", options=["1","2","3","4"], width="small"),
                "needs_review": st.column_config.CheckboxColumn("需教師確認", width="small"),
            },
            disabled=["subject", "qtype"],
            key="editor_import",
        )
        selected = edited[edited["export"] == True].copy()

        st.success(f"✅ 已載入 {len(edited)} 題；已選擇匯出 {len(selected)} 題")

        st.markdown("## ④ 匯出 / Google Form / 電郵分享")
        st.caption("先勾選要匯出的題目，然後使用以下功能。")

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
