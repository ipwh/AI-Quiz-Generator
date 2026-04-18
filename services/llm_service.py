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
# 科目特性（同你已用緊的版本）
# -------------------------
SUBJECT_TRAITS = {
    "中國語文": (
        "重點：以『讀寫聽說』為主導，帶動文學、中華文化、品德情意、思維、語文自學九大範疇；"
        "出題同時兼顧工具性（語文運用）與人文性（思想、文化、審美）。"
        "題型：閱讀主旨/段意/寫作手法、語境推斷、語體得體、文學感受→鑒賞。"
        "干擾項：只看字面忽略語境、混淆作者/敘述者觀點、把描寫當論證、以偏概全、忽略轉折承接。"
        "用語：『細讀文本』『誦讀/背誦』『文道並重』『慎思明辨』『語文自學』『文化認識/反思/認同』等。"
    ),
    "英國語文": (
        "Focus: reading comprehension, inference, tone/purpose, vocabulary in context, grammar usage. "
        "Distractors: near-synonym traps, extreme options."
    ),
    "數學": "重點：概念+運算、步驟正確性、圖像/表格解讀、公式應用。干擾項：公式套錯、單位/符號錯、概念混淆。",
    "公民與社會發展": "重點：概念辨析、情境應用、因果關係。干擾項：概念混淆、因果倒置、以偏概全。",
    "公民、經濟及社會": (
        "重點：三大範疇——（1）個人與群性發展；（2）資源與經濟活動；（3）社會體系與公民精神。"
        "題型：情境題、數據/表格解讀、概念辨析、因果與利弊分析。"
        "干擾項：因果倒置、權利vs義務、公平vs公義、需要vs想要混淆、忽略數據趨勢。"
    ),
    "公民、經濟與社會": "重點同「公民、經濟及社會」。",
    "科學": (
        "重點：主題式設計，涵蓋生命與生活、物料世界、能量與變化、地球與太空；強調 STSE 與 STEM。"
        "統一概念：系統和組織、證據和模型、變化和恆常、形態與功能。"
        "探究技能：問題/假說、辨識變量、公平測試、量度、圖表、推論與結論、科學語言。"
        "干擾項：把相關性當因果、混淆變量、忽略公平測試、忽略誤差與安全守則。"
    ),
    "物理": "重點：定律應用、方向性、單位、圖像解讀。干擾項：方向/符號、把速度當加速度。",
    "化學": "重點：粒子模型、方程式、酸鹼/氧化還原、實驗觀察。干擾項：配平錯、概念混淆。",
    "生物": "重點：結構與功能、恆常性、遺傳、生態互動。干擾項：器官功能混淆、相關性當因果。",
    "資訊及通訊科技（ICT）": (
        "重點：資訊處理 + 系統基礎 + 互聯網與保安 + 計算思維/程式 + 社會影響（道德/法律）。"
        "題型：進制轉換、字符編碼、試算表/DBMS/SQL、TCP/IP、DNS、HTTP/HTTPS、除錯、知識產權/私隱/網安。"
        "干擾項：RAM/ROM/Cache 混用、HTTP vs HTTPS 誤解、ASCII vs Unicode 混淆、SQL鍵/冗餘/正規化混亂。"
    ),
    "地理": (
        "重點：空間、地方、區域、人地互動、全球相互依存、可持續發展；題型含地圖/圖表/實地考察/GIS。"
        "干擾項：把描述當解釋、因果倒置、忽略尺度、地圖比例/方向/圖例誤讀。"
    ),
    "歷史": (
        "重點：時序、因果、轉變與延續、史料為本、多角度詮釋、證據支持結論、同理心與持平判斷。"
        "干擾項：事實/見解不分、單因論、忽略時空背景、只背結論不引用證據。"
    ),
    "中國歷史": (
        "重點：時序脈絡、因果、史料分析、香港與國家關係；干擾項：年代混淆、張冠李戴、把結果當原因。"
    ),
    "經濟": (
        "重點：實證+規範；供需/彈性/盈餘/干預/效率公平；GDP/物價/失業、AD-AS、貨幣與銀行；比較優勢。"
        "干擾項：稀少性≠短缺；需求改變≠需求量改變；效率≠公平；GDP≠福利；比較優勢≠絕對優勢。"
    ),
    "企業、會計與財務概論": (
        "重點：營商環境、管理功能、會計循環與報表、財務/個人理財、道德與社會責任。"
        "干擾項：收入/利潤/現金流混淆、比率誤用、成本分類錯、忽略持份者。"
    ),
    "企業、會計及財務概論": "重點同「企業、會計與財務概論」。",
    "旅遊與款待": (
        "重點：行業體系、分銷途徑、產品生命週期、承載力、影響評估、RATER/GAP、服務補救、可持續發展。"
        "干擾項：概念混淆（承載力/PLC/RATER/GAP）、只講經濟忽略社會文化/環境。"
    ),
    "宗教": (
        "【天主教用字硬規則】\n"
        "必用：天主、伯多祿、聖母瑪利亞、教宗/主教/神父、教友。\n"
        "避免：上帝、神、彼得、牧師、長老、傳道、基督徒（作天主教內部稱呼）。\n"
    ),
}

DEFAULT_TRAITS = "重點：根據教材內容出題，避免離題。干擾項：以常見誤解作干擾。"


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


def _normalize_options(opts):
    if not isinstance(opts, list):
        opts = []
    opts = [str(x).strip() for x in opts][:4]
    while len(opts) < 4:
        opts.append("")
    return opts


def _normalize_correct(corr):
    if isinstance(corr, str):
        corr = [corr]
    if not isinstance(corr, list):
        corr = []
    corr = [str(x).strip() for x in corr if str(x).strip().isdigit()]
    corr = [c for c in corr if c in {"1", "2", "3", "4"}]
    if not corr:
        corr = ["1"]
    return [corr[0]]


def _prefix_review_warning(expl: str) -> str:
    expl = (expl or "").strip()
    if expl.startswith("⚠️需教師確認"):
        return expl
    return "⚠️需教師確認：" + (expl if expl else "系統推測答案，請老師核對。")


_CATHOLIC_REPLACE = [
    (r"\b彼得\b", "伯多祿"),
    (r"\b上帝\b", "天主"),
    (r"\b神\b", "天主"),
    (r"\b馬利亞\b", "聖母瑪利亞"),
    (r"\b基督徒\b", "教友"),
]
_CATHOLIC_FLAG_ONLY = ["牧師", "長老", "傳道", "傳道人", "會眾", "敬拜讚美"]


def _apply_catholic_terms(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, repl in _CATHOLIC_REPLACE:
        out = re.sub(pattern, repl, out)
    return out


def _contains_flag_terms(text: str) -> bool:
    if not text:
        return False
    return any(t in text for t in _CATHOLIC_FLAG_ONLY)


def _enforce_catholic_language(item: dict) -> dict:
    q = str(item.get("question", "") or "")
    exp = str(item.get("explanation", "") or "")
    opts = item.get("options", [])
    if not isinstance(opts, list):
        opts = []

    q2 = _apply_catholic_terms(q)
    exp2 = _apply_catholic_terms(exp)
    opts2 = [_apply_catholic_terms(str(o or "")) for o in opts]

    flagged = _contains_flag_terms(q2) or _contains_flag_terms(exp2) or any(_contains_flag_terms(o) for o in opts2)
    needs_review = bool(item.get("needs_review", False)) or flagged

    if flagged:
        exp2 = _prefix_review_warning("用字可能出現非天主教版本稱謂/概念，請老師核對。 " + exp2)

    item["question"] = q2.strip()
    item["explanation"] = exp2.strip()
    item["options"] = opts2[:4] + [""] * (4 - len(opts2[:4]))
    item["needs_review"] = needs_review
    return item


def _post_openai_compat(api_key: str, base_url: str, payload: dict, timeout: int = 90, max_retries: int = 5):
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


def _post_azure(api_key: str, endpoint: str, deployment: str, api_version: str, payload: dict, timeout: int = 90, max_retries: int = 3):
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
# ✅ 新增：一鍵測試 API 用（極短 prompt）
# -------------------------
def ping_llm(cfg: dict, timeout: int = 25):
    """
    回傳 dict:
      - ok: bool
      - latency_ms: int
      - output: str
      - error: str
    """
    t0 = time.time()
    try:
        out = _chat(
            cfg,
            messages=[{"role": "user", "content": "回覆 OK"}],
            temperature=0.0,
            max_tokens=10,
            timeout=timeout,
        )
        ms = int((time.time() - t0) * 1000)
        return {"ok": True, "latency_ms": ms, "output": (out or "").strip(), "error": ""}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"ok": False, "latency_ms": ms, "output": "", "error": repr(e)}


def _fix_json(cfg: dict, bad_output: str, schema_hint: str, timeout: int):
    prompt = f"""
你剛才輸出不是有效 JSON 或格式不符合要求。
請只回覆「純 JSON array」，不要任何解釋文字。

必須符合此 schema：
{schema_hint}

以下是你剛才的輸出（供修正）：
{bad_output}
"""
    return _chat(cfg, [{"role": "user", "content": prompt}], temperature=0, max_tokens=2500, timeout=timeout)


def _call_with_retries(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int, schema_hint: str):
    out = _chat(cfg, messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
    try:
        return extract_json(out)
    except Exception:
        out2 = _fix_json(cfg, out, schema_hint=schema_hint, timeout=timeout)
        return extract_json(out2)


_FEWSHOT = """
示例（只示範格式，不要照抄內容）：
[
  {
    "type": "single",
    "question": "（示例）根據教材內容，下列哪一項最恰當？",
    "options": ["選項一", "選項二", "選項三", "選項四"],
    "correct": ["2"],
    "explanation": "（極短）因為…",
    "needs_review": false
  }
]
"""


def generate_questions(cfg, text, subject, level, question_count, fast_mode: bool = False):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    text = _clean_text(text)

    text_limit = 2600 if fast_mode else 5000
    text = text[:text_limit]

    schema_hint = """
每題必須包含：
- type: 固定 "single"
- question: 字串
- options: list（必須 4 個字串）
- correct: list（只含 1 個字串 "1"~"4"）
- explanation: 字串（建議極短，不超過 20 字）
- needs_review: true/false
"""

    temperature = 0.15 if fast_mode else 0.2
    max_tokens = 1200 if fast_mode else 1800
    timeout = 90 if fast_mode else 180

    catholic_hard_rule = ""
    if subject == "宗教":
        catholic_hard_rule = """
【天主教用字硬規則（再次強調）】
- 嚴禁：彼得、上帝、神、馬利亞（敬禮語境用單稱）、牧師、長老、傳道、基督徒（作天主教內部稱呼）
- 必須：伯多祿、天主、聖母瑪利亞、教宗/主教/神父、教友
- 若不確定用字：needs_review=true，explanation 以「⚠️需教師確認：」開頭
"""

    prompt = f"""
你是一名香港中學教師，熟悉 DSE/校內測驗出題。
科目：{subject}；整體難度：{level}

【科目特性（必須遵守）】
{traits}

{catholic_hard_rule}

【出題硬規則】
1) 只生成 {question_count} 條「單選題（4選1）」
2) options 必須剛好 4 個
3) correct 必須是 ["1"~"4"]（只 1 個）
4) 每題 question 或 explanation 必須包含教材中出現過的至少 2 個關鍵詞（貼題）
5) 干擾項要合理：基於常見誤解/混淆點，避免無關選項
6) 若教材資訊不足令答案不肯定：needs_review=true，explanation 以「⚠️需教師確認：」開頭

【輸出】
只輸出「純 JSON array」，不要任何額外文字。

{_FEWSHOT}

【教材內容】
{text}
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
        opts = _normalize_options(q.get("options", []))
        corr = _normalize_correct(q.get("correct", []))
        needs_review = bool(q.get("needs_review", False))
        expl = str(q.get("explanation", "")).strip()

        if len(expl) > 40:
            expl = expl[:40]
        if needs_review:
            expl = _prefix_review_warning(expl)

        item = {
            "type": "single",
            "question": str(q.get("question", "")).strip(),
            "options": opts,
            "correct": corr,
            "explanation": expl,
            "needs_review": needs_review,
        }

        if subject == "宗教":
            item = _enforce_catholic_language(item)

        cleaned.append(item)

    return cleaned


def assist_import_questions(cfg, raw_text, subject, allow_guess=True, fast_mode: bool = False):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    raw_text = _clean_text(raw_text)

    raw_limit = 3500 if fast_mode else 7000
    raw_text = raw_text[:raw_limit]

    schema_hint = """
每題必須包含：
- type: 固定 "single"
- question: 字串
- options: list（必須 4 個字串）
- correct: list（只含 1 個字串 "1"~"4"）
- explanation: 字串（needs_review=true 時以 ⚠️需教師確認： 開頭）
- needs_review: true/false
"""

    temperature = 0.0 if fast_mode else 0.1
    max_tokens = 2200 if fast_mode else 3000
    timeout = 45 if fast_mode else 90

    guess_rule = (
        "若原文未提供答案，你可以推測最可能正確答案，但必須 needs_review=true，並在 explanation 開頭加「⚠️需教師確認：」。"
        if allow_guess
        else "若原文未提供答案，請 correct 設為 ['1'] 並 needs_review=true。"
    )

    catholic_hard_rule = ""
    if subject == "宗教":
        catholic_hard_rule = """
【天主教用字硬規則（再次強調）】
- 嚴禁：彼得、上帝、神、馬利亞（敬禮語境用單稱）、牧師、長老、傳道、基督徒（作天主教內部稱呼）
- 必須：伯多祿、天主、聖母瑪利亞、教宗/主教/神父、教友
"""

    prompt = f"""
你是一名香港中學教師，正在把現有選擇題整理成標準格式。
科目：{subject}

【科目特性】
{traits}

{catholic_hard_rule}

【最重要規則】
- 原文若有答案（例如：答案：B / Answer: 2），必須跟從。
- {guess_rule}

【輸出要求】
- 只輸出純 JSON array
- 每題必須 4 選項（不足補空字串）
- correct 只可 "1"~"4"（list 只有 1 個）
- needs_review：推測/不肯定時 true

{_FEWSHOT}

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
        opts = _normalize_options(q.get("options", []))
        corr = _normalize_correct(q.get("correct", []))
        needs_review = bool(q.get("needs_review", False))
        expl = str(q.get("explanation", "")).strip()

        if needs_review:
            expl = _prefix_review_warning(expl)

        item = {
            "type": "single",
            "question": str(q.get("question", "")).strip(),
            "options": opts,
            "correct": corr,
            "explanation": expl[:60],
            "needs_review": needs_review,
        }

        if subject == "宗教":
            item = _enforce_catholic_language(item)

        cleaned.append(item)

    return cleaned


def parse_import_questions_locally(raw_text: str):
    raw_text = _clean_text(raw_text)
    if not raw_text:
        return []

    parts = re.split(r"(?:\n(?=\s*(?:\d+\s*[\.、]|Q\d+|第\s*\d+\s*題)))", raw_text, flags=re.IGNORECASE)
    blocks = [p.strip() for p in parts if p.strip()]
    out = []

    for b in blocks:
        m_ans = re.search(r"(?:答案|Answer)\s*[:：]\s*([A-D]|[1-4])", b, flags=re.IGNORECASE)
        ans = m_ans.group(1).upper() if m_ans else None
        correct_num = "1"
        needs_review = False

        if ans:
            correct_num = ans if ans.isdigit() else str(ord(ans) - ord("A") + 1)
        else:
            needs_review = True

        optA = re.search(r"(?:\n|\r|\A)\s*(?:A[\.\)、\)]|\(A\))\s*(.+)", b)
        optB = re.search(r"(?:\n|\r|\A)\s*(?:B[\.\)、\)]|\(B\))\s*(.+)", b)
        optC = re.search(r"(?:\n|\r|\A)\s*(?:C[\.\)、\)]|\(C\))\s*(.+)", b)
        optD = re.search(r"(?:\n|\r|\A)\s*(?:D[\.\)、\)]|\(D\))\s*(.+)", b)

        options = [
            optA.group(1).strip() if optA else "",
            optB.group(1).strip() if optB else "",
            optC.group(1).strip() if optC else "",
            optD.group(1).strip() if optD else "",
        ]
        options = _normalize_options(options)

        qstem = re.sub(r"(?:答案|Answer)\s*[:：]\s*([A-D]|[1-4]).*", "", b, flags=re.IGNORECASE).strip()
        qstem = re.sub(r"(?m)^\s*(?:[A-D][\.\)、\)]|\([A-D]\))\s*.+$", "", qstem).strip()

        expl = "⚠️需教師確認：未找到答案，請老師核對。" if needs_review else ""

        out.append({
            "type": "single",
            "question": qstem,
            "options": options,
            "correct": [correct_num],
            "explanation": expl,
            "needs_review": needs_review,
        })

    return out
