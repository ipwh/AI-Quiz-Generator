import io
import re

import fitz  # PyMuPDF
import docx
import openpyxl
from pptx import Presentation


def _clean_text(s: str) -> str:
    if not s:
        return ''
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _extract_pdf_text(data: bytes) -> str:
    text = ''
    with fitz.open(stream=data, filetype='pdf') as doc:
        for page in doc:
            text += page.get_text()
    return _clean_text(text)


def _extract_docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    text = '\n'.join(p.text for p in document.paragraphs if p.text)
    return _clean_text(text)


def _extract_txt_text(data: bytes) -> str:
    try:
        return _clean_text(data.decode('utf-8'))
    except Exception:
        return _clean_text(data.decode('utf-8', errors='ignore'))


def _extract_xlsx_text(data: bytes) -> str:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    chunks = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if cell is None:
                    continue
                s = str(cell).strip()
                if s:
                    chunks.append(s)
    return _clean_text('\n'.join(chunks))


def _extract_pptx_text(data: bytes) -> str:
    prs = Presentation(io.BytesIO(data))
    chunks = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, 'text'):
                s = str(shape.text).strip()
                if s:
                    chunks.append(s)
    return _clean_text('\n'.join(chunks))


def extract_text(file) -> str:
    ext = file.name.split('.')[-1].lower()
    data = file.getvalue()

    if ext == 'pdf':
        return _extract_pdf_text(data)
    if ext == 'docx':
        return _extract_docx_text(data)
    if ext == 'txt':
        return _extract_txt_text(data)
    if ext == 'xlsx':
        return _extract_xlsx_text(data)
    if ext == 'pptx':
        return _extract_pptx_text(data)

    # 不支援：圖片（已移除 OCR）及舊格式 doc/xls/ppt
    return ''
