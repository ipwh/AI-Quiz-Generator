import json
import re
import requests
import threading
import time
import random

_SESSION = requests.Session()
_SESSION_LOCK = threading.Lock()

def _chat(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int):
    """
    統一呼叫 LLM 的入口：
    - cfg['type'] == 'azure' 用 Azure
    - 其他用 OpenAI-compatible（DeepSeek / OpenAI / 自訂）
    """
    if cfg.get("type") == "azure":
        data = _post_azure(
            api_key=cfg["api_key"],
            endpoint=cfg["endpoint"],
            deployment=cfg["deployment"],
            api_version=cfg.get("api_version", "2024-02-15-preview"),
            payload={
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
    else:
        data = _post_openai_compat(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            payload={
                "model": cfg["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )

    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
def _reset_session():
    """
    重新建立 requests.Session（當 keep-alive 連線壞咗、或 ConnectionError 時用）
    用 helper 包住 global，避免在其他函數出現 'used prior to global' 語法錯。
    """
    global _SESSION
    try:
        _SESSION.close()
    except Exception:
        pass
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
# ====== 中國語文（通用：如你的下拉選單只有「中國語文」就用這個）======
"中國語文": (
    "重點：以『讀寫聽說』為主導，帶動文學、中華文化、品德情意、思維、語文自學九大範疇；"
    "出題必須同時兼顧工具性（語文運用）與人文性（思想、文化、審美）。"
    "題型建議："
    "（1）閱讀理解：主旨、段落關係、寫作手法（描寫/抒情/議論）、人物形象、語境推斷；"
    "（2）語文基礎：詞語用法、句式、語體得體（口語/書面語）；"
    "（3）文學賞析：意象、語言特色、情感線索（以整體感受→再分析鑒賞）；"
    "（4）中華文化：從文本/生活素材辨識『物質/制度/精神』文化元素，並作簡短反思；"
    "（5）思維：要求學生作慎思明辨（比較、歸納、推論）而非死記。"
    "干擾項設計："
    "常見錯誤包括只看字面不顧語境、把作者/敘述者觀點混淆、把描寫當論證、以偏概全、"
    "忽略關鍵詞句/承接轉折、將情感線索斷裂、混淆修辭效果。"
    "用語要求："
    "題幹與選項需使用課程常用語：『細讀文本』『誦讀/背誦』『文道並重』『慎思明辨』"
    "『語文自學』『文化認識/反思/認同』等；避免只考術語定義。"
),

# ====== 中國歷史（通用：如你的下拉選單只有「中國歷史」就用這個）======
"中國歷史": (
    "重點：按時間脈絡理解歷史發展，強調『古今並重』、九個歷史時期的宏觀特徵，"
    "以『政治演變』為主軸，兼及『文化特色』與『香港發展』，並培養探究與史料分析能力。"
    "題型建議："
    "（1）時序與脈絡：辨識事件先後、朝代/時期定位；"
    "（2）因果關係：原因→經過→影響（政治/社會/經濟/文化）；"
    "（3）史料解讀：從材料分辨觀點、證據與推論；"
    "（4）香港與國家關係：在相關時期把香港角色放回中國歷史脈絡理解。"
    "干擾項："
    "常見錯誤包括朝代時序混淆、人物/事件張冠李戴、把結果當原因、以單一史觀下結論、"
    "忽略史料立場與限制、用現代價值直接套入而無證據。"
    "用語："
    "題幹宜使用『史料』『脈絡』『因果』『比較』『評價』『求真持平』『延續與轉變』等歷史研習用語。"
),

# ====== 中國歷史（中一至中三）：更貼合課程九時期＋三主軸＋探究學習 ======
"中國歷史（中一至中三）": (
    "重點：九個歷史時期（史前至夏商周、秦漢、三國兩晉南北朝、隋唐、宋元、明、清、中華民國、中華人民共和國），"
    "以政治演變為主，並以文化特色與香港發展作輔；加入社會文化史課題以提升興趣。"
    "題型建議："
    "（1）時期特徵題：用關鍵制度/政策/現象判斷所屬時期；"
    "（2）因果與影響題：制度改革、民族互動、中外交流、外力衝擊的因果鏈；"
    "（3）人物/事件配對：人物事蹟與其時代關係；"
    "（4）史料/圖像題：用材料支持結論（避免純背誦）。"
    "干擾項："
    "混淆相近時期（例如不同改革/變法）、把文化特色誤當政治制度、忽略香港相關史事在中國脈絡中的位置、"
    "用沒有證據的價值判斷取代分析。"
    "用語："
    "強調『探究式學習』『史識（鑑古知今）』『求真持平』與『國民身份認同/責任感』等價值觀元素，但必須以史料/史實作支撐。"
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
def _post_openai_compat(api_key: str, base_url: str, payload: dict, timeout: int = 90, max_retries: int = 5):
    """
    OpenAI 相容 API（OpenAI / DeepSeek / 自訂 OpenAI-compatible）
    正確 Header：Authorization: Bearer <API_KEY>
    加入：timeout tuple + retry + session lock + session reset
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # connect/read timeout 分拆，避免讀取長回應時更容易斷線
    t = (15, timeout) # connect 15s, read timeout 90/180s

    last_err = None
    for attempt in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=payload, timeout=t)
            r.raise_for_status()
            return r.json()

        except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
            last_err = e
            # 指數退避 + 抖動
            time.sleep(((2 ** attempt) * 2)+ random.random())
            with _SESSION_LOCK:
                _reset_session()

        except requests.exceptions.HTTPError:
            # 401/403/429/5xx 等，交回上層處理（唔好盲目重試浪費quota）
            raise

        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep((2 ** attempt) + random.random())
            with _SESSION_LOCK:
                _reset_session()

    raise requests.exceptions.ConnectionError(f"OpenAI-compatible request failed after retries: {last_err}")


def _post_azure(api_key: str, endpoint: str, deployment: str, api_version: str, payload: dict, timeout: int = 90, max_retries: int = 3):
    """
    Azure OpenAI：Header 用 api-key
    加入：timeout tuple + retry + session lock + session reset
    """
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
    """
    統一呼叫 LLM 的入口：
    - cfg['type'] == 'azure' → Azure OpenAI
    - 其他 → OpenAI-compatible（DeepSeek / OpenAI / 自訂）
    """
    if cfg.get("type") == "azure":
        data = _post_azure(
            api_key=cfg["api_key"],
            endpoint=cfg["endpoint"],
            deployment=cfg["deployment"],
            api_version=cfg.get("api_version", "2024-02-15-preview"),
            payload={
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
    else:
        data = _post_openai_compat(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            payload={
                "model": cfg["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
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
    max_tokens = 1200 if fast_mode else 1800
    timeout = 90 if fast_mode else 180

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
