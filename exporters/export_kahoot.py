import pandas as pd
from io import BytesIO


def export_kahoot_excel(df: pd.DataFrame) -> bytes:
    """
    匯出符合 Kahoot 官方 Excel 模板的檔案：
    - Correct answer(s) 使用 1–4 數字（可多個，用逗號）
    """

    rows = []

    for _, r in df.iterrows():
        # correct 是 "1"~"4"
        correct = str(r["correct"]).strip()

        row = {
            "Question": r["question"],
            "Answer 1": r["option_1"],
            "Answer 2": r["option_2"],
            "Answer 3": r["option_3"],
            "Answer 4": r["option_4"],
            "Time limit (sec)": 20,
            "Correct answer(s)": correct,  # ✅ 數字 1–4
        }
        rows.append(row)

    out_df = pd.DataFrame(rows)

    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Quiz")

    return bio.getvalue()
