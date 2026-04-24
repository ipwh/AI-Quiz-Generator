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
    (re.compile(r"\u6839\u636e(\u6559\u6750|\u6587\u672c|\u4ee5\u4e0a|\u4e0a\u6587|\u77ed\u6587|\u6587\u7ae0|\u8cc7\u6599|\u5716\u8868|\u4ee5\u4e0b|\u984c\u76ee|\u5185\u5bb9)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u6309\u7167(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u4f9d\u64da(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u53c3\u8003(\u6559\u6750|\u6587\u672c|\u8ab2\u6587)[\uff0c,\uff1a:\u3001\s]?"), ""),
    (re.compile(r"\u5f9e(\u6559\u6750|\u6587\u672c|\u4ee5\u4e0a|\u4e0a\u6587|\u77ed\u6587|\u6587\u7ae0|\u8cc7\u6599)\u4e2d[\uff0c,\s]?"), ""),
    (re.compile(r"(?i)according\s+to\s+the\s+(passage|text|article|material|textbook)[,\s]?"), ""),
    (re.compile(r"(?i)based\s+on\s+the\s+(passage|text|article|material|textbook)[,\s]?"), ""),
    (re.compile(r"(?i)from\s+the\s+(passage|text|article)[,\s]?"), ""),
    (re.compile(r"(?i)the\s+(passage|text)\s+(states?|mentions?|says?|tells?\s+us)[,\s]?"), ""),
    (re.compile(r"(?i)as\s+(stated|mentioned|described)\s+in\s+the\s+(passage|text)[,\s]?"), ""),
    (re.compile(r"(?i)refer\s+to\s+the\s+(passage|text|material)[,\s]?"), ""),
]

_FORBIDDEN_STEMS_STR = (
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


def extract_json(text: str) -> Any:
    """
    Extract JSON from LLM output.
    Strategy 1: direct json.loads
    Strategy 2: strip markdown code block (```json ... ```)
    Strategy 3: regex extract first [...] or {...}
    """
    if not text:
        raise ValueError("AI returned empty content")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    stripped = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped.strip())
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue

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
    """Shuffle option order to balance A/B/C/D distribution. Handles int/float/str correct values."""
    if seed is None:
        seed = int(time.time()) % 100000
    rng = random.Random(seed)

    valid: List[dict] = []
    for q in items or []:
        corr = q.get("correct", [])
        if isinstance(corr, list) and len(corr) == 1:
            # Normalise: int 1 / float 1.0 / str "1" all become str "1"
            corr_str = str(corr[0]).strip().split(".")[0]  # handles "1.0" -> "1"
            if corr_str in {"1", "2", "3", "4"}:
                q["correct"] = [corr_str]  # normalise in-place
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

    prompt = f"""You are a Hong Kong secondary school teacher creating internal assessment questions.
This is a knowledge-based multiple choice quiz. Students answer from personal knowledge only - there is NO reading passage or textbook in the exam room.

[Subject] {subject}
[Difficulty] {level}
[Number of questions] Exactly {question_count}

[Subject traits]
{traits}

[Common misconceptions (use for distractor design)]
{mc_text}

[Subject-specific distractor templates (must reference)]
{sd_text}

[Distractor intensity]
{distractor_rules}

[ABSOLUTE PROHIBITION - violation = question is void and must be rewritten]
Do NOT use any of the following phrases in question stems or options:
{_FORBIDDEN_STEMS_STR}
Reason: Students have no textbook. All questions must be answerable from personal knowledge.
Test the knowledge point directly without citing a source.

Correct: "What gas is released by plants during photosynthesis?"
Wrong:   "According to the passage, what gas is released during photosynthesis?"

[Strict output requirements]
- Output ONLY a raw JSON array. No extra text. No markdown code blocks. No ```json wrapper.
- Each item: qtype = "single"
- options: exactly 4 strings
- correct: list with exactly 1 element, value must be string "1", "2", "3", or "4"
- explanation: concise key reasoning (1-3 sentences), note common errors in wrong options
- needs_review: true if question stem or answer is uncertain
- Distribute correct answers evenly across A/B/C/D positions

[Content for reference - NOT a student reading passage]
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
                    + f"\n\n[Top-up] You generated too few questions. Add {remain} more. Output ONLY the new questions as a JSON array."
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
        max_tokens=2400,
        timeout=120,
    )


def parse_import_questions_locally(raw_text: str):
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []
    return []
