# ui/sidebar.py
# ---------------------------------------------------------
# Default: DeepSeek (built-in Key + auto model selection)
# Teacher can input own Key to override
# Advanced expander: API test, OCR settings, OpenAI / xAI / Azure / custom
# ---------------------------------------------------------

from __future__ import annotations
import os
import requests
import streamlit as st

try:
    from services.llm_service import ping_llm, SUBJECT_GROUPS
except Exception as e:
    ping_llm = None
    SUBJECT_GROUPS = {}
    st.sidebar.error(f"llm_service import failed: {e}")

try:
    from services.llm_service import get_xai_default_model
except Exception:
    get_xai_default_model = None

try:
    from services.cache_service import clear_all_cache
except Exception:
    clear_all_cache = None


# =========================================================
# Built-in Key
# =========================================================

def _get_builtin_deepseek_key() -> str:
    try:
        return st.secrets["deepseek"]["api_key"]
    except Exception:
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


# =========================================================
# xAI Helpers
# =========================================================

@st.cache_data(ttl=600, show_spinner=False)
def _xai_list_language_models(api_key: str, base_url: str) -> list:
    url = base_url.rstrip("/") + "/language-models"
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json() or {}
    models = data.get("models") or data.get("data") or []
    return [m for m in models if isinstance(m, dict)]


def _xai_build_model_options(models: list) -> list:
    options = []
    for m in models:
        for a in m.get("aliases", []):
            if isinstance(a, str):
                options.append(a)
        mid = m.get("id")
        if isinstance(mid, str):
            options.append(mid)
    seen, uniq = set(), []
    for x in options:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _xai_pick_default(models: list, preferred: str = "grok-3-latest") -> str:
    ids, aliases = [], []
    for m in models:
        if isinstance(m.get("id"), str):
            ids.append(m["id"])
        for a in m.get("aliases", []):
            if isinstance(a, str):
                aliases.append(a)
    for candidate in [preferred] + aliases + ids:
        if "grok" in candidate.lower():
            return candidate
    return "grok-2-latest"


# =========================================================
# Subject Groups Helper
# =========================================================

def _build_grouped_subject_options(subject_groups: dict) -> tuple:
    if not subject_groups:
        return [], {}
    options, mapping = [], {}
    for group_name, subjects in subject_groups.items():
        sep = f"--- {group_name} ---"
        options.append(sep)
        mapping[sep] = None
        for subject in subjects:
            options.append(subject)
            mapping[subject] = subject
    return options, mapping


# =========================================================
# render_sidebar()
# =========================================================

def render_sidebar() -> dict:
    st.sidebar.header("🔌 AI API 設定")

    # --- Fast Mode ---
    fast_mode = st.sidebar.checkbox(
        "⚡ 快速模式",
        value=True,
        help="快速模式：deepseek-chat（快）；關閉：deepseek-reasoner（慢但更準）",
    )
    st.sidebar.caption(
        "快速模式用 `deepseek-chat`；關閉後用 `deepseek-reasoner`（適合數理難題）。"
    )

    st.sidebar.divider()

    # =========================================================
    # Block A: DeepSeek default (daily teacher use)
    # =========================================================
    builtin_key = _get_builtin_deepseek_key()
    has_builtin = bool(builtin_key)

    if has_builtin:
        st.sidebar.success("✅ 已載入校內預設 Key（老師可直接使用）")
    else:
        st.sidebar.warning("⚠️ 未偵測到校內預設 Key，請在下方填入 API Key 或聯絡 IT。")

    teacher_key = st.sidebar.text_input(
        "API Key（選填）",
        type="password",
        key="api_key",
        placeholder="留空即用校內預設 Key",
        help="如需使用自己的 DeepSeek 帳戶，請填入個人 Key。",
    )

    effective_key = teacher_key if teacher_key else builtin_key

    deepseek_model = "deepseek-chat" if fast_mode else "deepseek-reasoner"
    deepseek_base_url = "https://api.deepseek.com/v1"

    st.sidebar.caption(f"🤖 使用模型：`{deepseek_model}`")

    # =========================================================
    # Block B: Advanced expander (IT / power users)
    # =========================================================
    advanced_cfg: dict | None = None

    with st.sidebar.expander("⚙️ 進階設定", expanded=False):
        st.caption("一般老師毋須設定。IT 或進階用戶可在此切換 LLM、測試連線及設定讀圖模式。")

        # --------------------------------------------------
        # B1: Switch LLM provider
        # --------------------------------------------------
        st.markdown("**切換 LLM 供應商**")
        adv_preset = st.selectbox(
            "LLM Provider",
            ["— 不切換（用上方 DeepSeek）—", "DeepSeek", "OpenAI 相容（自訂）", "Grok (xAI)", "Azure OpenAI"],
            key="adv_preset",
        )

        if adv_preset == "DeepSeek":
            adv_key = st.text_input("DeepSeek API Key", type="password", key="adv_ds_key")
            adv_model = st.selectbox(
                "Model",
                ["deepseek-chat", "deepseek-reasoner"],
                index=0 if fast_mode else 1,
                key="adv_ds_model",
            )
            st.caption("`deepseek-chat`: fast general; `deepseek-reasoner`: slower, better for STEM.")
            if adv_key:
                advanced_cfg = {
                    "type": "openai_compat",
                    "api_key": adv_key,
                    "base_url": "https://api.deepseek.com/v1",
                    "model": adv_model,
                }
            else:
                st.info("請填入 DeepSeek API Key（使用個人帳戶計費）。")

        elif adv_preset == "OpenAI 相容（自訂）":
            adv_key = st.text_input("API Key", type="password", key="adv_key")
            adv_url = st.text_input(
                "Base URL (include /v1)", key="adv_base_url", placeholder="https://api.openai.com/v1"
            )
            adv_model = st.text_input("Model", key="adv_model", placeholder="gpt-4o-mini")
            if adv_key and adv_url and adv_model:
                advanced_cfg = {
                    "type": "openai_compat",
                    "api_key": adv_key,
                    "base_url": adv_url,
                    "model": adv_model,
                }

        elif adv_preset == "Grok (xAI)":
            adv_key = st.text_input("xAI API Key", type="password", key="adv_xai_key")
            adv_url = "https://api.x.ai/v1"
            preferred = "grok-3-latest"
            xai_model = st.session_state.get("xai_selected_model", preferred)

            if adv_key:
                if st.button("🔍 取得可用 Grok 模型", key="btn_xai_models"):
                    try:
                        ml = _xai_list_language_models(adv_key, adv_url)
                        st.session_state["xai_models_cache"] = ml
                        st.success(f"✅ 載入 {len(ml)} 個模型")
                    except Exception as e:
                        st.error(f"{repr(e)}")

                ml = st.session_state.get("xai_models_cache", [])
                if ml:
                    opts = _xai_build_model_options(ml)
                    default_pick = _xai_pick_default(ml, preferred)
                    xai_model = st.selectbox(
                        "Grok 模型",
                        opts,
                        index=opts.index(default_pick) if default_pick in opts else 0,
                        key="xai_model_sel",
                    )
                else:
                    xai_model = st.text_input(
                        "Model（手動填入）", value=preferred, key="xai_model_manual"
                    )

                st.session_state["xai_selected_model"] = xai_model
                advanced_cfg = {
                    "type": "openai_compat",
                    "api_key": adv_key,
                    "base_url": adv_url,
                    "model": xai_model,
                }
            else:
                st.info("請填入 xAI API Key。")

        elif adv_preset == "Azure OpenAI":
            adv_key = st.text_input("Azure API Key", type="password", key="adv_az_key")
            az_endpoint = st.text_input(
                "Endpoint", key="adv_az_endpoint", placeholder="https://xxxxx.openai.azure.com/"
            )
            az_deployment = st.text_input("Deployment name", key="adv_az_deploy")
            az_api_version = st.text_input(
                "API version", value="2024-02-15-preview", key="adv_az_ver"
            )
            if adv_key and az_endpoint and az_deployment:
                advanced_cfg = {
                    "type": "azure",
                    "api_key": adv_key,
                    "endpoint": az_endpoint,
                    "deployment": az_deployment,
                    "api_version": az_api_version,
                }

        st.divider()

        # --------------------------------------------------
        # B2: API connection test (moved inside Advanced)
        # --------------------------------------------------
        st.markdown("**🧪 API 連線測試**")

        def _current_cfg() -> dict:
            if advanced_cfg:
                return advanced_cfg
            return {
                "type": "openai_compat",
                "api_key": effective_key,
                "base_url": deepseek_base_url,
                "model": deepseek_model,
            }

        def _can_call(cfg: dict) -> bool:
            if not cfg.get("api_key"):
                return False
            if cfg.get("type") == "azure":
                return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
            return bool(cfg.get("base_url")) and bool(cfg.get("model"))

        cfg_test = _current_cfg()

        ping_timeout = st.slider(
            "測試超時（秒）",
            min_value=10,
            max_value=120,
            value=45,
            key="ping_timeout_sec",
            help="DeepSeek-reasoner 較慢，建議 60 秒以上。",
        )

        if st.button("🧪 一鍵測試 API（回覆 OK）", key="btn_ping_api"):
            if ping_llm is None:
                st.warning("⚠️ llm_service 未提供 ping_llm()。")
            elif not _can_call(cfg_test):
                st.error("❌ 請先填妥 API Key 或聯絡 IT 設定校內預設 Key。")
            else:
                with st.spinner("正在測試連線…"):
                    r = ping_llm(cfg_test, timeout=int(ping_timeout))
                if r.get("ok"):
                    st.success(
                        f"✅ 成功：{r.get('latency_ms', 0)} ms　模型：{cfg_test.get('model', '')}"
                    )
                else:
                    st.error("❌ 失敗：請檢查 Key / 服務狀態")
                    st.code(r.get("error", ""))

        st.divider()

        # --------------------------------------------------
        # B3: OCR / Vision settings (moved inside Advanced)
        # --------------------------------------------------
        st.markdown("**🔬 OCR / 讀圖設定**")
        st.caption("數學／物理／化學建議開啟 Vision 模式。")

        ocr_mode = st.radio(
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
            vision_pdf_max_pages = st.slider(
                "Vision PDF 最多讀取頁數",
                min_value=1,
                max_value=10,
                value=3,
                key="vision_pdf_max_pages",
            )
            st.info("💡 DeepSeek 不支援 Vision，請在進階切換至 Grok / GPT-4o。")

    # =========================================================
    # Final cfg assembly (outside expander)
    # =========================================================
    def api_config() -> dict:
        if advanced_cfg:
            return advanced_cfg
        return {
            "type": "openai_compat",
            "api_key": effective_key,
            "base_url": deepseek_base_url,
            "model": deepseek_model,
        }

    def can_call_ai(cfg: dict) -> bool:
        if not cfg.get("api_key"):
            return False
        if cfg.get("type") == "azure":
            return bool(cfg.get("endpoint")) and bool(cfg.get("deployment"))
        return bool(cfg.get("base_url")) and bool(cfg.get("model"))

    # =========================================================
    # Question settings
    # =========================================================
    st.sidebar.divider()
    st.sidebar.header("📘 出題設定")

    if clear_all_cache is not None:
        _, col2 = st.sidebar.columns([3, 1])
        with col2:
            if st.button("🗑️ 清空快取", key="btn_clear_cache"):
                with st.spinner("清空中…"):
                    clear_all_cache()
                st.success("✅ 完成")

    st.sidebar.divider()

    subject = "中國語文"
    if SUBJECT_GROUPS:
        options, mapping = _build_grouped_subject_options(SUBJECT_GROUPS)
        default_idx = 1
        for i, o in enumerate(options):
            if o not in mapping or mapping[o] is None:
                continue
            default_idx = i
            break
        sel = st.sidebar.selectbox("科目", options, index=default_idx, key="subject_grouped")
        while sel in mapping and mapping[sel] is None:
            idx = options.index(sel) + 1
            sel = options[idx] if idx < len(options) and mapping.get(options[idx]) is not None else sel
            break
        subject = mapping.get(sel) or subject
    else:
        subject = st.sidebar.selectbox(
            "科目",
            [
                "中國語文", "英國語文", "數學",
                "物理", "化學", "生物", "科學",
                "公民與社會發展", "地理",
                "歷史", "中國歷史", "宗教",
                "經濟", "企業、會計與財務概論", "資訊及通訊科技（ICT）", "旅遊與款待",
            ],
            key="subject_flat",
        )

    level_label = st.sidebar.radio(
        "🎯 難度",
        [
            "基礎（理解與記憶）",
            "標準（應用與理解）",
            "進階（分析與思考）",
            "混合（課堂活動建議）",
        ],
        index=1,
        key="level_label",
    )

    level_code = {
        "基礎（理解與記憶）": "easy",
        "標準（應用與理解）": "medium",
        "進階（分析與思考）": "hard",
        "混合（課堂活動建議）": "mixed",
    }[level_label]

    question_count = st.sidebar.selectbox(
        "🧮 題目數目",
        [5, 8, 10, 12, 15, 20],
        index=2,
        key="question_count",
    )

    cfg_final = api_config()

    return {
        "fast_mode": fast_mode,
        "ocr_mode": ocr_mode,
        "vision_pdf_max_pages": vision_pdf_max_pages,
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": subject,
        "level_code": level_code,
        "question_count": question_count,
        "model": cfg_final.get("model", deepseek_model),
        "base_url": cfg_final.get("base_url", deepseek_base_url),
        "preset": adv_preset if advanced_cfg else "DeepSeek",
    }
