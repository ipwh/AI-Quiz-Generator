import streamlit as st

# ✅ 兼容不同版本 llm_service：可能沒有 ping_llm / get_xai_default_model
try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None

try:
    from services.llm_service import get_xai_default_model as _get_xai_default_model
except Exception:
    _get_xai_default_model = None


def _local_detect_xai_model(api_key: str, base_url: str) -> str:
    """在沒有 get_xai_default_model() 時，本地用 OpenAI-compatible /models 自動偵測 Grok 型號。"""
    import requests

    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    models = data.get("data", []) if isinstance(data, dict) else []
    ids = []
    for m in models:
        mid = m.get("id") if isinstance(m, dict) else None
        if isinstance(mid, str):
            ids.append(mid)

    # 偏好：含 grok、含 latest
    grok = [i for i in ids if "grok" in i.lower()]
    if not grok:
        return "grok-4-latest"

    latest = [i for i in grok if "latest" in i.lower()]
    if latest:
        # 若多個 latest，取字串排序最後一個
        return sorted(latest)[-1]

    # 否則取字串排序最後一個
    return sorted(grok)[-1]


@st.cache_data(ttl=600, show_spinner=False)
def _detect_xai_model_cached(api_key: str, base_url: str) -> str:
    if _get_xai_default_model:
        return _get_xai_default_model(api_key, base_url)
    return _local_detect_xai_model(api_key, base_url)


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

    if preset == "DeepSeek":
        base_url = "https://api.deepseek.com/v1"
        model = "deepseek-chat"

    elif preset == "OpenAI":
        base_url = "https://api.openai.com/v1"
        model = "gpt-4o-mini"

    elif preset == "Grok (xAI)":
        base_url = "https://api.x.ai/v1"
        model = "grok-4-latest"
        auto_xai = st.sidebar.checkbox(
            "🤖 自動偵測可用最新 Grok 型號（建議）",
            value=True,
            key="auto_xai",
        )

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

    # Grok auto-detect
    if preset == "Grok (xAI)" and auto_xai and api_key:
        try:
            detected = _detect_xai_model_cached(api_key, base_url)
            if detected and detected != model:
                model = detected
                st.sidebar.caption(f"✅ 已自動選用：{model}")
        except Exception as e:
            st.sidebar.caption("（自動偵測失敗，將使用 grok-4-latest）")

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

    if st.sidebar.button("🧪 一鍵測試 API（回覆 OK）", key="btn_ping_api"):
        if ping_llm is None:
            st.sidebar.warning("⚠️ 此版本 llm_service 未提供 ping_llm()，已略過測試。")
        elif not can_call_ai(cfg_test):
            st.sidebar.error("請先填妥 API Key／Base URL／Model（Azure 要 Endpoint + Deployment）。")
        else:
            with st.sidebar.spinner("正在測試連線…"):
                r = ping_llm(cfg_test, timeout=25)
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
    }
