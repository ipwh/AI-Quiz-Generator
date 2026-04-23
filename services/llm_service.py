```python
# =========================================================
# services/llm_service.py
# ---------------------------------------------------------
# ✅ OpenAI-compatible /v1/chat/completions
# ✅ 支援：Generate / Import / JSON 修復 / API Ping
# ✅ 強化：SUBJECT_TRAITS / SUBJECT_MISCONCEPTIONS / SUBJECT_DISTRACTOR_HINTS
# ✅ 附加：Grok 型號自動偵測 get_xai_default_model()
# ✅ 附加：答案位置分佈平衡（避免 correct 長期偏 2/3）
# ✅ 新增：_sanitise_question_stems()（禁用「根據教材」等字眼）
# ✅ 修復：extract_json() 支援 markdown code block 剝除
# =========================================================

from __future__ import annotations

import json
import os
import random
import re
import time
import threading
import yaml
from typing import Any, Dict, List, Optional

import requests

# =========================================================
# HTTP Session
# =========================================================

_SESSION_LOCK = threading.Lock()
_SESSION = requests.Session()


def _reset_session() -> None:
    global _SESSION
    with _SESSION_LOCK:
        try:
            _SESSION.close()
        except Exception:
            pass
        _SESSION = requests.Session()


# =========================================================
# Load Subject Configuration from YAML
# =========================================================

def _load_subjects_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(__file__), "..", "subjects_config.yaml")
    try:
        if not os.path.exists(config_path):
            return {}
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


_SUBJECTS_CONFIG = _load_subjects_config()
_SUBJECTS_DATA = _SUBJECTS_CONFIG.get("subjects", {})

SUBJECT_TRAITS: Dict[str, str] = {
    subject: data.get("traits", "")
    for subject, data in _SUBJECTS_DATA.items()
    if isinstance(data, dict)
}

SUBJECT_MISCONCEPTIONS: Dict[str, List[str]] = {
    subject: data.get("misconceptions", [])
    for subject, data in _SUBJECTS_DATA.items()
    if isinstance(data, dict)
}

SUBJECT_DISTRACTOR_HINTS: Dict[str, List[str]] = {
    subject: data.get("distractor_hints", [])
    for subject, data in _SUBJECTS_DATA.items()
    if isinstance(data, dict)
}

DISTRACTOR_RULES_BY_LEVEL: Dict[str, str] = _SUBJECTS_CONFIG.get("distractor_rules_by_level", {
    "easy":   "干擾項反映基本誤解；錯在單一步驟；避免過度相似。",
    "medium": "干擾項包含部分正確但推論錯或漏條件；至少兩個看似合理。",
    "hard":   "干擾項為多步推理陷阱：條件誤判、圖像誤讀、單位/方向/定義域錯。",
    "mixed":  "混合 medium/hard 強度；同一套題可含不同難度但每題仍要清晰。",
})

DEFAULT_TRAITS = _SUBJECTS_CONFIG.get(
    "default_traits",
    "請按內容出題，語句自然，題目須憑個人知識作答。",
)

# =========================================================
# Subject Groups for UI Display
# =========================================================

SUBJECT_GROUPS = {
    "語文": ["中國語文", "英國語文"],
    "數學與科學": ["數學", "科學", "物理", "化學", "生物"],
    "人文與社會": ["公民與社會發展", "公民、經濟及社會", "地理", "歷史", "中國歷史", "宗教"],
    "商業與科技": ["經濟", "企業、會計與財務概論", "資訊及通訊科技（ICT）", "旅遊與款待"],
}

# =========================================================
# Forbidden stem patterns（防線二：後處理用）
# =========================================================

_FORBIDDEN_PATTERNS: List[tuple] = [
    (re.compile(r"根據(教材|文本|以上|上文|短文|文章|資料|圖表|以下|題目|內容)[，,：:、\s]?"), ""),
    (re.compile(r"按照(教材|文本|課文)[，,：:、\s]?"), ""),
    (re.compile(r"依據(教材|文本|課文)[，,：:、\s]?"), ""),
    (re.compile(r"參考(教材|文本|課文)[，,：:、\s]?"), ""),
    (re.compile(r"從(教材|文本|以上|上文|短文|文章|資料)中[，,\s]?"), ""),
    (re.compile(r"(?i)according\s+to\s+the\s+(passage|text|article|material|textbook)[,\s]?"), ""),
    (re.compile(r"(?i)based\s+on\s+the\s+(passage|text|article|material|textbook)[,\s]?"), ""),
    (re.compile(r"(?i)from\s+the\s+(passage|text|article)[,\s]?"), ""),
    (re.compile(r"(?i)the\s+(passage|text)\s+(states?|mentions?|says?|tells?\s+us)[,\s]?"), ""),
    (re.compile(r"(?i)as\s+(stated|mentioned|described)\s+in\s+the\s+(passage|text)[,\s]?"), ""),
    (re.compile(r"(?i)refer\s+to\s+the\s+(passage|text|material)[,\s]?"), ""),
]

_FORBIDDEN_STEMS_STR = (
    "『根據教材』『根據文本』『根據以上』『根據上文』『根據短文』"
    "『根據文章』『根據資料』『根據圖表』『根據以下』『按照教材』"
    "『依據課文』『從文章中』"
    "『according to the passage/text』『based on the passage/text』"
    "『from the passage』『the passage states/mentions』"
)

# =========================================================
# Utilities
# =========================================================

def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_json(text: str) -> Any:
    """
    從 LLM 回傳文字中提取 JSON。
    支援三種策略：
    1. 直接解析（LLM 輸出乾淨 JSON）
    2. 剝除 markdown code block（```json ... ```）
    3. regex 提取第一個 [...] 或 {...}
    """
    if not text:
        raise ValueError("AI 回傳內容是空的")

    # 策略一：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略二：剝除 markdown code block
    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 策略三：regex 提取第一個 JSON array 或 object
    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue

    raise ValueError(f"無法解析 AI 回傳的 JSON，原始內容：\n{text[:300]}")


# =========================================================
# Question stem sanitiser（防線二：後處理）
# =========================================================

def _sanitise_question_stems(items: List[dict]) -> List[dict]:
    """後處理：自動移除題幹中禁用字眼，並標 needs_review=True。"""
    for q in items or []:
        if not isinstance(q, dict):
            continue
        original = q.get("question", "")
        if not isinstance(original, str):
            continue
        cleaned = original
        for pattern, replacement in _FORBIDDEN_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        cleaned = re.sub(r"^[，,、\s]+", "", cleaned).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        if cleaned != original:
            q["question"] = cleaned
            q["needs_review"] = True
    return items


# =========================================================
# OpenAI-compatible call
# =========================================================

def _post_openai_compat(
    api_key: str,
    base_url: str,
    payload: dict,
    timeout: int = 120,
    max_retries: int = 3,
) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    allowed = {"model", "messages", "temperature", "max_tokens", "stream", "response_format"}
    safe_payload = {k: v for k, v in payload.items() if k in allowed}

    last_err: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=safe_payload, timeout=(10, timeout))
            if not r.ok:
                raise requests.HTTPError(
                    f"{r.status_code} Client Error: {r.reason} for url: {r.url}"
                    f"\n\n--- response body ---\n{r.text}",
                    response=r,
                )
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
        except requests.HTTPError as e:
            if 400 <= e.response.status_code < 500:
                raise
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(1)
                continue

    raise last_err  # type: ignore


def _chat(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int) -> str:
    data = _post_openai_compat(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        payload={
            "model": cfg["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        timeout=timeout,
    )
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


# =========================================================
# Ping
# =========================================================

def ping_llm(cfg: dict, timeout: int = 25) -> dict:
    t0 = time.time()
    try:
        out = _chat(
            cfg,
            messages=[{"role": "user", "content": "只輸出 OK 兩字。"}],
            temperature=0.0,
            max_tokens=5,
            timeout=timeout,
        )
        ms = int((time.time() - t0) * 1000)
        return {"ok": "OK" in (out or "").upper(), "latency_ms": ms, "output": out, "error": ""}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"ok": False, "latency_ms": ms, "output": "", "error": repr(e)}


# =========================================================
# xAI model auto-detect
# =========================================================

def get_xai_default_model(api_key: str, base_url: str = "https://api.x.ai/v1") -> str:
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    with _SESSION_LOCK:
        r = _SESSION.get(url, headers=headers, timeout=(10, 25))
    if not r.ok:
        return "grok-2-latest"
    data = r.json() or {}
    models = data.get("data", []) if isinstance(data, dict) else []
    ids = [m.get("id") for m in models if isinstance(m, dict) and isinstance(m.get("id"), str)]
    grok = [i for i in ids if "grok" in i.lower()]
    if not grok:
        return "grok-2-latest"
    latest = [i for i in grok if "latest" in i.lower()]
    return sorted(latest)[-1] if latest else sorted(grok)[-1]


# =========================================================
# JSON repair
# =========================================================

def _fix_json(cfg: dict, bad_output: str, timeout: int) -> str:
    prompt = (
        "你剛才輸出不是有效的題目 JSON。\n\n"
        "請只輸出一個【題目 JSON array】，不要任何解釋或對話紀錄。\n"
        "嚴禁輸出 role、content、markdown code block（不要 ```json）。\n\n"
        "每題必須包含：\n"
        "- qtype: \"single\"\n"
        "- question: string\n"
        "  ⚠️ 嚴禁出現以下字眼：\n"
        f"  {_FORBIDDEN_STEMS_STR}\n"
        "  學生考試時沒有教材，所有題目須憑個人知識作答。\n"
        "- options: 4 strings\n"
        "- correct: [\"1\"~\"4\"]（只可 1 個）\n"
        "- explanation: string\n"
        "- needs_review: boolean\n\n"
        "請根據以下內容修正：\n"
        f"{bad_output}"
    )
    return _chat(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=2400,
        timeout=timeout,
    )


def _call_with_retries(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int):
    out = _chat(cfg, messages, temperature, max_tokens, timeout)
    try:
        return extract_json(out)
    except Exception:
        repaired = _fix_json(cfg, out, timeout)
        return extract_json(repaired)


# =========================================================
# Answer position rebalance
# =========================================================

def rebalance_correct_positions(items: List[dict], seed: Optional[int] = None) -> List[dict]:
    """只改 options 排列 + 同步 correct，以平衡 A/B/C/D 分佈。"""
    if seed is None:
        seed = int(time.time()) % 100000
    rng = random.Random(seed)

    valid: List[dict] = []
    for q in items or []:
        corr = q.get("correct", [])
        if isinstance(corr, list) and len(corr) == 1 and corr in {"1", "2", "3", "4"}:
            opts = q.get("options", [])
            if isinstance(opts, list) and len(opts) == 4:
                valid.append(q)

    n = len(valid)
    if n == 0:
        return items

    targets = [n // 4] * 4
    for i in range(n % 4):
        targets[i] += 1

    rng.shuffle(valid)

    desired_positions: List[str] = []
    for pos, cnt in enumerate(targets, start=1):
        desired_positions.extend([str(pos)] * cnt)
    rng.shuffle(desired_positions)

    for q, desired in zip(valid, desired_positions):
        cur = q["correct"]
        if cur == desired:
            continue
        opts = list(q["options"])
        cur_idx = int(cur) - 1
        desired_idx = int(desired) - 1
        correct_opt = opts[cur_idx]
        rest = [o for i, o in enumerate(opts) if i != cur_idx]
        rest.insert(desired_idx, correct_opt)
        q["options"] = rest
        q["correct"] = [desired]

    return items


# =========================================================
# Generate
# =========================================================

def generate_questions(
    cfg: dict,
    text: str,
    subject: str,
    level: str,
    question_count: int,
    fast_mode: bool = False,
    qtype: str = "single",
):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    misconceptions = SUBJECT_MISCONCEPTIONS.get(subject, [])
    distractor_rules = DISTRACTOR_RULES_BY_LEVEL.get(level, "")
    templates = SUBJECT_DISTRACTOR_HINTS.get(subject, [])

    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]

    mc_text = "\n".join(f"- {m}" for m in misconceptions[:12])
    sd_text = "\n".join(f"- {d}" for d in templates[:6])

    prompt = f"""
你是一名香港中學教師，負責出校內評估題。
這是知識性選擇題：學生憑個人知識作答，考場內沒有任何教材或閱讀材料。

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

【絕對禁止——違反即視為廢題，必須重寫】
❌ 題幹及選項中，嚴禁出現以下任何字眼（中英文均適用）：
   {_FORBIDDEN_STEMS_STR}
❌ 原因：學生考試時沒有教材，所有題目須憑個人知識作答。
❌ 若題目概念來自教材內容，請直接考核該知識點，無須引用來源。

   ✅ 錯誤示範：「根據教材，光合作用的產物是什麼？」
   ✅ 正確示範：「植物進行光合作用時，會同時產生哪兩種物質？」

   ✅ 錯誤示範："According to the passage, what is the main cause of..."
   ✅ 正確示範："What is the main cause of..."

【嚴格輸出要求】
- 只輸出純 JSON array，不加任何文字，不加 markdown code block（不要 ```json）
- 每題必為四選一：qtype = "single"
- options 必須剛好 4 個字串
- correct 必須為只含 1 個元素的 list：["1"~"4"]
- explanation 簡潔指出關鍵理由（1-3 句），並點明錯誤選項的常見誤解
- needs_review: 若題幹/答案不確定或需教師判斷，請設為 true
- 正確答案位置請避免長期集中於 B/C（2/3），A/B/C/D 需大致均勻

【內容（供出題參考，非學生閱讀材料）】
{text}
"""

    data = _call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2 if fast_mode else 0.3,
        max_tokens=2600,
        timeout=160,
    )

    if isinstance(data, list):
        if len(data) > question_count:
            data = data[:question_count]
        elif len(data) < question_count:
            remain = question_count - len(data)
            if remain > 0:
                prompt2 = (
                    prompt
                    + f"\n\n【補齊要求】你剛才題數不足，請再補 {remain} 題，只輸出新增題目的 JSON array。"
                    + f"\n⚠️ 同樣嚴禁出現：{_FORBIDDEN_STEMS_STR}"
                )
                more = _call_with_retries(
                    cfg,
                    messages=[{"role": "user", "content": prompt2}],
                    temperature=0.2,
                    max_tokens=2000,
                    timeout=160,
                )
                if isinstance(more, list):
                    data.extend(more)
                data = data[:question_count]

    data = _sanitise_question_stems(data)
    data = rebalance_correct_positions(data)

    return data


# =========================================================
# Import
# =========================================================

def assist_import_questions(
    cfg: dict,
    raw_text: str,
    subject: str,
    allow_guess: bool = True,
    fast_mode: bool = False,
    qtype: str = "single",
):
    raw_text = _clean_text(raw_text)
    policy = "可合理推斷並標 needs_review=true" if allow_guess else "請標 needs_review=true 並把 correct 留空"

    prompt = f"""
你是一名香港中學教師，正在把現有題目整理成標準 JSON。

【科目】{subject}
【要求】
- 每題四選一（qtype=single）
- options 必須 4 個
- 必須提供 correct（["1"~"4"] 只 1 個）
- 只輸出純 JSON array，不加任何文字，不加 markdown code block（不要 ```json）
- 若原文欠缺答案：{policy}
- 題幹嚴禁出現「根據教材/根據文本/根據以上/according to the passage」等字眼
  若原題有此字眼，請直接移除並改寫為獨立知識題

【原始題目】
{raw_text}
"""

    return _call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0 if fast_mode else 0.1,
        max_tokens=2400,
        timeout=120,
    )


def parse_import_questions_locally(raw_text: str):
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []
    return []
```

***

## 修復摘要

| 問題 | 原因 | 修復 |
|------|------|------|
| `JSONDecodeError` | LLM 回傳 ` ```json...``` ` 包裹的 JSON | `extract_json()` 加三重解析策略 |
| 策略一 | 直接 `json.loads()`（乾淨 JSON） | 原有邏輯保留 |
| 策略二 | 剝除 markdown code block | 新增 regex strip |
| 策略三 | 提取回傳文字中第一個 `[...]` | 新增 regex search |
| prompt 補強 | `_fix_json()` 及所有 prompt 加入「不要 ` ```json ` 」 | 從源頭減少 LLM 包裹 markdown |
