# services/llm_service.py
# ---------------------------------------------------------
# OpenAI-compatible /v1/chat/completions
# Support: Generate / Import / JSON repair / API Ping
# Enhanced: SUBJECT_TRAITS / SUBJECT_MISCONCEPTIONS / SUBJECT_DISTRACTOR_HINTS
# Added: Grok model auto-detect get_xai_default_model()
# Added: Answer position rebalance (with robust type normalisation)
# Added: _sanitise_question_stems() - forbid "according to passage" etc.
# Fixed: extract_json() supports markdown code block stripping
# Fixed: rebalance_correct_positions() handles int/float correct values
# ---------------------------------------------------------

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
    "easy":   "Distractors reflect basic misconceptions; error in a single step; avoid excessive similarity.",
    "medium": "Distractors partially correct but wrong inference or missing condition; at least two plausible.",
    "hard":   "Distractors are multi-step traps: wrong condition, misread diagram, unit/direction/domain error.",
    "mixed":  "Mix medium/hard intensity; same set may have varying difficulty but each item must be clear.",
})

# 難度詳細定義：讓「基礎(easy)」與「進階(hard)」有實質差異，AI 必須依此調節題目深淺
DIFFICULTY_GUIDE: Dict[str, str] = _SUBJECTS_CONFIG.get("difficulty_guide", {
    "easy": (
        "【基礎】只測單一核心概念的直接記憶／理解，不需跨概念整合。\n"
        "- 題幹：簡短直接，只問一件事，用字清楚；選項差距明顯。\n"
        "- 作答：學生憑課堂所學或單一步驟即可答出，無需多步推理。\n"
        "- 干擾項：明顯錯誤，或只錯在單一步驟，不設多重陷阱。"
    ),
    "medium": (
        "【標準】需把概念應用到新情境，或比較兩個相近概念。\n"
        "- 題幹：清楚但含少量轉折或條件限制。\n"
        "- 作答：需 1-2 步推理，能分辨相近概念。\n"
        "- 干擾項：部分正確但推論錯或漏條件；至少兩個看似合理。"
    ),
    "hard": (
        "【進階】需分析、綜合或評估，可跨章節整合多個概念。\n"
        "- 題幹：可含條件限制、數據或圖表判讀，或需先處理多餘資訊。\n"
        "- 作答：需多步推理（條件誤判、單位／方向／定義域、先後次序等）。\n"
        "- 干擾項：多步陷阱，正確與錯誤選項差距很小，需細心比較。"
    ),
    "mixed": (
        "【混合】同一套題內混合 medium/hard 強度，各題可難易不一。\n"
        "- 每題仍須題幹清晰、有唯一正確答案，不因混合而含糊。"
    ),
})

DEFAULT_TRAITS = _SUBJECTS_CONFIG.get(
    "default_traits",
    "Set questions based on content. Use natural language. Students answer from personal knowledge only.",
)

# =========================================================
# Subject Groups for UI Display
# =========================================================

SUBJECT_GROUPS = {
    "語文科": ["中國語文", "英國語文"],
    "數理科": [ "數學", "物理", "化學", "生物", "科學"],
    "人文學科": [ "公民與社會發展", "公民、經濟及社會", "地理", "歷史", "中國歷史", "宗教", "經濟"],
    "科技及經濟科": [ "企業、會計與財務概論", "資訊及通訊科技（ICT）", "旅遊與款待"],
}

# =========================================================
# Forbidden stem patterns (post-processing defence)
# =========================================================

_FORBIDDEN_PATTERNS: List[tuple] = [
    (re.compile(r"根據(教材|文本|以上|上文|短文|文章|資料|圖表|以下|題目|內容)[，,：:、\s]?"), ""),
    (re.compile(r"按照(教材|文本|課文)[，,：:、\s]?"), ""),
    (re.compile(r"依據(教材|文本|課文)[，,：:、\s]?"), ""),
    (re.compile(r"參考(教材|文本|課文)[，,：:、\s]?"), ""),
    (re.compile(r"從(教材|文本|以上|上文|短文|文章|資料)中[，,\s]?"), ""),
    (re.compile(r"在(教材|文本|課文|資料)中[，,：:、\s]?"), ""),
    (re.compile(r"從(教材|文本|課文)(得知|可知|可見|可觀察到)[，,：:、\s]?"), ""),
    (re.compile(r"由(教材|文本|課文)(可見|可知|可得知)[，,：:、\s]?"), ""),
    (re.compile(r"綜合(教材|上文|資料)(內容)?[，,：:、\s]?"), ""),
    (re.compile(r"\u6839\u636e(\u6559\u6750|\u6587\u672c|\u4ee5\u4e0a|\u4e0a\u6587|\u77ed\u6587|\u6587\u7ae0|\u8cc7\u6599|\u5716\u8868|\u4ee5\u4e0b|\u984c\u76ee|\u5185\u5bb9)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u6309\u7167(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u4f9d\u64da(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u53c3\u8003(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u5f9e(\u6559\u6750|\u6587\u672c|\u4ee5\u4e0a|\u4e0a\u6587|\u77ed\u6587|\u6587\u7ae0|\u8cc7\u6599)\u4e2d[\uff0c,\s]?"), ""),
    (re.compile(r"\u5f9e(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)(\u5f97\u77e5|\u53ef\u77e5|\u53ef\u898b|\u53ef\u89c0\u5bdf\u5230)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u7531(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)(\u53ef\u898b|\u53ef\u77e5|\u53ef\u5f97\u77e5)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u7d9c\u5408(\u6559\u6750|\u4e0a\u6587|\u8cc7\u6599)(\u5167\u5bb9)?[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u4ece(\u6559\u6750|\u6587\u672c|\u4e0a\u6587|\u8d44\u6599)\u4e2d?(\u5f97\u77e5|\u53ef\u77e5|\u53ef\u89c1)?[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"(?i)according\s+to\s+the\s+(passage|text|article|material|textbook)[,\s]?"), ""),
    (re.compile(r"(?i)based\s+on\s+the\s+(passage|text|article|material|textbook)[,\s]?"), ""),
    (re.compile(r"(?i)from\s+the\s+(passage|text|article)[,\s]?"), ""),
    (re.compile(r"(?i)the\s+(passage|text)\s+(states?|mentions?|says?|tells?\s+us)[,\s]?"), ""),
    (re.compile(r"(?i)as\s+(stated|mentioned|described)\s+in\s+the\s+(passage|text)[,\s]?"), ""),
    (re.compile(r"(?i)refer\s+to\s+the\s+(passage|text|material)[,\s]?"), ""),
]

_FORBIDDEN_STEMS_STR = (
    "'根據教材' '從教材得知' '由教材可見' '在教材中' '綜合教材內容' "
    "'according to the passage/text' 'based on the passage/text' "
    "'from the passage' 'the passage states/mentions' "
    "'refer to the passage'"
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


def _extract_first_json_object(text: str) -> Any:
    """Find and parse the first valid JSON object/array embedded in text."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", text):
        start = m.start()
        try:
            obj, _ = decoder.raw_decode(text[start:])
            return obj
        except Exception:
            continue
    raise ValueError("No JSON object/array found in text")


def _normalise_questions_payload(data: Any) -> Any:
    """Unwrap common response wrappers used by OpenAI-compatible providers."""
    current = data
    # Bound unwrapping depth to avoid pathological/self-referential payload loops.
    for _ in range(6):
        if isinstance(current, list):
            return current

        if not isinstance(current, dict):
            return current

        unwrapped = None
        for key in ("items", "questions", "data", "result", "output"):
            v = current.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                unwrapped = v
                break

        if unwrapped is not None:
            current = unwrapped
            continue

        msg = current.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                c = content.strip().replace("\ufeff", "")
                if c.startswith("{") or c.startswith("["):
                    try:
                        current = json.loads(c)
                        continue
                    except Exception:
                        pass

        content = current.get("content")
        if isinstance(content, str):
            c = content.strip().replace("\ufeff", "")
            if c.startswith("{") or c.startswith("["):
                try:
                    current = json.loads(c)
                    continue
                except Exception:
                    pass

        return current

    return current


def extract_json(text: Any) -> Any:
    """
    Extract JSON from LLM output.
    Strategy 1: direct json.loads
    Strategy 2: strip markdown code block (```json ... ```)
    Strategy 3: regex extract first [...] or {...}
    """
    if text is None:
        raise ValueError("AI returned empty content")

    # If upstream already decoded JSON, return as-is.
    if isinstance(text, (list, dict)):
        return _normalise_questions_payload(text)

    if not isinstance(text, str):
        text = str(text)

    if not text.strip():
        raise ValueError("AI returned empty content")

    text = text.replace("\ufeff", "").strip()

    try:
        maybe = json.loads(text)
        # Quoted JSON string: "[{...}]" -> [{...}]
        if isinstance(maybe, str):
            try:
                maybe2 = json.loads(maybe)
                return _normalise_questions_payload(maybe2)
            except Exception:
                pass
        return _normalise_questions_payload(maybe)
    except json.JSONDecodeError:
        pass

    # Strip fenced code block anywhere in output.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return _normalise_questions_payload(json.loads(candidate))
        except json.JSONDecodeError:
            try:
                return _normalise_questions_payload(_extract_first_json_object(candidate))
            except Exception:
                pass

    # Common preface: "json\n[...]"
    text_no_tag = re.sub(r"^json\s*", "", text, flags=re.IGNORECASE).strip()
    if text_no_tag != text:
        try:
            return _normalise_questions_payload(json.loads(text_no_tag))
        except json.JSONDecodeError:
            pass

    try:
        return _normalise_questions_payload(_extract_first_json_object(text_no_tag))
    except Exception:
        pass

    raise ValueError(f"Cannot parse AI JSON output:\n{text[:300]}")


# =========================================================
# Question stem sanitiser (post-processing)
# =========================================================

def _sanitise_question_stems(items: List[dict]) -> List[dict]:
    """Remove forbidden stems from question field. Marks modified items as needs_review=True."""
    for q in items or []:
        if not isinstance(q, dict):
            continue
        original = q.get("question", "")
        if not isinstance(original, str):
            continue
        cleaned = original
        for pattern, replacement in _FORBIDDEN_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        cleaned = re.sub(r"^[\uff0c,\u3001\s]+", "", cleaned).strip()
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
    allowed = {"model", "messages", "temperature", "max_tokens", "stream", "response_format", "thinking"}
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
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    # DeepSeek V4 預設 Thinking Mode：思考會消耗 max_tokens，一旦在思考階段
    # 用盡，content 會回傳空字串 → 「AI returned empty content」。
    # 出題需直接輸出 JSON，故對 deepseek-v4* 關閉 thinking mode。
    if str(cfg.get("model", "")).lower().startswith("deepseek-v4"):
        payload["thinking"] = {"type": "disabled"}

    data = _post_openai_compat(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        payload=payload,
        timeout=timeout,
    )
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

    # Some providers return content as structured parts (e.g. [{"type":"text","text":"..."}]).
    if isinstance(content, list):
        parts: List[str] = []
        for p in content:
            if isinstance(p, dict):
                t = p.get("text") or p.get("content")
                if t is not None:
                    parts.append(str(t))
            elif p is not None:
                parts.append(str(p))
        return "\n".join(parts).strip()

    if content is None:
        return ""

    return str(content)


# =========================================================
# Ping
# =========================================================

def ping_llm(cfg: dict, timeout: int = 25) -> dict:
    t0 = time.time()
    try:
        out = _chat(
            cfg,
            messages=[{"role": "user", "content": "Reply OK only."}],
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
        "Your previous output was not valid JSON.\n\n"
        "Output ONLY a valid JSON array of question objects. No explanation, no markdown code blocks.\n\n"
        "Each item must have:\n"
        "- qtype: \"single\"\n"
        "- question: string (NO phrases like 'according to the passage/text')\n"
        "- options: exactly 4 strings\n"
        "- correct: list with exactly 1 element, value must be \"1\", \"2\", \"3\", or \"4\"\n"
        "- explanation: string\n"
        "- needs_review: boolean\n\n"
        "Fix the following:\n"
        f"{bad_output}"
    )
    return _chat(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=4096,
        timeout=timeout,
    )


def _call_with_retries(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int):
    out = _chat(cfg, messages, temperature, max_tokens, timeout)
    try:
        return extract_json(out)
    except Exception:
        if not (out or "").strip():
            raise ValueError("AI 回傳了空內容（可能因 Thinking Mode 耗盡 token）。請重試，或在「進階設定」加大超時／改用其他模型。")
        repaired = _fix_json(cfg, out, timeout)
        return extract_json(repaired)


def _coerce_question_items(data: Any) -> List[dict]:
    """Normalise provider output into a list of question dicts."""
    data = _normalise_questions_payload(data)

    if isinstance(data, dict):
        if any(k in data for k in ("question", "options", "correct")):
            data = [data]
        else:
            for key in ("items", "questions", "data", "result", "output"):
                value = data.get(key)
                if isinstance(value, list):
                    data = value
                    break

    if not isinstance(data, list):
        raise ValueError(f"AI returned unsupported question payload type: {type(data).__name__}")

    items = [q for q in data if isinstance(q, dict)]
    if not items and data:
        raise ValueError("AI returned a question payload without any question objects")
    return items


def _ground_generated_questions(
    cfg: dict,
    text: str,
    subject: str,
    level: str,
    question_count: int,
    items: List[dict],
    timeout: int = 140,
) -> List[dict]:
    """Rewrite or drop questions that are not clearly grounded in the uploaded material."""
    if not items:
        return []

    difficulty_guide = DIFFICULTY_GUIDE.get(level, "")

    prompt = f"""You are reviewing AI-generated multiple-choice questions for a Hong Kong secondary school teacher.

[Task]
Review the generated questions against the uploaded teaching material.
Rewrite any question that is off-topic, too generic, or not clearly supported by the material.
If a question cannot be salvaged, replace it with a new question that is clearly grounded in the material.

[Hard requirements]
- Final output should aim for exactly {question_count} questions if the material supports it.
- Every question must be traceable to the uploaded material.
- Do NOT introduce outside topics just because they belong to the same subject.
- Do NOT use textbook-referential phrasing such as: {_FORBIDDEN_STEMS_STR}
- Students do not see the material during the quiz, so question stems must be standalone.
- Output ONLY a raw JSON array. No extra text. No markdown.
- Each item must keep this schema:
  - qtype: \"single\"
  - question: string
  - options: exactly 4 strings
  - correct: list with exactly 1 element, value must be \"1\", \"2\", \"3\", or \"4\"
  - explanation: concise string
  - needs_review: boolean

[Subject]
{subject}

[Difficulty]
{level}

[Difficulty specification - preserve this level strictly; easy (基礎) and hard (進階) must differ clearly]
{difficulty_guide}

[Uploaded material]
{text}

[Generated questions to review]
{json.dumps(items, ensure_ascii=False)}
"""

    reviewed = _coerce_question_items(_call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=6000,
        timeout=timeout,
    ))
    return reviewed[:question_count]


def _dedupe_question_items(items: List[dict]) -> List[dict]:
    """Preserve order while removing duplicate question stems."""
    seen: set[str] = set()
    deduped: List[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        stem = _clean_text(str(item.get("question", "") or "")).lower()
        key = stem or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalise_correct_slot(value: Any) -> Optional[str]:
    """Return a single answer slot '1'..'4' from list/str/int/float payloads."""
    if isinstance(value, list):
        if len(value) != 1:
            return None
        value = value[0]

    if value is None:
        return None

    slot = str(value).strip().split(".")[0]
    return slot if slot in {"1", "2", "3", "4"} else None


# =========================================================
# Answer position rebalance
# =========================================================

def rebalance_correct_positions(items: List[dict], seed: Optional[int] = None) -> List[dict]:
    """Shuffle option order to balance A/B/C/D distribution. Handles int/float/str correct values."""
    if seed is None:
        seed = int(time.time()) % 100000
    rng = random.Random(seed)

    normalized_items = [q for q in (items or []) if isinstance(q, dict)]

    valid: List[dict] = []
    for q in normalized_items:
        corr_str = _normalise_correct_slot(q.get("correct", []))
        if corr_str:
            q["correct"] = [corr_str]  # normalise in-place for downstream mappers/exporters
            opts = q.get("options", [])
            if isinstance(opts, list) and len(opts) == 4:
                valid.append(q)

    n = len(valid)
    if n == 0:
        return normalized_items

    targets = [n // 4] * 4
    for i in range(n % 4):
        targets[i] += 1

    rng.shuffle(valid)

    desired_positions: List[str] = []
    for pos, cnt in enumerate(targets, start=1):
        desired_positions.extend([str(pos)] * cnt)
    rng.shuffle(desired_positions)

    for q, desired in zip(valid, desired_positions):
        cur = q["correct"][0]  # guaranteed str "1"~"4" after normalisation above
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

    return normalized_items


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
    images: Optional[List[str]] = None,
):
    # Backward compatibility: some UI versions pass images to this function.
    # If images exist, delegate to vision pipeline and let it fallback safely.
    if images:
        try:
            from services.vision_service import vision_generate_questions
            return vision_generate_questions(
                cfg=cfg,
                text=text,
                image_data_urls=images,
                subject=subject,
                level=level,
                question_count=question_count,
                fast_mode=fast_mode,
                qtype=qtype,
            )
        except Exception:
            # Keep text-only generation as a safe fallback.
            pass

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    misconceptions = SUBJECT_MISCONCEPTIONS.get(subject, [])
    distractor_rules = DISTRACTOR_RULES_BY_LEVEL.get(level, "")
    difficulty_guide = DIFFICULTY_GUIDE.get(level, "")
    templates = SUBJECT_DISTRACTOR_HINTS.get(subject, [])

    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]

    mc_text = "\n".join(f"- {m}" for m in misconceptions[:12])
    sd_text = "\n".join(f"- {d}" for d in templates[:6])

    prompt = f"""You are a Hong Kong secondary school teacher creating internal assessment questions.
This is a knowledge-based multiple choice quiz. Students answer from personal knowledge only, but EVERY question must be grounded in the uploaded teaching material. There is NO reading passage or textbook in the exam room.

[Subject] {subject}
[Difficulty] {level}
[Number of questions] Exactly {question_count}

[Difficulty specification - follow strictly; easy (基礎) and hard (進階) must differ clearly]
{difficulty_guide}

[Subject traits]
{traits}

[Common misconceptions (use for distractor design)]
{mc_text}

[Subject-specific distractor templates (must reference)]
{sd_text}

[Distractor intensity]
{distractor_rules}

[Grounding and scope control]
- Use ONLY knowledge points, concepts, cases, data, terms, relationships, and policy issues that are explicitly present in the uploaded material.
- Do NOT introduce outside topics just because they belong to the same subject.
- If a question cannot be clearly traced back to the uploaded material, do not generate it.
- Before finalising each question, internally check: "Can this question be justified directly from the uploaded material?" If not, rewrite or discard it.
- Prefer the most central and repeated ideas in the material; avoid weakly related side facts.
- If the material is too short or unclear for a question, generate fewer but better-grounded questions and mark uncertain ones with needs_review=true.

[ABSOLUTE PROHIBITION - violation = question is void and must be rewritten]
Do NOT use any of the following phrases in question stems or options:
{_FORBIDDEN_STEMS_STR}
Reason: Students have no textbook. All questions must be answerable from personal knowledge.
Test the knowledge point directly without citing a source, but the knowledge point itself must still come from the uploaded material.

Chinese examples that are strictly forbidden in question stems:
- 根據教材
- 從教材得知
- 從教材可見
- 由教材可見
- 在教材中
- 綜合教材內容
- 根據以上資料 / 從上文可知

Correct: "What gas is released by plants during photosynthesis?"
Wrong:   "According to the passage, what gas is released during photosynthesis?"

[Strict output requirements]
- Output ONLY a raw JSON array. No extra text. No markdown code blocks. No ```json wrapper.
- Each item: qtype = "single"
- options: exactly 4 strings
- correct: list with exactly 1 element, value must be string "1", "2", "3", or "4"
- explanation: concise key reasoning (1-3 sentences), note common errors in wrong options
- needs_review: true if question stem or answer is uncertain
- Reject any question that is not clearly supported by the uploaded material.
- Distribute correct answers evenly across A/B/C/D positions

[Content for reference - NOT a student reading passage]
{text}
"""

    data = _coerce_question_items(_call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2 if fast_mode else 0.3,
        max_tokens=8192,
        timeout=160,
    ))

    if isinstance(data, list):
        if len(data) > question_count:
            data = data[:question_count]
        elif len(data) < question_count:
            remain = question_count - len(data)
            if remain > 0:
                prompt2 = (
                    prompt
                    + f"\n\n[Top-up] You generated too few questions. Add {remain} more. Output ONLY the new questions as a JSON array."
                )
                more = _coerce_question_items(_call_with_retries(
                    cfg,
                    messages=[{"role": "user", "content": prompt2}],
                    temperature=0.2,
                    max_tokens=4096,
                    timeout=160,
                ))
                if isinstance(more, list):
                    data.extend(more)
                data = data[:question_count]

    data = _ground_generated_questions(
        cfg=cfg,
        text=text,
        subject=subject,
        level=level,
        question_count=question_count,
        items=data,
    )
    data = _dedupe_question_items(data)

    recovery_attempts = 0
    while len(data) < question_count and recovery_attempts < 2:
        remain = question_count - len(data)
        recovery_prompt = (
            prompt
            + "\n\n[Recovery] After grounding review, too few questions remain. "
            + f"Generate exactly {remain} ADDITIONAL grounded questions. "
            + "Do not repeat or paraphrase the existing questions below. Output ONLY the new questions as a JSON array.\n\n"
            + f"[Existing accepted questions]\n{json.dumps(data, ensure_ascii=False)}"
        )
        more = _coerce_question_items(_call_with_retries(
            cfg,
            messages=[{"role": "user", "content": recovery_prompt}],
            temperature=0.1,
            max_tokens=4096,
            timeout=160,
        ))
        more = _ground_generated_questions(
            cfg=cfg,
            text=text,
            subject=subject,
            level=level,
            question_count=remain,
            items=more,
        )
        if not more:
            break
        data = _dedupe_question_items(data + more)
        recovery_attempts += 1

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
    policy = (
        "infer the answer and mark needs_review=true"
        if allow_guess
        else "leave correct empty and mark needs_review=true"
    )

    prompt = f"""You are a Hong Kong secondary school teacher converting existing questions to standard JSON.

[Subject] {subject}
[Requirements]
- Each question: 4-option single choice (qtype=single)
- options: exactly 4 strings
- correct: list with exactly 1 element, string "1"~"4"
- Output ONLY a raw JSON array. No markdown code blocks. No ```json wrapper.
- If answer is missing: {policy}
- Question stems must NOT contain 'according to the passage/text' or similar phrases.
  If the original question has such phrases, remove them and rewrite as a standalone knowledge question.

[Original questions]
{raw_text}
"""

    return _call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0 if fast_mode else 0.1,
        max_tokens=4096,
        timeout=120,
    )


def parse_import_questions_locally(raw_text: str):
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []
    return []
