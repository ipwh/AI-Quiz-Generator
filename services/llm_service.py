import json
import re
import requests
import threading
import time
import random

_SESSION = requests.Session()
_SESSION_LOCK = threading.Lock()


def _reset_session():
    """重建 requests.Session（keep-alive 連線壞咗、或 ConnectionError/ReadTimeout 時用）"""
    global _SESSION
    try:
        _SESSION.close()
    except Exception:
        pass
    _SESSION = requests.Session()


# -------------------------
# 科目特性（可按校本再擴充）
# 注意：同一 key 只保留一份；並補齊 app 下拉選單會用到的 alias key
# -------------------------
SUBJECT_TRAITS = {
    # ==== 語文 / 人文 ====
    "中國語文": (
        "重點：以『讀寫聽說』為主導，帶動文學、中華文化、品德情意、思維、語文自學九大範疇；"
        "出題同時兼顧工具性（語文運用）與人文性（思想、文化、審美）。"
        "題型：閱讀主旨/段意/寫作手法、語境推斷、語體得體、文學感受→鑒賞。"
        "干擾項：只看字面忽略語境、混淆作者/敘述者觀點、把描寫當論證、以偏概全、忽略轉折承接。"
        "用語：『細讀文本』『誦讀/背誦』『文道並重』『慎思明辨』『語文自學』『文化認識/反思/認同』等。"
    ),
    "英國語文": (
        "Focus: reading comprehension, inference, tone/purpose, vocabulary in context, grammar usage. "
        "Distractors: near-synonym traps, extreme options, misreading of reference/pronouns."
    ),
    "歷史": (
        "重點：史料解讀、時序因果、證據支持。干擾項：年代混淆、單因解釋多因現象、以偏概全。"
    ),

    # app 下拉選單用「中國歷史」，所以要有這個 key
    "中國歷史": (
        "重點：九個歷史時期以政治演變為主，兼及文化特色與香港發展；強調史料分析、因果、脈絡、比較與評價。"
        "題型：時期特徵判斷、因果與影響、人物/事件配對、史料/圖像題。"
        "干擾項：相近時期混淆、把文化特色誤當政治制度、忽略香港在中國脈絡的位置、無證據價值判斷。"
        "用語：『史料』『脈絡』『因果』『比較』『評價』『求真持平』『探究式學習』等。"
    ),

    "宗教": (
        "【天主教用字硬規則】\n"
        "1) 必須使用天主教版本用字，嚴禁使用基督宗教其他派別常用詞。\n"
        "2) 必用詞：天主（不用「上帝」「神」）、伯多祿（不用「彼得」）、聖母瑪利亞、教宗/主教/神父、教友。\n"
        "3) 題幹/選項/解說維持天主教教理語境（聖事、彌撒、聖體、教會、信經等）。\n"
        "4) 干擾項：以概念混淆（聖事/禮儀、聖經/聖傳、訓導/個人意見等）設計。\n"
    ),

    # ==== 數理科 / 科學 ====
    "數學": (
        "重點：概念+運算、步驟正確、圖像/表格解讀、公式應用。干擾項：公式套錯、單位/符號錯、概念混淆。"
    ),
    "物理": (
        "重點：定律應用、方向性、單位、圖像解讀。干擾項：方向/符號錯、把速度當加速度。"
    ),
    "化學": (
        "重點：粒子模型、方程式、酸鹼/氧化還原、實驗觀察。干擾項：配平錯、概念混淆。"
    ),
    "生物": (
        "重點：結構與功能、恆常性、遺傳、生態互動。干擾項：器官功能混淆、相關性當因果。"
    ),

    "科學": (
        "重點：初中科學以主題式設計，涵蓋生命與生活、物料世界、能量與變化、地球與太空；"
        "並強調科學、科技、社會與環境（STSE）及 STEM 綜合應用。"
        "統一概念：系統和組織、證據和模型、變化和恆常、形態與功能。"
        "科學探究：提出問題/假說、辨識變量、公平測試、量度、圖表、數據分析、推論與結論、科學語言傳意。"
        "干擾項：把相關性當因果、混淆自變量/因變量/控制變量、忽略公平測試、把模型當事實、忽略誤差與安全守則。"
    ),

    # ==== 地理 ====
    "地理": (
        "重點：核心概念（空間、地方、區域、人地互動、全球相互依存、可持續發展）；"
        "以議題探究（提問→蒐集→組織→分析→結論）培養地理思考。"
        "題型：地圖/照片/衛星圖像判讀、圖表與統計（密度/比率/趨勢）、實地考察情境、可持續決策（權衡利弊/持份者）。"
        "干擾項：把描述當解釋、因果倒置、忽略尺度、地圖比例/方向/圖例誤讀、把 GIS 當圖片而非分析工具。"
    ),

    # ==== 經濟 ====
    # 你 app 下拉選單用「經濟」，保留詳細版（刪走舊短版）
    "經濟": (
        "重點：實證分析 + 規範判斷並行；用經濟學概念/模型作明辨性思考與理性決策。"
        "核心：稀少性/機會成本/私有產權/專門化；需求供應/彈性/盈餘/干預/效率公平；"
        "宏觀（GDP/物價/失業、AD-AS、貨幣與銀行、政策）及國際貿易（比較優勢等）。"
        "題型：供需圖比較靜態、稅/津貼/配額/價格上限下限、盈餘與淨損失、弧彈性計算、GDP/失業率詮釋、AD-AS短長期比較。"
        "干擾項：稀少性≠短缺；需求改變≠需求量改變（供應同理）；效率≠公平；GDP≠福利；比較優勢≠絕對優勢；干預需有效才有影響。"
        "用語：稀少性、機會成本、邊際、均衡、彈性、盈餘、淨損失、GDP、物價指數、失業率、AD-AS、貨幣供應/需求等。"
    ),

    # ==== 公民、經濟及社會（app 用「公民、經濟及社會」，所以加 alias）====
    "公民、經濟及社會": (
        "重點：三大範疇——"
        "（1）個人與群性發展；（2）資源與經濟活動（理財/公共財政/經濟指標）；（3）社會體系與公民精神（法治/基本法/國民身份等）。"
        "題型：情境題、數據/表格解讀、概念辨析、因果與利弊分析。"
        "干擾項：把描述當解釋、因果倒置、權利vs義務、公平vs公義、需要vs想要混淆、忽略數據趨勢。"
    ),
   # ==== ICT（app key：資訊及通訊科技（ICT））====
    "資訊及通訊科技（ICT）": (
        "重點：資訊處理 + 系統理解 + 互聯網與保安 + 計算思維/程式 + 社會影響（道德/法律）。"
        "強調資訊素養（選取/組織/分析/使用資訊）、解難與創意、負責任使用科技。"
        "題型：進制轉換/溢出、字符編碼（ASCII/Unicode）、試算表/樞紐分析、DBMS/SQL、"
        "網絡概念（TCP/IP、DNS、HTTP/HTTPS）、程式流程與除錯（語法/邏輯/運行時）、知識產權/私隱/網安。"
        "干擾項：RAM/ROM/Cache 混用、HTTP vs HTTPS 誤解、ASCII vs Unicode 混淆、SQL鍵/冗餘/正規化概念混亂、忽略邊界測試。"
    ),

"企業、會計與財務概論": (
    "重點：兩大範疇（會計、商業管理），強調把概念應用於真實商業情境，培養明辨性思考、決策、溝通與協作；"
    "同時重視商業道德與社會責任。"
    "核心必修：營商環境（香港經濟特徵、全球化、企業擁有權：獨資/合夥/有限公司、跨國公司）、"
    "管理基礎（管理功能：計劃/組織/領導/控制；主要商業功能）、會計基礎（會計循環、複式記帳、財務報表）、"
    "基礎個人理財（時間值、信貸、投資與風險）。"
    "常見選修範圍："
    "會計：財務會計、成本會計（成本分類、邊際/吸收成本、決策）；"
    "管理：管理導論/財務管理/人力資源/市場營銷（視校本選擇）。"
    "題型建議："
    "（1）情境決策題：在限制（資源/時間/風險）下選方案，需用概念與數據支持；"
    "（2）會計題：報表編製/解讀、會計原則與用途、比率分析與解釋；"
    "（3）成本與定價：成本分類、盈虧/邊際概念、決策取捨；"
    "（4）倫理題：非法 vs 不道德、持份者影響、社會責任與長短期代價。"
    "常見干擾項："
    "混淆收入/利潤/現金流、把資產當開支、誤用財務比率（分子分母/意義）、成本分類錯、"
    "把風險與回報關係說反、忽略道德/社會責任、把企業擁有權特徵（責任/融資/控制權）混淆。"
    "用語要求：必用『營商環境』『企業擁有權』『持份者』『商業道德/社會責任』『管理功能』"
    "『會計循環』『複式記帳』『財務報表/比率分析』『時間值（現值/未來值）』『風險管理』等。"
),


    "旅遊與款待": (
    "重點：理解旅遊與款待業的重要性與行業體系，能評估其經濟/社會文化/環境影響，並運用服務質素概念改善顧客體驗；"
    "同時強調可持續發展與東道主（host）角色。"
    "課程主軸（五大課題）：旅遊導論、款待導論、地理名勝、客務關係及服務、旅遊與款待業趨勢及議題（另含實地考察）。"
    "題型建議："
    "（1）概念/模型題：旅遊動機（Maslow/推拉等）、旅客分類（Cohen/Plog）、產品生命週期、承載力、分銷途徑；"
    "（2）影響評估題：旅遊對經濟/社會文化/環境的正負面影響與權衡；"
    "（3）服務質素題：RATER、服務質差距（Gap Model）、服務補救（service recovery）與投訴處理；"
    "（4）情境題：住宿/餐飲/會展（MICE）運作、食物安全五要點、文化禮儀與溝通技巧。"
    "常見干擾項："
    "混淆旅遊/旅行/旅客定義、把承載力等同旅客量、把產品生命週期階段混淆、"
    "混淆RATER五維與Gap Model差距來源、住宿/餐飲分類錯、只講經濟效益忽略社會文化與環境成本。"
    "用語要求：必用『可持續發展』『承載力』『產品生命週期』『分銷途徑』『東道主』『RATER』『Gap Model』"
    "『服務補救』『食物安全』等；題幹宜採行業情境（酒店/旅行社/目的地/會展）來設問。"
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
# 宗教科：天主教用字後處理（自動校正 + 違規標記 needs_review）
# -------------------------
_CATHOLIC_REPLACE = [
    (r"\b彼得\b", "伯多祿"),
    (r"\b上帝\b", "天主"),
    (r"\b神\b", "天主"),
    (r"\b馬利亞\b", "聖母瑪利亞"),
    (r"\b基督徒\b", "教友"),
]

_CATHOLIC_FLAG_ONLY = [
    "牧師", "長老", "傳道", "傳道人", "會眾", "敬拜讚美"
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
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t = (15, timeout)  # connect, read

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
    """統一呼叫 LLM 的入口"""
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
# 自動修 JSON（失敗自救）
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
        optB = re.search(r"(?:\n|\r|\A)\s*(?:B[\.\、\)]|\(B\))\s*(.+)", b)
        optC = re.search(r"(?:\n|\r|\A)\s*(?:C[\.\、\)]|\(C\))\s*(.+)", b)
        optD = re.search(r"(?:\n|\r|\A)\s*(?:D[\.\、\)]|\(D\))\s*(.+)", b)

        options = [
            optA.group(1).strip() if optA else "",
            optB.group(1).strip() if optB else "",
            optC.group(1).strip() if optC else "",
            optD.group(1).strip() if optD else "",
        ]
        options = _normalize_options(options)

        qstem = re.sub(r"(?:答案|Answer)\s*[:：]\s*([A-D]|[1-4]).*", "", b, flags=re.IGNORECASE).strip()
        qstem = re.sub(r"(?m)^\s*(?:[A-D][\.\、\)]|\([A-D]\))\s*.+$", "", qstem).strip()

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
