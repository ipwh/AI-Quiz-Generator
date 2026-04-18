import json
import os
from typing import Any, Dict

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", ".cache.json")


def load_cache() -> Dict[str, Any]:
    """讀取本地 JSON cache；檔案不存在或損壞就回傳空 dict。"""
    try:
        if not os.path.exists(CACHE_PATH):
            return {}
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(cache: Dict[str, Any], max_items: int = 200) -> None:
    """寫入本地 JSON cache；限制最多保留 max_items 筆避免無限增長。"""
    try:
        if not isinstance(cache, dict):
            return

        if max_items and len(cache) > max_items:
            cache = dict(list(cache.items())[-max_items:])

        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
