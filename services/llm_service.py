import json
import re
import requests
import threading
import time
import random

_SESSION = requests.Session()
_SESSION_LOCK = threading.Lock()


def _reset_session():
    global _SESSION
    try:
        _SESSION.close()
    except Exception:
        pass
    _SESSION = requests.Session()


# -------------------------
# 科目特性（你可按校本再擴充）
# -------------------------
SUBJECT_TRAITS = {
    "中國語文": "重點：篇章理解、語境推斷、段落主旨、作者態度。干擾項：以偏概全、張冠李戴。",
    "英國語文": "Focus: inference, tone, vocab in context. Distractors: near-synonym traps.",
    "數學": "重點：概念+運算、步驟、圖表、公式。干擾項：公式套錯、單位錯。",
    "公民與社會發展": "重點：概念辨析、情境應用、因果。干擾項：概念混淆、因果倒置。",
    "科學": "重點：概念+探究（變量、公平測試、數據）。干擾項：相關性當因果、混淆變量。",
    "物理": "重點：定律應用、方向、單位、圖像。干擾項：符號/方向錯。",
    "化學": "重點：粒子模型、方程式、實驗觀察。干擾項：配平錯、概念混淆。",
    "生物": "重點：結構功能、恆常性、遺傳、生態。干擾項：器官功能混淆。",
    "資訊及通訊科技（ICT）": "重點：資料處理/網絡/保安/程式。干擾項：概念混用。",
    "地理": "重點：地圖/圖表、成因+影響、案例。干擾項：把描述當解釋、忽略尺度。",
    "歷史": "重點：時序、因果、史料分析、多角度。干擾項：事實/見解不分、單因論。",
    "中國歷史": "重點：時序脈絡、因果、史料。干擾項：年代混淆。",
    "經濟": "重點：供需/彈性/政策影響。干擾項：需求改變vs需求量改變。",
    "企業、會計與財務概論": "重點：營商環境、管理、會計、財務、道德。",
    "企業、會計及財務概論": "重點同「企業、會計與財務概論」。",
    "旅遊與款待": "重點：行業體系、承載力、服務質素、可持續。",
    "宗教": "天主教用字：天主、伯多祿、聖母瑪利亞、教宗/主教/神父、教友。",
}
DEFAULT_TRAITS = "重點：根據教材內容出題，避免離題。"


# -------------------------
# 工具：清洗文字
# -------------------------
def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# -------------------------
# 工具：抽 JSON（容錯）
# -------------------------
def extract_json(text: str):
    if not text:
        raise ValueError("AI 回傳內容是空的")

    t = text.strip()
    t = re.sub(r"^```json", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"^```", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"```$", "", t).strip()

    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[.*\]", t, re.DOTALL)
    if m:
        return json.loads(m.group())

    raise ValueError("無法從 AI 回傳解析 JSON（可能回傳了非 JSON 內容）")


def _normalize_options(opts, qtype: str):
    if qtype == "true_false":
        return ["對", "錯", "", ""]
    if not isinstance(opts, list):
        opts = []
    opts = [str(x).strip() for x in opts][:4]
    while len(opts) < 4:
        opts.append("")
    return opts


def _normalize_correct(corr, qtype: str):
    if isinstance(corr, str):
        parts = [p.strip() for p in corr.split(",") if p.strip()]
        corr = parts
    if not isinstance(corr, list):
        corr = []
    corr = [str(x).strip() for x in corr]
    corr = [c for c in corr if c in {"1", "2", "3", "4"}]

    if qtype == "true_false":
        corr = [c for c in corr if c in {"1", "2"}]
        return [corr[0]] if corr else ["1"]

    if qtype == "multiple":
        seen = set()
        out = []
        for c in corr:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out[:4] if out else ["1"]

    return [corr[0]] if corr else ["1"]


# -------------------------
# HTTP：OpenAI compatible / Azure
# -------------------------
def _post_openai_compat(api_key: str, base_url: str, payload: dict, timeout: int = 120, max_retries: int = 5):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t = (15, timeout)
    last_err = None

    for attempt in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=payload, timeout=t)
            r.raise_for_status()
            return r.json()

        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            last_err = e
            time.sleep(((2 ** attempt) * 2) + random.random())
            with _SESSION_LOCK:
                _reset_session()

        except requests.exceptions.HTTPError:
            raise

        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(((2 ** attempt) * 2) + random.random())
            with _SESSION_LOCK:
                _reset_session()

    raise requests.exceptions.ConnectionError(f"OpenAI-compatible request failed after retries: {last_err}")


def _post_azure(api_key: str, endpoint: str, deployment: str, api_version: str, payload: dict, timeout: int = 120, max_retries: int = 3):
    url = endpoint.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    t = (10, timeout)
    last_err = None

    for attempt in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=payload, timeout=t)
            r.raise_for_status()
            return r.json()

        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            last_err = e
            time.sleep((2 ** attempt) + random.random())
            with _SESSION_LOCK:
                _reset_session()

        except requests.exceptions.HTTPError:
            raise

        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep((2 ** attempt) + random.random())
            with _SESSION_LOCK:
                _reset_session()

    raise requests.exceptions.ConnectionError(f"Azure request failed after retries: {last_err}")


def _chat(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int):
    if cfg.get("type") == "azure":
        data = _post_azure(
            api_key=cfg["api_key"],
            endpoint=cfg["endpoint"],
            deployment=cfg["deployment"],
            api_version=cfg.get("api_version", "2024-02-15-preview"),
            payload={"messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=timeout,
        )
    else:
        data = _post_openai_compat(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            payload={"model": cfg["model"], "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=timeout,
        )
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


# -------------------------
# API 測試
# -------------------------
def ping_llm(cfg: dict, timeout: int = 25):
    t0 = time.time()
    try:
        out = _chat(
            cfg,
            messages=[{"role": "user", "content": "只輸出兩個字：OK。不要輸出任何其他文字、標點或換行。"}],
            temperature=0.0,
            max_tokens=3,
            timeout=timeout,
        )
        ms = int((time.time() - t0) * 1000)
        text = (out or "").strip()
        if "OK" in text.upper():
            text = "OK"
        return {"ok": True, "latency_ms": ms, "output": text, "error": ""}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"ok": False, "latency_ms": ms, "output": "", "error": repr(e)}


# -------------------------
# Grok 自動偵測（供 app.py 使用）
# -------------------------
def get_xai_default_model(api_key: str, base_url: str = "https://api.x.ai/v1", timeout: int = 15) -> str:
    preferred_aliases = ["grok-4-latest", "grok-4", "grok-3-latest", "grok-3", "grok-2-latest"]
    url = base_url.rstrip("/") + "/language-models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with _SESSION_LOCK:
            r = _SESSION.get(url, headers=headers, timeout=(10, timeout))
        r.raise_for_status()
        payload = r.json()

        models = payload.get("models") or payload.get("data") or []
        if not isinstance(models, list):
            models = []

        alias_set = set()
        grok_models = []
        for m in models:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id", "") or "")
            created = m.get("created", 0) or 0
            aliases = m.get("aliases") or []
            if isinstance(aliases, list):
                for a in aliases:
                    if isinstance(a, str):
                        alias_set.add(a)
            if mid.startswith("grok-"):
                grok_models.append((created, mid))

        for a in preferred_aliases:
            if a in alias_set:
                return a

        if grok_models:
            grok_models.sort(key=lambda x: x[0], reverse=True)
            return grok_models[0][1]

        return "grok-4-latest"
    except Exception:
        return "grok-4-latest"


# -------------------------
# JSON 修復（失敗自救）
# -------------------------
def _fix_json(cfg: dict, bad_output: str, schema_hint: str, timeout: int):
    prompt = (
        "你剛才輸出不是有效 JSON 或格式不符合要求。\n"
        "請只回覆「純 JSON array」，不要任何解釋文字。\n\n"
        "必須符合此 schema：\n"
        f"{schema_hint}\n\n"
        "以下是你剛才的輸出（供修正）：\n"
        f"{bad_output}\n"
    )
    return _chat(cfg, [{"role": "user", "content": prompt}], temperature=0, max_tokens=2500, timeout=timeout)


def _call_with_retries(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int, schema_hint: str):
    out = _chat(cfg, messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    try:
        return extract_json(out)
    except Exception:
        out2 = _fix_json(cfg, out, schema_hint=schema_hint, timeout=timeout)
        return extract_json(out2)


_FEWSHOT_STRONG = r"""
[
  {
    "qtype": "single",
    "question": "下列哪一項最能解釋需求量上升？",
    "options": ["商品價格下跌", "消費者收入上升", "替代品價格下跌", "消費者偏好下降"],
    "correct": ["2"],
    "explanation": "",
    "needs_review": false
  },
  {
    "qtype": "single",
    "question": "以下哪一項最符合「公平測試」的做法？",
    "options": ["同時改變兩個變量以加快比較", "只改變一個變量，其餘保持不變", "每次用不同器材以增加多樣性", "只做一次測試以避免誤差"],
    "correct": ["2"],
    "explanation": "",
    "needs_review": false
  },
  {
    "qtype": "single",
    "question": "哪些屬於新媒體？\n(1) 商業電台\n(2) 實體報章\n(3) 明報網上版\n(4) YouTube",
    "options": ["只有（1）和（2）", "只有（3）和（4）", "只有（1）、（3）和（4）", "以上皆是"],
    "correct": ["2"],
    "explanation": "",
    "needs_review": false
  },
  {
    "qtype": "single",
    "question": "若要減少測量誤差，下列哪一項最有效？",
    "options": ["只量一次以節省時間", "多次量度取平均值", "用較短的尺以便攜帶", "把結果四捨五入到整數"],
    "correct": ["2"],
    "explanation": "",
    "needs_review": false
  }
]
"""


# -------------------------
# ✅ 生成題目（single 會偏好 (1)(2)… + A-D）
# -------------------------
def generate_questions(cfg, text, subject, level, question_count, fast_mode: bool = False, qtype: str = "single"):
    """
    單選（single）生成：
    - 強制格式配額：至少 75% 直接問答；最多 25% (1)-(4) 組合題
    - 分階段生成：先 direct，再生成剩餘（混合）
    - 程式端檢查：超配額就用 direct 補回並替換
    - 保證回傳題數 = question_count（不足會自動補題 + 去重）
    """
    import math, re, random

    qtype = "single"  # 目前生成固定單選（4選1）
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]
    n = int(question_count)

    DIRECT_MIN_RATIO = 0.75
    COMBO_MAX_RATIO = 0.25
    direct_target = max(1, math.ceil(n * DIRECT_MIN_RATIO))
    combo_max = max(0, math.floor(n * COMBO_MAX_RATIO))

    # 溫度：提升多樣化（fast_mode 稍低）
    temperature = 0.18 if fast_mode else 0.28
    max_tokens = 1500 if fast_mode else 2300
    timeout = 120 if fast_mode else 180

    banned_phrases = "教材、教材中、教材內、教材出現、教材提及、根據教材、根據以上資料、文中提及、上文提到、資料顯示"

    def strip_boilerplate(q: str) -> str:
        if not q:
            return ""
        s = q.strip()
        patterns = [
            r"^(根據|依據|參考).{0,12}(教材|內容|資料|文本|上文|文中).{0,12}[，,：:]*",
            r"^(教材|內容|資料|文本|上文|文中).{0,12}(提及|出現|指出|提到).{0,12}[，,：:]*",
            r"^根據.{0,12}[，,：:]*",
        ]
        for p in patterns:
            s = re.sub(p, "", s).strip()
        s = re.sub(r"^[,，:：\-\s]+", "", s).strip()
        return s

    def is_combo_style(question: str, options: list) -> bool:
        if not question:
            return False
        q_has = ("(1)" in question) or ("（1）" in question)
        opt_text = " ".join([str(o) for o in (options or [])])
        opt_has = ("只有" in opt_text) or ("以上皆是" in opt_text) or ("（1）" in opt_text) or ("(1)" in opt_text)
        return q_has and opt_has

    def dedupe(items: list) -> list:
        seen = set()
        out = []
        for it in items:
            q = (it.get("question") or "").strip()
            key = re.sub(r"\s+", " ", q).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    def difficulty_spec(code: str) -> str:
        if code == "easy":
            return "【Easy 基礎】定義/辨識/直接理解；禁止多步推理。"
        if code == "medium":
            return "【Medium 標準】情境應用/一步推論；干擾項要接近但錯在條件。"
        if code == "hard":
            return "【Hard 進階】分析/比較/至少2步推理；干擾項以常見混淆點設陷。"
        return "【Mixed 混合】必須同時包含 easy/medium/hard。"

    def build_prompt(level_code: str, count_needed: int, mode: str) -> str:
        """
        mode:
          - 'direct': 強制全部 direct（嚴禁(1)-(4)）
          - 'mixed' : 至少 75% direct，最多 25% combo（仍要混合）
        """
        rules_top = f"""
【強制格式規則（最優先，違反即無效）】
- 必須生成至少 75%「直接問答題」：題幹直接提出問題，選項為 A~D 四個獨立描述。
- 絕對不要在題幹出現 (1)(2)(3)(4) 或（1）（2）（3）（4）。
- 最多只能有 25%「(1)-(4) 組合題」。
- 嚴禁全部或大部分題目使用同一格式；必須混合。
- 若你傾向生成組合題，請立即調整為混合並增加直接問答題比例。
"""
        if mode == "direct":
            rules_top += """
【補充強制（direct 模式）】
- 本次生成的所有題目必須是「直接問答」格式。
- 嚴禁：題幹出現 (1)-(4)；嚴禁選項出現「只有」「以上皆是」或任何(1)-(4)組合語。
"""

        return f"""
{rules_top}

你是一名香港中學教師，負責出校內測驗題。
科目：{subject}

【難度規格（必須嚴格遵守）】
{difficulty_spec(level_code)}

【科目特性（必須遵守）】
{traits}

【題幹規則】
- 題幹要直接、簡潔。
- 禁止出現：{banned_phrases}
- 不要用「根據…」開頭句式。

【題型】多項選擇題（四選一 single）
【出題要求】
1) 只生成 {count_needed} 題
2) options 必須剛好 4 個
3) correct 必須是 ["1"~"4"]（只 1 個）
4) 每題題幹或選項必須包含提供內容中出現過的至少 2 個關鍵詞（貼題）
5) 若資訊不足：needs_review=true，但仍要給出最可能答案

【輸出】
只輸出純 JSON array，不要任何額外文字。

【示例（非常重要，請模仿）】
{_FEWSHOT_STRONG}

【提供內容】
{text}
"""

    def call_once(level_code: str, count_needed: int, mode: str) -> list:
        prompt = build_prompt(level_code, count_needed, mode=mode)
        items = _call_with_retries(
            cfg,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            schema_hint="JSON array",
        )

        cleaned = []
        for q in items or []:
            opts = _normalize_options(q.get("options", []), "single")
            corr = _normalize_correct(q.get("correct", []), "single")
            question = strip_boilerplate(str(q.get("question", "")).strip())
            if not question:
                continue
            cleaned.append({
                "qtype": "single",
                "question": question,
                "options": opts,
                "correct": corr,
                "explanation": str(q.get("explanation", "")).strip()[:60],
                "needs_review": bool(q.get("needs_review", False)),
            })

        return dedupe(cleaned)

    def fill_to_count(level_code: str, target: int, mode: str) -> list:
        out = call_once(level_code, target, mode=mode)
        rounds = 0
        while len(out) < target and rounds < 3:
            missing = target - len(out)
            existing = "\n".join([f"- {it['question']}" for it in out[:25]])
            # 追加「不可重複」規則
            extra_prompt = build_prompt(level_code, missing, mode=mode) + f"\n\n【去重】不可與以下題目重複：\n{existing}\n"
            items = _call_with_retries(
                cfg,
                messages=[{"role": "user", "content": extra_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                schema_hint="JSON array",
            )
            more = []
            for q in items or []:
                opts = _normalize_options(q.get("options", []), "single")
                corr = _normalize_correct(q.get("correct", []), "single")
                question = strip_boilerplate(str(q.get("question", "")).strip())
                if not question:
                    continue
                more.append({
                    "qtype": "single",
                    "question": question,
                    "options": opts,
                    "correct": corr,
                    "explanation": str(q.get("explanation", "")).strip()[:60],
                    "needs_review": bool(q.get("needs_review", False)),
                })
            out = dedupe(out + more)
            rounds += 1

        if len(out) < target:
            raise ValueError(f"AI 只生成了 {len(out)}/{target} 題（已多次重試）。請重試或減少題目數目。")

        return out[:target]

    # -------------------------
    # 分階段生成（中期建議，直接做）
    # -------------------------
    if level == "mixed":
        # mixed：先按比例分層生成 direct，再生成混合補足
        n_easy = max(1, round(n * 0.4))
        n_med = max(1, round(n * 0.4))
        n_hard = max(1, n - n_easy - n_med)

        a = fill_to_count("easy", n_easy, mode="mixed")
        b = fill_to_count("medium", n_med, mode="mixed")
        c = fill_to_count("hard", n_hard, mode="mixed")

        out = a + b + c
        random.shuffle(out)
        out = out[:n]
    else:
        # Stage A：先生成 direct_target（強制 direct）
        direct_part = fill_to_count(level, direct_target, mode="mixed")

        # Stage B：再生成剩餘（mixed 模式，但仍限制比例）
        remaining = n - len(direct_part)
        if remaining > 0:
            rest = fill_to_count(level, remaining, mode="mixed")
            out = dedupe(direct_part + rest)
        else:
            out = direct_part[:n]

        # 若因去重不足，再補（mixed）
        if len(out) < n:
            out = dedupe(out + fill_to_count(level, n - len(out), mode="mixed"))
            out = out[:n]

    # -------------------------
    # 程式端檢查：combo 超配額 → 用 direct 補回並替換
    # -------------------------
    combo_idx = [i for i, it in enumerate(out) if is_combo_style(it["question"], it["options"])]
    if len(combo_idx) > combo_max:
        need = len(combo_idx) - combo_max
        direct_more = fill_to_count("medium" if level == "mixed" else level, need, mode="mixed")
        for k, idx in enumerate(combo_idx[:need]):
            if k < len(direct_more):
                out[idx] = direct_more[k]

    # 最終保險：回傳正確題數
    return out[:n]
# =========================
# ✅ Restore import helpers (used by app.py)
# - assist_import_questions
# - parse_import_questions_locally
# =========================

def assist_import_questions(cfg, raw_text, subject, allow_guess=True, fast_mode: bool = False, qtype: str = "single"):
    """
    匯入題目整理：固定 single（4選1）
    - 若原文有答案：跟從
    - 若無答案：allow_guess=True 時推測，但 needs_review=true + explanation 以「⚠️需教師確認：」開頭
    """
    qtype = "single"
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    raw_text = _clean_text(raw_text)
    raw_text = raw_text[: (8000 if fast_mode else 10000)]

    guess_rule = (
        "若原文未提供答案，你必須推測最可能正確答案，但 needs_review=true，explanation 以「⚠️需教師確認：」開頭。"
        if allow_guess
        else "若原文未提供答案，correct=['1'] 並 needs_review=true，explanation 以「⚠️需教師確認：」開頭。"
    )

    temperature = 0.0 if fast_mode else 0.1
    max_tokens = 1600 if fast_mode else 2400
    timeout = 120 if fast_mode else 180

    prompt = f"""
你是一名香港中學教師，正在把現有題目整理成標準格式。
科目：{subject}
目標題型：single（4選1）

【科目特性（參考）】
{traits}

【最重要規則】
- 原文若有答案（例如：答案：B / Answer: 2），必須跟從。
- {guess_rule}
- 無論如何，每題都必須填 correct（不可留空）。

【輸出要求】
- 只輸出純 JSON array，不要任何額外文字。
- 每題必須有 4 個選項（不足補空字串）。
- correct 必須是 ["1"~"4"]（只 1 個）。

【原始文字】
{raw_text}
"""

    items = _call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        schema_hint="JSON array",
    )

    cleaned = []
    for q in items or []:
        opts = _normalize_options(q.get("options", []), "single")
        corr = _normalize_correct(q.get("correct", []), "single")
        expl = str(q.get("explanation", "")).strip()
        needs_review = bool(q.get("needs_review", False))

        # 若 needs_review=true，確保 explanation 有提示字樣
        if needs_review and not expl.startswith("⚠️需教師確認："):
            expl = "⚠️需教師確認：" + (expl if expl else "系統推測答案，請老師核對。")

        cleaned.append({
            "qtype": "single",
            "question": str(q.get("question", "")).strip(),
            "options": opts,
            "correct": corr,
            "explanation": expl[:120],
            "needs_review": needs_review,
        })

    return cleaned


def parse_import_questions_locally(raw_text: str):
    """
    本地拆題備援：支援 A-D 選項 & (答案: A/B/1/2/3/4)
    """
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []

    # 按題號粗分（可容錯）
    parts = re.split(r"(?:\n(?=\s*(?:\d+\s*[\.、]|Q\d+|第\s*\d+\s*題)))", raw_text, flags=re.IGNORECASE)
    blocks = [p.strip() for p in parts if p.strip()] or [raw_text]

    opt_pat = re.compile(r"(?m)^\s*(?:\(?([A-D])\)?)[\.\)、\):：]\s*(.+?)\s*$")
    ans_pat = re.compile(r"(?:答案|Answer)\s*[:：]\s*([A-D]|[1-4])", flags=re.IGNORECASE)

    out = []
    for b in blocks:
        text = b.strip()

        m_ans = ans_pat.search(text)
        ans = m_ans.group(1).upper() if m_ans else None

        opts = {"A": "", "B": "", "C": "", "D": ""}
        for m in opt_pat.finditer(text):
            opts[m.group(1).upper()] = m.group(2).strip()

        options = _normalize_options([opts["A"], opts["B"], opts["C"], opts["D"]], "single")

        qstem = opt_pat.sub("", text)
        qstem = ans_pat.sub("", qstem).strip()

        needs_review = False
        correct_num = "1"
        if ans:
            correct_num = ans if ans.isdigit() else str(ord(ans) - ord("A") + 1)
        else:
            needs_review = True

        expl = "⚠️需教師確認：未找到答案，請老師核對。" if needs_review else ""

        out.append({
            "qtype": "single",
            "question": qstem,
            "options": options,
            "correct": [correct_num],
            "explanation": expl,
            "needs_review": needs_review,
        })

    return out

def xai_pick_vision_model(api_key: str, base_url: str = "https://api.x.ai/v1", timeout: int = 15) -> str | None:
    """
    從 /v1/language-models 挑一個 input_modalities 含 image 的 Grok 模型。[3](https://www.aidoczh.com/streamlit/develop/concepts/connections/secrets-management.html)
    """
    url = base_url.rstrip("/") + "/language-models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        with _SESSION_LOCK:
            r = _SESSION.get(url, headers=headers, timeout=(10, timeout))
        r.raise_for_status()
        payload = r.json()
        models = payload.get("models") or payload.get("data") or []
        if not isinstance(models, list):
            return None

        candidates = []
        for m in models:
            if not isinstance(m, dict):
                continue
            input_mods = m.get("input_modalities") or []
            if isinstance(input_mods, list) and "image" in input_mods:
                created = m.get("created", 0) or 0
                mid = str(m.get("id", "") or "")
                aliases = m.get("aliases") or []
                alias_latest = None
                if isinstance(aliases, list):
                    for a in aliases:
                        if isinstance(a, str) and a.endswith("-latest"):
                            alias_latest = a
                            break
                candidates.append((created, alias_latest or mid))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None

def llm_ocr_extract_text(cfg: dict, images_data_urls: list[str], lang_hint: str = "zh-Hant", fast_mode: bool = False) -> str:
    """
    使用多模態 LLM 做 OCR：輸出「純文字」。
    images_data_urls: ["data:image/png;base64,...", ...]
    """
    if not images_data_urls:
        return ""

    temperature = 0.0 if fast_mode else 0.1
    max_tokens = 1800 if fast_mode else 3000
    timeout = 120 if fast_mode else 180

    prompt = f"""
你是一個 OCR 文字抽取器。請從圖片中抽取所有可辨識文字，輸出「純文字」即可。
規則：
- 不要解釋、不要總結、不要加入你推測的內容。
- 保留原有段落/換行（能分段就分段）。
- 語言提示：{lang_hint}
"""

    content = [{"type": "text", "text": prompt}]
    for url in images_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    out = _chat(
        cfg,
        messages=[{"role": "user", "content": content}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    return (out or "").strip()
