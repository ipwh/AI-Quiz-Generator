import pandas as pd
import io
import json
import ast

KAHOOT_COLUMNS = [
    "Question - max 120 characters",
    "Answer 1 - max 75 characters",
    "Answer 2 - max 75 characters",
    "Answer 3 - max 75 characters",
    "Answer 4 - max 75 characters",
    "Time limit (sec) – 5, 10, 20, 30, 60, 90, 120, or 240 secs",
    "Correct answer(s) - choose at least one",
]

VALID_TIME = {5, 10, 20, 30, 60, 90, 120, 240}


def _is_empty(x):
    return x is None or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and x.strip() == "")


def _to_list(value):
    if _is_empty(value):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        if "," in s:
            return [x.strip() for x in s.split(",") if x.strip()]
        return [s]
    return [str(value)]


def _normalize_options_list(value):
    opts = [str(x).strip() for x in _to_list(value)]
    opts = opts[:4]
    while len(opts) < 4:
        opts.append("")
    return [o[:75] for o in opts]


def _normalize_correct(value):
    corr = [str(x).strip() for x in _to_list(value)]
    corr = [c for c in corr if c.isdigit() and c in {"1", "2", "3", "4"}]
    if not corr:
        corr = ["1"]
    return ",".join(corr)


def _normalize_time(value):
    if _is_empty(value):
        return 20
    try:
        t = int(float(value))
        return t if t in VALID_TIME else 20
    except Exception:
        return 20


def export_kahoot(df: pd.DataFrame):
    if df is None or df.empty:
        out_df = pd.DataFrame(columns=KAHOOT_COLUMNS)
        buf = io.BytesIO()
        out_df.to_excel(buf, index=False)
        return buf.getvalue()

    rows = []
    has_opt_cols = all(c in df.columns for c in ["option_1", "option_2", "option_3", "option_4"])

    for _, q in df.iterrows():
        question = q.get("question", "")
        if _is_empty(question):
            continue
        question = str(question).strip()[:120]

        if has_opt_cols:
            options = [
                "" if _is_empty(q.get("option_1")) else str(q.get("option_1")).strip(),
                "" if _is_empty(q.get("option_2")) else str(q.get("option_2")).strip(),
                "" if _is_empty(q.get("option_3")) else str(q.get("option_3")).strip(),
                "" if _is_empty(q.get("option_4")) else str(q.get("option_4")).strip(),
            ]
            options = [(o[:75] if o else "") for o in options]
        else:
            options = _normalize_options_list(q.get("options", None))

        # 確保至少兩個非空選項（避免 Kahoot 匯入出錯）
        non_empty = [o for o in options if o]
        if len(non_empty) < 2:
            options = [non_empty[0] if non_empty else "（選項A）", "（選項B）", "", ""]

        correct_str = _normalize_correct(q.get("correct", None))
        time_limit = _normalize_time(q.get("time_limit", 20))

        rows.append({
            "Question - max 120 characters": question,
            "Answer 1 - max 75 characters": options[0],
            "Answer 2 - max 75 characters": options[1],
            "Answer 3 - max 75 characters": options[2],
            "Answer 4 - max 75 characters": options[3],
            "Time limit (sec) – 5, 10, 20, 30, 60, 90, 120, or 240 secs": time_limit,
            "Correct answer(s) - choose at least one": correct_str,
        })

    out_df = pd.DataFrame(rows, columns=KAHOOT_COLUMNS)
    buf = io.BytesIO()
    out_df.to_excel(buf, index=False)
    return buf.getvalue()
