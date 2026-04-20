from io import BytesIO
from docx import Document


def export_wayground_docx(df, subject: str) -> bytes:
    """
    匯出 Wayground / 教學用 DOCX。
    """
    doc = Document()
    doc.add_heading(f"{subject} 題目練習", level=1)

    for i, r in df.iterrows():
        doc.add_paragraph(f"{i+1}. {r['question']}")

        doc.add_paragraph(f"A. {r['option_1']}")
        doc.add_paragraph(f"B. {r['option_2']}")
        doc.add_paragraph(f"C. {r['option_3']}")
        doc.add_paragraph(f"D. {r['option_4']}")

        correct = r["correct"]
        doc.add_paragraph(f"✅ 正確答案：{correct}")

        if r.get("explanation"):
            doc.add_paragraph(f"解說：{r['explanation']}")

        doc.add_paragraph("")

    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()
