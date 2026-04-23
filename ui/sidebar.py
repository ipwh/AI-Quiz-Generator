import streamlit as st
import requests

"""
ui/sidebar.py
重點：
- xAI（Grok）在輸入 API Key 後，自動取得可用最新 model
- 不再硬編寫 grok-* 型號，避免 Model not found
- 若 API 不支援列出模型，安全回退（讓 server 自行決定）
- 回傳 ctx dict 供 pages 使用
"""

# ------------------------------------------------------------
# Optional helpers
# ------------------------------------------------------------
try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None

# ------------------------------------------------------------
# xAI helper: list models
# ------------------------------------------------------------
@st.cache_data(ttl=300)
def _xai_list_models(api_key: str, base_url: str) -> list[str]:
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        models = []
        for m in data.get("data", []):
            mid = m.get("id")
            if isinstance(mid, str):
                models.append(mid)
        return models
    except Exception:
        return []


def _pick_latest_model(models: list[str]) -> str | None:
    """Pick a reasonable latest Grok model if present."""
    if not models:
        return None
    # prefer grok-4 / grok-3, avoid image/video-only models
    prefer = [m for m in models if m.startswith("grok-") and "image" not in m and "video" not in m]
    if prefer:
        return sorted(prefer, reverse=True)[0]
    return sorted(models, reverse=True)[0]


# ------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------

def render_sidebar() -> dict:
    st.sidebar.header("⚙️ 基本設定")

    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式",
        value=True,
        help="較快、較保守：較短輸出與較短超時；適合日常快速出題。",
        key="fast_mode",
    )

    st.sidebar.divider()
    st.sidebar.header("🤖 AI 設定")

    provider = st.sidebar.selectbox(
        "模型供應商",
        ["OpenAI 相容", "xAI（Grok）"],
        index=0,
        key="provider",
    )

    api_key = st.sidebar.text_input("API Key", type="password", key="api_key")

    base_url = ""
    model = None

    if provider == "OpenAI 相容":
        base_url = st.sidebar.text_input(
            "Base URL",
            value="https://api.openai.com/v1",
            key="base_url",
        )
        model = st.sidebar.text_input(
            "Model（可留空，讓伺服器自選）",
            value="",
            key="model",
        )
        if not model:
            model = None

    else:
        # xAI Grok
        base_url = "https://api.x.ai/v1"
        st.sidebar.caption("已選 xAI（Grok）：將自動選擇最新可用型號")

        if api_key:
            models = _xai_list_models(api_key, base_url)
            picked = _pick_latest_model(models)
            if picked:
                st.sidebar.success(f"✅ 已自動選用：{picked}")
                model = picked
            else:
                st.sidebar.warning("⚠️ 無法取得模型清單，將不指定 model 交由伺服器決定")
                model = None
        else:
            model = None

    # ------------------------------------------------------------
    # API config builders
    # ------------------------------------------------------------
    def api_config() -> dict:
        cfg = {
            "api_key": api_key,
            "base_url": base_url,
        }
        if model:
            cfg["model"] = model
        return cfg

    def can_call_ai(cfg: dict) -> bool:
        return bool(cfg.get("api_key")) and bool(cfg.get("base_url"))

    st.sidebar.divider()
    st.sidebar.header("📘 出題設定")

    subject = st.sidebar.selectbox(
        "科目",
        ["中國語文", "英文", "數學", "科學", "通識"],
        key="subject",
    )

    level_code = st.sidebar.selectbox(
        "難度",
        ["easy", "medium", "hard"],
        index=1,
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
        "subject": subject,
        "level_code": level_code,
        "question_count": question_count,
        "fast_mode": fast_mode,
        "ocr_mode": st.session_state.get("ocr_mode", "📄 純文字"),
        "vision_pdf_max_pages": st.session_state.get("vision_pdf_max_pages", 3),
    }
