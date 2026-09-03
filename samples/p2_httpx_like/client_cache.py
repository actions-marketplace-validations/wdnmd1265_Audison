"""Test fixture 2: requests-like HTTP client project.

Patterns: cache key bypass, ETag handling, cookie jar signing.
"""
import hashlib
import json
import time
from typing import Any, Dict, Optional, Tuple


# BUG: make_cache_key uses url but not headers → caching behavior
# should differ based on accept/cache-control headers but doesn't
_cache_store: Dict[str, Tuple[Any, float]] = {}

def make_cache_key(url: str, headers: Dict[str, str] = None) -> str:
    return hashlib.sha256(url.encode()).hexdigest()

def cache_get(url: str, headers: Dict[str, str] = None) -> Optional[Any]:
    key = make_cache_key(url, headers)
    entry = _cache_store.get(key)
    if entry:
        data, expires = entry
        if time.time() < expires:
            return data
        del _cache_store[key]
    return None


# CORRECT: uses all params in hash
def hash_request(url: str, method: str, body: bytes) -> str:
    h = hashlib.sha256()
    h.update(url.encode())
    h.update(method.encode())
    h.update(body)
    return h.hexdigest()


# BUG: salt not included in hash → session fixation risk
def sign_cookie(value: str, salt: str = "") -> str:
    h = hashlib.blake2b(value.encode(), key=b"secret")
    return h.hexdigest()


# BUG: missing domain parameter → cookie domain confusion
_cookie_store: Dict[str, str] = {}

def store_cookie(name: str, value: str, domain: str = "") -> None:
    key = hashlib.sha256(f"{name}:{value}".encode()).hexdigest()
    _cookie_store[key] = domain
