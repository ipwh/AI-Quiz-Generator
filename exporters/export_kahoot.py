import pandas as pd
from io import BytesIO


def export_kahoot_excel(df: pd.DataFrame) -> bytes:
    """
    匯出符合 Kahoot 官方格式的 Excel：
    - Correct Answer 必須是 A / B / C / D
    """

    rows = []

    for _, r in df.iterrows():
        # correct 原本是 "1"~"4"
        idx = int(r["correct"]) - 1
        correct_letter = ["A", "B", "C", "D"][idx]

        row = {
            "Question": r["question"],
            "Answer 1": r["option_1"],
            "Answer 2": r["option_2"],
            "Answer 3": r["option_3"],
            "Answer 4": r["option_4"],
            "Correct Answer": correct_letter,  # ✅ A–D
            "Time limit (sec)": 20,
        }
        rows.append(row)

    out_df = pd.DataFrame(rows)

    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Kahoot Quiz")

    return bio.getvalue()
