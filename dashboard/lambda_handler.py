"""AWS Lambda entry point — wraps the Dash/Flask WSGI app for serverless."""

import logging
import time

import serverless_wsgi

from app.main import server

logger = logging.getLogger("tempsensor")
logger.setLevel(logging.INFO)

_cold = True


def handler(event, context):
    global _cold
    t0 = time.time()
    method = event.get("requestContext", {}).get("http", {}).get("method", "?")
    path = event.get("rawPath", event.get("path", "/"))

    if _cold:
        fn = getattr(context, "function_name", "local")
        logger.info("COLD_START fn=%s", fn)
        _cold = False

    resp = serverless_wsgi.handle_request(server, event, context)

    ms = (time.time() - t0) * 1000
    status = resp.get("statusCode", "?")
    logger.info("REQ %s %s → %s (%.0fms)", method, path, status, ms)
    return resp
