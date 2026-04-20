import pandas as pd
from io import BytesIO


def export_kahoot_excel(df: pd.DataFrame) -> bytes:
    """
    將題目 DataFrame 轉成 Kahoot Excel 格式。
    必須欄位：
      - question
      - option_1 ~ option_4
      - correct (1-4)
    """
    rows = []

    for _, r in df.iterrows():
        correct_idx = int(r["correct"]) - 1

        row = {
            "Question": r["question"],
            "Answer 1": r["option_1"],
            "Answer 2": r["option_2"],
            "Answer 3": r["option_3"],
            "Answer 4": r["option_4"],
            "Correct Answer": ["Answer 1", "Answer 2", "Answer 3", "Answer 4"][correct_idx],
            "Time limit (sec)": 20,
        }
        rows.append(row)

    out_df = pd.DataFrame(rows)

    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Kahoot Quiz")

    return bio.getvalue()
