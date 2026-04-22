# =========================================================
# services/llm_service.py
# FINAL-FULL（穩定版）
# ---------------------------------------------------------
# ✅ OpenAI-compatible chat/completions
# ✅ 支援：Generate / Import / JSON 修復 / API Ping
# ✅ 強化：全科目 SUBJECT_TRAITS / SUBJECT_MISCONCEPTIONS / DISTRACTOR
# ✅ 附加：Grok 型號自動偵測 get_xai_default_model()
# ---------------------------------------------------------
# 設計目標：讓題目更「貼科目」、干擾項更合理、減少 AI 口水與「根據教材」等字眼
# =========================================================

from __future__ import annotations

import json
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
# 科目特性（HK 中學常用科目）
# =========================================================

# 提示：此表只影響「出題方向與語言」，不影響 JSON schema。
SUBJECT_TRAITS: Dict[str, str] = {
    # 語文
    "中國語文": (
        "重點：篇章理解、語境推斷、段落主旨、作者態度、修辭與寫作意圖。"
        "題幹宜短清晰，避免『根據教材』等提示語；可用引文或情境替代。"
        "干擾項：常見為斷章取義、過度推論、概念混淆（描寫/抒情/議論）。"
    ),
    "英國語文": (
        "Focus: reading comprehension, inference, tone/attitude, vocabulary in context, cohesion."
        "Avoid meta phrasing like 'based on the text'; use authentic question stems."
        "Distractors: near-synonyms, wrong referent, overgeneralization, opposite tone."
    ),

    # 數學
    "數學": (
        "重點：概念理解、運算步驟、條件限制、表示與轉換（式/圖/表）。"
        "題目要有明確已知/所求；注意單位、範圍、四捨五入、定義域。"
        "干擾項：常見為運算次序/符號錯、漏條件、單位/比例/角度制錯。"
    ),

    # 綜合科學/學科科學
    "科學": (
        "重點：概念理解、證據推論、變量控制、公平測試、資料處理與結論。"
        "題目常用表格/圖像/實驗描述；要求學生判斷變量、步驟、結果解釋。"
        "干擾項：把相關性當因果、控制變量不全、結論超出數據。"
    ),
    "物理": (
        "重點：定律應用、受力分析、能量/動量、圖像解讀、單位與方向。"
        "題目需清楚標明方向/正負號/基準；可要求比較大小、判斷趨勢。"
        "干擾項：混淆標量/向量、忽略摩擦/能量損耗、單位/比例錯。"
    ),
    "化學": (
        "重點：粒子模型、化學方程式與配平、計量、反應條件、實驗設計與安全。"
        "題目可用反應觀察/數據/滴定情境；要求推斷產物、限量試劑、pH。"
        "干擾項：未配平、物質/摩爾混淆、把溶質/溶劑或濃度概念混淆。"
    ),
    "生物": (
        "重點：結構與功能、恆常性、遺傳與演化、生態與人類影響、數據解讀。"
        "題目常用流程圖/器官結構/生態圖；要求解釋機制或預測影響。"
        "干擾項：把相關當因果、混淆系統層級（細胞/組織/器官/系統）。"
    ),

    # 人文
    "地理": (
        "重點：成因→過程→影響→管理、空間分佈、案例比較、數據/地圖判讀。"
        "題目可用新聞情境/地圖/氣候圖；要求推論區域差異與政策取捨。"
        "干擾項：單一原因化、忽略尺度與地點條件、混淆天氣/氣候。"
    ),
    "歷史": (
        "重點：時序、因果、史料解讀、觀點與偏見、短/長期影響。"
        "題目可用史料節錄；要求判斷作者立場、史料可靠性、事件關聯。"
        "干擾項：年代混淆、把後果當原因、以今論古、單一因素決定論。"
    ),
    "中國歷史": (
        "重點：朝代脈絡、制度與社會、因果與延續/變革、史料與論證。"
        "題目可用制度改革/外交戰爭/思想文化；要求比較不同朝代政策影響。"
        "干擾項：朝代先後混淆、制度名詞混淆、把結果當原因。"
    ),

    # 經濟/商科
    "經濟": (
        "重點：供需、彈性、成本收益、外部性、市場失靈、政策影響與圖像解讀。"
        "題目可用需求供給圖、稅補貼、最低工資、價格上限；要求判斷均衡變化。"
        "干擾項：需求 vs 需求量、供給 vs 供給量、均衡移動方向錯、把福利變化搞錯。"
    ),
    "企業、會計與財務概論": (
        "重點：企業決策、會計原則、報表解讀、成本/定價、財務比率與現金流。"
        "題目可用損益表/資產負債表節錄；要求判斷盈利能力/流動性/營運效率。"
        "干擾項：利潤 vs 現金流、資產/支出/費用混淆、比率公式代錯。"
    ),

    # 公民/社會
    "公民與社會發展": (
        "重點：概念理解（法治、身份、全球化、可持續發展）、資料判讀、立場辨析。"
        "題目宜用時事情境；要求分辨事實/觀點、政策利弊、權利與責任。"
        "干擾項：概念混淆（法治/人治、平等/公平）、把個案當普遍規律。"
    ),
    "公民、經濟及社會": (
        "重點：公民身份、經濟基本概念、社會議題、資料解讀與價值判斷。"
        "題目可用家庭/社區/學校情境；要求應用概念作判斷與選擇。"
        "干擾項：以偏概全、把道德判斷當事實推論、忽略持份者差異。"
    ),

    # 宗教
    "宗教": (
        "重點：宗教概念、倫理抉擇、文本/教義理解、比較不同觀點與反思。"
        "題目可用道德情境；要求指出可能的宗教倫理觀點或價值衝突。"
        "干擾項：把個人意見當教義、混淆不同宗教核心概念。"
    ),

    # ICT
    "資訊及通訊科技（ICT）": (
        "重點：系統概念、資料表示、網絡與安全、演算法思維、硬件/軟件與應用。"
        "題目可用情境（釣魚、加密、網絡拓撲、資料庫）；要求選擇最佳方案。"
        "干擾項：混淆加密/雜湊、IP/MAC、備份/同步、權限/認證。"
    ),

    # 旅遊與款待
    "旅遊與款待": (
        "重點：旅遊系統、服務質素、款待營運、安全與風險、可持續旅遊、客戶體驗。"
        "題目可用酒店/旅行團情境；要求判斷最佳處理、服務補救、風險管理。"
        "干擾項：只顧短期成本忽略品牌/口碑、把投訴處理當推卸責任。"
    ),
}

DEFAULT_TRAITS = (
    "請按教材內容出題，語句自然，避免使用『根據教材/根據文本/根據以上』等提示語。"
)


# =========================================================
# 誤概念庫（干擾項用）— 已擴充全科目
# =========================================================

SUBJECT_MISCONCEPTIONS: Dict[str, List[str]] = {
    "中國語文": [
        "把例子當主旨", "斷章取義", "把作者描述當作者立場", "過度推論（推到文中沒有）",
        "混淆修辭手法作用（比喻/擬人/排比）", "混淆表達方式（敘述/描寫/抒情/議論）",
        "忽略語境造成詞義誤判", "把『轉折』當『因果』", "忽略代詞指代", "主客觀混淆",
    ],
    "英國語文": [
        "選了字面意思忽略 implied meaning", "tone/attitude 判斷錯（sarcasm/irony）",
        "overgeneralization", "confuse referents (pronouns)", "wrong collocation", "tense/time reference error",
        "confuse fact vs opinion", "misread negatives (not/unless)", "cause vs effect swapped", "false synonym trap",
    ],
    "數學": [
        "忽略限制條件/定義域", "運算次序錯誤", "符號/正負號錯", "單位未轉換",
        "把『等號』當『指向』", "把比例當差", "四捨五入/有效數字處理錯", "角度制/弧度混淆（如適用）",
        "把面積/周界混淆", "把平均數與中位數/眾數混淆", "把函數輸入輸出混淆（如適用）",
        "誤解百分率增減（基數不同）",
    ],
    "科學": [
        "相關性當因果", "未控制變量（公平測試）", "樣本太少就下結論", "結論超出數據",
        "把觀察當解釋", "混淆自變/應變/控制變量", "忘記重複試驗/平均", "把精確度當準確度",
        "忽略測量誤差", "把假設寫成結論",
    ],
    "物理": [
        "混淆標量/向量", "方向或單位錯", "忽略摩擦/能量損耗", "把速度當加速度",
        "自由體圖漏力", "把作用力反作用力當同一物體", "把功率當能量", "把質量當重量",
        "圖像斜率/面積意義判斷錯", "把平衡當沒有力",
    ],
    "化學": [
        "化學方程式未配平", "把物質的量與質量/體積混淆", "把濃度與體積混淆",
        "把溶質/溶劑角色混淆", "把離子方程式寫錯", "酸鹼強弱與濃度混淆",
        "把氧化/還原對象混淆", "錯用限量試劑", "忽略狀態符號/條件", "把沉澱與氣體生成搞錯",
    ],
    "生物": [
        "把相關當因果", "混淆系統層級（細胞/組織/器官）", "把適應當意圖（目的論）",
        "把基因型/表型混淆", "把呼吸作用當呼吸（breathing）", "把消化/吸收混淆",
        "把恆常性調節方向搞反（負回饋）", "忽略變異與選擇", "把食物鏈能量流向搞錯",
        "把生物量/個體數混淆",
    ],
    "地理": [
        "單一原因化", "混淆天氣與氣候", "忽略地點/尺度差異", "把相關當因果",
        "把短期事件當長期趨勢", "忽略人為因素/管理措施", "把結果當原因",
        "把推論超出資料", "忽略成本/效益/持份者取捨",
    ],
    "歷史": [
        "年代/時序混淆", "把後果當原因", "以今論古", "單一因素決定論",
        "混淆不同陣營立場", "史料來源/目的忽略", "把主張當事實", "忽略背景條件",
        "混淆短期/長期影響", "把相似事件視為同一事件",
    ],
    "中國歷史": [
        "朝代先後混淆", "制度名詞混淆", "把結果當原因", "忽略延續與變革",
        "混淆中央/地方權力", "把史料立場當客觀", "以偏概全（以一例概括一代）",
        "忽略地理/經濟基礎因素",
    ],
    "經濟": [
        "需求與需求量混淆", "供給與供給量混淆", "價格變動與需求曲線移動混淆",
        "把均衡移動方向搞錯", "把彈性大小判斷反", "把總收益與利潤混淆",
        "忽略外部性", "把稅負歸宿只看法定承擔者", "把補貼效果看成加稅", "把機會成本忽略",
    ],
    "企業、會計與財務概論": [
        "利潤與現金流混淆", "收入與收款混淆", "資產/費用/支出混淆", "存貨與成本計算錯",
        "折舊視為現金流出", "比率公式代錯", "把流動性與盈利性混淆", "忽略權責發生制",
        "把資產負債表與損益表混用", "把毛利與淨利混淆",
    ],
    "公民與社會發展": [
        "法治與人治混淆", "平等與公平混淆", "權利與責任只談一邊",
        "把個案當普遍規律", "把立場當事實", "把相關當因果",
        "忽略持份者差異", "忽略政策成本/取捨", "把全球化只看經濟層面",
    ],
    "公民、經濟及社會": [
        "把道德判斷當事實推論", "以偏概全", "忽略多方持份者", "把因果倒置",
        "把權利義務混淆", "把經濟概念字面化", "忽略證據/資料來源",
    ],
    "宗教": [
        "把個人意見當教義", "混淆不同宗教核心概念", "把宗教倫理簡化成單一規條",
        "忽略情境與價值衝突", "把描述當評價",
    ],
    "資訊及通訊科技（ICT）": [
        "把加密與雜湊混淆", "把 IP 與 MAC 混淆", "把備份與同步混淆",
        "把授權與認證混淆", "忽略最小權限原則", "把防火牆與防毒混淆",
        "把演算法效率只看步數不看輸入規模", "把資料庫主鍵/外鍵混淆",
    ],
    "旅遊與款待": [
        "只顧短期成本忽略品牌/口碑", "把服務補救當推卸責任", "忽略安全與風險管理",
        "忽略可持續旅遊原則", "把顧客需求一概而論", "忽略旅遊系統供需互動",
    ],
}


# =========================================================
# 干擾項設計（DISTRACTOR）
# =========================================================

# 1) 難度層級（全科通用）
DISTRACTOR_RULES_BY_LEVEL: Dict[str, str] = {
    "easy": (
        "干擾項反映基本誤解；錯在單一步驟；避免過於相近導致猜測。"
        "正確選項應明顯更完整/更符合條件。"
    ),
    "medium": (
        "干擾項包含『部分正確但推論錯』或『條件漏掉』；至少兩個干擾項看似合理。"
        "避免用純語感猜到；需要讀題與簡單推理。"
    ),
    "hard": (
        "干擾項設計為常見陷阱：多步推理中某一步出錯、條件誤判、圖表讀錯、單位/方向/定義域錯。"
        "正確答案需能用解釋指出關鍵步驟。"
    ),
    "mixed": (
        "混合 medium 與 hard 強度；同一套題可包含不同難度（但每題仍需清晰可判斷）。"
    ),
}

# 2) 科目專屬干擾項模板（額外強化；若缺則忽略）
SUBJECT_DISTRACTOR_HINTS: Dict[str, List[str]] = {
    "中國語文": [
        "以『過度推論』製作一個干擾項", "以『斷章取義』製作一個干擾項", "以『把描述當立場』製作一個干擾項"
    ],
    "英國語文": [
        "include a near-synonym distractor", "include a wrong referent distractor", "include an opposite-tone distractor"
    ],
    "數學": [
        "設一個『漏條件/定義域』干擾項", "設一個『單位/比例』干擾項", "設一個『運算次序/符號』干擾項"
    ],
    "物理": [
        "設一個『方向/向量』干擾項", "設一個『圖像斜率/面積』干擾項", "設一個『忽略摩擦/損耗』干擾項"
    ],
    "化學": [
        "設一個『未配平/係數錯』干擾項", "設一個『摩爾/質量混淆』干擾項", "設一個『濃度概念錯』干擾項"
    ],
    "經濟": [
        "設一個『需求 vs 需求量』干擾項", "設一個『曲線移動方向錯』干擾項", "設一個『福利/稅負』干擾項"
    ],
}


# =========================================================
# 工具：清洗文字
# =========================================================

def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =========================================================
# JSON 解析
# =========================================================

def extract_json(text: str) -> Any:
    if not text:
        raise ValueError("AI 回傳內容是空的")
    return json.loads(text)


# =========================================================
# OpenAI-compatible API 呼叫
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

    allowed = {"model", "messages", "temperature", "max_tokens"}
    safe_payload = {k: v for k, v in payload.items() if k in allowed}

    last_err: Optional[Exception] = None
    for _ in range(max_retries):
        try:
            with _SESSION_LOCK:
                r = _SESSION.post(url, headers=headers, json=safe_payload, timeout=(10, timeout))
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.6)

    raise last_err  # type: ignore


# =========================================================
# Chat 統一入口（文字模式）
# =========================================================

def _chat(cfg: dict, messages: list, temperature: float, max_tokens: int, timeout: int) -> str:
    for m in messages:
        if not isinstance(m.get("content"), str):
            raise RuntimeError("文字模式不支援非字串 content")

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


# =========================================================
# API 測試
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
# Grok 型號自動偵測（供 sidebar 使用）
# =========================================================

def get_xai_default_model(api_key: str, base_url: str = "https://api.x.ai/v1") -> str:
    """透過 OpenAI-compatible /models 列出可用型號，挑選最新 grok。"""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    with _SESSION_LOCK:
        r = _SESSION.get(url, headers=headers, timeout=(10, 25))
    r.raise_for_status()
    data = r.json() or {}

    models = data.get("data", []) if isinstance(data, dict) else []
    ids: List[str] = []
    for m in models:
        if isinstance(m, dict) and isinstance(m.get("id"), str):
            ids.append(m["id"])

    grok = [i for i in ids if "grok" in i.lower()]
    if not grok:
        return "grok-4-latest"

    latest = [i for i in grok if "latest" in i.lower()]
    if latest:
        return sorted(latest)[-1]

    return sorted(grok)[-1]


# =========================================================
# JSON 修復（自救）
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
        max_tokens=2000,
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
# ✅ 生成題目
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
    """Generate MCQ questions as JSON array."""

    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    misconceptions = SUBJECT_MISCONCEPTIONS.get(subject, [])
    distractor_rules = DISTRACTOR_RULES_BY_LEVEL.get(level, "")
    subject_distractors = SUBJECT_DISTRACTOR_HINTS.get(subject, [])

    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]

    mc_text = "\n".join(f"- {m}" for m in misconceptions[:12])
    sd_text = "\n".join(f"- {d}" for d in subject_distractors[:6])

    # 重要：避免出現 meta 字眼；要求數量精確；要求每題必有 correct
    prompt = f"""
你是一名香港中學教師，負責出校內評估題。

【科目】{subject}
【難度】{level}
【題目數目】必須剛好 {question_count} 題

【科目特性】
{traits}

【常見誤概念（用作干擾項設計）】
{mc_text}

【科目專屬干擾項提示】
{sd_text}

【干擾項強度】
{distractor_rules}

【嚴格輸出要求】
- 只輸出純 JSON array（不加任何文字）
- 每題必為四選一：qtype = \"single\"
- options 必須剛好 4 個字串
- correct 必須為只含 1 個元素的 list： [\"1\"~\"4\"]
- question 請用自然題幹，不要以「根據教材/根據文本/根據以上」等字眼開頭
- explanation 簡潔指出關鍵理由（1-3 句）
- needs_review: 若題幹/答案不確定或需教師判斷，請設為 true

【教材內容】
{text}
"""

    data = _call_with_retries(
        cfg,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2 if fast_mode else 0.3,
        max_tokens=2400,
        timeout=150,
    )

    # 盡量把數量拉回指定題數（避免模型多/少）
    if isinstance(data, list):
        if len(data) > question_count:
            return data[:question_count]
        if len(data) < question_count:
            # 追加一次補齊
            remain = question_count - len(data)
            if remain > 0:
                prompt2 = prompt + f"\n\n【補齊要求】你剛才題數不足，請再補 {remain} 題，只輸出新增題目的 JSON array。"
                more = _call_with_retries(
                    cfg,
                    messages=[{"role": "user", "content": prompt2}],
                    temperature=0.2,
                    max_tokens=2000,
                    timeout=150,
                )
                if isinstance(more, list):
                    data.extend(more)
            return data[:question_count]

    return data


# =========================================================
# ✅ 匯入題目（Import）
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

    prompt = f"""
你是一名香港中學教師，正在把現有題目整理成標準 JSON。

【科目】{subject}
【要求】
- 每題四選一（qtype=single）
- options 必須 4 個
- 必須提供 correct（[\"1\"~\"4\"] 只 1 個）
- 只輸出純 JSON array
- 若原文欠缺答案：{'可合理推斷並標 needs_review=true' if allow_guess else '請標 needs_review=true 並把 correct 留空'}

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
    return []  # 預留本地 parser
