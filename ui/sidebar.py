import streamlit as st

# =========================================================
# ui/sidebar.py (修正版)
# ---------------------------------------------------------
# ✅ 修正 xAI 400 Model not found：改用 /v1/language-models 取得可用模型清單
# ✅ 預設優先：grok-4-0709（若清單存在）
# ✅ 支援：Grok (xAI) + 自訂（OpenAI 相容）+ DeepSeek/OpenAI/Azure
# ✅ 兼容不同版本 llm_service：可能沒有 ping_llm / get_xai_default_model
# =========================================================

import requests

# 兼容不同版本 llm_service
try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None

try:
    from services.llm_service import get_xai_default_model  # 可選：若你的 llm_service 有提供
except Exception:
    get_xai_default_model = None


# ---------------------------------------------------------
# xAI: /v1/language-models（列出 chat + image understanding）
# ---------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def _xai_list_language_models(api_key: str, base_url: str) -> list:
    """讀取 xAI /v1/language-models，回傳 list[dict]。

    xAI 官方提供：/v1/language-models 可列出可用 chat/image understanding 模型及 aliases。
    """
    url = base_url.rstrip("/") + "/language-models"
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json() or {}

    # 官方文件字段：models（部分 gateway 可能用 data）
    models = data.get("models")
    if isinstance(models, list):
        return [m for m in models if isinstance(m, dict)]

    models = data.get("data")
    if isinstance(models, list):
        return [m for m in models if isinstance(m, dict)]

    return []


def _xai_build_model_options(models: list) -> list:
    """把 models 的 aliases + id 合併成下拉選單，去重並保持順序。"""
    options = []
    for m in models:
        als = m.get("aliases", [])
        if isinstance(als, list):
            options.extend([a for a in als if isinstance(a, str)])
        mid = m.get("id")
        if isinstance(mid, str):
            options.append(mid)

    seen = set()
    uniq = []
    for x in options:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _xai_pick_default_model(models: list, preferred: str = "grok-4-0709") -> str:
    """依序挑選：preferred → 任一 grok alias → 任一 grok id → grok-2-latest。"""
    ids, aliases = [], []
    for m in models:
        mid = m.get("id")
        if isinstance(mid, str):
            ids.append(mid)
        als = m.get("aliases", [])
        if isinstance(als, list):
            for a in als:
                if isinstance(a, str):
                    aliases.append(a)

    if preferred in ids or preferred in aliases:
        return preferred

    for a in aliases:
        if "grok" in a.lower():
            return a

    for mid in ids:
        if "grok" in mid.lower():
            return mid

    return "grok-2-latest"


def render_sidebar() -> dict:
    """渲染側邊欄設定，回傳 ctx dict，供 pages_generate.py / pages_import.py 使用。"""

    st.sidebar.header("🔌 AI API 設定")

    # Fast Mode
    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式",
        value=True,
        help="較快、較保守：較短輸出與較短超時；適合日常快速出題。",
    )
    st.sidebar.caption("關閉快速模式：較慢，但題目更豐富/更有變化。")
    st.sidebar.divider()

    # API Preset
    preset = st.sidebar.selectbox(
        "快速選擇（簡易）",
        ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"],
        key="preset",
    )

    api_key = st.sidebar.text_input("API Key", type="password", key="api_key")

    auto_xai = False
    azure_endpoint = ""
    azure_deployment = ""
    azure_api_version = "2024-02-15-preview"

    # Preset defaults
    if preset == "DeepSeek":
        base_url = "https://api.deepseek.com/v1"
        model = "deepseek-chat"

    elif preset == "OpenAI":
        base_url = "https://api.openai.com/v1"
        model = "gpt-4o-mini"

    elif preset == "Grok (xAI)":
        base_url = "https://api.x.ai/v1"

        # 你指定預設：grok-4-0709
        preferred = "grok-4-0709"
        model = st.session_state.get("xai_selected_model", preferred)

        auto_xai = st.sidebar.checkbox(
            "🤖 自動偵測可用最新 Grok 型號（建議）",
            value=True,
            key="auto_xai",
        )

        st.sidebar.caption("建議：先按『🔍 取得可用模型』，再從清單選擇，避免 Model not found。")

        if api_key:
            # 手動拉清單
            if st.sidebar.button("🔍 取得可用模型", key="btn_xai_fetch_models"):
                try:
                    models = _xai_list_language_models(api_key, base_url)
                    st.session_state["xai_models_cache"] = models
                    st.sidebar.success(f"✅ 已載入 {len(models)} 個可用模型")
                except Exception as e:
                    st.sidebar.error("❌ 取得模型清單失敗（請檢查 Key/網絡）")
                    st.sidebar.code(repr(e))

            models = st.session_state.get("xai_models_cache", [])

            # 如果 llm_service 有 get_xai_default_model，就可先用它（保持向後相容）
            if auto_xai and api_key and get_xai_default_model:
                try:
                    detected = get_xai_default_model(api_key, base_url)
                    if detected:
                        model = detected
                        st.session_state["xai_selected_model"] = model
                        st.sidebar.caption(f"✅ 已自動選用：{model}")
                except Exception:
                    pass

            # 優先用 /v1/language-models（你指定）
            if auto_xai and models:
                picked = _xai_pick_default_model(models, preferred=preferred)
                model = picked
                st.session_state["xai_selected_model"] = model
                st.sidebar.caption(f"✅ 已自動選用：{model}")

            # 有清單就給下拉
            if models:
                options = _xai_build_model_options(models)
                if model not in options:
                    model = _xai_pick_default_model(models, preferred=preferred)
                model = st.sidebar.selectbox(
                    "Grok 模型（從可用清單選擇）",
                    options,
                    index=options.index(model) if model in options else 0,
                    key="xai_model_selectbox",
                )
                st.session_state["xai_selected_model"] = model
            else:
                # 沒清單時提供手動輸入（仍可用）
                model = st.sidebar.text_input(
                    "Model（建議先按『取得可用模型』）",
                    value=model,
                    key="xai_model_manual",
                )
                st.session_state["xai_selected_model"] = model
        else:
            st.sidebar.info("先填入 xAI API Key 才能載入可用模型清單。")

    elif preset == "Azure OpenAI":
        base_url = ""
        model = ""
        with st.sidebar.expander("⚙️ Azure 設定", expanded=True):
            azure_endpoint = st.text_input("Azure Endpoint", value="", key="azure_endpoint")
            azure_deployment = st.text_input("Deployment name", value="", key="azure_deployment")
            azure_api_version = st.text_input("API version", value=azure_api_version, key="azure_api_version")

    else:
        base_url = st.sidebar.text_input("Base URL（含 /v1）", value="", key="custom_base_url")
        model = st.sidebar.text_input("Model", value="", key="custom_model")

    # API config
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

    def can_call_ai(cfg: dict) -> bool:
        if not cfg.get("api_key"):
            return False
        if cfg.get("type") == "azure":
            return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
        return bool(cfg.get("base_url")) and bool(cfg.get("model"))

    # Ping
    st.sidebar.divider()
    st.sidebar.header("🧪 API 連線測試")
    cfg_test = api_config()

    # ✅ 把測試 timeout 拉長些：避免 DeepSeek 25s 易 timeout
    ping_timeout = st.sidebar.slider(
        "測試超時（秒）",
        min_value=10,
        max_value=120,
        value=45,
        key="ping_timeout_sec",
        help="DeepSeek/網絡繁忙時建議 45–90 秒。",
    )

    if st.sidebar.button("🧪 一鍵測試 API（回覆 OK）", key="btn_ping_api"):
        if ping_llm is None:
            st.sidebar.warning("⚠️ 此版本 llm_service 未提供 ping_llm()，已略過測試。")
        elif not can_call_ai(cfg_test):
            st.sidebar.error("請先填妥 API Key／Base URL／Model（Azure 要 Endpoint + Deployment）。")
        else:
            with st.sidebar.spinner("正在測試連線…"):
                r = ping_llm(cfg_test, timeout=int(ping_timeout))
            if r.get("ok"):
                st.sidebar.success(f"✅ 成功：{r.get('latency_ms', 0)} ms；回覆：{r.get('output','')}")
            else:
                st.sidebar.error("❌ 失敗：請檢查 Key/Endpoint/Model 或服務狀態")
                st.sidebar.code(r.get("error", ""))

    # OCR / Vision
    st.sidebar.divider()
    st.sidebar.header("🔬 OCR / 讀圖設定（數理科必讀）")
    st.sidebar.caption("數學／物理／化學／生物建議開啟 Vision 模式以辨識圖表與方程式。")

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
            help="頁數越多越準確，但耗時與費用也越高。",
        )
        st.sidebar.info("💡 DeepSeek 不支援 Vision，請改用 Grok 或 GPT-4o 等模型。")

    # 出題設定
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

    question_count = st.sidebar.selectbox(
        "🧮 題目數目（生成用）",
        [5, 8, 10, 12, 15, 20],
        index=2,
        key="question_count",
    )

    return {
        "fast_mode": fast_mode,
        "ocr_mode": ocr_mode,
        "vision_pdf_max_pages": vision_pdf_max_pages,
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": subject,
        "level_code": level_code,
        "question_count": question_count,

        # debug echoes
        "preset": preset,
        "model": model,
        "base_url": base_url,
    }
