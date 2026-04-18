import io
from docx import Document


def _num_to_letter(n: str) -> str:
    return {"1": "A", "2": "B", "3": "C", "4": "D"}.get(n, n)


def _normalize_correct_to_letter(value) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        if not value:
            return ""
        value = value[0]

    s = str(value).strip().upper()
    if not s:
        return ""

    if "," in s:
        s = s.split(",")[0].strip()

    if s in {"A", "B", "C", "D"}:
        return s

    s = _num_to_letter(s)
    return s if s in {"A", "B", "C", "D"} else ""


def export_wayground_docx(df, subject: str = "", include_explanation: bool = True):
    doc = Document()
    title = f"Wayground 題目（{subject}）" if subject else "Wayground 題目"
    doc.add_heading(title, level=1)

    q_num = 1
    for _, row in df.iterrows():
        q = str(row.get("question", "")).strip()
        if not q:
            continue

        o1 = str(row.get("option_1", "")).strip()
        o2 = str(row.get("option_2", "")).strip()
        o3 = str(row.get("option_3", "")).strip()
        o4 = str(row.get("option_4", "")).strip()

        correct_letter = _normalize_correct_to_letter(row.get("correct", ""))
        expl = str(row.get("explanation", "")).strip()

        doc.add_paragraph(f"{q_num}. {q}")
        doc.add_paragraph(f"A. {o1}")
        doc.add_paragraph(f"B. {o2}")
        doc.add_paragraph(f"C. {o3}")
        doc.add_paragraph(f"D. {o4}")
        doc.add_paragraph(f"答案：{correct_letter}")

        if include_explanation and expl:
            doc.add_paragraph(f"解說：{expl}")

        doc.add_paragraph("")
        q_num += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
