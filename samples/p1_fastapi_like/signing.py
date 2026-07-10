"""Test fixture 1: fastapi-like project — response signing.

BUG: sign_response uses body but not status_code → different HTTP status codes
with same body could share the same validation signature.
"""
import hashlib
import hmac
import time
from typing import Optional


SECRET = b"test-secret-key-1234567890abcdef"


# BUG: missing status_code in sign → 200 OK and 404 Not Found with same body
# would have identical signatures
def sign_response(body: str, status_code: int = 200, timestamp: Optional[int] = None) -> str:
    ts = timestamp or int(time.time())
    data = f"{body}:{ts}".encode()
    return hmac.new(SECRET, data, hashlib.sha256).hexdigest()


# BUG: missing algorithm parameter in hash comparison
# → downgrade attack possible if attacker supplies weaker hash
def verify_hash(data: str, expected: str, algorithm: str = "sha256") -> bool:
    h = hashlib.new("sha256")
    h.update(data.encode())
    return h.hexdigest() == expected
