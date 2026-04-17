import requests
import json
import re

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
    "宗教": "重點﹕嚴禁使用基督教版本的字眼，一定要使用天主教版本，例如不可以用彼得，而要用伯多祿"
}
DEFAULT_TRAITS = "重點：根據教材內容出題，避免離題。干擾項：以常見誤解作干擾。"


def extract_json(text: str):
    if not text:
        raise ValueError("AI 回傳內容是空的")
    text = text.strip()
    text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^```", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError("無法從 AI 回傳解析 JSON")


def _post_openai_compat(api_key: str, base_url: str, payload: dict, timeout: int = 90):
    url = base_url.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post_azure(api_key: str, endpoint: str, deployment: str, api_version: str, payload: dict, timeout: int = 90):
    url = endpoint.rstrip('/') + f'/openai/deployments/{deployment}/chat/completions?api-version={api_version}'
    headers = {'api-key': api_key, 'Content-Type': 'application/json'}
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _chat(cfg: dict, messages: list, temperature: float):
    if cfg.get('type') == 'azure':
        data = _post_azure(cfg['api_key'], cfg['endpoint'], cfg['deployment'], cfg.get('api_version','2024-02-15-preview'), {'messages': messages, 'temperature': temperature})
    else:
        data = _post_openai_compat(cfg['api_key'], cfg['base_url'], {'model': cfg['model'], 'messages': messages, 'temperature': temperature})
    return data.get('choices', [{}])[0].get('message', {}).get('content', '')


def _normalize_options(opts):
    if not isinstance(opts, list):
        opts = []
    opts = [str(x).strip() for x in opts][:4]
    while len(opts) < 4:
        opts.append('')
    return opts


def _normalize_correct(corr):
    if isinstance(corr, str):
        corr = [corr]
    if not isinstance(corr, list):
        corr = []
    corr = [str(x).strip() for x in corr if str(x).strip().isdigit()]
    corr = [c for c in corr if c in {'1','2','3','4'}]
    if not corr:
        corr = ['1']
    return [corr[0]]


def generate_questions(cfg, text, subject, level, question_count):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    prompt = f"""
你是一名香港中學教師，熟悉 DSE/校內測驗出題。
你正在為「科目：{subject}」設計課堂選擇題。整體難度：{level}。

【科目特性（必須遵守）】
{traits}

【規則】
- 只生成 {question_count} 條題目
- 全部為單選題（4選1）
- options 必須 4 個
- correct 只可用 1-4（list，只有 1 個）
- 若對答案不肯定：needs_review=true，explanation 以「⚠️需教師確認：」開頭
- 每題 question 或 explanation 必須包含教材中出現過的至少 2 個關鍵詞
- 只輸出 JSON array，純 JSON，不要任何額外文字

【輸出欄位】
type（固定 single）, question, options(4), correct(list of 1), explanation, needs_review

【教材內容】
{text}
"""
    content = _chat(cfg, [{'role':'user','content': prompt}], temperature=0.2)
    items = extract_json(content)

    cleaned = []
    for q in items:
        opts = _normalize_options(q.get('options', []))
        corr = _normalize_correct(q.get('correct', []))
        needs_review = bool(q.get('needs_review', False))
        explanation = str(q.get('explanation','')).strip()
        if needs_review and not explanation.startswith('⚠️需教師確認'):
            explanation = '⚠️需教師確認：' + (explanation if explanation else '系統推測答案，請老師核對。')
        cleaned.append({'type':'single','question': str(q.get('question','')).strip(),'options': opts,'correct': corr,'explanation': explanation,'needs_review': needs_review})
    return cleaned


def _split_into_blocks(raw_text: str):
    text = (raw_text or '').strip()
    if not text:
        return []
    parts = re.split(r"(?:\n(?=\s*(?:\d+\s*[\.、]|Q\d+|第\s*\d+\s*題)))", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def _extract_explicit_answer(block: str):
    if not block:
        return None
    m = re.search(r"(?:答案|正確答案|Answer|Ans)\s*[:：]\s*([A-Da-d]|[1-4])", block)
    if not m:
        return None
    ans = m.group(1).strip()
    if ans.isdigit() and ans in {'1','2','3','4'}:
        return ans
    ans = ans.upper()
    if ans in {'A','B','C','D'}:
        return str(ord(ans) - ord('A') + 1)
    return None


def _strip_answer_line(block: str) -> str:
    return re.sub(r"(?m)^\s*(?:答案|正確答案|Answer|Ans)\s*[:：]\s*([A-Da-d]|[1-4]).*$", '', block).strip()


def assist_import_questions(cfg, raw_text, subject, allow_guess=True):
    traits = SUBJECT_TRAITS.get(subject, DEFAULT_TRAITS)
    blocks = _split_into_blocks(raw_text)
    if not blocks:
        return []

    explicit = []
    cleaned_blocks = []
    for b in blocks:
        explicit.append(_extract_explicit_answer(b))
        cleaned_blocks.append(_strip_answer_line(b))

    allow_guess_text = '若原文未提供答案，可推測最可能答案，但 needs_review=true。' if allow_guess else "若原文未提供答案，correct=['1'] 並 needs_review=true。"

    numbered = []
    for idx, b in enumerate(cleaned_blocks, start=1):
        hint = explicit[idx-1]
        hint_text = f'（原文明示答案：{hint}）' if hint else '（原文未提供答案）'
        numbered.append(f'[題目{idx}]{hint_text}\n{b}')

    prompt = f"""
你是一名香港中學教師，正在整理「科目：{subject}」的現有選擇題。

【科目特性】
{traits}

【最重要規則】
1) 請保持題目順序輸出。
2) 若標示「原文明示答案：X」，必須 correct=["X"]，不可改動。
3) {allow_guess_text}

【輸出】
只輸出 JSON array（不要任何額外文字）。每題欄位：
- type（single）
- question
- options（4個）
- correct（list，1個數字"1"~"4"）
- explanation（needs_review=true 時以 ⚠️需教師確認： 開頭）
- needs_review（true/false）

【原始題目】
{chr(10).join(numbered)}
"""

    content = _chat(cfg, [{'role':'user','content': prompt}], temperature=0.1)
    items = extract_json(content)

    cleaned = []
    for i, q in enumerate(items):
        opts = _normalize_options(q.get('options', []))
        corr = _normalize_correct(q.get('correct', []))
        needs_review = bool(q.get('needs_review', False))
        explanation = str(q.get('explanation','')).strip()

        if i < len(explicit) and explicit[i] is not None:
            corr = [explicit[i]]
            needs_review = False
        else:
            needs_review = True
            if not explanation.startswith('⚠️需教師確認'):
                explanation = '⚠️需教師確認：' + (explanation if explanation else '系統推測答案，請老師核對。')

        cleaned.append({'type':'single','question': str(q.get('question','')).strip(),'options': opts,'correct': corr,'explanation': explanation,'needs_review': needs_review})
    return cleaned


def parse_import_questions_locally(raw_text: str):
    blocks = _split_into_blocks(raw_text)
    if not blocks:
        return []

    out = []
    for b in blocks:
        ans = _extract_explicit_answer(b)

        optA = re.search(r"(?:\n|\r|\A)\s*(?:A[\.、\)]|\(A\))\s*(.+)", b)
        optB = re.search(r"(?:\n|\r|\A)\s*(?:B[\.、\)]|\(B\))\s*(.+)", b)
        optC = re.search(r"(?:\n|\r|\A)\s*(?:C[\.、\)]|\(C\))\s*(.+)", b)
        optD = re.search(r"(?:\n|\r|\A)\s*(?:D[\.、\)]|\(D\))\s*(.+)", b)

        options = [
            optA.group(1).strip() if optA else '',
            optB.group(1).strip() if optB else '',
            optC.group(1).strip() if optC else '',
            optD.group(1).strip() if optD else '',
        ]

        qstem = _strip_answer_line(b)
        qstem = re.sub(r"(?m)^\s*(?:[A-D][\.、\)]|\([A-D]\))\s*.+$", '', qstem).strip()

        needs_review = False
        correct_num = '1'
        if ans:
            correct_num = ans
        else:
            needs_review = True

        explanation = '⚠️需教師確認：未找到答案，請老師核對。' if needs_review else ''

        out.append({'type':'single','question': qstem,'options': _normalize_options(options),'correct': [correct_num],'explanation': explanation,'needs_review': needs_review})

    return out
