import io
from docx import Document

def _num_to_letter(n: str) -> str:
    return {'1':'A','2':'B','3':'C','4':'D'}.get(n, n)

def _normalize_correct_to_letter(value) -> str:
    if value is None:
        return ''
    if isinstance(value, list):
        if not value:
            return ''
        value = value[0]
    s = str(value).strip()
    if not s:
        return ''
    if ',' in s:
        s = s.split(',')[0].strip()
    return _num_to_letter(s)

def export_wayground_docx(df, subject=''):
    doc = Document()
    title = f'Wayground 題目（{subject}）' if subject else 'Wayground 題目'
    doc.add_heading(title, level=1)
    q_num = 1
    for _, row in df.iterrows():
        q = str(row.get('question','')).strip()
        if not q:
            continue
        o1 = str(row.get('option_1','')).strip()
        o2 = str(row.get('option_2','')).strip()
        o3 = str(row.get('option_3','')).strip()
        o4 = str(row.get('option_4','')).strip()
        correct_letter = _normalize_correct_to_letter(row.get('correct',''))
        doc.add_paragraph(f'{q_num}. {q}')
        doc.add_paragraph(f'A. {o1}')
        doc.add_paragraph(f'B. {o2}')
        doc.add_paragraph(f'C. {o3}')
        doc.add_paragraph(f'D. {o4}')
        doc.add_paragraph(f'答案：{correct_letter}')
        doc.add_paragraph('')
        q_num += 1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
