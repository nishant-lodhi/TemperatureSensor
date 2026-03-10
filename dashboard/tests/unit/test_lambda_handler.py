"""Tests for dashboard/lambda_handler.py — Lambda WSGI entry point."""

import pytest

serverless_wsgi = pytest.importorskip("serverless_wsgi", reason="serverless_wsgi not installed in dev env")


class TestLambdaHandler:
    def test_handler_is_callable(self):
        from lambda_handler import handler
        assert callable(handler)

    def test_server_is_flask_app(self):
        from flask import Flask

        from lambda_handler import server
        assert isinstance(server, Flask)

    def test_handler_with_minimal_event(self):
        """Ensure handler doesn't crash on a minimal API Gateway v2 event."""
        from lambda_handler import handler

        event = {
            "version": "2.0",
            "requestContext": {
                "http": {
                    "method": "GET",
                    "path": "/",
                    "sourceIp": "127.0.0.1",
                    "protocol": "HTTP/1.1",
                },
                "accountId": "123456789012",
                "apiId": "api-id",
                "stage": "$default",
                "requestId": "req-id",
                "time": "09/Mar/2026:00:00:00 +0000",
                "timeEpoch": 1773100800000,
            },
            "rawPath": "/",
            "rawQueryString": "",
            "headers": {
                "host": "example.com",
                "accept": "text/html",
            },
            "isBase64Encoded": False,
        }
        result = handler(event, None)
        assert "statusCode" in result
        assert result["statusCode"] in (200, 302, 308)
