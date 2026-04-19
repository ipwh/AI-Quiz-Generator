from typing import List, Dict
import pandas as pd
from core.models import QuestionItem


def dicts_to_items(data: List[Dict], subject: str, source: str) -> List[QuestionItem]:
    items: List[QuestionItem] = []
    for q in data or []:
        opts = q.get("options", [])
        if not isinstance(opts, list):
            opts = []
        opts = [str(x) for x in opts][:4]
        while len(opts) < 4:
            opts.append("")

        corr = q.get("correct", ["1"])
        if isinstance(corr, str):
            corr = [corr]
        if not isinstance(corr, list):
            corr = ["1"]
        corr = [str(x).strip() for x in corr if str(x).strip()]
        if not corr:
            corr = ["1"]

        items.append(
            QuestionItem(
                subject=subject,
                qtype=q.get("qtype", "single") or "single",
                question=str(q.get("question", "") or ""),
                options=opts,
                correct=[corr[0]],
                explanation=str(q.get("explanation", "") or ""),
                needs_review=bool(q.get("needs_review", False)),
                source=source,
            )
        )
    return items


def items_to_editor_df(items: List[QuestionItem]) -> pd.DataFrame:
    rows = []
    for it in items or []:
        opts = list(it.options or [])
        opts = [str(x) for x in opts][:4]
        while len(opts) < 4:
            opts.append("")
        corr = (it.correct or ["1"])[0] if isinstance(it.correct, list) else str(it.correct or "1")

        rows.append(
            {
                "export": True,
                "subject": it.subject,
                "qtype": it.qtype,
                "question": it.question,
                "option_1": opts[0],
                "option_2": opts[1],
                "option_3": opts[2],
                "option_4": opts[3],
                "correct": str(corr),
                "explanation": it.explanation,
                "needs_review": bool(it.needs_review),
            }
        )

    return pd.DataFrame(rows)


def editor_df_to_items(df: pd.DataFrame, default_subject: str, source: str) -> List[QuestionItem]:
    out: List[QuestionItem] = []
    if df is None or df.empty:
        return out

    for _, r in df.iterrows():
        opts = [str(r.get(f"option_{i}", "") or "") for i in range(1, 5)]
        corr = str(r.get("correct", "1") or "1").strip()
        if corr not in {"1", "2", "3", "4"}:
            corr = "1"
        out.append(
            QuestionItem(
                subject=str(r.get("subject", default_subject) or default_subject),
                qtype=str(r.get("qtype", "single") or "single"),
                question=str(r.get("question", "") or ""),
                options=opts,
                correct=[corr],
                explanation=str(r.get("explanation", "") or ""),
                needs_review=bool(r.get("needs_review", False)),
                source=source,
            )
        )
    return out


def items_to_export_df(items: List[QuestionItem]) -> pd.DataFrame:
    # exporters 目前吃 DataFrame：用同一 schema 輸出
    return items_to_editor_df(items)