"""Test fixture 3: rich-like terminal formatting library.

Patterns: style cache, layout cache, export cache with missing parameters.
"""
import hashlib
import json
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple


# BUG: cache rendering only uses segments, missing style
# → same content with different styles would share cache
_render_cache: Dict[str, str] = {}

def cache_render(segments: List[str], style: Optional[str] = None) -> str:
    key = hashlib.sha256(json.dumps(segments).encode()).hexdigest()
    if key in _render_cache:
        return _render_cache[key]
    rendered = "".join(segments)
    _render_cache[key] = rendered
    return rendered


# CORRECT: all params in hash
def hash_export(text: str, width: int, height: int) -> str:
    h = hashlib.sha256()
    h.update(text.encode())
    h.update(str(width).encode())
    h.update(str(height).encode())
    return h.hexdigest()


# BUG: missing encoding parameter
_export_cache: Dict[str, bytes] = {}

def export_svg(text: str, width: int, height: int, encoding: str = "utf-8") -> bytes:
    key = hashlib.sha256(f"{text}:{width}:{height}".encode()).hexdigest()
    if key in _export_cache:
        return _export_cache[key]
    svg = f"<svg width='{width}' height='{height}'>{text}</svg>".encode()
    _export_cache[key] = svg
    return svg


# BUG: missing theme parameter in style cache
_style_cache: Dict[str, Dict[str, Any]] = {}

def get_style(name: str, theme: str = "default") -> Dict[str, Any]:
    key = hashlib.md5(name.encode()).hexdigest()
    return _style_cache.get(key, {})
