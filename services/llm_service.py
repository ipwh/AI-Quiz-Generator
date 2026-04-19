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
# 科目特性
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

DEFAULT_TRAITS = "重點：根據教材內容出題，避免離題。"



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
    # true_false 固定兩個選項
    if qtype == "true_false":
        return ["對", "錯", "", ""]

    if not isinstance(opts, list):
        opts = []
    opts = [str(x).strip() for x in opts][:4]
    while len(opts) < 4:
        opts.append("")
    return opts


def _normalize_correct(corr, qtype: str):
    # corr 期望 list[str]，內容為 "1"~"4"
    if isinstance(corr, str):
        # 允許 "1,3" 類型
        parts = [p.strip() for p in corr.split(",") if p.strip()]
        corr = parts
    if not isinstance(corr, list):
        corr = []
    corr = [str(x).strip() for x in corr]
    corr = [c for c in corr if c in {"1", "2", "3", "4"}]

    if qtype == "true_false":
        # 只允許 1 或 2
        corr = [c for c in corr if c in {"1", "2"}]
        return [corr[0]] if corr else ["1"]

    if qtype == "multiple":
        # 多選：至少 1 個，最多 4 個，去重保序
        seen = set()
        out = []
        for c in corr:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out[:4] if out else ["1"]

    # single
    return [corr[0]] if corr else ["1"]


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
    """
    xAI /v1/language-models 會列出 chat 模型並包含 aliases，可用作自動選型。[1](https://zhuanlan.zhihu.com/p/1964739506629490036)
    """
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
    "question": "（示例）根據教材內容，下列哪一項最恰當？",
    "options": ["選項一", "選項二", "選項三", "選項四"],
    "correct": ["2"],
    "explanation": "（極短）因為…",
    "needs_review": false
  }
]
"""


def generate_questions(cfg, text, subject, level, question_count, fast_mode: bool = False, qtype: str = "single"):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    text = _clean_text(text)

    text = text[: (8000 if fast_mode else 10000)]

    schema_hint = """
每題必須包含：
- qtype: "single" / "multiple" / "true_false"
- question: 字串
- options: list（single/multiple 必須 4 個字串；true_false 可只用前 2 個）
- correct:
   - single/true_false: list（只含 1 個字串 "1"~"4"；true_false 只用 1 或 2）
   - multiple: list（可多於 1 個，元素為 "1"~"4"）
- explanation: 字串（建議極短）
- needs_review: true/false
"""

    qtype_rule = ""
    if qtype == "single":
        qtype_rule = "題型固定為 single（四選一單選）。"
    elif qtype == "multiple":
        qtype_rule = "題型固定為 multiple（四選多選），correct 可以有多個答案。"
    else:
        qtype_rule = "題型固定為 true_false（是非題），options 必須是 ['對','錯']（其餘可留空）。"

    temperature = 0.15 if fast_mode else 0.2
    max_tokens = 1400 if fast_mode else 2200
    timeout = 90 if fast_mode else 180

    prompt = f"""
你是一名香港中學教師，熟悉 DSE/校內測驗出題。
科目：{subject}；整體難度：{level}

【科目特性（必須遵守）】
{traits}

【題型】
{qtype_rule}

【出題硬規則】
1) 只生成 {question_count} 條
2) 必須輸出純 JSON array，不要任何額外文字
3) 每題至少包含教材中出現過的 2 個關鍵詞
4) 干擾項要合理（常見誤解）
5) 不足以肯定答案：needs_review=true

【輸出格式示例】
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
        qt = str(q.get("qtype", qtype)).strip() or qtype
        if qt not in {"single", "multiple", "true_false"}:
            qt = qtype

        opts = _normalize_options(q.get("options", []), qt)
        corr = _normalize_correct(q.get("correct", []), qt)

        cleaned.append({
            "qtype": qt,
            "question": str(q.get("question", "")).strip(),
            "options": opts,
            "correct": corr,
            "explanation": str(q.get("explanation", "")).strip()[:80],
            "needs_review": bool(q.get("needs_review", False)),
        })

    return cleaned


def assist_import_questions(cfg, raw_text, subject, allow_guess=True, fast_mode: bool = False, qtype: str = "single"):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    raw_text = _clean_text(raw_text)

    raw_limit = 8000 if fast_mode else 10000
    raw_text = raw_text[:raw_limit]

    schema_hint = """
每題必須包含：
- qtype: "single" / "multiple" / "true_false"
- question: 字串
- options: list（single/multiple 必須 4 個；true_false 可只用前 2 個）
- correct:
   - single/true_false: list（只含 1 個 "1"~"4"；true_false 只用 1 或 2）
   - multiple: list（可多於 1 個，元素為 "1"~"4"）
- explanation: 字串（若推測答案：必須以「⚠️需教師確認：」開頭）
- needs_review: true/false
"""

    guess_rule = (
        "若原文未提供答案，你必須推測最可能正確答案，但必須 needs_review=true，"
        "並在 explanation 開頭加「⚠️需教師確認：」說明是推測。"
        if allow_guess
        else "若原文未提供答案，請 correct 設為 ['1'] 並 needs_review=true，explanation 以「⚠️需教師確認：」開頭。"
    )

    temperature = 0.0 if fast_mode else 0.1
    max_tokens = 2400 if fast_mode else 3400
    timeout = 45 if fast_mode else 90

    qtype_rule = (
        "目標題型為 single（4選1）。" if qtype == "single" else
        "目標題型為 multiple（4選多選，可多於1個正確答案）。" if qtype == "multiple" else
        "目標題型為 true_false（是非題，options 必須是 ['對','錯']）。"
    )

    prompt = f"""
你是一名香港中學教師，正在把現有題目整理成標準格式。
科目：{subject}
{qtype_rule}

【科目特性（參考）】
{traits}

【最重要規則】
- 原文若有答案（例如：答案：B / Answer: 2），必須跟從。
- {guess_rule}
- 無論如何，每題都必須填 correct（不可留空）。

【輸出要求】
- 只輸出純 JSON array，不要任何額外文字。
- options 不足要補空字串到 4 個（true_false 可只用前 2 個，其餘補空）。
- correct 必須以 "1"~"4" 表示（list）。

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
        qt = str(q.get("qtype", qtype)).strip() or qtype
        if qt not in {"single", "multiple", "true_false"}:
            qt = qtype

        opts = _normalize_options(q.get("options", []), qt)
        corr = _normalize_correct(q.get("correct", []), qt)

        expl = str(q.get("explanation", "")).strip()
        needs_review = bool(q.get("needs_review", False))

        # ✅ 如果模型推測但冇寫警告，幫佢補上
        if needs_review and not expl.startswith("⚠️需教師確認："):
            expl = "⚠️需教師確認：" + (expl if expl else "系統推測答案，請老師核對。")

        cleaned.append({
            "qtype": qt,
            "question": str(q.get("question", "")).strip(),
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
        out.append({
            "qtype": "single",
            "question": b,
            "options": ["", "", "", ""],
            "correct": [correct_num],
            "explanation": "",
            "needs_review": needs_review,
        })
    return out
