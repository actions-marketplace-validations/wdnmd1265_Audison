"""Test fixture 1: fastapi-like project with intentional hash/cache bugs.

Patterns from real-world open-source: missing parameters in cache key construction.
"""
import hashlib
import json
from typing import Any, Dict, Optional


# BUG: cache_key only uses key, missing namespace
# → 不同 namespace 下的相同 key 会产生冲突
_cache: Dict[str, Any] = {}

def get_from_cache(key: str, namespace: str = "default") -> Optional[Any]:
    cache_key = hashlib.sha256(key.encode()).hexdigest()
    return _cache.get(cache_key)

def set_cache(key: str, value: Any, namespace: str = "default"):
    cache_key = hashlib.sha256(key.encode()).hexdigest()
    _cache[cache_key] = value


# BUG: etag only uses content, missing content_type
# → 不同 content_type 但相同 content 的响应返回相同 etag
def compute_etag(content: str, content_type: str = "text/plain") -> str:
    return hashlib.md5(content.encode()).hexdigest()


# CORRECT: all params used in hash
def hash_route(path: str, methods: list, host: str) -> str:
    data = json.dumps({"path": path, "methods": methods, "host": host})
    return hashlib.sha256(data.encode()).hexdigest()


# BUG: only uses file_path, missing etag
_fingerprint_cache: Dict[str, str] = {}

def file_fingerprint(file_path: str, etag: str = "") -> str:
    cached = _fingerprint_cache.get(file_path)
    if cached:
        return cached
    h = hashlib.sha256(file_path.encode()).hexdigest()
    _fingerprint_cache[file_path] = h
    return h
