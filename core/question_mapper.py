
from __future__ import annotations

from typing import List, Dict
import pandas as pd

from core.models import QuestionItem
from core.validators import normalize_single_options, normalize_single_correct


def dicts_to_items(data: List[Dict], subject: str, source: str) -> List[QuestionItem]:
    items: List[QuestionItem] = []
    for q in data or []:
        opts = q.get("options", [])
        if not isinstance(opts, list):
            opts = []
        opts = normalize_single_options([str(x) for x in opts])

        corr = q.get("correct", ["1"])
        corr = normalize_single_correct(corr)

        items.append(
            QuestionItem(
                subject=subject,
                qtype=str(q.get("qtype", "single") or "single"),
                question=str(q.get("question", "") or ""),
                options=opts,
                correct=corr,
                explanation=str(q.get("explanation", "") or ""),
                needs_review=bool(q.get("needs_review", False)),
                source=source,
            )
        )
    return items


def items_to_editor_df(items: List[QuestionItem], report: List[Dict] | None = None) -> pd.DataFrame:
    # map index->errors for display
    err_map = {}
    ok_map = {}
    if report:
        for r in report:
            idx = r.get("index")
            err_map[idx] = "; ".join(r.get("errors", []) or [])
            ok_map[idx] = bool(r.get("ok"))

    rows = []
    for i, it in enumerate(items or [], start=1):
        opts = normalize_single_options(it.options)
        corr = normalize_single_correct(it.correct)

        rows.append({
            "export": True,
            "validation_ok": ok_map.get(i, True),
            "validation_errors": err_map.get(i, ""),
            "subject": it.subject,
            "qtype": it.qtype,
            "question": it.question,
            "option_1": opts[0],
            "option_2": opts[1],
            "option_3": opts[2],
            "option_4": opts[3],
            "correct": corr[0],
            "explanation": it.explanation,
            "needs_review": bool(it.needs_review),
        })

    return pd.DataFrame(rows)


def editor_df_to_items(df: pd.DataFrame, default_subject: str, source: str) -> List[QuestionItem]:
    out: List[QuestionItem] = []
    if df is None or df.empty:
        return out

    for _, r in df.iterrows():
        subject = str(r.get("subject", default_subject) or default_subject)
        qtype = str(r.get("qtype", "single") or "single")
        question = str(r.get("question", "") or "")
        opts = [str(r.get(f"option_{i}", "") or "") for i in range(1, 5)]
        opts = normalize_single_options(opts)
        corr = normalize_single_correct([str(r.get("correct", "1") or "1")])
        explanation = str(r.get("explanation", "") or "")
        needs_review = bool(r.get("needs_review", False))

        out.append(QuestionItem(
            subject=subject,
            qtype=qtype,
            question=question,
            options=opts,
            correct=corr,
            explanation=explanation,
            needs_review=needs_review,
            source=source,
        ))

    return out


def items_to_export_df(items: List[QuestionItem]) -> pd.DataFrame:
    # exporters currently expect the classic df columns
    rows = []
    for it in items or []:
        opts = normalize_single_options(it.options)
        corr = normalize_single_correct(it.correct)[0]
        rows.append({
            "export": True,
            "subject": it.subject,
            "qtype": it.qtype,
            "question": it.question,
            "option_1": opts[0],
            "option_2": opts[1],
            "option_3": opts[2],
            "option_4": opts[3],
            "correct": corr,
            "explanation": it.explanation,
            "needs_review": bool(it.needs_review),
        })
    return pd.DataFrame(rows)
