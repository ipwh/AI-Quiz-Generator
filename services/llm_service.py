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



_FEWSHOT = """
[
  {
    "qtype": "single",
    "question": "下列哪一項不是媒體資訊帶來的效益？",
    "options": ["A 選項", "B 選項", "C 選項", "D 選項"],
    "correct": ["1"],
    "explanation": "",
    "needs_review": false
  },
  {
    "qtype": "single",
    "question": "哪些屬於新媒體？
(1) 商業電台
(2) 實體報章
(3) 明報網上版
(4) YouTube",
    "options": ["只有（1）和（2）", "只有（3）和（4）", "只有（1）、（3）和（4）", "以上皆是"],
    "correct": ["2"],
    "explanation": "",
    "needs_review": false
  }
]
"""


def _difficulty_guidance(level_code: str) -> str:
    if level_code == "easy":
        return (
            "【Easy 基礎】
"
            "- 題目重點：定義/關鍵詞辨識/直接理解。
"
            "- 不可：跨段推論、多步推理。
"
            "- 干擾項：較明顯錯或典型誤解。"
        )
    if level_code == "medium":
        return (
            "【Medium 標準】
"
            "- 題目重點：情境應用、一步推論。
"
            "- 干擾項：接近正確但在條件/概念上差一點。"
        )
    if level_code == "hard":
        return (
            "【Hard 進階】
"
            "- 題目重點：分析/比較/判斷（至少2步推理）。
"
            "- 干擾項：非常接近、以常見混淆點設陷。"
        )
    return (
        "【Mixed 混合】
"
        "- 必須同時包含 easy/medium/hard 三類題目（比例由系統分配）。"
    )


def _strip_boilerplate(question: str) -> str:
    if not question:
        return ""
    s = question.strip()
    patterns = [
        r"^(根據|依據|參考).{0,12}(教材|內容|資料|文本|上文|文中).{0,12}[，,：:]*",
        r"^(教材|內容|資料|文本|上文|文中).{0,12}(提及|出現|指出|提到).{0,12}[，,：:]*",
        r"^根據.{0,12}[，,：:]*",
    ]
    for p in patterns:
        s = re.sub(p, "", s).strip()
    s = re.sub(r"^[,，:：\-\s]+", "", s).strip()
    return s


def _is_list_combo_style(q: str, options: list) -> bool:
    if not q:
        return False
    q_has = ("(1)" in q) or ("（1）" in q)
    opt_text = " ".join([str(o) for o in (options or [])])
    opt_has = ("只有" in opt_text) or ("以上皆是" in opt_text) or ("（1）" in opt_text) or ("(1)" in opt_text)
    return q_has and opt_has


def _dedupe(items: list) -> list:
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


def _build_prompt(subject: str, traits: str, level_code: str, count: int, text: str) -> str:
    banned = "教材、教材中、教材內、教材出現、教材提及、根據教材、根據以上資料、文中提及、上文提到、資料顯示"
    max_list = max(1, round(count * 0.3))
    min_direct = count - max_list

    return f"""
你是一名香港中學教師，負責出校內測驗題。
科目：{subject}

【難度規格（必須嚴格遵守）】
{_difficulty_guidance(level_code)}

【科目特性（必須遵守）】
{traits}

【題幹規則（必須遵守）】
- 題幹要直接、簡潔。
- 禁止出現：{banned}
- 不要用「根據…」開頭句式。

【題型】多項選擇題（四選一 single）
【版式配額（必須遵守）】
- 至少 {min_direct} 題必須使用「直接問答」：題幹 + A~D（四個純選項，不要(1)~(4)組合題）。
- 最多 {max_list} 題可使用「資料題」：題幹 + (1)~(4) + A~D（選項是(1)~(4)組合）。

【出題硬規則】
1) 只生成 {count} 題
2) options 必須剛好 4 個
3) correct 必須是 ["1"~"4"]（只 1 個）
4) 題幹或選項必須包含提供內容中出現過的至少 2 個關鍵詞（貼題）
5) 若資訊不足：needs_review=true，但仍要給出最可能答案

【輸出】
只輸出純 JSON array，不要任何額外文字。

【格式示例】
{_FEWSHOT}

【提供內容】
{text}
"""


def _generate_once(cfg, subject: str, level_code: str, count: int, text: str, fast_mode: bool) -> list:
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    temperature = 0.12 if fast_mode else 0.2
    max_tokens = 1400 if fast_mode else 2200
    timeout = 120 if fast_mode else 180

    prompt = _build_prompt(subject, traits, level_code, count, text)

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
        question = _strip_boilerplate(str(q.get("question", "")).strip())
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

    return _dedupe(cleaned)


def _fill_to_count(cfg, subject: str, level_code: str, target: int, text: str, fast_mode: bool) -> list:
    out = _generate_once(cfg, subject, level_code, target, text, fast_mode)

    rounds = 0
    while len(out) < target and rounds < 3:
        missing = target - len(out)
        existing = "
".join([f"- {it['question']}" for it in out[:25]])
        prompt_suffix = f"

【補充】請再生成 {missing} 題，不可與以下題目重複：
{existing}
"
        more = _generate_once(cfg, subject, level_code, missing, text + prompt_suffix, fast_mode)
        out = _dedupe(out + more)
        rounds += 1

    if len(out) < target:
        raise ValueError(f"AI 只生成了 {len(out)}/{target} 題（已多次重試）。請重試或減少題目數目。")

    return out[:target]


def generate_questions(cfg, text, subject, level, question_count, fast_mode: bool = False, qtype: str = "single"):
    """確保回傳題目數量 = question_count；mixed 會分層生成再混合。"""
    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]

    n = int(question_count)

    if level == "mixed":
        n_easy = max(1, round(n * 0.4))
        n_med = max(1, round(n * 0.4))
        n_hard = max(1, n - n_easy - n_med)

        a = _fill_to_count(cfg, subject, "easy", n_easy, text, fast_mode)
        b = _fill_to_count(cfg, subject, "medium", n_med, text, fast_mode)
        c = _fill_to_count(cfg, subject, "hard", n_hard, text, fast_mode)

        merged = a + b + c
        random.shuffle(merged)
        merged = merged[:n]

        if len(merged) < n:
            merged = _dedupe(merged + _fill_to_count(cfg, subject, "medium", n - len(merged), text, fast_mode))
            merged = merged[:n]

        # 版式保險：控制(1)-(4)組合題比例
        max_list = max(1, round(n * 0.3))
        list_idx = [i for i, it in enumerate(merged) if _is_list_combo_style(it["question"], it["options"])]
        if len(list_idx) > max_list:
            need = len(list_idx) - max_list
            direct_more = _fill_to_count(cfg, subject, "medium", need, text + "

【補充強制】只可用直接問答版式（禁止(1)~(4)組合題）。", fast_mode)
            for k, idx in enumerate(list_idx[:need]):
                merged[idx] = direct_more[k]

        return merged

    out = _fill_to_count(cfg, subject, level, n, text, fast_mode)

    max_list = max(1, round(n * 0.3))
    list_idx = [i for i, it in enumerate(out) if _is_list_combo_style(it["question"], it["options"])]
    if len(list_idx) > max_list:
        need = len(list_idx) - max_list
        direct_more = _fill_to_count(cfg, subject, level, need, text + "

【補充強制】只可用直接問答版式（禁止(1)~(4)組合題）。", fast_mode)
        for k, idx in enumerate(list_idx[:need]):
            out[idx] = direct_more[k]

    return out
def assist_import_questions(cfg, raw_text, subject, allow_guess=True, fast_mode: bool = False, qtype: str = "single"):
    # ✅ 匯入固定 single
    qtype = "single"

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    raw_text = _clean_text(raw_text)

    raw_text = raw_text[: (8000 if fast_mode else 10000)]

    schema_hint = """
每題必須包含：
- qtype: 固定 "single"
- question: 字串
- options: list（必須 4 個字串）
- correct: list（只含 1 個 "1"~"4"）
- explanation: 字串（若推測答案：必須以「⚠️需教師確認：」開頭）
- needs_review: true/false
"""

    guess_rule = (
        "若原文未提供答案，你必須推測最可能正確答案，但必須 needs_review=true，"
        "並在 explanation 開頭加「⚠️需教師確認：」說明是推測。"
        if allow_guess
        else "若原文未提供答案，correct 設為 ['1'] 並 needs_review=true，explanation 以「⚠️需教師確認：」開頭。"
    )

    temperature = 0.0 if fast_mode else 0.1
    max_tokens = 1600 if fast_mode else 2400
    timeout = 120 if fast_mode else 180  # ✅ 提高，避免 DeepSeek 超時

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
        schema_hint=schema_hint,
    )

    cleaned = []
    for q in items:
        opts = _normalize_options(q.get("options", []), "single")
        corr = _normalize_correct(q.get("correct", []), "single")

        expl = str(q.get("explanation", "")).strip()
        needs_review = bool(q.get("needs_review", False))

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


# -------------------------
# ✅ 本地拆題（支援 A-D + 題幹含(1)(2)…）
# -------------------------
def parse_import_questions_locally(raw_text: str):
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []

    parts = re.split(r"(?:\n(?=\s*(?:\d+\s*[\.、]|Q\d+|第\s*\d+\s*題)))", raw_text, flags=re.IGNORECASE)
    blocks = [p.strip() for p in parts if p.strip()]
    if not blocks:
        blocks = [raw_text]

    opt_pat = re.compile(r"(?m)^\s*(?:\(?([A-D])\)?)[\.\)、\):：]\s*(.+?)\s*$")
    ans_pat = re.compile(r"(?:答案|Answer)\s*[:：]\s*([A-D]|[1-4])", flags=re.IGNORECASE)

    out = []
    for b in blocks:
        text = b.strip()

        m_ans = ans_pat.search(text)
        ans = m_ans.group(1).upper() if m_ans else None

        opts = {"A": "", "B": "", "C": "", "D": ""}
        for m in opt_pat.finditer(text):
            letter = m.group(1).upper()
            content = m.group(2).strip()
            opts[letter] = content

        options = [opts["A"], opts["B"], opts["C"], opts["D"]]
        options = _normalize_options(options, "single")

        qstem = opt_pat.sub("", text)
        qstem = ans_pat.sub("", qstem)
        qstem = qstem.strip()

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
