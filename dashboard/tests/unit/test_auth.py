"""Tests for app.auth — cookie signing, verification, token resolution, hints."""

import base64
import json
import time
from unittest.mock import MagicMock, patch

from app.auth import (
    COOKIE_MAX_AGE,
    _sign,
    create_cookie,
    get_client_id,
    get_client_name,
    resolve_token,
    validate_token_hint,
    verify_cookie,
)

SECRET = "test-secret-key-12345"


# ── Signing primitive ─────────────────────────────────────


class TestSign:
    def test_deterministic(self):
        sig1 = _sign(b"payload", SECRET)
        sig2 = _sign(b"payload", SECRET)
        assert sig1 == sig2

    def test_different_payloads(self):
        assert _sign(b"alpha", SECRET) != _sign(b"beta", SECRET)

    def test_different_secrets(self):
        assert _sign(b"data", "key-a") != _sign(b"data", "key-b")

    def test_returns_hex_string(self):
        sig = _sign(b"data", SECRET)
        assert isinstance(sig, str)
        int(sig, 16)  # valid hex


# ── Cookie creation ───────────────────────────────────────


class TestCreateCookie:
    def test_roundtrip(self):
        cookie = create_cookie("client_a", "Alpha Facility", "a7f3b2c1", SECRET)
        result = verify_cookie(cookie, SECRET)
        assert result is not None
        assert result["client_id"] == "client_a"
        assert result["client_name"] == "Alpha Facility"
        assert result["token_hint"] == "a7f3b2c1"

    def test_contains_dot_separator(self):
        cookie = create_cookie("c", "N", "hint1234", SECRET)
        assert "." in cookie

    def test_base64_payload_decodable(self):
        cookie = create_cookie("c", "N", "hint1234", SECRET)
        b64 = cookie.rsplit(".", 1)[0]
        decoded = json.loads(base64.urlsafe_b64decode(b64))
        assert decoded["cid"] == "c"
        assert decoded["cn"] == "N"
        assert decoded["th"] == "hint1234"
        assert "exp" in decoded

    def test_expiration_is_30_days_ahead(self):
        before = int(time.time())
        cookie = create_cookie("c", "N", "12345678", SECRET)
        after = int(time.time())
        b64 = cookie.rsplit(".", 1)[0]
        exp = json.loads(base64.urlsafe_b64decode(b64))["exp"]
        assert before + COOKIE_MAX_AGE <= exp <= after + COOKIE_MAX_AGE

    def test_unicode_client_name(self):
        cookie = create_cookie("c", "Ünîcödé Fàcîlîty", "hintaaaa", SECRET)
        result = verify_cookie(cookie, SECRET)
        assert result["client_name"] == "Ünîcödé Fàcîlîty"

    def test_uses_default_secret_when_none(self):
        cookie = create_cookie("c", "N", "hint1234")
        result = verify_cookie(cookie)
        assert result is not None
        assert result["client_id"] == "c"


# ── Cookie verification ───────────────────────────────────


class TestVerifyCookie:
    def test_wrong_secret_fails(self):
        cookie = create_cookie("client_a", "Alpha", "abcd1234", SECRET)
        assert verify_cookie(cookie, "wrong-secret") is None

    def test_tampered_payload_fails(self):
        cookie = create_cookie("client_a", "Alpha", "abcd1234", SECRET)
        b64, sig = cookie.rsplit(".", 1)
        tampered = "X" + b64[1:]
        assert verify_cookie(f"{tampered}.{sig}", SECRET) is None

    def test_tampered_signature_fails(self):
        cookie = create_cookie("client_a", "Alpha", "abcd1234", SECRET)
        b64, sig = cookie.rsplit(".", 1)
        bad_sig = "0" * len(sig)
        assert verify_cookie(f"{b64}.{bad_sig}", SECRET) is None

    def test_expired_cookie_fails(self):
        payload = json.dumps({
            "cid": "client_a", "cn": "Alpha",
            "th": "abcd1234", "exp": int(time.time()) - 100,
        }, separators=(",", ":")).encode()
        b64 = base64.urlsafe_b64encode(payload).decode()
        sig = _sign(payload, SECRET)
        assert verify_cookie(f"{b64}.{sig}", SECRET) is None

    def test_empty_string_fails(self):
        assert verify_cookie("", SECRET) is None

    def test_garbage_fails(self):
        assert verify_cookie("not-a-cookie", SECRET) is None

    def test_no_dot_fails(self):
        assert verify_cookie("nodothere", SECRET) is None

    def test_multiple_dots_handled(self):
        cookie = create_cookie("c", "N", "hint1234", SECRET)
        result = verify_cookie(cookie, SECRET)
        assert result is not None

    def test_invalid_base64_fails(self):
        assert verify_cookie("!!!invalid-base64!!!.fakesig", SECRET) is None

    def test_valid_json_but_missing_fields_fails(self):
        payload = json.dumps({"foo": "bar", "exp": int(time.time()) + 3600},
                             separators=(",", ":")).encode()
        b64 = base64.urlsafe_b64encode(payload).decode()
        sig = _sign(payload, SECRET)
        assert verify_cookie(f"{b64}.{sig}", SECRET) is None


# ── Multiple clients ──────────────────────────────────────


class TestMultipleClients:
    def test_different_clients_get_different_cookies(self):
        c1 = create_cookie("client_a", "Alpha", "aaaa1111", SECRET)
        c2 = create_cookie("client_b", "Beta", "bbbb2222", SECRET)
        assert c1 != c2
        r1 = verify_cookie(c1, SECRET)
        r2 = verify_cookie(c2, SECRET)
        assert r1["client_id"] == "client_a"
        assert r2["client_id"] == "client_b"

    def test_cookies_isolated(self):
        """Verifying one client's cookie doesn't leak another's info."""
        c1 = create_cookie("client_a", "Alpha", "aaaa1111", SECRET)
        r1 = verify_cookie(c1, SECRET)
        assert r1["token_hint"] == "aaaa1111"
        assert "client_b" not in str(r1)


# ── Token resolution (Secrets Manager) ────────────────────


class TestLoadTokenMap:
    def test_load_token_map_populates_cache(self):
        import app.auth as auth_mod
        auth_mod._TOKEN_MAP = {}
        auth_mod._TOKEN_MAP_TS = 0

        mock_sm = MagicMock()
        mock_paginator = MagicMock()
        mock_sm.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{
            "SecretList": [{
                "Name": "TempMonitor/0000000000/client_x"
            }]
        }]
        mock_sm.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "access_token": "tok-123-abc",
                "client_id": "client_x",
                "client_name": "Facility X",
            })
        }

        with patch("boto3.client", return_value=mock_sm):
            result = auth_mod.load_token_map("0000000000")
        assert "tok-123-abc" in result
        assert result["tok-123-abc"]["client_id"] == "client_x"
        assert result["tok-123-abc"]["client_name"] == "Facility X"

    def test_load_token_map_uses_cache_within_ttl(self):
        import app.auth as auth_mod
        auth_mod._TOKEN_MAP = {"cached-tok": {"client_id": "c1", "client_name": "N1"}}
        auth_mod._TOKEN_MAP_TS = time.time()
        result = auth_mod.load_token_map()
        assert "cached-tok" in result

    def test_load_token_map_handles_boto3_error(self):
        import app.auth as auth_mod
        auth_mod._TOKEN_MAP = {}
        auth_mod._TOKEN_MAP_TS = 0

        with patch("boto3.client", side_effect=Exception("AWS not available")):
            result = auth_mod.load_token_map()
        assert result == {}


class TestResolveToken:
    @patch("app.auth.load_token_map")
    def test_resolve_known_token(self, mock_load):
        mock_load.return_value = {"my-token": {"client_id": "c1", "client_name": "N1"}}
        result = resolve_token("my-token")
        assert result["client_id"] == "c1"

    @patch("app.auth.load_token_map")
    def test_resolve_unknown_token(self, mock_load):
        mock_load.return_value = {"other-tok": {"client_id": "c2", "client_name": "N2"}}
        assert resolve_token("nonexistent") is None


class TestValidateTokenHint:
    @patch("app.auth.load_token_map")
    def test_matching_hint(self, mock_load):
        mock_load.return_value = {"abcd1234-rest-of-token": {"client_id": "c1", "client_name": "N1"}}
        assert validate_token_hint("c1", "abcd1234") is True

    @patch("app.auth.load_token_map")
    def test_mismatching_hint(self, mock_load):
        mock_load.return_value = {"abcd1234-rest-of-token": {"client_id": "c1", "client_name": "N1"}}
        assert validate_token_hint("c1", "xxxx9999") is False

    @patch("app.auth.load_token_map")
    def test_unknown_client(self, mock_load):
        mock_load.return_value = {"tok": {"client_id": "c1", "client_name": "N1"}}
        assert validate_token_hint("unknown_client", "abcd1234") is False


# ── Flask context helpers ─────────────────────────────────


class TestFlaskContextHelpers:
    def test_get_client_id_returns_value(self):
        assert get_client_id() == "demo_client_1"

    def test_get_client_name_returns_value(self):
        assert get_client_name() == "Demo Facility"
