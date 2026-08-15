from __future__ import annotations

import hashlib
import hmac

from app.core.security.password import verify_password


REFRESH_TOKEN_HASH_PREFIX = "sha256:"


def hash_refresh_token(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{REFRESH_TOKEN_HASH_PREFIX}{digest}"


def verify_refresh_token_hash(token: str, stored_hash: str) -> bool:
    if stored_hash.startswith(REFRESH_TOKEN_HASH_PREFIX):
        expected = hash_refresh_token(token)
        return hmac.compare_digest(expected, stored_hash)

    # Sessions created before this format used bcrypt and remain valid until rotation.
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return verify_password(token, stored_hash)
    return False
