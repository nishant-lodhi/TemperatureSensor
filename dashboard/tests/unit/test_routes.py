"""Tests for Flask routes in app.main — /connect, /disconnect, auth middleware."""

from unittest.mock import patch

import app.main

# ── Auth middleware ────────────────────────────────────────


class TestAuthMiddleware:
    def test_mock_mode_sets_demo_client(self):
        """In mock mode, middleware sets g.client_id = demo_client_1."""
        with app.main.server.test_request_context("/"):
            app.main.auth_middleware()
            from flask import g
            assert g.client_id == "demo_client_1"
            assert g.client_name == "Demo Facility"

    def test_mock_mode_returns_none(self):
        with app.main.server.test_request_context("/"):
            result = app.main.auth_middleware()
            assert result is None

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_skip_auth_for_connect(self):
        with app.main.server.test_request_context("/connect/test-token"):
            result = app.main.auth_middleware()
            assert result is None

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_skip_auth_for_assets(self):
        with app.main.server.test_request_context("/assets/style.css"):
            result = app.main.auth_middleware()
            assert result is None

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_skip_auth_for_dash_internal(self):
        with app.main.server.test_request_context("/_dash-component-suites/something"):
            result = app.main.auth_middleware()
            assert result is None

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_skip_auth_for_disconnect(self):
        with app.main.server.test_request_context("/disconnect"):
            result = app.main.auth_middleware()
            assert result is None

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_no_cookie_returns_expired_page(self):
        with app.main.server.test_request_context("/", headers={}):
            result = app.main.auth_middleware()
            assert result is not None
            html = result.get_data(as_text=True)
            assert "expired" in html.lower() or "TEMPMONITOR" in html

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_invalid_cookie_clears_cookie(self):
        with app.main.server.test_request_context("/", headers={"Cookie": "tm_session=bad-value"}):
            result = app.main.auth_middleware()
            assert result is not None

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_valid_cookie_with_valid_hint(self):
        from app.auth import COOKIE_SECRET, create_cookie
        cookie_val = create_cookie("c1", "TestFacility", "abcd1234", COOKIE_SECRET)
        with patch("app.auth.validate_token_hint", return_value=True):
            with app.main.server.test_request_context("/", headers={"Cookie": f"tm_session={cookie_val}"}):
                result = app.main.auth_middleware()
                assert result is None
                from flask import g
                assert g.client_id == "c1"
                assert g.client_name == "TestFacility"

    @patch("app.main.cfg.AWS_MODE", True)
    def test_aws_mode_valid_cookie_revoked_hint(self):
        from app.auth import COOKIE_SECRET, create_cookie
        cookie_val = create_cookie("c1", "TestFacility", "abcd1234", COOKIE_SECRET)
        with patch("app.auth.validate_token_hint", return_value=False):
            with app.main.server.test_request_context("/", headers={"Cookie": f"tm_session={cookie_val}"}):
                result = app.main.auth_middleware()
                assert result is not None
                html = result.get_data(as_text=True)
                assert "updated" in html.lower() or "expired" in html.lower()


# ── /disconnect ───────────────────────────────────────────


class TestDisconnectRoute:
    def test_disconnect_redirects(self):
        """Use a direct request context to bypass Dash page validation."""
        with app.main.server.test_request_context("/disconnect"):
            resp = app.main.disconnect()
            assert resp.status_code in (301, 302, 308)
            set_cookie = resp.headers.get("Set-Cookie", "")
            assert "tm_session" in set_cookie


# ── Expired page ──────────────────────────────────────────


class TestExpiredPage:
    def test_expired_page_default_message(self):
        with app.main.server.test_request_context("/"):
            resp = app.main._expired_page()
            html = resp.get_data(as_text=True)
            assert "session has expired" in html.lower()
            assert "TEMPMONITOR" in html or "TempMonitor" in html

    def test_expired_page_custom_message(self):
        with app.main.server.test_request_context("/"):
            resp = app.main._expired_page("Custom error message")
            html = resp.get_data(as_text=True)
            assert "Custom error message" in html

    def test_expired_page_contains_brand_colors(self):
        from app import config as cfg
        with app.main.server.test_request_context("/"):
            resp = app.main._expired_page()
            html = resp.get_data(as_text=True)
            assert cfg.COLORS["bg"] in html
            assert cfg.COLORS["primary"] in html

    def test_expired_page_has_dm_sans_font(self):
        with app.main.server.test_request_context("/"):
            resp = app.main._expired_page()
            html = resp.get_data(as_text=True)
            assert "DM Sans" in html


# ── App layout ────────────────────────────────────────────


class TestAppLayout:
    def test_layout_exists(self):
        assert app.main.app.layout is not None

    def test_server_is_flask(self):
        from flask import Flask
        assert isinstance(app.main.server, Flask)

    def test_app_title(self):
        assert app.main.app.title == "TempMonitor"


# ── Callback: update_clock ────────────────────────────────


class TestUpdateClock:
    def test_returns_time_and_badge(self):
        clock, badge = app.main.update_clock(1)
        assert "UTC" in clock
        assert ":" in clock
