# app.py — 更新版（已拆分 export 面板 + 強化 Vision 與隱私提醒）

import io
import traceback
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from core.question_mapper import dicts_to_items, items_to_editor_df
from services.llm_service import (
    llm_ocr_extract_text,
    generate_questions,
    assist_import_questions,
    parse_import_questions_locally,
    ping_llm,
    get_xai_default_model,
)
from services.cache_service import save_cache
from extractors.extract import extract_payload
from services.google_oauth import (
    oauth_is_configured,
    get_auth_url,
    exchange_code_for_credentials,
    credentials_to_dict,
    credentials_from_dict,
)
from ui.components_export import render_export_panel   # ← 新增：使用模組化 export 面板

# ------------------------- Session State Init -------------------------
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

# ------------------------- Helpers -------------------------
def build_text_with_highlights(raw_text, marked_idx, limit):
    if not raw_text:
        return ""
    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return ""
    highlighted = [p for i, p in enumerate(paragraphs) if i in marked_idx]
    others = [p for i, p in enumerate(paragraphs) if i not in marked_idx]
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

# ------------------------- Page Config -------------------------
st.set_page_config(page_title="AI 題目生成器", layout="wide")
st.title("🏫 AI 題目生成器")

# ------------------------- OAuth Callback -------------------------
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

# ------------------------- Sidebar -------------------------
st.sidebar.header("🟦 Google 連接（Google Forms / Google Drive 一鍵分享）")
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

# Fast Mode
fast_mode = st.sidebar.checkbox(
    "⚡ 快速模式", value=True,
    help="較快、較保守：較短輸出與較短超時；適合日常快速出題。"
)
st.sidebar.caption("關閉快速模式：較慢，但題目更豐富/更有變化。")

# AI API 設定（保持原邏輯不變）
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

azure_endpoint = azure_deployment = ""
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

# OCR / Vision 設定
st.sidebar.header("🔬 OCR / 讀圖設定（數理科必讀）")
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
        "Vision PDF 最多讀取頁數", min_value=1, max_value=10, value=3, key="vision_pdf_max_pages"
    )
    st.sidebar.info("💡 DeepSeek 不支援 Vision，請改用 Grok / GPT-4o 等模型。")

st.sidebar.divider()

# 出題設定
st.sidebar.header("📘 出題設定")
subject = st.sidebar.selectbox("科目", [
    "中國語文", "英國語文", "數學", "公民與社會發展", "科學", "公民、經濟及社會",
    "物理", "化學", "生物", "地理", "歷史", "中國歷史", "宗教",
    "資訊及通訊科技（ICT）", "經濟", "企業、會計與財務概論", "旅遊與款待",
], key="subject")

level_label = st.sidebar.radio(
    "🎯 難度",
    ["基礎（理解與記憶）", "標準（應用與理解）", "進階（分析與思考）", "混合（課堂活動建議）"],
    index=1, key="level_label"
)
level_map = {"基礎（理解與記憶）": "easy", "標準（應用與理解）": "medium",
             "進階（分析與思考）": "hard", "混合（課堂活動建議）": "mixed"}
level_code = level_map[level_label]

question_count = st.sidebar.selectbox("🧮 題目數目（生成用）", [5, 8, 10, 12, 15, 20], index=2, key="question_count")

# ------------------------- 隱私提醒（新增） -------------------------
st.sidebar.divider()
st.sidebar.markdown("### ⚠️ 隱私提醒")
st.sidebar.info(
    "教材內容將傳送至您所選的 AI 服務商（OpenAI / xAI / DeepSeek 等）。\n\n"
    "**請勿上傳含有學生個人資料、敏感資訊或受版權嚴格保護的完整教材。**"
)

# ------------------------- 使用流程（新增隱私提醒） -------------------------
with st.expander("🧭 使用流程", expanded=True):
    st.markdown("""
**⚠️ 重要隱私提醒**  
教材內容會上傳至第三方 AI 服務，請避免上傳含學生姓名、學號或其他個人資料的文件。

### 🪄 生成新題目
1. 左側欄選擇科目、難度、題目數目  
2. 填寫 AI API Key 並測試連線  
3. **① 上載教材**（支援 Vision 讀圖）  
4. **② 重點段落標記**（可選）  
5. 按「🪄 生成題目」  
6. **④ 檢視與微調**（特別留意 `⚠️ 需教師確認` 的題目）  
7. 勾選匯出 → **⑤ 匯出**（Kahoot / Wayground / Google Forms / 電郵分享）

### 📄 匯入現有題目
1. 貼上或上載題目  
2. 選擇是否使用 AI 協助整理  
3. 按「✨ 整理並轉換」後核對答案  
4. 勾選匯出

**💡 小提示**：數理科建議開啟 Vision 模式；重要測驗請關閉快速模式。
""")

tab_generate, tab_import = st.tabs(["🪄 生成新題目", "📄 匯入現有題目"])

# ========================= Tab 1: Generate =========================
with tab_generate:
    st.markdown("## ① 上載教材")
    st.caption("支援 PDF / DOCX / TXT / PPTX / XLSX / PNG / JPG；可配合 OCR 或 Vision 讀圖。")

    cfg = api_config()

    reset_generation = st.checkbox(
        "🧹 清除上一輪生成記憶（切換課題時建議勾選）",
        value=False,
        help="清空上一輪生成的題目與快取。",
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

        if use_vision and vision_images:
            with st.expander("🖼️ 預覽已讀取圖像（前 3 張）"):
                for i, img in enumerate(vision_images[:3]):
                    st.image(img, caption=f"第 {i + 1} 張／頁", use_container_width=True)

    # 重點段落標記（保持不變）
    st.markdown("## ② 重點段落標記（可選）")
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
            new_checked = st.checkbox(f"第 {i + 1} 段", value=checked, key=f"para_{i}")
            if new_checked:
                st.session_state.mark_idx.add(i)
            else:
                st.session_state.mark_idx.discard(i)
            st.write(p[:200] + ("…" if len(p) > 200 else ""))

    # 生成題目
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
                vision_used = False
                if vision_images and ocr_mode == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）":
                    try:
                        data = llm_ocr_extract_text(
                            cfg,
                            text=used_text,
                            images=vision_images,
                            subject=subject,
                            level=level_code,
                            count=question_count,
                            fast_mode=fast_mode,
                        )
                        vision_used = True
                    except Exception:
                        st.warning("⚠️ Vision 模式執行失敗，已自動回退至純文字模式。")
                        data = generate_questions(
                            cfg, used_text, subject, level_code, question_count,
                            fast_mode=fast_mode, qtype="single"
                        )
                else:
                    data = generate_questions(
                        cfg, used_text, subject, level_code, question_count,
                        fast_mode=fast_mode, qtype="single"
                    )

                # 強化 Vision 回退提示
                if ocr_mode == "🤖 LLM Vision 讀圖（圖表/方程式/手寫，最準）" and not vision_used:
                    st.info(
                        "ℹ️ **Vision 模式已回退至純文字出題**\n\n"
                        "原因：目前所選模型不支援圖像輸入（例如 DeepSeek），或圖像處理失敗。\n"
                        "建議：改用支援 Vision 的模型（如 Grok、GPT-4o）以獲得更好圖表／方程式辨識效果。"
                    )

            if not data:
                st.error("❌ AI 沒有回傳任何題目")
            else:
                st.session_state.generated_items = dicts_to_items(data, subject=subject, source="generate")
                st.session_state.pop("export_init_generate", None)
                st.success(f"✅ 成功生成 {len(st.session_state.generated_items)} 題")
        except Exception as e:
            show_exception("⚠️ 生成題目失敗。", e)

    # 檢視與微調 + 匯出
    if st.session_state.generated_items:
        items = st.session_state.generated_items
        total_count = len(items)
        review_count = sum(1 for q in items if q.needs_review)
        ok_count = total_count - review_count

        st.markdown("## ✅ 題目品質摘要")
        c1, c2 = st.columns(2)
        with c1: st.metric("✅ 通過題目", ok_count)
        with c2: st.metric("⚠️ 需教師留意", review_count)

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

        # 使用模組化 export 面板（取代舊的 export_and_share_panel）
        render_export_panel(selected, subject, st.session_state.get("google_creds"), prefix="generate")

        if st.session_state.get("current_section") == "export":
            components.html(
                '<script>var el=document.getElementById("export_anchor_generate");if(el){el.scrollIntoView({behavior:"smooth"});}</script>',
                height=0,
            )

# ========================= Tab 2: Import =========================
with tab_import:
    st.markdown("## ① 上載 / 貼上題目")
    st.caption("支援 DOCX / TXT 或直接貼上。匯入模式固定為單選（4 選 1）。")

    cfg = api_config()

    def load_import_file_to_textbox():
        f = st.session_state.get("import_file")
        if f is None: return
        from extractors.extract import extract_text
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
    import_can_run = import_has_text and (not use_ai_assist or can_call_ai(cfg))

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
            st.success(f"✅ 已整理 {len(items)} 題")
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

        # 使用模組化 export 面板
        render_export_panel(selected, subject, st.session_state.get("google_creds"), prefix="import")

        if st.session_state.get("current_section") == "export":
            components.html(
                '<script>var el=document.getElementById("export_anchor_import");if(el){el.scrollIntoView({behavior:"smooth"});}</script>',
                height=0,
            )
