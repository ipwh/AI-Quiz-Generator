
from __future__ import annotations

from typing import List, Dict, Tuple
from core.models import QuestionItem

VALID_CORRECT = {"1", "2", "3", "4"}


def normalize_single_options(options: List[str]) -> List[str]:
    opts = [str(x).strip() for x in (options or [])]
    opts = opts[:4]
    while len(opts) < 4:
        opts.append("")
    return opts


def normalize_single_correct(correct: List[str]) -> List[str]:
    if correct is None:
        return ["1"]
    if isinstance(correct, str):
        correct = [correct]
    if not isinstance(correct, list):
        return ["1"]
    cleaned = [str(x).strip() for x in correct if str(x).strip()]
    cleaned = [c for c in cleaned if c in VALID_CORRECT]
    return [cleaned[0]] if cleaned else ["1"]


def validate_question(q: QuestionItem) -> List[str]:
    errs: List[str] = []

    stem = (q.question or "").strip()
    if not stem:
        errs.append("題幹為空")

    if q.qtype != "single":
        # 目前只實作 single，其他題型先標記
        errs.append("目前只支援 single 題型驗證")
        return errs

    opts = normalize_single_options(q.options)
    non_empty = [x for x in opts if x]

    if len(non_empty) < 2:
        errs.append("少於兩個有效選項")

    if len(set(non_empty)) != len(non_empty):
        errs.append("選項內容重複")

    corr = normalize_single_correct(q.correct)
    idx = int(corr[0]) - 1
    if idx < 0 or idx >= 4 or not opts[idx].strip():
        errs.append("正確答案無法對應到有效選項")

    # 教學實務：題幹過短通常不理想（作為警告也可）
    if stem and len(stem) < 6:
        errs.append("題幹過短（請教師留意）")

    return errs


def validate_questions(items: List[QuestionItem]) -> List[Dict]:
    report: List[Dict] = []
    for i, q in enumerate(items or [], start=1):
        errs = validate_question(q)
        report.append({
            "index": i,
            "question": (q.question or "")[:60],
            "errors": errs,
            "ok": len(errs) == 0,
        })
    return report


def summarize_report(report: List[Dict]) -> Tuple[int, Dict[str, int]]:
    bad = 0
    counts: Dict[str, int] = {}
    for r in report or []:
        if not r.get("ok"):
            bad += 1
            for e in r.get("errors", []) or []:
                counts[e] = counts.get(e, 0) + 1
    return bad, counts
