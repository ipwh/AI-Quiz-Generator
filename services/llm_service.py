# =========================================================
# services/llm_service.py
# FINAL-FULL（穩定版・加強科目特性/誤概念/干擾項模板）
# ---------------------------------------------------------
# ✅ OpenAI-compatible chat/completions
# ✅ 支援：Generate / Import / JSON 修復 / API Ping
# ✅ 強化：SUBJECT_TRAITS / SUBJECT_MISCONCEPTIONS / SUBJECT_DISTRACTOR_HINTS（全科目）
# ✅ 附加：Grok 型號自動偵測 get_xai_default_model()
# ✅ 附加：答案位置分佈平衡（避免 correct 長期偏 2/3）
# ---------------------------------------------------------
# 設計目標：
# - 題目更貼科目特色、干擾項更像真實考評
# - 減少 meta 字眼（如「根據教材」）
# - 題數盡量精準；correct schema 嚴格
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
# 科目特性（HK 中學常用科目）
# =========================================================

SUBJECT_TRAITS: Dict[str, str] = {
    "中國語文": (
        "重點：篇章理解、語境推斷、段落主旨、作者態度、修辭與寫作意圖。"
        "題幹宜短清晰，避免『根據教材』等提示語；可用引文或情境替代。"
        "干擾項：斷章取義、過度推論、把描述當立場、概念混淆（描寫/抒情/議論）。"
    ),
    "英國語文": (
        "Focus: reading comprehension, inference, tone/attitude, vocabulary in context, cohesion."
        "Avoid meta phrasing like 'based on the text'; use natural question stems."
        "Distractors: near-synonyms, wrong referent, overgeneralization, opposite tone."
    ),
    "數學": (
        "重點：概念理解、運算步驟、條件限制、表示與轉換（式/圖/表）。"
        "題目要有明確已知/所求；注意單位、範圍、四捨五入、定義域。"
        "干擾項：運算次序/符號錯、漏條件、單位/比例/角度制錯。"
    ),
    "公民與社會發展": (
        "重點：法治、身份、全球化、可持續發展、資料判讀、立場辨析。"
        "題目宜用時事情境；分辨事實/觀點、政策利弊、權利責任。"
        "干擾項：概念混淆（法治/人治、公平/平等）、把個案當普遍、忽略持份者取捨。"
    ),
    "科學": (
        "重點：概念理解、證據推論、變量控制、公平測試、資料處理與結論。"
        "題目常用表格/圖像/實驗描述；判斷變量、步驟、結果解釋。"
        "干擾項：相關性當因果、控制變量不全、結論超出數據。"
    ),
    "物理": (
        "重點：定律應用、受力分析、能量/動量、圖像解讀、單位與方向。"
        "題目需標明方向/正負號/基準；可比較大小、判斷趨勢。"
        "干擾項：混淆標量/向量、忽略摩擦/損耗、單位/比例錯、圖像斜率/面積誤讀。"
    ),
    "化學": (
        "重點：粒子模型、方程式配平、計量、反應條件、實驗設計與安全。"
        "題目可用觀察/數據/滴定情境；推斷產物、限量試劑、pH。"
        "干擾項：未配平、摩爾/質量混淆、濃度概念錯、酸鹼強弱與濃度混淆。"
    ),
    "生物": (
        "重點：結構與功能、恆常性、遺傳與演化、生態與人類影響、數據解讀。"
        "題目常用流程圖/結構圖/生態圖；解釋機制或預測影響。"
        "干擾項：把相關當因果、混淆層級、目的論、負回饋方向搞反。"
    ),
    "地理": (
        "重點：成因→過程→影響→管理、空間分佈、案例比較、地圖/數據判讀。"
        "題目可用新聞情境/地圖/氣候圖；推論差異與政策取捨。"
        "干擾項：單一原因化、混淆天氣/氣候、忽略尺度/地點條件、結果當原因。"
    ),
    "歷史": (
        "重點：時序、因果、史料解讀、觀點與偏見、短/長期影響。"
        "題目可用史料節錄；判斷立場、可靠性、事件關聯。"
        "干擾項：年代混淆、把後果當原因、以今論古、單一因素決定論。"
    ),
    "中國歷史": (
        "重點：朝代脈絡、制度與社會、因果與延續/變革、史料與論證。"
        "題目可用制度改革/外交戰爭/文化；比較不同朝代政策影響。"
        "干擾項：朝代先後混淆、制度名詞混淆、中央/地方權力概念混淆。"
    ),
    "宗教": (
        "重點：宗教概念、倫理抉擇、教義理解、比較觀點與反思。"
        "題目可用道德情境；指出倫理觀點或價值衝突。"
        "干擾項：把個人意見當教義、混淆宗教核心概念、只講規條忽略情境。"
    ),
    "資訊及通訊科技（ICT）": (
        "重點：系統概念、資料表示、網絡與安全、演算法思維、硬/軟件。"
        "題目用釣魚/加密/拓撲/資料庫情境；選擇最佳方案。"
        "干擾項：加密vs雜湊、IP/MAC、備份/同步、授權/認證混淆。"
    ),
    "經濟": (
        "重點：供需、彈性、成本收益、外部性、市場失靈、政策影響與圖像解讀。"
        "題目可用需求供給圖、稅補貼、最低工資；判斷均衡變化。"
        "干擾項：需求vs需求量、曲線移動方向錯、稅負歸宿誤判、福利變化誤判。"
    ),
    "企業、會計與財務概論": (
        "重點：會計原則、報表解讀、成本/定價、財務比率、現金流。"
        "題目可用損益表/資產負債表；判斷盈利/流動性/效率。"
        "干擾項：利潤vs現金流、資產/費用/支出混淆、比率公式錯。"
    ),
    "公民、經濟及社會": (
        "重點：公民身份、經濟基本概念、社會議題、資料解讀與價值判斷。"
        "題目用家庭/社區情境；應用概念作判斷。"
        "干擾項：以偏概全、道德判斷當事實、因果倒置、忽略多方持份者。"
    ),
    "旅遊與款待": (
        "重點：旅遊系統、服務質素、營運、安全與風險、可持續、客戶體驗。"
        "題目用酒店/旅行團情境；判斷最佳處理與服務補救。"
        "干擾項：只顧短期成本忽略口碑、服務補救不當、忽略安全與風險。"
    ),
}

DEFAULT_TRAITS = "請按內容出題，語句自然，避免使用『根據教材/根據文本/根據以上』等提示語。"


# =========================================================
# 誤概念庫（干擾項用）— 全科目
# =========================================================

SUBJECT_MISCONCEPTIONS: Dict[str, List[str]] = {
    "中國語文": [
        "把例子當主旨", "斷章取義", "把作者描述當作者立場", "過度推論", "忽略語境導致詞義誤判",
        "混淆表達方式（敘述/描寫/抒情/議論）", "混淆修辭作用", "忽略代詞指代", "把轉折當因果",
    ],
    "英國語文": [
        "literal meaning over implied meaning", "tone/attitude misread", "overgeneralization",
        "wrong referent (pronouns)", "false synonym trap", "misread negatives (not/unless)",
        "cause vs effect swapped", "collocation error",
    ],
    "數學": [
        "忽略限制條件/定義域", "運算次序錯誤", "符號/正負號錯", "單位未轉換",
        "比例/百分率基數錯", "四捨五入/有效數字錯", "面積/周界混淆", "平均數/中位數混淆",
    ],
    "公民與社會發展": [
        "法治/人治混淆", "平等/公平混淆", "把立場當事實", "把個案當普遍",
        "忽略持份者差異", "忽略政策成本/取捨", "把相關當因果", "權利/責任只談一邊",
    ],
    "科學": [
        "相關性當因果", "未控制變量", "樣本太少就下結論", "結論超出數據",
        "把觀察當解釋", "精確度與準確度混淆", "忽略誤差", "忘記重複試驗/平均",
    ],
    "物理": [
        "混淆標量/向量", "方向或單位錯", "把速度當加速度", "自由體圖漏力",
        "作用力反作用力概念錯", "忽略摩擦/能量損耗", "圖像斜率/面積意義判斷錯", "質量/重量混淆",
    ],
    "化學": [
        "方程式未配平", "摩爾/質量/體積混淆", "濃度概念錯", "酸鹼強弱與濃度混淆",
        "離子方程式寫錯", "氧化/還原對象混淆", "限量試劑錯", "忽略反應條件/狀態符號",
    ],
    "生物": [
        "把相關當因果", "混淆系統層級", "目的論（適應當意圖）", "基因型/表型混淆",
        "呼吸作用/呼吸混淆", "消化/吸收混淆", "負回饋方向搞反", "食物鏈能量流向錯",
    ],
    "地理": [
        "單一原因化", "混淆天氣與氣候", "忽略尺度/地點差異", "把短期事件當長期趨勢",
        "忽略人為管理措施", "把結果當原因", "推論超出資料", "忽略持份者取捨",
    ],
    "歷史": [
        "年代/時序混淆", "把後果當原因", "以今論古", "單一因素決定論",
        "忽略背景條件", "把史料立場當客觀", "混淆短期/長期影響", "混淆事件與人物",
    ],
    "中國歷史": [
        "朝代先後混淆", "制度名詞混淆", "把結果當原因", "忽略延續與變革",
        "中央/地方權力混淆", "史料立場忽略", "以偏概全", "忽略經濟/地理基礎",
    ],
    "宗教": [
        "把個人意見當教義", "混淆不同宗教概念", "把倫理簡化成單一規條", "忽略情境與價值衝突",
        "把描述當評價",
    ],
    "資訊及通訊科技（ICT）": [
        "加密 vs 雜湊混淆", "IP vs MAC 混淆", "備份 vs 同步混淆", "授權 vs 認證混淆",
        "忽略最小權限原則", "防火牆 vs 防毒混淆", "資料庫主鍵/外鍵混淆", "效能只看步數不看規模",
    ],
    "經濟": [
        "需求 vs 需求量", "供給 vs 供給量", "曲線移動方向搞錯", "均衡變化判斷錯",
        "彈性大小判斷反", "總收益 vs 利潤", "稅負歸宿只看法定承擔者", "忽略外部性",
    ],
    "企業、會計與財務概論": [
        "利潤 vs 現金流", "收入 vs 收款", "資產/費用/支出混淆", "折舊視為現金流出",
        "比率公式代錯", "盈利性/流動性混淆", "權責發生制忽略", "毛利/淨利混淆",
    ],
    "公民、經濟及社會": [
        "把道德判斷當事實推論", "以偏概全", "忽略多方持份者", "把因果倒置",
        "把權利義務混淆", "忽略證據/資料來源", "把經濟概念字面化", "把個案當普遍",
    ],
    "旅遊與款待": [
        "只顧短期成本忽略口碑", "服務補救當推卸責任", "忽略安全與風險管理", "忽略可持續旅遊原則",
        "把顧客需求一概而論", "忽略供需互動",
    ],
}


# =========================================================
# 干擾項設計（強度 + 科目模板）
# =========================================================

DISTRACTOR_RULES_BY_LEVEL: Dict[str, str] = {
    "easy": "干擾項反映基本誤解；錯在單一步驟；避免過度相似。",
    "medium": "干擾項包含部分正確但推論錯或漏條件；至少兩個干擾項看似合理。",
    "hard": "干擾項設計為多步推理陷阱：條件誤判、圖表讀錯、單位/方向/定義域錯。",
    "mixed": "混合 medium 與 hard；同一套題可包含不同難度但每題仍要清晰。",
}

# ✅ 全科目「專屬干擾項模板」：生成選項時務必參考（由你要求加強）
SUBJECT_DISTRACTOR_HINTS: Dict[str, List[str]] = {
    "中國語文": [
        "以『斷章取義』做一個干擾項（取原文片段但偏離主旨）",
        "以『過度推論』做一個干擾項（推到文中沒有的意思）",
        "以『把描述當立場』做一個干擾項（把敘述誤當作者態度）",
        "以『修辭作用誤判』做一個干擾項（手法對但作用錯）",
        "以『轉折/因果混淆』做一個干擾項（把轉折看成因果或相反）",
    ],
    "英國語文": [
        "Include a near-synonym distractor (close meaning but wrong nuance)",
        "Include an opposite-tone distractor (tone/attitude flipped)",
        "Include a wrong referent distractor (pronoun/it/they misreferenced)",
        "Include an overgeneralization distractor (too broad/absolute)",
        "Include a negation trap distractor (misread not/unless)",
    ],
    "數學": [
        "設『漏條件/定義域』干擾項（忽略範圍或限制）",
        "設『單位/比例』干擾項（單位未轉換或比例基數錯）",
        "設『運算次序/符號』干擾項（括號/正負號/先乘除錯）",
        "設『四捨五入/有效數字』干擾項",
        "設『概念混淆』干擾項（如面積/周界、平均數/中位數）",
    ],
    "公民與社會發展": [
        "設『概念混淆』干擾項（法治/人治、公平/平等、權利/責任）",
        "設『把立場當事實』干擾項（價值判斷偽裝成事實）",
        "設『以偏概全』干擾項（個案推論普遍）",
        "設『忽略持份者差異』干擾項",
        "設『忽略政策取捨』干擾項（只講好處或只講成本）",
    ],
    "科學": [
        "設『相關≠因果』干擾項",
        "設『未控制變量』干擾項（公平測試失敗）",
        "設『結論超出數據』干擾項",
        "設『精確度/準確度混淆』干擾項",
        "設『樣本/重複不足』干擾項",
    ],
    "物理": [
        "設『方向/向量』干擾項（正負號/方向反了）",
        "設『單位』干擾項（N/J/W 等混淆或未轉換）",
        "設『忽略摩擦/損耗』干擾項（理想化假設錯用）",
        "設『圖像斜率/面積誤讀』干擾項",
        "設『作用力反作用力混淆』干擾項",
    ],
    "化學": [
        "設『方程式未配平/係數錯』干擾項",
        "設『摩爾/質量/體積混淆』干擾項",
        "設『濃度概念錯』干擾項（稀釋/體積變化）",
        "設『酸鹼強弱 vs 濃度』干擾項",
        "設『限量試劑判斷錯』干擾項",
    ],
    "生物": [
        "設『目的論』干擾項（把適應當有意圖）",
        "設『層級混淆』干擾項（細胞/組織/器官/系統）",
        "設『相關≠因果』干擾項",
        "設『恆常性調節方向反』干擾項（負回饋）",
        "設『能量流向/生態概念錯』干擾項",
    ],
    "地理": [
        "設『單一原因化』干擾項（忽略多因素互動）",
        "設『天氣/氣候混淆』干擾項",
        "設『尺度/地點條件忽略』干擾項",
        "設『結果當原因』干擾項",
        "設『只講一面』干擾項（忽略取捨/持份者）",
    ],
    "歷史": [
        "設『時序/年代混淆』干擾項",
        "設『後果當原因』干擾項",
        "設『以今論古』干擾項",
        "設『單一因素決定論』干擾項",
        "設『史料立場忽略』干擾項（把主張當事實）",
    ],
    "中國歷史": [
        "設『朝代先後混淆』干擾項",
        "設『制度名詞混淆』干擾項",
        "設『結果當原因』干擾項",
        "設『中央/地方權力混淆』干擾項",
        "設『以偏概全』干擾項（以一例概括一代）",
    ],
    "宗教": [
        "設『把個人意見當教義』干擾項",
        "設『混淆不同宗教概念』干擾項",
        "設『只講規條忽略情境』干擾項",
        "設『價值衝突忽略』干擾項",
        "設『描述當評價』干擾項",
    ],
    "資訊及通訊科技（ICT）": [
        "設『加密 vs 雜湊』干擾項",
        "設『IP vs MAC』干擾項",
        "設『備份 vs 同步』干擾項",
        "設『授權 vs 認證』干擾項",
        "設『安全措施角色混淆』干擾項（防火牆/防毒/權限）",
    ],
    "經濟": [
        "設『需求 vs 需求量』干擾項",
        "設『曲線移動方向錯』干擾項（把價格變動當曲線移動）",
        "設『稅負歸宿誤判』干擾項（只看法定承擔者）",
        "設『彈性判斷反』干擾項",
        "設『福利變化誤判』干擾項（剩餘/死重損失）",
    ],
    "企業、會計與財務概論": [
        "設『利潤 vs 現金流』干擾項",
        "設『收入 vs 收款』干擾項",
        "設『資產/費用/支出混淆』干擾項",
        "設『比率公式代錯』干擾項",
        "設『折舊/應收應付理解錯』干擾項",
    ],
    "公民、經濟及社會": [
        "設『道德判斷當事實』干擾項",
        "設『以偏概全』干擾項",
        "設『因果倒置』干擾項",
        "設『忽略多方持份者』干擾項",
        "設『概念字面化』干擾項（忽略情境/證據）",
    ],
    "旅遊與款待": [
        "設『只顧短期成本忽略口碑/品牌』干擾項",
        "設『服務補救不當』干擾項（推卸責任/缺乏同理）",
        "設『忽略安全與風險』干擾項",
        "設『忽略可持續/承載量』干擾項",
        "設『忽略顧客需求差異』干擾項",
    ],
}


# =========================================================
# Text helpers
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
# OpenAI-compatible HTTP
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
        except Exception as e:
    ms = int((time.time() - t0) * 1000)

    # ✅ 嘗試取出 HTTP response body
    body = ""
    try:
        resp = getattr(e, "response", None)
        if resp is not None:
            body = resp.text or ""
    except Exception:
        body = ""

    return {
        "ok": False,
        "latency_ms": ms,
        "output": "",
        "error": repr(e) + ("\n\n--- response body ---\n" + body if body else ""),
    }



# =========================================================
# Grok model auto-detect (xAI)
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
# Answer position rebalance (A/B/C/D)
# =========================================================

def rebalance_correct_positions(items: List[dict], seed: Optional[int] = None) -> List[dict]:
    """平衡 correct 分佈：把 options 重新排列，令 1~4 出現次數更平均。"""

    if seed is None:
        seed = int(time.time()) % 100000
    rng = random.Random(seed)

    valid = []
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
# ✅ Generate
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
    subject_templates = SUBJECT_DISTRACTOR_HINTS.get(subject, [])

    text = _clean_text(text)
    text = text[: (8000 if fast_mode else 10000)]

    mc_text = "\n".join(f"- {m}" for m in misconceptions[:12])
    sd_text = "\n".join(f"- {d}" for d in subject_templates[:6])

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
        # 盡量把數量拉回指定題數
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

        # ✅ 平衡答案位置（只做排列，不改內容）
        data = rebalance_correct_positions(data)

    return data


# =========================================================
# ✅ Import
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
