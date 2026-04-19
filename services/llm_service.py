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
DEFAULT_TRAITS = "重點：根據提供內容出題，避免離題。"


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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

    return [corr[0]] if corr else ["1"]


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
import requests

def xai_pick_vision_model(api_key: str, base_url: str = "https://api.x.ai/v1", timeout: int = 15) -> str | None:
    """
    從 xAI /v1/language-models 中挑一個支援 image 的模型。
    /v1/language-models 會列出可用語言模型，並包含 input_modalities / aliases 等資訊。[3](https://cameledge.com/post/llm/mcq)
    回傳 model id 或 alias；若找不到則回傳 None。
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

        # 先嘗試用 alias（較穩），再用 id
        # 只要 input_modalities 包含 "image" 就視作 vision model
        candidates = []
        for m in models:
            if not isinstance(m, dict):
                continue
            input_mods = m.get("input_modalities") or []
            if isinstance(input_mods, list) and "image" in input_mods:
                created = m.get("created", 0) or 0
                mid = str(m.get("id", "") or "")
                aliases = m.get("aliases") or []
                # 優先用 alias 中帶 latest 的（如果有）
                alias_latest = None
                if isinstance(aliases, list):
                    for a in aliases:
                        if isinstance(a, str) and a.endswith("-latest"):
                            alias_latest = a
                            break
                candidates.append((created, alias_latest or mid))

        if not candidates:
            return None

        # 取 created 最新的一個
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    except Exception:
        return None


def generate_questions_from_images(cfg: dict, images_data_urls: list[str], subject: str, level: str,
                                   question_count: int, fast_mode: bool = False, qtype: str = "single"):
    """
    Vision fallback：直接把圖片交給多模態 LLM（Grok）讀圖出題。
    xAI chat completions /v1/chat/completions 支援 text/image chat prompts。[1](https://www.aidoczh.com/streamlit/develop/concepts/connections/secrets-management.html)[2](https://blog.csdn.net/gitblog_00250/article/details/142274805)
    """
    if qtype not in {"single", "true_false"}:
        qtype = "single"

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)

    banned = "教材、教材中、根據教材、根據以上資料、文中提及、上文提到、資料顯示"
    if qtype == "true_false":
        qtype_rules = """
【題型】是非題（true_false）
- options 固定為：["對","錯"]（其餘留空）
- 題幹必須是一句可判斷對/錯的陳述句（避免問句）
- correct 只可 ["1"] 或 ["2"]
"""
        fewshot = """
[
  {"qtype":"true_false","question":"光合作用會產生氧氣。","options":["對","錯","",""],"correct":["1"],"explanation":"","needs_review":false}
]
"""
    else:
        qtype_rules = """
【題型】多項選擇題（四選一 single）
- options 必須 4 個
- correct 必須 ["1"~"4"]（只 1 個）
"""
        fewshot = """
[
  {"qtype":"single","question":"以下哪一項正確？","options":["A","B","C","D"],"correct":["2"],"explanation":"","needs_review":false}
]
"""

    prompt_text = f"""
你是一名香港中學教師，負責出校內測驗題。
科目：{subject}；難度：{level}

【科目特性（必須遵守）】
{traits}

【題幹規則（必須遵守）】
- 題幹要直接、簡潔。
- 禁止出現：{banned}
- 不要用「根據…」開頭。

{qtype_rules}

【輸出要求】
- 只輸出純 JSON array，不要任何額外文字。
- 只生成 {question_count} 題
- qtype 固定為 "{qtype}"
- 若圖片資訊不完整：needs_review=true，但仍要給出最可能答案

【格式示例】
{fewshot}

請根據以下圖片內容出題（你需要先理解圖片文字/圖表/題目內容，再輸出題目JSON）。
"""

    # OpenAI-compatible 多模態 message content（text + image_url）
    content = [{"type": "text", "text": prompt_text}]
    for url in images_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    temperature = 0.1 if fast_mode else 0.2
    max_tokens = 1600 if fast_mode else 2600
    timeout = 120 if fast_mode else 180

    out = _chat(
        cfg,
        messages=[{"role": "user", "content": content}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    items = extract_json(out)

    cleaned = []
    for q in items:
        qt = qtype  # 強制題型
        opts = _normalize_options(q.get("options", []), qt)
        corr = _normalize_correct(q.get("correct", []), qt)

        question = str(q.get("question", "")).strip()
        question = _strip_boilerplate_question(question)  # 你之前已有

        cleaned.append({
            "qtype": qt,
            "question": question,
            "options": opts,
            "correct": corr,
            "explanation": str(q.get("explanation", "")).strip()[:60],
            "needs_review": bool(q.get("needs_review", False)),
        })

    return cleaned

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


def _strip_boilerplate_question(q: str) -> str:
    """刪走題幹開頭常見套話（雙保險）。"""
    if not q:
        return q
    s = q.strip()

    # 刪除各種「根據/教材/文中/資料」開頭的套話（只針對開頭）
    patterns = [
        r"^(根據|依據|參考).{0,12}(教材|內容|資料|文本|上文|文中).{0,12}，?",
        r"^(教材|內容|資料|文本|上文|文中).{0,12}(提及|出現|指出|提到).{0,12}，?",
        r"^根據.{0,12}，?",
        r"^以下.{0,12}(教材|內容|資料|文本).{0,12}，?",
    ]
    for p in patterns:
        s = re.sub(p, "", s).strip()

    # 再清一次開頭逗號/冒號
    s = re.sub(r"^[,，:：\-\s]+", "", s).strip()
    return s


def _difficulty_guidance(level_code: str) -> str:def _difficulty_guidance(level_code: str level_code == "easy":
        return (
            "【Easy 基礎】\n"
            "- 題目重點：定義/關鍵詞辨識/直接理解。\n"
            "- 不可：跨段推論、多步推理、計算鏈。\n"
            "- 干擾項：明顯錯或典型誤解，但不要太接近正確答案。"
        )
    if level_code == "medium":
        return (
            "【Medium 標準】\n"
            "- 題目重點：情境應用、把概念套落例子、一步推論。\n"
            "- 可：用短情境（1~2句）要求判斷。\n"
            "- 干擾項：接近正確但在概念/條件上差一點（常見混淆）。"
        )
    if level_code == "hard":
        return (
            "【Hard 進階】\n"
            "- 題目重點：分析/比較/判斷（至少2步推理）。\n"
            "- 可：對立概念辨析、因果判斷、限制條件推論。\n"
            "- 干擾項：非常接近、以常見混淆點設陷（例如因果倒置/忽略限制）。"
        )
    return (
        "【Mixed 混合】\n"
        "- 必須同時包含 easy/medium/hard 三類題目（比例由系統分配）。\n"
        "- 題幹形式也要混合（直接問答為主，少量使用(1)-(4)資料題）。"
    )


def _build_prompt(subject: str, traits: str, qtype: str, level_code: str, count: int, text: str) -> str:
    banned = "教材、教材中、根據教材、根據以上資料、文中提及、上文提到、資料顯示、教材中出現、教材中提及"
    difficulty_spec = _difficulty_guidance(level_code)

    common = f"""
你是一名香港中學教師，負責出校內測驗題。
科目：{subject}

【難度規格（必須嚴格遵守）】
{difficulty_spec}

【科目特性（必須遵守）】
{traits}

【題幹規則（必須遵守）】
- 題幹要直接、簡潔。
- 禁止出現：{banned}
- 不要用「根據…」開頭句式。
"""

    if qtype == "true_false":
        qtype_rules = f"""
【題型】是非題（true_false）
- options 固定為：["對","錯"]（其餘留空）
- 題幹必須是一句可判斷對/錯的陳述句（避免問句）
"""
        schema = f"""
【輸出要求】
- 只輸出純 JSON array
- 只生成 {count} 題
- qtype 固定為 "true_false"
- options 必須是 ["對","錯","",""]
- correct 只可 ["1"] 或 ["2"]
"""
        fewshot = """
[
  {"qtype":"true_false","question":"YouTube 屬於新媒體。","options":["對","錯","",""],"correct":["1"],"explanation":"","needs_review":false}
]
"""
    else:
        # ✅ 版式配額：直接問答為主，限制 (1)-(4) 組合題比例
        max_list = max(1, round(count * 0.3))
        min_direct = count - max_list

        qtype_rules = f"""
【題型】多項選擇題（四選一 single）
【版式配額（必須遵守）】
- 至少 {min_direct} 題必須使用「直接問答」：題幹 + A~D（四個純選項，不要(1)~(4)組合題）。
- 最多 {max_list} 題可使用「資料題」：題幹 + (1)~(4) + A~D（選項是(1)~(4)組合）。
- 請把兩種版式混合，不要集中使用同一模板。
"""
        schema = f"""
【輸出要求】
- 只輸出純 JSON array
- 只生成 {count} 題
- qtype 固定為 "single"
- options 必須剛好 4 個
- correct 必須是 ["1"~"4"]（只 1 個）
"""
        fewshot = """
[
  {"qtype":"single","question":"下列哪一項不是媒體資訊帶來的效益？","options":["A選項","B選項","C選項","D選項"],"correct":["1"],"explanation":"","needs_review":false}
]
"""

    extra = """
【貼題要求】
- 題幹或選項必須包含提供內容中出現過的至少 2 個關鍵詞。
- 若資訊不足：needs_review=true，但仍要給出最可能答案。
"""

    return f"""{common}
{qtype_rules}
{schema}
{extra}

【格式示例】
{fewshot}

【提供內容】
{text}
"""


def _is_list_combo_style(q: str, options: list) -> bool:
    # 粗略判斷：題幹含 (1) 且選項含「只有（」/「以上皆是」/「（1）」等組合語
    if not q:
        return False
    q_has = ("(1)" in q) or ("（1）" in q)
    opt_text = " ".join([str(o) for o in (options or [])])
    opt_has = ("只有" in opt_text) or ("以上皆是" in opt_text) or ("（1）" in opt_text) or ("(1)" in opt_text)
    return q_has and opt_has


def _generate_batch(cfg, text, subject, level_code, count, fast_mode, qtype):
    if count <= 0:
        return []

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)

    temperature = 0.15 if fast_mode else 0.2
    max_tokens = 900 if qtype == "true_false" else (1400 if fast_mode else 2200)
    timeout = 90 if fast_mode else 180

    prompt = _build_prompt(subject, traits, qtype, level_code, count, text)
    items = _call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        schema_hint="JSON array",
    )

    cleaned = []
    for q in items:
        qt = qtype
        opts = _normalize_options(q.get("options", []), qt)
        corr = _normalize_correct(q.get("correct", []), qt)
        question = _strip_boilerplate_question(str(q.get("question", "")).strip())

        cleaned.append({
            "qtype": qt,
            "question": question,
            "options": opts,
            "correct": corr,
            "explanation": str(q.get("explanation", "")).strip()[:60],
            "needs_review": bool(q.get("needs_review", False)),
        })

    # ✅ single 題：再做一次「版式比例」檢查，必要時補回直接問答題
    if qtype == "single" and count >= 4:
        max_list = max(1, round(count * 0.3))
        list_idx = [i for i, it in enumerate(cleaned) if _is_list_combo_style(it["question"], it["options"])]
        if len(list_idx) > max_list:
            need = len(list_idx) - max_list

            # 用「直接問答」補題：在 prompt 加一句硬性要求只出直接問答
            direct_prompt = prompt + "\n\n【補充強制】接下來只可用「直接問答」版式：題幹 + A~D（禁止(1)~(4)列表/組合題）。\n"
            more = _call_with_retries(
                cfg,
                messages=[{"role": "user", "content": direct_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                schema_hint="JSON array",
            )

            direct_items = []
            for q2 in more:
                opts2 = _normalize_options(q2.get("options", []), "single")
                corr2 = _normalize_correct(q2.get("correct", []), "single")
                question2 = _strip_boilerplate_question(str(q2.get("question", "")).strip())
                direct_items.append({
                    "qtype": "single",
                    "question": question2,
                    "options": opts2,
                    "correct": corr2,
                    "explanation": str(q2.get("explanation", "")).strip()[:60],
                    "needs_review": bool(q2.get("needs_review", False)),
                })

            # 替換超標的組合題（只替換 need 題）
            replace_targets = list_idx[:need]
            for k, idx in enumerate(replace_targets):
                if k < len(direct_items):
                    cleaned[idx] = direct_items[k]

    return cleaned


def generate_questions(cfg, text, subject, level, question_count, fast_mode: bool = False, qtype: str = "single"):
    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]

    if qtype not in {"single", "true_false"}:
        qtype = "single"

    if level == "mixed":
        n = int(question_count)
        n_easy = max(1, round(n * 0.4))
        n_med = max(1, round(n * 0.4))
        n_hard = max(1, n - n_easy - n_med)

        batch = []
        batch += _generate_batch(cfg, text, subject, "easy", n_easy, fast_mode, qtype)
        batch += _generate_batch(cfg, text, subject, "medium", n_med, fast_mode, qtype)
        batch += _generate_batch(cfg, text, subject, "hard", n_hard, fast_mode, qtype)

        random.shuffle(batch)
        return batch[:n]

    return _generate_batch(cfg, text, subject, level, int(question_count), fast_mode, qtype)
def generate_questions_from_images(cfg, images_data_urls, subject, level, question_count, fast_mode: bool = False, qtype: str = "single"):
    """
    Vision fallback：直接把圖片交給多模態 LLM，要求它讀圖並輸出題目 JSON。
    images_data_urls: ["data:image/png;base64,...", ...]
    """
    if qtype not in {"single", "true_false"}:
        qtype = "single"

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)

    # 針對你要求：題幹簡潔，禁用「教材/根據」套話
    banned = "教材、教材中、教材內、教材出現、教材提及、根據教材、根據以上資料、文中提及、上文提到、資料顯示"

    if qtype == "true_false":
        qtype_rules = """
【題型】是非題（true_false）
- options 固定為：["對","錯"]（其餘留空）
- 題幹必須是一句可判斷對/錯的陳述句（避免問句）
- correct 只可 ["1"] 或 ["2"]
"""
        fewshot = """
[
  {"qtype":"true_false","question":"物體在真空中不受空氣阻力影響。","options":["對","錯","",""],"correct":["1"],"explanation":"","needs_review":false}
]
"""
    else:
        qtype_rules = """
【題型】多項選擇題（四選一 single）
- options 必須 4 個
- correct 必須 ["1"~"4"]（只 1 個）
"""
        fewshot = """
[
  {"qtype":"single","question":"以下哪一項最符合題目？","options":["A","B","C","D"],"correct":["2"],"explanation":"","needs_review":false}
]
"""

    schema = f"""
【輸出要求】
- 只輸出純 JSON array，不要任何額外文字
- 只生成 {question_count} 題
- qtype 固定為 "{qtype}"
- 題幹要直接、簡潔，禁止出現：{banned}
- 若圖片資訊不完整：needs_review=true，但仍要給出最可能答案
"""

    prompt_text = f"""
你是一名香港中學教師，負責出校內測驗題。
科目：{subject}；難度：{level}

【科目特性（必須遵守）】
{traits}

【題幹規則】
- 題幹要直接、簡潔，不要使用「根據…」「教材…」等套話。

{qtype_rules}
{schema}

【格式示例】
{fewshot}

現在請根據以下圖片內容出題（你需要先理解圖片文字/圖表/題目內容，然後輸出題目JSON）。
"""

    # 組合多模態 messages（OpenAI-compatible image_url）
    content = [{"type": "text", "text": prompt_text}]
    for url in images_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    temperature = 0.1 if fast_mode else 0.2
    max_tokens = 1600 if fast_mode else 2600
    timeout = 120 if fast_mode else 180

    out = _chat(
        cfg,
        messages=[{"role": "user", "content": content}],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    items = extract_json(out)

    cleaned = []
    for q in items:
        qt = qtype  # 強制用選定題型
        opts = _normalize_options(q.get("options", []), qt)
        corr = _normalize_correct(q.get("correct", []), qt)

        question = str(q.get("question", "")).strip()
        # 再次保險：刪除開頭套話
        question = _strip_boilerplate_question(question)

        cleaned.append({
            "qtype": qt,
            "question": question,
            "options": opts,
            "correct": corr,
            "explanation": str(q.get("explanation", "")).strip()[:60],
            "needs_review": bool(q.get("needs_review", False)),
        })

    return cleaned

# ---- 匯入：固定 single（保持現狀）----
def assist_import_questions(cfg, raw_text, subject, allow_guess=True, fast_mode: bool = False, qtype: str = "single"):
    qtype = "single"
    raw_text = _clean_text(raw_text)[: (8000 if fast_mode else 10000)]

    guess_rule = "若原文未提供答案，你必須推測最可能正確答案，但 needs_review=true，explanation 以「⚠️需教師確認：」開頭。"

    temperature = 0.0 if fast_mode else 0.1
    max_tokens = 1600 if fast_mode else 2400
    timeout = 120 if fast_mode else 180

    prompt = f"""
你是一名香港中學教師，正在把現有題目整理成標準格式。
科目：{subject}
目標題型：single（4選1）

【規則】
- 原文若有答案必須跟從。
- {guess_rule}
- 每題都必須填 correct（不可留空）。

【輸出】
只輸出純 JSON array，不要任何額外文字。
每題 options 必須 4 個，correct 必須 ["1"~"4"]（只 1 個）。

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
    for q in items:
        opts = _normalize_options(q.get("options", []), "single")
        corr = _normalize_correct(q.get("correct", []), "single")

        expl = str(q.get("explanation", "")).strip()
        needs_review = bool(q.get("needs_review", False))
        if needs_review and not expl.startswith("⚠️需教師確認："):
            expl = "⚠️需教師確認：" + (expl if expl else "系統推測答案，請老師核對。")

        cleaned.append({
            "qtype": "single",
            "question": _strip_boilerplate_question(str(q.get("question", "")).strip()),
            "options": opts,
            "correct": corr,
            "explanation": expl[:120],
            "needs_review": needs_review,
        })

    return cleaned


def parse_import_questions_locally(raw_text: str):
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []

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
            "question": _strip_boilerplate_question(qstem),
            "options": options,
            "correct": [correct_num],
            "explanation": expl,
            "needs_review": needs_review,
        })

    return out
