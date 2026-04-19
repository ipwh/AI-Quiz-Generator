from typing import List, Dict
from core.models import QuestionItem


VALID_CORRECT = {"1", "2", "3", "4"}


def validate_question(q: QuestionItem) -> List[str]:
    errs: List[str] = []

    if not (q.question or "").strip():
        errs.append("題幹為空")

    options = [str(x).strip() for x in (q.options or [])]
    # single 必須有 4 個位置（不足補空，過多截斷）
    if len(options) < 4:
        options = options + [""] * (4 - len(options))
    if len(options) > 4:
        options = options[:4]

    non_empty = [x for x in options if x]
    if len(non_empty) < 2:
        errs.append("少於兩個有效選項")

    if len(set(non_empty)) != len(non_empty):
        errs.append("選項內容重複")

    # correct 必須能對應到有效選項（非空）
    valid_correct = []
    for c in (q.correct or []):
        c = str(c).strip()
        if c in VALID_CORRECT:
            idx = int(c) - 1
            if 0 <= idx < len(options) and options[idx].strip():
                valid_correct.append(c)

    if not valid_correct:
        errs.append("正確答案無法對應到有效選項")

    # 題幹過短（警告級別，仍當作 errors 但你可改成 warnings）
    if len((q.question or "").strip()) < 6:
        errs.append("題幹過短（請教師留意）")

    return errs


def validate_questions(items: List[QuestionItem]) -> List[Dict]:
    out = []
    for i, q in enumerate(items, start=1):
        errs = validate_question(q)
        out.append(
            {
                "index": i,
                "question": (q.question or "")[:60],
                "errors": errs,
                "ok": len(errs) == 0,
            }
        )
    return out