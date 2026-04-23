import streamlit as st
import requests

"""
ui/sidebar.py（修正 import 錯誤＋科目補齊版）

✅ 本版先解決的『硬問題』
1) ✅ 修正語法／縮排錯誤，確保 app.py 第 14 行
       from ui.sidebar import render_sidebar
   可以成功 import
2) ✅ 保留你上載版本的設計方向（OpenAI 相容 + xAI Grok）
3) ✅ 補齊並固定你指定的科目清單（不猜、不自動生成）

保證：
- ✅ python -m py_compile ui/sidebar.py 可通過
- ✅ Streamlit 可正常啟動
"""

# ------------------------------------------------------------
# Optional helpers (safe import)
# ------------------------------------------------------------
try:
    from services.llm_service import ping_llm
except Exception:
    ping_llm = None

# ------------------------------------------------------------
# xAI helpers
# ------------------------------------------------------------
@st.cache_data(ttl=300)
def _xai_list_models(api_key: str, base_url: str) -> list[str]:
    """List available xAI models. Return empty list on any failure."""
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        models: list[str] = []
        for m in data.get("data", []):
            mid = m.get("id")
            if isinstance(mid, str):
                models.append(mid)
        return models
    except Exception:
        return []


def _pick_latest_model(models: list[str]) -> str | None:
    """Pick a reasonable latest Grok chat model; avoid image/video-only models."""
    if not models:
        return None
    prefer = [m for m in models if m.startswith("grok-") and "image" not in m and "video" not in m]
    if prefer:
        return sorted(prefer, reverse=True)[0]
    return sorted(models, reverse=True)[0]


# ------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------

def render_sidebar() -> dict:
    # =========================
    # 基本設定
    # =========================
    st.sidebar.header("⚙️ 基本設定")

    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式",
        value=True,
        help="較快、較保守：較短輸出與較短超時；適合日常快速出題。",
        key="fast_mode",
    )

    st.sidebar.divider()

    # =========================
    # AI 設定
    # =========================
    st.sidebar.header("🤖 AI 設定")

    provider = st.sidebar.selectbox(
        "模型供應商",
        ["OpenAI 相容", "xAI（Grok）"],
        index=0,
        key="provider",
    )

    api_key = st.sidebar.text_input("API Key", type="password", key="api_key")

    base_url: str = ""
    model: str | None = None

    if provider == "OpenAI 相容":
        base_url = st.sidebar.text_input(
            "Base URL",
            value="https://api.openai.com/v1",
            key="base_url",
        )
        model_input = st.sidebar.text_input(
            "Model（可留空，讓伺服器自選）",
            value="",
            key="model",
        )
        model = model_input.strip() or None
    else:
        # xAI Grok
        base_url = "https://api.x.ai/v1"
        st.sidebar.caption("xAI（Grok）：將自動選擇最新可用模型；若失敗則不指定 model")
        if api_key:
            models = _xai_list_models(api_key, base_url)
            picked = _pick_latest_model(models)
            if picked:
                st.sidebar.success(f"✅ 已自動選用：{picked}")
                model = picked
            else:
                st.sidebar.warning("⚠️ 無法取得模型清單，將不指定 model")
                model = None

    # =========================
    # API 連線測試
    # =========================
    with st.sidebar.expander("🧪 API 連線測試", expanded=False):
        if not ping_llm:
            st.info("此版本未提供 ping_llm，略過測試。")
        else:
            if st.button("🧪 測試 API", key="btn_ping_api"):
                if not api_key or not base_url:
                    st.error("請先輸入 API Key 與 Base URL")
                else:
                    cfg_test = {"api_key": api_key, "base_url": base_url}
                    if model:
                        cfg_test["model"] = model
                    with st.spinner("測試中…"):
                        r = ping_llm(cfg_test)
                    if r.get("ok"):
                        st.success("✅ API 可正常使用")
                    else:
                        st.error("❌ API 測試失敗")
                        st.code(r)

    st.sidebar.divider()

    # =========================
    # 出題設定（✅ 依你指定補齊科目）
    # =========================
    st.sidebar.header("📘 出題設定")

    subject = st.sidebar.selectbox(
        "科目",
        [
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
        ],
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

    # =========================
    # ctx 回傳（供 app / pages 使用）
    # =========================
    def api_config() -> dict:
        cfg = {"api_key": api_key, "base_url": base_url}
        if model:
            cfg["model"] = model
        return cfg

    def can_call_ai(cfg: dict) -> bool:
        return bool(cfg.get("api_key")) and bool(cfg.get("base_url"))

    return {
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": subject,
        "level_code": level_code,
        "question_count": question_count,
        "fast_mode": fast_mode,
    }
