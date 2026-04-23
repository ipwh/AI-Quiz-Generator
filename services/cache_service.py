import json
import os
import time
from typing import Any, Dict

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", ".cache.json")
CACHE_EXPIRY_HOURS = 24  # 快取 24 小時後過期


def load_cache() -> Dict[str, Any]:
    """
    讀取本地 JSON cache；檔案不存在或損壞就回傳空 dict。
    同時檢查快取過期時間，移除已過期的項目。
    """
    try:
        if not os.path.exists(CACHE_PATH):
            return {}
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            
            # 檢查並移除過期的快取項目
            current_time = time.time()
            cache_expiry_seconds = CACHE_EXPIRY_HOURS * 3600
            
            # 遍歷並移除過期項目
            expired_keys = []
            for key, value in data.items():
                if isinstance(value, dict) and "_timestamp" in value:
                    timestamp = value.get("_timestamp", 0)
                    if current_time - timestamp > cache_expiry_seconds:
                        expired_keys.append(key)
            
            for key in expired_keys:
                del data[key]
            
            # 若有移除過期項目，保存更新後的快取
            if expired_keys:
                save_cache(data, max_items=None)
            
            return data
    except Exception:
        return {}


def save_cache(cache: Dict[str, Any], max_items: int = 200) -> None:
    """
    寫入本地 JSON cache；限制最多保留 max_items 筆避免無限增長。
    每個快取項目會自動添加 _timestamp，用於過期檢查。
    
    Args:
        cache: 要保存的快取字典
        max_items: 最多保留項目數（None 表示不限制）
    """
    try:
        if not isinstance(cache, dict):
            return

        current_time = time.time()
        
        # 為每個項目添加或更新時間戳（如果尚無時間戳）
        for key in cache:
            if isinstance(cache[key], dict) and "_timestamp" not in cache[key]:
                cache[key]["_timestamp"] = current_time

        # 限制快取大小
        if max_items and len(cache) > max_items:
            # 按時間戳排序，保留最新的 max_items 項
            sorted_items = sorted(
                cache.items(),
                key=lambda x: x[1].get("_timestamp", 0) if isinstance(x[1], dict) else 0,
                reverse=True
            )
            cache = dict(sorted_items[:max_items])

        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def clear_expired_cache() -> int:
    """
    手動清除所有過期快取項目。
    返回被移除的項目數。
    """
    try:
        cache = load_cache()
        current_time = time.time()
        cache_expiry_seconds = CACHE_EXPIRY_HOURS * 3600
        
        removed_count = 0
        for key in list(cache.keys()):
            if isinstance(cache[key], dict) and "_timestamp" in cache[key]:
                timestamp = cache[key].get("_timestamp", 0)
                if current_time - timestamp > cache_expiry_seconds:
                    del cache[key]
                    removed_count += 1
        
        if removed_count > 0:
            save_cache(cache, max_items=None)
        
        return removed_count
    except Exception:
        return 0

