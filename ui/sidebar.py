import streamlit as st
from services.llm_service import ping_llm, get_xai_default_model


def render_sidebar() -> dict:
    """
    渲染側邊欄設定
    回傳 ctx dict，供 pages_generate.py 和 pages_import.py 使用
    """
    st.sidebar.header("🔌 AI API 設定")

    # Fast Mode
    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式",
        value=True,
        help="較快、較保守：較短輸出與較短超時；適合日常快速出題。"
    )
    st.sidebar.caption("關閉快速模式：較慢，但題目更豐富/更有變化。")

    st.sidebar.divider()

    # API Preset 選擇
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

    # Grok 自動偵測
    @st.cache_data(ttl=600, show_spinner=False)
    def _detect_xai_model_cached(k: str, u: str) -> str:
        return get_xai_default_model(k, u)

    if preset == "Grok (xAI)" and auto_xai and api_key:
        detected = _detect_xai_model_cached(api_key, base_url)
        if detected and detected != model:
            model = detected
            st.sidebar.caption(f"✅ 已自動選用：{model}")

    # API 配置函數
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

    # OCR / Vision 設定
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
            help="頁數越多越準確，但耗時與費用也越高。"
        )
        st.sidebar.info("💡 DeepSeek 不支援 Vision，請改用 Grok 或 GPT-4o 等模型。")

    st.sidebar.divider()

    # 出題設定
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

    # 回傳上下文給主程式與各頁面使用
    return {
        "fast_mode": fast_mode,
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": subject,
        "level_code": level_code,
        "question_count": question_count,
        "preset": preset,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }
