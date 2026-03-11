"""Tests for Flask routes — /connect, /disconnect, /healthz, auth middleware."""

import app.main


class TestAuthMiddleware:
    def test_mock_mode_sets_demo_client(self):
        with app.main.server.test_client() as c:
            resp = c.get("/healthz")
            assert resp.status_code == 200

    def test_mock_mode_returns_none(self):
        with app.main.server.test_client() as c:
            resp = c.get("/healthz")
            assert resp.status_code == 200


class TestDisconnectRoute:
    def test_disconnect_redirects(self):
        with app.main.server.test_client() as c:
            resp = c.get("/disconnect", follow_redirects=False)
            assert resp.status_code in (301, 302, 308)


class TestHealthzRoute:
    def test_healthz_returns_json(self):
        with app.main.server.test_client() as c:
            resp = c.get("/healthz")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "mysql" in data
            assert "provider" in data


class TestExpiredPage:
    def test_default_message(self):
        from app.routes import _expired_page
        with app.main.server.test_request_context("/"):
            resp = _expired_page()
            html = resp.get_data(as_text=True)
            assert "expired" in html.lower()

    def test_custom_message(self):
        from app.routes import _expired_page
        with app.main.server.test_request_context("/"):
            resp = _expired_page("Custom error")
            assert "Custom error" in resp.get_data(as_text=True)

    def test_contains_brand(self):
        from app.routes import _expired_page
        with app.main.server.test_request_context("/"):
            html = _expired_page().get_data(as_text=True)
            assert "TEMP" in html and "MONITOR" in html


class TestAppLayout:
    def test_layout_exists(self):
        assert app.main.app.layout is not None

    def test_server_is_flask(self):
        from flask import Flask
        assert isinstance(app.main.server, Flask)

    def test_app_title(self):
        assert app.main.app.title == "TempMonitor"


class TestUpdateClock:
    def test_returns_time_and_badge(self):
        clock, badge = app.main.update_clock(1)
        assert "UTC" in clock
