# =========================================================
# services/llm_service.py
# FINAL-FULL（穩定可用・已修復 SyntaxError）
# ---------------------------------------------------------
# ✅ OpenAI-compatible /v1/chat/completions
# ✅ 支援：Generate / Import / JSON 修復 / API Ping
# ✅ 強化：SUBJECT_TRAITS / SUBJECT_MISCONCEPTIONS / SUBJECT_DISTRACTOR_HINTS（全科目）
# ✅ 附加：Grok 型號自動偵測 get_xai_default_model()
# ✅ 附加：答案位置分佈平衡（避免 correct 長期偏 2/3）
# ---------------------------------------------------------
# 注意：
# - 嚴格 Python 語法、4 spaces 縮排
# - 不輸出『根據教材/根據文本』等 meta 字眼
# =========================================================

from __future__ import annotations

import json
import random
import re
import time
import threading
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
# SUBJECT TRAITS / MISCONCEPTIONS / DISTRACTOR HINTS
# =========================================================

SUBJECT_TRAITS: Dict[str, str] = {
    "中國語文": "篇章理解、語境推斷、主旨、作者態度、修辭與寫作意圖。題幹自然，避免『根據教材』字眼。",
    "英國語文": "Reading comprehension, inference, tone/attitude, vocabulary in context, cohesion. Avoid meta phrasing.",
    "數學": "概念理解、運算步驟、條件限制、單位與定義域。題目清楚已知/所求。",
    "公民與社會發展": "概念（法治、身份、全球化、可持續）、資料判讀、立場辨析、政策取捨。",
    "科學": "概念理解、變量控制、公平測試、數據解讀、由證據推論。",
    "物理": "定律應用、受力分析、能量/動量、圖像解讀、單位與方向。",
    "化學": "粒子模型、方程式與配平、計量、反應條件、實驗設計與安全。",
    "生物": "結構與功能、恆常性、遺傳演化、生態與人類影響、數據解讀。",
    "地理": "成因→過程→影響→管理、空間分佈、案例比較、地圖/數據判讀。",
    "歷史": "時序、因果、史料解讀、觀點與偏見、短/長期影響。",
    "中國歷史": "朝代脈絡、制度與社會、延續/變革、史料與論證。",
    "宗教": "宗教概念、倫理抉擇、教義理解、比較觀點與反思。",
    "資訊及通訊科技（ICT）": "系統概念、資料表示、網絡與安全、演算法思維、硬/軟件與應用。",
    "經濟": "供需、彈性、外部性、市場失靈、政策影響與圖像解讀。",
    "企業、會計與財務概論": "會計原則、報表解讀、成本/定價、比率、現金流。",
    "公民、經濟及社會": "公民身份、經濟基本概念、社會議題、資料解讀與價值判斷。",
    "旅遊與款待": "旅遊系統、服務質素、營運、安全與風險、可持續、客戶體驗。",
}

DEFAULT_TRAITS = "請按內容出題，語句自然，避免使用『根據教材/根據文本/根據以上』等提示語。"

SUBJECT_MISCONCEPTIONS: Dict[str, List[str]] = {
    "中國語文": ["斷章取義", "過度推論", "把描述當立場", "忽略語境", "修辭作用誤判", "轉折/因果混淆"],
    "英國語文": ["near-synonym trap", "opposite tone", "wrong referent", "overgeneralization", "negation trap"],
    "數學": ["漏條件/定義域", "單位/比例錯", "運算次序/符號錯", "四捨五入/有效數字錯", "概念混淆"],
    "公民與社會發展": ["概念混淆", "把立場當事實", "以偏概全", "忽略持份者差異", "忽略政策取捨"],
    "科學": ["相關≠因果", "未控制變量", "結論超出數據", "精確度/準確度混淆", "樣本不足"],
    "物理": ["方向/向量錯", "單位混淆", "忽略摩擦/損耗", "圖像斜率/面積誤讀", "作用力反作用力混淆"],
    "化學": ["未配平", "摩爾/質量/體積混淆", "濃度概念錯", "強弱vs濃度", "限量試劑錯"],
    "生物": ["目的論", "層級混淆", "相關≠因果", "負回饋方向反", "能量流向概念錯"],
    "地理": ["單一原因化", "天氣/氣候混淆", "尺度/地點忽略", "結果當原因", "只講一面"],
    "歷史": ["時序混淆", "後果當原因", "以今論古", "單一因素決定論", "史料立場忽略"],
    "中國歷史": ["朝代先後混淆", "制度名詞混淆", "結果當原因", "中央/地方混淆", "以偏概全"],
    "宗教": ["個人意見當教義", "混淆宗教概念", "只講規條忽略情境", "忽略價值衝突"],
    "資訊及通訊科技（ICT）": ["加密vs雜湊", "IPvsMAC", "備份vs同步", "授權vs認證", "安全措施角色混淆"],
    "經濟": ["需求vs需求量", "曲線移動方向錯", "稅負歸宿誤判", "彈性判斷反", "福利變化誤判"],
    "企業、會計與財務概論": ["利潤vs現金流", "收入vs收款", "資產/費用/支出混淆", "比率公式代錯", "折舊/應收應付理解錯"],
    "公民、經濟及社會": ["道德判斷當事實", "以偏概全", "因果倒置", "忽略多方持份者", "概念字面化"],
    "旅遊與款待": ["短期成本忽略口碑", "服務補救不當", "忽略安全風險", "忽略可持續/承載量", "忽略顧客差異"],
}

DISTRACTOR_RULES_BY_LEVEL: Dict[str, str] = {
    "easy": "干擾項反映基本誤解；錯在單一步驟；避免過度相似。",
    "medium": "干擾項包含部分正確但推論錯或漏條件；至少兩個看似合理。",
    "hard": "干擾項為多步推理陷阱：條件誤判、圖像誤讀、單位/方向/定義域錯。",
    "mixed": "混合 medium/hard 強度；同一套題可含不同難度但每題仍要清晰。",
}

# ✅ 全科目專屬干擾項模板（加強版）
SUBJECT_DISTRACTOR_HINTS: Dict[str, List[str]] = {
    "中國語文": [
        "斷章取義（取片段偏離主旨）",
        "過度推論（推到文中沒有）",
        "把描述當立場（敘述誤當態度）",
        "修辭作用誤判（手法對但作用錯）",
        "轉折/因果混淆",
    ],
    "英國語文": [
        "near-synonym trap",
        "opposite tone",
        "wrong referent",
        "overgeneralization",
        "negation trap",
    ],
    "數學": [
        "漏條件/定義域",
        "單位/比例錯",
        "運算次序/符號錯",
        "四捨五入/有效數字錯",
        "概念混淆（面積/周界、平均/中位等）",
    ],
    "公民與社會發展": [
        "概念混淆（法治/人治、公平/平等、權利/責任）",
        "把立場當事實",
        "以偏概全（個案推普遍）",
        "忽略持份者差異",
        "忽略政策取捨（只講好/只講壞）",
    ],
    "科學": [
        "相關≠因果",
        "未控制變量",
        "結論超出數據",
        "精確度/準確度混淆",
        "樣本/重複不足",
    ],
    "物理": [
        "方向/向量（正負號反）",
        "單位混淆（N/J/W 等）",
        "忽略摩擦/損耗（理想化錯用）",
        "圖像斜率/面積誤讀",
        "作用力反作用力混淆",
    ],
    "化學": [
        "方程式未配平/係數錯",
        "摩爾/質量/體積混淆",
        "濃度概念錯（稀釋/體積變化）",
        "酸鹼強弱 vs 濃度",
        "限量試劑判斷錯",
    ],
    "生物": [
        "目的論（把適應當有意圖）",
        "層級混淆（細胞/器官/系統）",
        "相關≠因果",
        "負回饋方向反",
        "能量流向/生態概念錯",
    ],
    "地理": [
        "單一原因化（忽略多因素互動）",
        "天氣/氣候混淆",
        "尺度/地點條件忽略",
        "結果當原因",
        "只講一面（忽略取捨/持份者）",
    ],
    "歷史": [
        "時序/年代混淆",
        "後果當原因",
        "以今論古",
        "單一因素決定論",
        "史料立場忽略（把主張當事實）",
    ],
    "中國歷史": [
        "朝代先後混淆",
        "制度名詞混淆",
        "結果當原因",
        "中央/地方權力混淆",
        "以偏概全（以一例概括一代）",
    ],
    "宗教": [
        "把個人意見當教義",
        "混淆不同宗教概念",
        "只講規條忽略情境",
        "忽略價值衝突",
        "描述當評價",
    ],
    "資訊及通訊科技（ICT）": [
        "加密 vs 雜湊",
        "IP vs MAC",
        "備份 vs 同步",
        "授權 vs 認證",
        "安全措施角色混淆（防火牆/防毒/權限）",
    ],
    "經濟": [
        "需求 vs 需求量",
        "曲線移動方向錯（把價格變動當移動）",
        "稅負歸宿誤判（只看法定承擔者）",
        "彈性判斷反",
        "福利變化誤判（剩餘/死重損失）",
    ],
    "企業、會計與財務概論": [
        "利潤 vs 現金流",
        "收入 vs 收款",
        "資產/費用/支出混淆",
        "比率公式代錯",
        "折舊/應收應付理解錯",
    ],
    "公民、經濟及社會": [
        "道德判斷當事實",
        "以偏概全",
        "因果倒置",
        "忽略多方持份者",
        "概念字面化（忽略情境/證據）",
    ],
    "旅遊與款待": [
        "只顧短期成本忽略口碑/品牌",
        "服務補救不當（推卸責任/欠同理）",
        "忽略安全與風險",
        "忽略可持續/承載量",
        "忽略顧客需求差異",
    ],
}


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
    if not text:
        raise ValueError("AI 回傳內容是空的")
    return json.loads(text)


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

    # 嚴格只送核心欄位，避免 xAI 400（不支援參數）
    allowed = {"model", "messages", "temperature", "max_tokens", "stream", "response_format"}
    safe_payload = {k: v for k, v in payload.items() if k in allowed}

    last_err: Optional[Exception] = None
    for _ in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=safe_payload, timeout=(10, timeout))
            if not r.ok:
                raise requests.HTTPError(
                    f"{r.status_code} Client Error: {r.reason} for url: {r.url}\n\n--- response body ---\n{r.text}",
                    response=r,
                )
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.6)

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
    """列出 /models 後挑選最新 grok（偏好 latest）。"""
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
        "嚴禁輸出 role、content。\n\n"
        "每題必須包含：\n"
        "- qtype: \"single\"\n"
        "- question: string（不要以『根據教材/根據文本』開頭）\n"
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
        if isinstance(corr, list) and len(corr) == 1 and corr[0] in {"1", "2", "3", "4"}:
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
        cur = q["correct"][0]
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
- 每題必為四選一：qtype = "single"
- options 必須剛好 4 個字串
- correct 必須為只含 1 個元素的 list： ["1"~"4"]
- question 請用自然題幹，不要以「根據教材/根據文本/根據以上」等字眼開頭
- explanation 簡潔指出關鍵理由（1-3 句）
- needs_review: 若題幹/答案不確定或需教師判斷，請設為 true
- 正確答案位置請避免長期集中於 B/C（2/3），A/B/C/D 需大致均勻

【內容】
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
                prompt2 = prompt + f"\n\n【補齊要求】你剛才題數不足，請再補 {remain} 題，只輸出新增題目的 JSON array。"
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
- 只輸出純 JSON array
- 若原文欠缺答案：{policy}

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
