import json
import os

FILE = 'cache.json'

def load_cache():
    if os.path.exists(FILE):
        with open(FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_cache(data):
    with open(FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
