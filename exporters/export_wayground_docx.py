import io
from docx import Document

_MAP = {"1": "A", "2": "B", "3": "C", "4": "D"}

def _normalize_correct_to_letters(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        corr = [str(x).strip() for x in value]
    else:
        corr = [x.strip() for x in str(value).split(",") if x.strip()]
    letters = []
    for c in corr:
        if c in _MAP and _MAP[c] not in letters:
            letters.append(_MAP[c])
    return ",".join(letters)

def export_wayground_docx(df, subject: str = "", include_explanation: bool = True):
    doc = Document()
    title = f"Wayground 題目（{subject}）" if subject else "Wayground 題目"
    doc.add_heading(title, level=1)

    q_num = 1
    for _, row in df.iterrows():
        q = str(row.get("question", "")).strip()
        if not q:
            continue

        qtype = str(row.get("qtype", "single")).strip()
        if qtype == "true_false":
            o1, o2, o3, o4 = "對", "錯", "", ""
        else:
            o1 = str(row.get("option_1", "")).strip()
            o2 = str(row.get("option_2", "")).strip()
            o3 = str(row.get("option_3", "")).strip()
            o4 = str(row.get("option_4", "")).strip()

        correct_letters = _normalize_correct_to_letters(row.get("correct", "1"))
        expl = str(row.get("explanation", "")).strip()

        doc.add_paragraph(f"{q_num}. [{qtype}] {q}")
        doc.add_paragraph(f"A. {o1}")
        doc.add_paragraph(f"B. {o2}")
        if o3 or o4:
            doc.add_paragraph(f"C. {o3}")
            doc.add_paragraph(f"D. {o4}")

        doc.add_paragraph(f"答案：{correct_letters}")
        if include_explanation and expl:
            doc.add_paragraph(f"解說：{expl}")
        doc.add_paragraph("")
        q_num += 1

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()