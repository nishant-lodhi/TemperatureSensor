"""Authentication — Secrets Manager token resolution + signed cookie management.

Flow:
  1. Admin creates a secret in Secrets Manager: TempMonitor/{deploy_id}/{client_id}
  2. Officer visits /connect/{token} — token is resolved to a client_id
  3. Signed HttpOnly cookie is set — subsequent requests use the cookie
  4. Cookie contains token_hint (first 8 chars) for revocation detection
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

import flask

logger = logging.getLogger(__name__)

_TOKEN_MAP: dict = {}
_TOKEN_MAP_TS: float = 0
_CACHE_TTL = 300  # 5 minutes

DEPLOYMENT_ID = os.environ.get("DEPLOYMENT_ID", "0000000000")
COOKIE_SECRET = os.environ.get("COOKIE_SECRET", "local-dev-secret-key")
COOKIE_NAME = "tm_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


def load_token_map(deployment_id: Optional[str] = None) -> dict:
    """Read all TempMonitor/{deployment_id}/* secrets, return {token: {client_id, client_name}}.

    Results are cached for 5 minutes to avoid excessive Secrets Manager calls.
    """
    global _TOKEN_MAP, _TOKEN_MAP_TS
    now = time.time()
    if _TOKEN_MAP and (now - _TOKEN_MAP_TS) < _CACHE_TTL:
        return _TOKEN_MAP

    deploy_id = deployment_id or DEPLOYMENT_ID
    prefix = f"TempMonitor/{deploy_id}/"

    try:
        import boto3
        sm = boto3.client("secretsmanager")
        token_map = {}
        paginator = sm.get_paginator("list_secrets")
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for entry in page.get("SecretList", []):
                try:
                    resp = sm.get_secret_value(SecretId=entry["Name"])
                    data = json.loads(resp["SecretString"])
                    token = data.get("access_token", "")
                    if token:
                        token_map[token] = {
                            "client_id": data.get("client_id", ""),
                            "client_name": data.get("client_name", "Unknown"),
                        }
                except Exception:
                    continue
        _TOKEN_MAP = token_map
        _TOKEN_MAP_TS = now
    except Exception as exc:
        logger.warning("Failed to load token map from Secrets Manager: %s", exc)

    return _TOKEN_MAP


def resolve_token(token: str) -> Optional[dict]:
    """Look up access_token -> {client_id, client_name} from cache."""
    token_map = load_token_map()
    return token_map.get(token)


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_cookie(client_id: str, client_name: str, token_hint: str, secret: Optional[str] = None) -> str:
    """Create a signed cookie value: base64(payload) + '.' + hmac_signature."""
    secret = secret or COOKIE_SECRET
    exp = int(time.time()) + COOKIE_MAX_AGE
    payload = json.dumps({
        "cid": client_id,
        "cn": client_name,
        "th": token_hint,
        "exp": exp,
    }, separators=(",", ":")).encode()
    b64 = base64.urlsafe_b64encode(payload).decode()
    sig = _sign(payload, secret)
    return f"{b64}.{sig}"


def verify_cookie(cookie_value: str, secret: Optional[str] = None) -> Optional[dict]:
    """Verify signature, check expiry, return {client_id, client_name, token_hint} or None."""
    secret = secret or COOKIE_SECRET
    try:
        b64, sig = cookie_value.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(b64)
        expected = _sign(payload, secret)
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if data.get("exp", 0) < time.time():
            return None
        return {
            "client_id": data["cid"],
            "client_name": data["cn"],
            "token_hint": data["th"],
        }
    except Exception:
        return None


def validate_token_hint(client_id: str, token_hint: str) -> bool:
    """Check that token_hint matches current token for the client in the cache."""
    token_map = load_token_map()
    for token, info in token_map.items():
        if info["client_id"] == client_id:
            return token[:8] == token_hint
    return False


def get_client_id() -> Optional[str]:
    """Read client_id from Flask g context (set by auth middleware)."""
    return getattr(flask.g, "client_id", None)


def get_client_name() -> Optional[str]:
    """Read client_name from Flask g context (set by auth middleware)."""
    return getattr(flask.g, "client_name", None)
