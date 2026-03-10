"""Shared test fixtures.

Sets AWS_MODE=false and initializes the Dash app with mock auth context
before any callback tests run.
"""

import os

import pytest

os.environ.setdefault("AWS_MODE", "false")


@pytest.fixture(autouse=True, scope="session")
def _init_dash_app():
    """Initialize Dash app once for the entire test session.

    Pages must be imported BEFORE pushing a request context,
    otherwise Dash 4.x thinks register_page is called inside a callback.
    """
    import app.main  # noqa: F401 — creates Dash app and triggers page discovery
    import app.pages.history  # noqa: F401
    import app.pages.monitor  # noqa: F401 — ensure page modules are loaded


@pytest.fixture(autouse=True)
def _request_context():
    """Push a Flask request context with auth info for each test."""
    import app.main
    ctx = app.main.server.test_request_context()
    ctx.push()
    from flask import g
    g.client_id = "demo_client_1"
    g.client_name = "Demo Facility"
    yield
    ctx.pop()


@pytest.fixture()
def provider():
    """Return a fresh mock data provider for demo_client_1."""
    from app.data.mock_provider import MockProvider
    return MockProvider("demo_client_1")
