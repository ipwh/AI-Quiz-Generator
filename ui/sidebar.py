import streamlit as st
import requests

"""ui/sidebar.py

目標（按你最新要求）：
- 預設使用 DeepSeek
- 不顯示 Base URL / Model（自動選擇最佳 model；仍提供「進階設定」可覆寫）
- 修復 KeyError('model')：任何 OpenAI-compatible 呼叫都一定會帶 model（至少 fallback default）
- 保留 xAI（Grok）與 OpenAI 相容的入口（放入「進階」）
- 提供 OCR/Vision 設定 + Vision PDF 頁數
- 提供題目難度說明（easy/medium/hard）
- 回傳 ctx 供 pages_generate/pages_import 使用

備註：
- DeepSeek 為 OpenAI-compatible，預設 base_url=https://api.deepseek.com/v1
- 自動選模型策略：嘗試 GET {base_url}/models 取得列表；再依優先序挑選
"""

# Optional helpers
try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None


# ------------------------------
# Model auto-pick helpers
# ------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _list_openai_compat_models(api_key: str, base_url: str) -> list[str]:
    """Try to list models from OpenAI-compatible endpoint. Return [] on any failure."""
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        out = []
        for m in data.get("data", []):
            mid = m.get("id")
            if isinstance(mid, str):
                out.append(mid)
        return out
    except Exception:
        return []


def _pick_best_deepseek_model(models: list[str]) -> str:
    """Pick best DeepSeek model from list; fallback to deepseek-chat."""
    if not models:
        return "deepseek-chat"
    # Prefer newer/reasoning models if present, else deepseek-chat
    priority = [
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-chat",
    ]
    ms = set(models)
    for p in priority:
        if p in ms:
            return p
    # Fallback: pick a model containing 'deepseek' and 'chat'
    for m in models:
        lm = m.lower()
        if "deepseek" in lm and "chat" in lm:
            return m
    # Last resort
    return models[0]


def _pick_best_grok_model(models: list[str]) -> str | None:
    if not models:
        return None
    prefer = [m for m in models if m.startswith("grok-") and "image" not in m and "video" not in m]
    if prefer:
        return sorted(prefer, reverse=True)[0]
    return sorted(models, reverse=True)[0]


# ------------------------------
# Subjects (按你指定，不猜)
# ------------------------------
SUBJECTS = [
    "中國語文",
    "英國語文",
    "數學",
    "公民與社會發展",
    "科學",
    "公民、經濟及社會",
    "物理",
    "化學",
    "生物",
    "地理",
    "歷史",
    "中國歷史",
    "宗教",
    "資訊及通訊科技（ICT）",
    "經濟",
    "企業、會計與財務概論",
    "旅遊與款待",
]

SUBJECT_GROUPS = {
    "語文": ["中國語文", "英國語文"],
    "數學與科學": ["數學", "科學", "物理", "化學", "生物"],
    "人文與社會": ["公民與社會發展", "公民、經濟及社會", "地理", "歷史", "中國歷史", "宗教"],
    "商業與科技": ["經濟", "企業、會計與財務概論", "資訊及通訊科技（ICT）", "旅遊與款待"],
}

def _build_subject_options() -> list[str]:
    opts: list[str] = []
    for g, items in SUBJECT_GROUPS.items():
        opts.append(f"— {g} —")
        opts.extend(items)
    return opts


# ------------------------------
# Sidebar renderer
# ------------------------------

def render_sidebar() -> dict:
    st.sidebar.header("⚙️ 基本設定")

    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式（較快、較保守）",
        value=True,
        help="開啟後會使用較短輸出與較短超時，適合日常快速出題。",
        key="fast_mode",
    )

    st.sidebar.divider()

    # ---- AI provider (default DeepSeek; hide base_url/model) ----
    st.sidebar.header("🤖 AI 設定")

    # Default provider fixed to DeepSeek; put others in advanced
    provider = st.sidebar.selectbox(
        "服務",
        ["DeepSeek（預設）", "OpenAI 相容（進階）", "xAI（Grok）（進階）"],
        index=0,
        key="provider",
        help="預設使用 DeepSeek。進階可切換其他服務。",
    )

    api_key = st.sidebar.text_input("API Key", type="password", key="api_key")

    # Provider configs
    base_url = "https://api.deepseek.com/v1"
    model = None

    if provider.startswith("DeepSeek"):
        base_url = "https://api.deepseek.com/v1"
        # Auto-pick model after API key provided
        if api_key:
            models = _list_openai_compat_models(api_key, base_url)
            model = _pick_best_deepseek_model(models)
        else:
            model = "deepseek-chat"

        st.sidebar.caption("已選 DeepSeek：Base URL / Model 由系統自動管理（不顯示）。")

        # (Optional) show what model picked (debug) in expander
        with st.sidebar.expander("🔎 顯示已選模型（除錯用）", expanded=False):
            st.write(model)

    elif provider.startswith("OpenAI 相容"):
        with st.sidebar.expander("⚙️ OpenAI 相容（進階）", expanded=True):
            base_url = st.text_input("Base URL", value="https://api.openai.com/v1", key="adv_base_url")
            # Try auto pick; allow override
            picked = None
            if api_key:
                ms = _list_openai_compat_models(api_key, base_url)
                picked = ms[0] if ms else None
            override = st.text_input("Model（可留空用自動選擇）", value="", key="adv_model")
            model = override.strip() or picked or "gpt-4o-mini"

    else:
        # xAI Grok
        base_url = "https://api.x.ai/v1"
        if api_key:
            models = _list_openai_compat_models(api_key, base_url)
            model = _pick_best_grok_model(models)
        model = model or "grok-2-latest"
        st.sidebar.caption("xAI：將自動選最新可用 Grok；若取不到清單則用預設。")

    # Ensure cfg ALWAYS has model to avoid KeyError('model') in llm_service
    def api_config() -> dict:
        return {
            "type": "openai_compat",
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
        }

    def can_call_ai(cfg: dict) -> bool:
        return bool(cfg.get("api_key")) and bool(cfg.get("base_url")) and bool(cfg.get("model"))

    # API test (expander)
    with st.sidebar.expander("🧪 API 連線測試", expanded=False):
        if ping_llm is None:
            st.info("此版本未提供 ping_llm，可直接嘗試生成題目測試。")
        else:
            if st.button("🧪 測試（回覆 OK）", key="btn_ping_api"):
                cfg_test = api_config()
                if not can_call_ai(cfg_test):
                    st.error("請先輸入 API Key（並確保已選到 model）。")
                else:
                    with st.spinner("測試中…"):
                        r = ping_llm(cfg_test, timeout=25)
                    if r.get("ok"):
                        st.success(f"✅ 成功：{r.get('latency_ms', 0)} ms；回覆：{r.get('output','')}")
                    else:
                        st.error("❌ 失敗")
                        st.code(r)

    st.sidebar.divider()

    # ---- OCR/Vision ----
    st.sidebar.header("🔍 OCR / Vision")

    ocr_mode = st.sidebar.radio(
        "教材擷取模式",
        [
            "📄 純文字（一般文件，最快）",
            "🔬 本地 OCR（掃描 PDF/圖片，離線）",
            "🤖 Vision OCR（LLM 讀圖，較準）",
        ],
        index=0,
        key="ocr_mode",
    )

    vision_pdf_max_pages = 3
    if ocr_mode.startswith("🤖"):
        vision_pdf_max_pages = st.sidebar.slider(
            "Vision PDF 最大頁數",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="vision_pdf_max_pages",
            help="頁數越多越準確，但耗時與成本較高。",
        )

    st.sidebar.divider()

    # ---- Question settings ----
    st.sidebar.header("📘 出題設定")

    subject_options = _build_subject_options()
    subject_display = st.sidebar.selectbox(
        "科目",
        subject_options,
        key="subject_display",
    )
    # If user accidentally chooses group header, keep previous subject or default
    if subject_display.startswith("— "):
        subject_display = st.session_state.get("subject", "中國語文")

    # Persist subject
    st.session_state["subject"] = subject_display

    level_code = st.sidebar.selectbox(
        "題目難度",
        ["easy", "medium", "hard"],
        index=1,
        format_func=lambda x: {
            "easy": "容易（基礎概念、直接題）",
            "medium": "中等（理解＋應用）",
            "hard": "困難（高階思維、綜合題）",
        }[x],
        key="level_code",
    )

    question_count = st.sidebar.slider(
        "題目數量",
        min_value=3,
        max_value=20,
        value=10,
        step=1,
        key="question_count",
    )

    return {
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": subject_display,
        "level_code": level_code,
        "question_count": question_count,
        "fast_mode": fast_mode,
        "ocr_mode": ocr_mode,
        "vision_pdf_max_pages": vision_pdf_max_pages,
    }
