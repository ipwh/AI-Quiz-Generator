# =========================================================
# services/vision_service.py
# FINAL-FULL（完整實作版：Vision 直接出題 + OpenAI-compatible + Grok + 自訂相容端點）
# ---------------------------------------------------------
# 你選擇：
# 1) 支援：B、C（Grok + 自訂 OpenAI 相容 Vision）
# 2) 流程：B（直接 Vision 出題：圖片 + 文字一起送入模型）
# ---------------------------------------------------------
# ✅ supports_vision(cfg)：模型/配置判斷
# ✅ file_to_data_url(bytes, filename)：修正 data URL
# ✅ vision_generate_questions()：直接 Vision 出題，失敗自動 fallback 到 llm_service.generate_questions()
# ✅ vision_ocr_extract_text()：提供「只抽文字」能力（備用）
# ✅ 全程只用 OpenAI-compatible /chat/completions（image_url 支援）
# =========================================================

from __future__ import annotations

import base64
import json
import mimetypes
import time
import threading
from typing import Any, Dict, List, Optional

import requests

from services.llm_service import generate_questions

# 盡量重用科目特性/誤概念/干擾模板
try:
    from services.llm_service import (
        SUBJECT_TRAITS,
        DEFAULT_TRAITS,
        SUBJECT_MISCONCEPTIONS,
        DISTRACTOR_RULES_BY_LEVEL,
        SUBJECT_DISTRACTOR_HINTS,
        rebalance_correct_positions,
    )
except Exception:
    SUBJECT_TRAITS = {}
    DEFAULT_TRAITS = "請按內容出題，語句自然，避免使用『根據教材/根據文本/根據以上』等提示語。"
    SUBJECT_MISCONCEPTIONS = {}
    DISTRACTOR_RULES_BY_LEVEL = {}
    SUBJECT_DISTRACTOR_HINTS = {}
    rebalance_correct_positions = None


# =========================================================
# HTTP Session
# =========================================================

_SESSION_LOCK = threading.Lock()
_SESSION = requests.Session()


def _post_openai_compat(
    api_key: str,
    base_url: str,
    payload: dict,
    timeout: int = 180,
    max_retries: int = 2,
) -> dict:
    """OpenAI-compatible chat/completions POST."""

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    allowed = {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "response_format",
        "stream",
    }
    safe_payload = {k: v for k, v in payload.items() if k in allowed}

    last_err: Optional[Exception] = None
    for _ in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=safe_payload, timeout=(10, timeout))
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.8)

    raise last_err  # type: ignore


def _chat_text(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int) -> str:
    data = _post_openai_compat(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        payload={
            "model": cfg["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def _chat_vision(
    cfg: dict,
    prompt_text: str,
    image_data_urls: List[str],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    """Vision chat: user content = [text + multiple image_url]."""

    content = [{"type": "text", "text": prompt_text}]
    for u in image_data_urls[:12]:
        if not isinstance(u, str) or not u:
            continue
        content.append({"type": "image_url", "image_url": {"url": u}})

    messages = [{"role": "user", "content": content}]

    data = _post_openai_compat(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        payload={
            "model": cfg["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # 盡量引導 JSON
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )

    # 某些相容端點會忽略 response_format，仍會回 text
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


# =========================================================
# Capability
# =========================================================

def supports_vision(cfg: dict) -> bool:
    """粗略判斷：gpt-4o / grok / vision 關鍵字；另外允許 cfg['vision']=True 強制。"""

    if cfg.get("vision") is True:
        return True

    model = (cfg.get("model") or "").lower()
    if not model:
        return False

    return (
        "gpt-4o" in model
        or "gpt-4.1" in model
        or "vision" in model
        or model.startswith("grok")
    )


# =========================================================
# Data URL
# =========================================================

def file_to_data_url(file_bytes: bytes, filename: str) -> str:
    """把 bytes 轉成 data:{mime};base64,..."""

    mime, _ = mimetypes.guess_type(filename)
    if not mime:
        # 圖像預設 png
        mime = "image/png"

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# =========================================================
# JSON helpers
# =========================================================

def _extract_json_any(text: str) -> Any:
    """嘗試從回傳中抽出 JSON（支援包裹在 ```json ...``` 的情況）。"""

    if not text:
        raise ValueError("empty output")

    t = text.strip()

    # fenced
    if t.startswith("```"):
        # remove first fence line and last fence
        t = t.strip("`")

    # try direct
    try:
        return json.loads(t)
    except Exception:
        pass

    # try find first [ ... ]
    s = t.find("[")
    e = t.rfind("]")
    if 0 <= s < e:
        return json.loads(t[s : e + 1])

    # try find first { ... }
    s = t.find("{")
    e = t.rfind("}")
    if 0 <= s < e:
        return json.loads(t[s : e + 1])

    raise ValueError("not valid json")


def _fix_json(cfg: dict, bad_output: str, timeout: int = 120) -> str:
    """用文字模式修復 JSON（不帶圖片），避免 Vision 端點有時輸出冗文字。"""

    prompt = (
        "你剛才輸出不是有效的題目 JSON。\n\n"
        "請只輸出一個【題目 JSON array】，不要任何解釋或對話紀錄。\n"
        "嚴禁輸出 role、content。\n\n"
        "每題必須包含：\n"
        "- qtype: \"single\"\n"
        "- question: string（不要以『根據教材/根據文本/根據以上』開頭）\n"
        "- options: 4 strings\n"
        "- correct: [\"1\"~\"4\"]（只可 1 個）\n"
        "- explanation: string\n"
        "- needs_review: boolean\n\n"
        "請根據以下內容修正：\n"
        f"{bad_output}"
    )

    return _chat_text(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=2400,
        timeout=timeout,
    )


# =========================================================
# Vision OCR (optional)
# =========================================================

def vision_ocr_extract_text(cfg: dict, image_data_urls: List[str], lang_hint: str = "zh-Hant") -> str:
    """用 Vision 把圖片內容轉成純文字（備用）。"""

    if not supports_vision(cfg):
        raise RuntimeError("模型不支援 Vision")

    prompt = (
        "你是一個 OCR 系統。請把圖片內的文字完整轉寫成純文字。\n"
        "- 只輸出純文字\n"
        "- 盡量保留段落與換行\n"
        f"- 語言提示：{lang_hint}\n"
    )

    out = _chat_vision(
        cfg,
        prompt_text=prompt,
        image_data_urls=image_data_urls,
        temperature=0.0,
        max_tokens=2000,
        timeout=180,
    )

    # Vision 端可能回 JSON；保守處理
    try:
        obj = _extract_json_any(out)
        if isinstance(obj, dict) and "text" in obj:
            return str(obj.get("text") or "")
    except Exception:
        pass

    return str(out or "").strip()


# =========================================================
# Vision generate questions
# =========================================================

def vision_generate_questions(
    cfg: dict,
    text: str,
    image_data_urls: List[str],
    subject: str,
    level: str,
    question_count: int,
    fast_mode: bool = True,
    qtype: str = "single",
):
    """Vision 出題主入口。

    - 直接 Vision 出題（圖片 + 文字一起送入）
    - 若不支援 Vision 或過程失敗：自動 fallback 到 generate_questions()
    """

    # fallback if no images
    if not image_data_urls:
        return generate_questions(cfg, text, subject, level, question_count, fast_mode=fast_mode, qtype=qtype)

    if not supports_vision(cfg):
        return generate_questions(cfg, text, subject, level, question_count, fast_mode=fast_mode, qtype=qtype)

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    misconceptions = SUBJECT_MISCONCEPTIONS.get(subject, [])
    distractor_rules = DISTRACTOR_RULES_BY_LEVEL.get(level, "")
    subject_templates = SUBJECT_DISTRACTOR_HINTS.get(subject, [])

    # truncate text for safety
    text = (text or "").strip()
    if fast_mode and len(text) > 8000:
        text = text[:8000]
    elif (not fast_mode) and len(text) > 10000:
        text = text[:10000]

    mc_text = "\n".join(f"- {m}" for m in misconceptions[:12])
    sd_text = "\n".join(f"- {d}" for d in subject_templates[:6])

    prompt = f"""
你是一名香港中學教師，負責出校內評估題。

【科目】{subject}
【難度】{level}
【題目數目】必須剛好 {question_count} 題

【科目特性】
{traits}

【常見誤概念（用作干擾項設計）】
{mc_text}

【科目專屬干擾項模板（必須參考）】
{sd_text}

【干擾項強度】
{distractor_rules}

【嚴格輸出要求】
- 只輸出純 JSON array（不加任何文字）
- 每題必為四選一：qtype = \"single\"
- options 必須剛好 4 個字串
- correct 必須為只含 1 個元素的 list： [\"1\"~\"4\"]
- question 請用自然題幹，不要以「根據教材/根據文本/根據以上」等字眼開頭
- explanation 簡潔指出關鍵理由（1-3 句）
- needs_review: 若題幹/答案不確定或需教師判斷，請設為 true
- 正確答案位置請避免長期集中於 B/C（2/3），A/B/C/D 需大致均勻

【已抽取文本（輔助）】
{text}

【圖片/掃描內容】
請以圖片內容為主、文本為輔。
"""

    try:
        out = _chat_vision(
            cfg,
            prompt_text=prompt,
            image_data_urls=image_data_urls,
            temperature=0.2 if fast_mode else 0.3,
            max_tokens=3200,
            timeout=220,
        )

        try:
            data = _extract_json_any(out)
        except Exception:
            repaired = _fix_json(cfg, out, timeout=140)
            data = _extract_json_any(repaired)

        # ensure list
        if isinstance(data, dict) and "items" in data and isinstance(data.get("items"), list):
            data = data["items"]

        if not isinstance(data, list):
            raise ValueError("vision output is not a list")

        # enforce count
        if len(data) > question_count:
            data = data[:question_count]
        elif len(data) < question_count:
            # top-up once with vision but without images to save cost; keep it simple
            remain = question_count - len(data)
            prompt2 = prompt + f"\n\n【補齊要求】你剛才題數不足，請再補 {remain} 題，只輸出新增題目的 JSON array。"
            out2 = _chat_text(
                cfg,
                messages=[{"role": "user", "content": prompt2}],
                temperature=0.2,
                max_tokens=2400,
                timeout=180,
            )
            more = _extract_json_any(out2)
            if isinstance(more, list):
                data.extend(more)
            data = data[:question_count]

        # rebalance answer positions
        if rebalance_correct_positions:
            data = rebalance_correct_positions(data)

        return data

    except Exception:
        # safe fallback
        return generate_questions(cfg, text, subject, level, question_count, fast_mode=fast_mode, qtype=qtype)
