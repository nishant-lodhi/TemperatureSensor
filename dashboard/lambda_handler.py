"""AWS Lambda entry point — wraps the Dash/Flask WSGI app for serverless."""

import serverless_wsgi

from app.main import server


def handler(event, context):
    return serverless_wsgi.handle_request(server, event, context)
