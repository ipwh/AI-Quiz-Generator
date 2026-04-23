import time
import requests
import streamlit as st

# DeepSeek 官方 OpenAI-compatible：base_url 可用 /v1；常用模型 alias：deepseek-chat / deepseek-reasoner [1](blob:https://m365.cloud.microsoft/9ce86d4e-2f80-4454-9f4f-8cd667877612)
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL_FAST = "deepseek-chat"
DEEPSEEK_MODEL_QUALITY = "deepseek-reasoner"

SUBJECTS = [
    "中國語文", "英國語文", "數學", "公民與社會發展", "科學", "公民、經濟及社會",
    "物理", "化學", "生物", "地理", "歷史", "中國歷史", "宗教",
    "資訊及通訊科技（ICT）", "經濟", "企業、會計與財務概論", "旅遊與款待",
]

SUBJECT_GROUPS = {
    "語文": ["中國語文", "英國語文"],
    "數學與科學": ["數學", "科學", "物理", "化學", "生物"],
    "人文與社會": ["公民與社會發展", "公民、經濟及社會", "地理", "歷史", "中國歷史", "宗教"],
    "商業與科技": ["資訊及通訊科技（ICT）", "經濟", "企業、會計與財務概論", "旅遊與款待"],
}

def _build_subject_options() -> listopts: list[str] = []
    for g, items in SUBJECT_GROUPS.items():
        opts.append(f"— {g} —")
        opts.extend(items)
    for s in SUBJECTS:
        if s not in opts:
            opts.append(s)
    return opts


def _ping_deepseek(api_key: str, model: str) -> dict:
    """
    真實 DeepSeek ping：POST /chat/completions
    回傳：ok/latency_ms/output/error/status_code/body
    """
    t0 = time.time()
    url = DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "temperature": 0,
        "stream": False,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        latency = int((time.time() - t0) * 1000)
        text = r.text or ""
        if r.status_code >= 400:
            # 盡量抽取 error.message
            err_msg = ""
            try:
                j = r.json()
                if isinstance(j, dict):
                    err = j.get("error")
                    if isinstance(err, dict):
                        err_msg = err.get("message") or ""
                    elif isinstance(err, str):
                        err_msg = err
            except Exception:
                pass
            if not err_msg:
                err_msg = f"HTTP {r.status_code}"
            return {
                "ok": False,
                "latency_ms": latency,
                "output": "",
                "error": err_msg,
                "status_code": r.status_code,
                "body": text[:1200],
            }

        j = r.json()
        out = ""
        try:
            out = j["choices"][0]["message"]["content"]
        except Exception:
            out = ""
        return {
            "ok": True,
            "latency_ms": latency,
            "output": out,
            "error": "",
            "status_code": r.status_code,
        }
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        msg = str(e) or e.__class__.__name__
        return {
            "ok": False,
            "latency_ms": latency,
            "output": "",
            "error": msg,
            "status_code": None,
        }


def render_sidebar() -> dict:
    st.sidebar.header("⚙️ 基本設定")

    # ✅ 用 form：避免每次改 slider 都 rerun（解決「跳到頁底」）[2](https://docs.streamlit.io/develop/concepts/architecture/forms)[3](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form)
    with st.sidebar.form("sidebar_form", clear_on_submit=False):
        fast_mode = st.checkbox(
            "⚡ 快速模式",
            value=st.session_state.get("fast_mode", True),
            help="開啟：較快、較保守；關閉：較慢但內容更豐富。",
        )

        st.divider()
        st.subheader("🤖 AI（預設 DeepSeek）")
        api_key = st.text_input(
            "DeepSeek API Key",
            type="password",
            value=st.session_state.get("api_key", ""),
        )

        model = DEEPSEEK_MODEL_FAST if fast_mode else DEEPSEEK_MODEL_QUALITY
        st.caption(f"✅ 自動模型：{model}（{'快速' if fast_mode else '高質'}）")

        # OCR / Vision
        st.divider()
        st.subheader("🔍 OCR / Vision")
        ocr_mode = st.radio(
            "教材擷取模式",
            ["📄 純文字", "🔬 本地 OCR（掃描 PDF / 圖片）", "🤖 Vision OCR（LLM 讀圖）"],
            index=["📄 純文字", "🔬 本地 OCR（掃描 PDF / 圖片）", "🤖 Vision OCR（LLM 讀圖）"].index(
                st.session_state.get("ocr_mode", "📄 純文字")
            ),
        )

        vision_pdf_max_pages = st.session_state.get("vision_pdf_max_pages", 3)
        if ocr_mode == "🤖 Vision OCR（LLM 讀圖）":
            vision_pdf_max_pages = st.slider(
                "Vision PDF 最大頁數",
                min_value=1,
                max_value=10,
                value=int(vision_pdf_max_pages),
                step=1,
                help="頁數越多越準確，但耗時與成本較高。",
            )

        # 出題設定
        st.divider()
        st.subheader("📘 出題設定")

        subject_options = _build_subject_options()
        subject = st.selectbox(
            "科目",
            subject_options,
            index=subject_options.index(st.session_state.get("subject", "中國語文"))
            if st.session_state.get("subject", "中國語文") in subject_options
            else 0,
        )
        if subject.startswith("— "):
            subject = "中國語文"

        level_code = st.selectbox(
            "題目難度",
            ["easy", "medium", "hard"],
            index=["easy", "medium", "hard"].index(st.session_state.get("level_code", "medium")),
            format_func=lambda x: {
                "easy": "容易（基礎概念、直接題）",
                "medium": "中等（理解＋應用）",
                "hard": "困難（高階思維、綜合題）",
            }[x],
        )

        question_count = st.slider(
            "題目數量",
            min_value=3,
            max_value=20,
            value=int(st.session_state.get("question_count", 10)),
            step=1,
        )

        # ✅ form submit：一次過套用，避免每次改動就 rerun [2](https://docs.streamlit.io/develop/concepts/architecture/forms)[3](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form)
        apply_btn = st.form_submit_button("✅ 套用設定")

    # 套用：寫回 session_state
    if apply_btn:
        st.session_state["fast_mode"] = fast_mode
        st.session_state["api_key"] = api_key
        st.session_state["ocr_mode"] = ocr_mode
        st.session_state["vision_pdf_max_pages"] = vision_pdf_max_pages
        st.session_state["subject"] = subject
        st.session_state["level_code"] = level_code
        st.session_state["question_count"] = question_count
        # 套用後 rerun 一次就好
        st.rerun()

    # 額外：API 測試（唔放入 form，按一次才 rerun）
    st.sidebar.divider()
    with st.sidebar.expander("🧪 API 連線測試（DeepSeek）", expanded=False):
        if st.button("🧪 測試 DeepSeek", key="btn_ping_deepseek"):
            key = st.session_state.get("api_key", "")
            fm = st.session_state.get("fast_mode", True)
            m = DEEPSEEK_MODEL_FAST if fm else DEEPSEEK_MODEL_QUALITY
            if not key:
                st.error("請先輸入 API Key，再按測試。")
            else:
                with st.spinner("測試中…"):
                    r = _ping_deepseek(key, m)
                if r.get("ok"):
                    st.success(f"✅ OK（{r.get('latency_ms')} ms）")
                    st.code(r.get("output", ""))
                else:
                    st.error(f"❌ 失敗（{r.get('latency_ms')} ms）: {r.get('error')}")
                    if r.get("body"):
                        st.code(r.get("body"))

    # ctx builders（永遠有 model）
    def api_config() -> dict:
        fm = st.session_state.get("fast_mode", True)
        m = DEEPSEEK_MODEL_FAST if fm else DEEPSEEK_MODEL_QUALITY
        return {
            "api_key": st.session_state.get("api_key", ""),
            "base_url": DEEPSEEK_BASE_URL,
            "model": m,
        }

    def can_call_ai(cfg: dict) -> bool:
        return bool(cfg.get("api_key")) and bool(cfg.get("base_url")) and bool(cfg.get("model"))

    return {
        "api_config": api_config,
        "can_call_ai": can_call_ai,
        "subject": st.session_state.get("subject", "中國語文"),
        "level_code": st.session_state.get("level_code", "medium"),
        "question_count": int(st.session_state.get("question_count", 10)),
        "fast_mode": st.session_state.get("fast_mode", True),
        "ocr_mode": st.session_state.get("ocr_mode", "📄 純文字"),
        "vision_pdf_max_pages": int(st.session_state.get("vision_pdf_max_pages", 3)),
    }
