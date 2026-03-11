"""Shared fixtures for dashboard tests.

Patches the data provider factory to return MockProvider.
Sets env vars so no real AWS / MySQL calls are made.
"""

import os
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("AWS_MODE", "false")
os.environ.setdefault("MYSQL_HOST", "localhost")
os.environ.setdefault("MYSQL_DATABASE", "test_db")
os.environ.setdefault("ALERTS_TABLE", "test-alerts")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.mock_provider import MockProvider  # noqa: E402


@pytest.fixture(autouse=True)
def flask_app_context():
    """Provide Flask app context + set g.client_id for all tests."""
    from app.main import server
    with server.app_context():
        from flask import g
        g.client_id = "test_client"
        g.client_name = "Test Facility"
        yield


@pytest.fixture(autouse=True)
def mock_provider():
    """Patch get_provider so every test gets a fresh MockProvider."""
    mp = MockProvider("test_client")
    with patch("app.data.provider.get_provider", return_value=mp):
        yield mp


@pytest.fixture
def provider(mock_provider):
    return mock_provider
