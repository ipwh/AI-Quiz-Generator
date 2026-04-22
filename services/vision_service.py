# =========================================================
# vision_service.py
# 穩定版 Vision OCR / Vision 出題模組
# 原則：
# ✅ 與 llm_service.py 分離
# ✅ 自動判斷模型是否支援 Vision
# ✅ 任何失敗都安全 fallback 到純文字流程
# =========================================================

import base64
import mimetypes
from typing import List

from services.llm_service import generate_questions

# ---------------------------------------------------------
# 模型能力判斷
# ---------------------------------------------------------

def supports_vision(cfg: dict) -> bool:
    model = (cfg.get("model") or "").lower()
    return (
        "gpt-4o" in model
        or model.startswith("grok")
        or "vision" in model
    )


# ---------------------------------------------------------
# Utils: image file -> data URL
# ---------------------------------------------------------

def file_to_data_url(file_bytes: bytes, filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    if not mime:
        mime = "image/png"
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------
# Vision OCR（純文字抽取）
# ---------------------------------------------------------

def vision_ocr_extract_text(cfg: dict, image_data_urls: List[str], lang_hint: str = "zh-Hant") -> str:
    if not supports_vision(cfg):
        raise RuntimeError("模型不支援 Vision")

    prompt = (
        "你是一個 OCR 文字抽取器。\n"
        "請從圖片中抽取所有可辨識文字，只輸出純文字，不要任何解釋。\n"
        f"語言提示：{lang_hint}"
    )

    content = [{"type": "text", "text": prompt}]
    for url in image_data_urls:
        content.append({
            "type": "image_url",
            "image_url": {"url": url, "detail": "high"},
        })

    from services.llm_service import _chat  # lazy import

    return _chat(
        cfg,
        messages=[{"role": "user", "content": content}],
        temperature=0,
        max_tokens=2500,
        timeout=180,
    ).strip()


# ---------------------------------------------------------
# Vision 出題（自動 fallback）
# ---------------------------------------------------------

def vision_generate_questions(
    cfg: dict,
    text: str,
    image_data_urls: List[str],
    subject: str,
    level: str,
    question_count: int,
    fast_mode: bool = True,
):
    """
    Vision 出題主入口。
    - 若模型不支援 Vision 或過程失敗，會自動 fallback 至 generate_questions()
    """

    try:
        if not supports_vision(cfg):
            raise RuntimeError("模型不支援 Vision")

        ocr_text = vision_ocr_extract_text(cfg, image_data_urls)
        merged_text = (text or "") + "\n\n" + ocr_text

        return generate_questions(
            cfg,
            merged_text,
            subject=subject,
            level=level,
            question_count=question_count,
            fast_mode=fast_mode,
        )

    except Exception:
        # ✅ 穩定 fallback
        return generate_questions(
            cfg,
            text,
            subject=subject,
            level=level,
            question_count=question_count,
            fast_mode=fast_mode,
        )
