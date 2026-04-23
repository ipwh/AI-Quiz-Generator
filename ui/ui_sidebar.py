import streamlit as st

"""ui/sidebar.py

重點：
- 只負責 AI / OCR / 科目設定（Google 登入已由 app.py 固定置頂）
- UX：把「一般老師常用」放前面，「進階/技術」收進 expander
- 回傳 ctx dict 供 pages 使用：api_config()、can_call_ai()、subject、level_code、question_count、fast_mode
"""

# 兼容不同版本 llm_service：可能沒有 ping_llm / get_xai_default_model
try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None

try:
    from services.llm_service import get_xai_default_model
except Exception:
    get_xai_default_model = None


def render_sidebar() -> dict:
    # ------------------------------------------------------------
    # 快速模式
    # ------------------------------------------------------------
    st.sidebar.header("⚙️ 基本設定")
    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式",
        value=True,
        help="較快、較保守：較短輸出與較短超時；適合日常快速出題。",
        key="fast_mode",
    )
    st.sidebar.caption("關閉快速模式：較慢，但題目更豐富/更有變化。")

    st.sidebar.divider()

    # ------------------------------------------------------------
    # AI API 設定（老師常用放前面）
    # ------------------------------------------------------------
    st.sidebar.header("🔌 AI 設定")

    preset = st.sidebar.selectbox(
        "快速選擇（簡易）",
        ["DeepSeek", "OpenAI", "Grok (xAI)", "Azure OpenAI", "自訂（OpenAI 相容）"],
        index=0,
        key="preset",
    )

    api_key = st.sidebar.text_input("API Key", type="password", key="api_key")

    # 預設值
    base_url = ""
    model = ""
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
        auto_xai = st.sidebar.checkbox(
            "🤖 自動偵測可用最新 Grok 型號（建議）",
            value=True,
            key="auto_xai",
        )
    elif preset == "Azure OpenAI":
        # 進階區輸入
        base_url = ""
        model = ""
    else:
        # 自訂
        base_url = st.sidebar.text_input("Base URL（含 /v1）", value="", key="custom_base_url")
        model = st.sidebar.text_input("Model", value="", key="custom_model")

    # Azure 進階
    azure_endpoint = ""
    azure_deployment = ""
    azure_api_version = "2024-02-15-preview"

    if preset == "Azure OpenAI":
        with st.sidebar.expander("⚙️ Azure 進階設定", expanded=True):
            azure_endpoint = st.text_input("Azure Endpoint", value="", key="azure_endpoint")
            azure_deployment = st.text_input("Deployment name", value="", key="azure_deployment")
            azure_api_version = st.text_input("API version", value=azure_api_version, key="azure_api_version")

    # xAI 自動偵測（如果 llm_service 有提供）
    @st.cache_data(ttl=600, show_spinner=False)
    def _detect_xai_model_cached(k: str, u: str) -> str:
        if get_xai_default_model is None:
            return ""
        try:
            return get_xai_default_model(k, u)
        except Exception:
            return ""

    if preset == "Grok (xAI)" and auto_xai and api_key:
        detected = _detect_xai_model_cached(api_key, base_url)
        if detected and detected != model:
            model = detected
            st.sidebar.caption(f"✅ 已自動選用：{model}")

    # ------------------------------------------------------------
    # API config 回傳
    # ------------------------------------------------------------
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
        if not isinstance(cfg, dict):
            return False
        if not cfg.get("api_key"):
            return False
        if cfg.get("type") == "azure":
            return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
        return bool(cfg.get("base_url")) and bool(cfg.get("model"))

    # ------------------------------------------------------------
    # API 測試（收進摺疊，避免 sidebar 太長）
    # ------------------------------------------------------------
    with st.sidebar.expander("🧪 測試 AI 連線", expanded=False):
        if ping_llm is None:
            st.info("此版本未提供 ping_llm()，可略過連線測試。")
        else:
            cfg_test = api_config()
            if st.button("🧪 一鍵測試（回覆 OK）", key="btn_ping_api"):
                if not can_call_ai(cfg_test):
                    st.error("請先填妥必要欄位。")
                else:
                    with st.spinner("正在測試連線…"):
                        r = ping_llm(cfg_test, timeout=25)
                    if r.get("ok"):
                        st.success(f"✅ 成功：{r.get('latency_ms', 0)} ms；回覆：{r.get('output','')}")
                    else:
                        st.error("❌ 失敗：請檢查 Key/Endpoint/Model 或服務狀態")
                        st.code(r.get("error", ""))

    st.sidebar.divider()

    # ------------------------------------------------------------
    # OCR / Vision 設定
    # ------------------------------------------------------------
    st.sidebar.header("🔬 掃描件 / 圖表處理")
    st.sidebar.caption("數學／理化／圖表多的教材，建議使用 Vision OCR。")

    ocr_mode = st.sidebar.radio(
        "教材擷取模式",
        [
            "📄 純文字（一般文件，最快）",
            "🔬 本地 OCR（掃描 PDF/圖片，離線）",
            "🤖 Vision OCR（先讀圖抽字，再用文字出題）",
        ],
        index=0,
        key="ocr_mode",
    )

    vision_pdf_max_pages = 3
    if ocr_mode == "🤖 Vision OCR（先讀圖抽字，再用文字出題）":
        vision_pdf_max_pages = st.sidebar.slider(
            "Vision PDF 最多讀取頁數",
            min_value=1,
            max_value=10,
            value=3,
            key="vision_pdf_max_pages",
            help="頁數越多越準確，但耗時與費用也越高。",
        )
        st.sidebar.info("提示：DeepSeek 通常不支援 Vision；建議使用 Grok / GPT-4o 等。")

    st.sidebar.divider()

    # ------------------------------------------------------------
    # 出題設定
    # ------------------------------------------------------------
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

    # 回傳 ctx
    return {
        "fast_mode": fast_mode,
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": subject,
        "level_code": level_code,
        "question_count": question_count,
        "ocr_mode": ocr_mode,
        "vision_pdf_max_pages": vision_pdf_max_pages,
        # debug / display
        "preset": preset,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }
