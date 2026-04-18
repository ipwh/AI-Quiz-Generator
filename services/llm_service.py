import json
import re
import time
import requests

# -------------------------
# 全域 Session（Keep-Alive 加快連線）
# -------------------------
_SESSION = requests.Session()

# -------------------------
# 科目特性（可按校本再擴充）
# -------------------------
SUBJECT_TRAITS = {
    "中國語文": "重點：篇章理解、修辭手法、語境推斷、段落主旨、作者態度。干擾項：以偏概全、張冠李戴、偷換概念。",
    "英國語文": "Focus: reading comprehension, inference, tone/purpose, vocabulary in context, grammar usage. Distractors: near-synonym traps, extreme options.",
    "數學": "重點：概念+運算、步驟正確性、圖像/表格解讀、公式應用。干擾項：公式套錯、單位/符號錯、概念混淆。",
    "公民與社會發展": "重點：概念辨析、情境應用、因果關係。干擾項：概念混淆、因果倒置、以偏概全。",
    "科學": "重點：核心概念+生活情境應用、變因控制。干擾項：把相關性當因果、混淆變因。",
    "物理": "重點：定律應用、方向性、單位、圖像解讀。干擾項：方向/符號、把速度當加速度。",
    "化學": "重點：粒子模型、方程式、酸鹼/氧化還原、實驗觀察。干擾項：配平錯、概念混淆。",
    "生物": "重點：結構與功能、恆常性、遺傳、生態互動。干擾項：器官功能混淆、相關性當因果。",
    "資訊及通訊科技（ICT）": "重點：實務應用（資料處理/試算表/網絡/安全/系統開發）。干擾項：忽略私隱/保安、概念混用。",
    "地理": "重點：地圖/圖表解讀、成因+影響、案例應用。干擾項：把描述當解釋、忽略尺度。",
    "歷史": "重點：史料解讀、時序因果、證據支持。干擾項：年代混淆、單因解釋多因現象。",
    "經濟": "重點：供求/彈性/成本收益/政策影響、圖表。干擾項：短期長期混、名義與實質混淆。",
# ===== 新增：公民、經濟與社會（中一至中三）=====
    "公民、經濟與社會": (
        "重點：按初中課程三大範疇出題——"
        "（1）個人與群性發展：自我認識、情緒與生活技能、健康生活、人際關係、多元共融；"
        "（2）資源與經濟活動：理財教育、金錢價值觀、公共財政、經濟表現指標與趨勢（如GDP/失業/通脹等）;"
        "（3）社會體系與公民精神：權利與義務、法治、憲法與基本法、國家安全、國民身份、全球互依與合作。"
        "題型：情境題、數據/表格解讀、概念辨析、因果與利弊分析。"
        "干擾項：把描述當解釋、因果倒置、概念混淆（權利vs義務、公平vs公義、公共資源vs私人資源、需要vs想要）、"
        "以偏概全、忽略數據趨勢。"
        "用語：採用課程常用詞，如『價值觀和態度』『慎思明辨』『公共資源/公共財政』『國民身份認同』等。"
    ),
    # 如你 app 下拉用「公民、經濟及社會」，建議同時加一個同義鍵
    "公民、經濟及社會": (
        "重點：按初中課程三大範疇出題——"
        "（1）個人與群性發展：自我認識、情緒與生活技能、健康生活、人際關係、多元共融；"
        "（2）資源與經濟活動：理財教育、金錢價值觀、公共財政、經濟表現指標與趨勢（如GDP/失業/通脹等）;"
        "（3）社會體系與公民精神：權利與義務、法治、憲法與基本法、國家安全、國民身份、全球互依與合作。"
        "題型：情境題、數據/表格解讀、概念辨析、因果與利弊分析。"
        "干擾項：把描述當解釋、因果倒置、概念混淆（權利vs義務、公平vs公義、公共資源vs私人資源、需要vs想要）、"
        "以偏概全、忽略數據趨勢。"
        "用語：採用課程常用詞，如『價值觀和態度』『慎思明辨』『公共資源/公共財政』『國民身份認同』等。"
    ),

    # ===== 新增：企業、會計與財務概論（中四至中六）=====
    "企業、會計與財務概論": (
        "重點：營商環境（經濟/社會/政治法律/科技等因素）、企業擁有權類型（獨資/合夥/有限公司）及其優劣、"
        "商業道德與社會責任（持份者/道德決策）、會計作商業溝通語言（會計資訊與決策）、"
        "管理功能（計劃/組織/領導/控制）、以及個人理財（時間價值/消費者信貸/投資與風險）。"
        "題型：情境決策題（企業/消費者/投資者/僱員/企業家角色）、計算或概念應用、比較題（融資方式/擁有權類型/信貸產品）。"
        "干擾項：把收入/利潤混淆、名義vs實質回報、風險vs回報關係、把短期現金流當作長期盈利、"
        "忽略持份者與社會責任、把會計信息用途誤解。"
        "用語：優先使用『持份者』『社會責任』『會計資訊』『策略/管理功能』『時間值（現值/未來值）』等。"
    ),
    # 如你 app 下拉用「企業、會計及財務概論」，建議同時加一個同義鍵
    "企業、會計及財務概論": (
        "重點：營商環境（經濟/社會/政治法律/科技等因素）、企業擁有權類型（獨資/合夥/有限公司）及其優劣、"
        "商業道德與社會責任（持份者/道德決策）、會計作商業溝通語言（會計資訊與決策）、"
        "管理功能（計劃/組織/領導/控制）、以及個人理財（時間價值/消費者信貸/投資與風險）。"
        "題型：情境決策題（企業/消費者/投資者/僱員/企業家角色）、計算或概念應用、比較題（融資方式/擁有權類型/信貸產品）。"
        "干擾項：把收入/利潤混淆、名義vs實質回報、風險vs回報關係、把短期現金流當作長期盈利、"
        "忽略持份者與社會責任、把會計信息用途誤解。"
        "用語：優先使用『持份者』『社會責任』『會計資訊』『策略/管理功能』『時間值（現值/未來值）』等。"
    ),

    # ===== 新增：旅遊與款待（中四至中六）=====
    "旅遊與款待": (
        "重點：旅遊與款待業的重要性、旅遊系統與界別（旅遊業/款待業/交通/公營與私營機構/中介分銷途徑）、"
        "旅遊與款待業的影響（經濟/社會文化/環境的正負面影響）、可持續發展旅遊策略、"
        "顧客服務原則與技巧、專業操守，以及本地與國際趨勢與議題。"
        "題型：情境服務題（顧客需要/客務流程/處理投訴）、案例分析（目的地/景點/酒店/旅行社）、"
        "概念辨析（旅遊vs旅行/旅客分類/承載力/可持續發展）、利弊題。"
        "干擾項：把旅遊影響只講正面、忽略承載力限制、把服務禮儀當作唯一專業、"
        "混淆旅遊界別角色（旅行代理商vs旅行團經營商）、忽略東道主與文化尊重。"
        "用語：優先使用『可持續發展』『承載力』『顧客服務』『東道主』『旅遊系統/分銷途徑』等。"
    ),

    # ✅ 新增：宗教（硬性規定天主教用字）
    "宗教": (
        "【天主教用字硬規則】\n"
        "1) 必須使用天主教版本用字，嚴禁使用基督宗教其他派別常用詞。\n"
        "2) 必用詞：\n"
        "   - 天主（不用「上帝」「神」）\n"
        "   - 伯多祿（不用「彼得」）\n"
        "   - 聖母瑪利亞（不用單稱「馬利亞」作敬禮語境）\n"
        "   - 教宗、主教、神父（不用「牧師」「長老」「傳道」）\n"
        "   - 教友（避免用「基督徒」作天主教內部稱呼）\n"
        "3) 題幹/選項/解說應維持天主教教理語境與概念（例如聖事、彌撒、聖體、教會、信經等）。\n"
        "4) 干擾項：以常見概念混淆（例如：聖事/禮儀、教會訓導/個人意見、聖經/聖傳等）作設計。\n"
    ),
}

DEFAULT_TRAITS = "重點：根據教材內容出題，避免離題。干擾項：以常見誤解作干擾。"


# -------------------------
# 工具：文字清洗（減 token、增穩定）
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


# -------------------------
# ✅ 宗教科：天主教用字後處理（自動校正 + 違規標記 needs_review）
# -------------------------
_CATHOLIC_REPLACE = [
    # 安全直接替換
    (r"\b彼得\b", "伯多祿"),
    (r"\b上帝\b", "天主"),
    (r"\b神\b", "天主"),
    # 「馬利亞」在敬禮語境常見：保守做法：直接替換為「聖母瑪利亞」
    (r"\b馬利亞\b", "聖母瑪利亞"),
    # 「基督徒」作天主教內部稱呼時：替換為「教友」
    (r"\b基督徒\b", "教友"),
]

# 這些詞通常表示「基督宗教其他派別領袖稱謂」，不建議自動換成神父/主教（語境未必對）
_CATHOLIC_FLAG_ONLY = [
    "牧師",
    "長老",
    "傳道",
    "傳道人",
    "會眾",
    "敬拜讚美",  # 常見新教用語（視校本而定）
]

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
    """
    對單題做後處理：
    - 可安全替換的詞：直接替換
    - 若出現「不應自動替換」的派別用語：needs_review=True + explanation 加警告
    """
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


# -------------------------
# HTTP：OpenAI 相容 / Azure
# -------------------------
def _post_openai_compat(api_key: str, base_url: str, payload: dict, timeout: int):
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = _SESSION.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post_azure(api_key: str, endpoint: str, deployment: str, api_version: str, payload: dict, timeout: int):
    url = endpoint.rstrip("/") + f"/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    r = _SESSION.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


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
# 自動修 JSON（失敗自救，減少老師見到錯誤）
# -------------------------
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
        items = extract_json(out)
        return items
    except Exception:
        out2 = _fix_json(cfg, out, schema_hint=schema_hint, timeout=timeout)
        items2 = extract_json(out2)
        return items2


# -------------------------
# Few-shot：最短示例（提高格式穩定）
# -------------------------
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


# -------------------------
# 生成新題目（fast_mode）
# -------------------------
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
    max_tokens = 1800 if fast_mode else 2600
    timeout = 45 if fast_mode else 90

    # ✅ 宗教科：額外硬規則再加一層，讓模型更少走樣
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

        # ✅ 宗教科：後處理強制天主教用字 + 標記
        if subject == "宗教":
            item = _enforce_catholic_language(item)

        cleaned.append(item)

    return cleaned


# -------------------------
# 匯入整理（fast_mode）
# -------------------------
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


# -------------------------
# 本地簡易拆題（不變）
# -------------------------
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

        item = {
            "type": "single",
            "question": qstem,
            "options": options,
            "correct": [correct_num],
            "explanation": expl,
            "needs_review": needs_review,
        }

        # 本地解析如要強制天主教用字，也可以加：
        # item = _enforce_catholic_language(item)

        out.append(item)

    return out
