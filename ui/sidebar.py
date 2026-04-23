
import streamlit as st
import requests

"""
ui/sidebar.py（L1 + L2 完整整理版）
✅ 本版一次過完成：
L1｜顯示名 vs 出題 key 對齊（不影響現有流程）
L2｜科目分組與排序（教師 UX 提升）
＋
- ✅ 自動支援 DeepSeek（OpenAI‑compatible，model 可留空）
- ✅ xAI（Grok）自動選最新可用模型（失敗則不指定）
- ✅ OCR / Vision 設定（含 Vision PDF 頁數）
- ✅ 題目難度清晰說明（教師可理解）
- ✅ 修正 import，確保 app.py: from ui.sidebar import render_sidebar 正常


保證：
- ✅ python -m py_compile ui/sidebar.py
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
# L1｜顯示名 → 出題 key 對齊（穩定層）
# ------------------------------------------------------------
SUBJECT_KEY_MAP = {
    "中國語文": "中國語文",
    "英國語文": "英國語文",
    "數學": "數學",
    "公民與社會發展": "公民與社會發展",
    "公民、經濟及社會": "公民、經濟及社會",
    "科學": "科學",
    "物理": "物理",
    "化學": "化學",
    "生物": "生物",
    "地理": "地理",
    "歷史": "歷史",
    "中國歷史": "中國歷史",
    "宗教": "宗教",
    "資訊及通訊科技（ICT）": "ICT",
    "經濟": "經濟",
    "企業、會計與財務概論": "BAFS",
    "旅遊與款待": "旅遊與款待",
}


# ------------------------------------------------------------
# L2｜科目分組（只影響顯示，不影響回傳值）
# ------------------------------------------------------------
SUBJECT_GROUPS = {
    "語文": [
        "中國語文",
        "英國語文",
    ],
    "數學與科學": [
        "數學",
        "科學",
        "物理",
        "化學",
        "生物",
    ],
    "人文與社會": [
        "公民與社會發展",
        "公民、經濟及社會",
        "地理",
        "歷史",
        "中國歷史",
        "宗教",
    ],
    "商業與科技": [
        "經濟",
        "企業、會計與財務概論",
        "資訊及通訊科技（ICT）",
        "旅遊與款待",
    ],
}


# 將分組攤平成帶標題的清單（— 分組名 —）
def _build_subject_options() -> list[str]:
    opts: list[str] = []
    for group, items in SUBJECT_GROUPS.items():
        opts.append(f"— {group} —")
        for it in items:
            opts.append(it)
    return opts




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
        help="較快、較保守：較短輸出；適合日常快速出題。",
        key="fast_mode",
    )


    st.sidebar.divider()

    # =========================
    # AI 設定（OpenAI / xAI / DeepSeek）
    # =========================
    st.sidebar.header("🤖 AI 設定")


    provider = st.sidebar.selectbox(
        "模型供應商",
        ["OpenAI 相容", "xAI（Grok）", "DeepSeek"],
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


    elif provider == "DeepSeek":
        base_url = st.sidebar.text_input(
            "Base URL",
            value="https://api.deepseek.com/v1",
            key="base_url",
        )
        st.sidebar.caption("DeepSeek（OpenAI 相容）：Model 可留空，交由伺服器自選（如 deepseek-chat）")
        model_input = st.sidebar.text_input("Model（可留空）", value="", key="model")
        model = model_input.strip() or None


    else:
        base_url = "https://api.x.ai/v1"
        st.sidebar.caption("xAI（Grok）：自動選擇最新可用模型；失敗則不指定 model")
        if api_key:
            models = _xai_list_models(api_key, base_url)
            picked = _pick_latest_model(models)
            if picked:
                st.sidebar.success(f"✅ 已自動選用：{picked}")
                model = picked
            else:
                st.sidebar.warning("⚠️ 無法取得模型清單，將不指定 model")
                model = None


    # API 測試
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
    # OCR / Vision
    # =========================
    st.sidebar.header("� OCR / Vision")


    ocr_mode = st.sidebar.radio(
        "教材擷取模式",
        [
            "📄 純文字",
            "🔬 本地 OCR（掃描 PDF / 圖片）",
            "🤖 Vision OCR（LLM 讀圖）",
        ],
        index=0,
        key="ocr_mode",
    )

    vision_pdf_max_pages = 3
    if ocr_mode == "🤖 Vision OCR（LLM 讀圖）":
        vision_pdf_max_pages = st.sidebar.slider(
            "Vision PDF 最大頁數",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="vision_pdf_max_pages",
            help="頁數越多越準確，但耗時與成本較高",
        )


    st.sidebar.divider()


    # =========================
    # 出題設定（L1 + L2）
    # =========================
    st.sidebar.header("📘 出題設定")


    subject_options = _build_subject_options()


    subject_display = st.sidebar.selectbox(
        "科目",
        subject_options,
        key="subject_display",
    )


    # 跳過分組標題
    if subject_display.startswith("— "):
        subject_display = "中國語文"


    subject = subject_display
    subject_key = SUBJECT_KEY_MAP.get(subject, subject)


    # 難度（含清楚說明）
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

    # =========================
    # ctx 回傳
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
        "subject": subject_key,  # ✅ 對齊出題 key
        "subject_display": subject,  # ✅ UI 顯示名（可選）
        "level_code": level_code,
        "question_count": question_count,
        "fast_mode": fast_mode,
        "ocr_mode": ocr_mode,
        "vision_pdf_max_pages": vision_pdf_max_pages,
    }
