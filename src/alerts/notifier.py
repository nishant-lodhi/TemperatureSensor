"""Alert notification via SNS."""

import logging

from config import settings

logger = logging.getLogger(__name__)

_sns_client = None


def _get_client():
    global _sns_client
    if _sns_client is None:
        try:
            import boto3
            _sns_client = boto3.client("sns", region_name=getattr(settings, "AWS_REGION", "us-east-1"))
        except Exception as e:
            logger.warning("SNS client init failed: %s", e)
    return _sns_client


def reset():
    """Clear cached SNS client."""
    global _sns_client
    _sns_client = None


def _format_message(alert: dict) -> str:
    """Multi-line string with alert details."""
    lines = [
        f"Alert: {alert.get('alert_type', 'UNKNOWN')}",
        f"Severity: {alert.get('severity', '')}",
        f"Message: {alert.get('message', '')}",
        f"Triggered: {alert.get('triggered_at', '')}",
        f"Status: {alert.get('status', '')}",
    ]
    for k, v in alert.items():
        if k in ("alert_type", "severity", "message", "triggered_at", "status"):
            continue
        if v is not None:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def send_alert(alert: dict) -> bool:
    """Route to SNS topic by severity. CRITICAL/HIGH -> critical topic, others -> standard. Log if no ARN."""
    severity = alert.get("severity", "")
    critical_arn = getattr(settings, "CRITICAL_ALERT_TOPIC_ARN", "") or ""
    standard_arn = getattr(settings, "STANDARD_ALERT_TOPIC_ARN", "") or ""

    if severity in ("CRITICAL", "HIGH"):
        arn = critical_arn
    else:
        arn = standard_arn

    subject = (alert.get("message", "") or "Alert")[:100]
    body = _format_message(alert)

    if not arn:
        logger.info("[LOCAL] Alert: %s | %s", subject, body.replace("\n", " | "))
        return True

    client = _get_client()
    if not client:
        logger.warning("No SNS client; logging alert: %s", subject)
        return False

    try:
        client.publish(TopicArn=arn, Subject=subject, Message=body)
        return True
    except Exception as e:
        logger.error("SNS publish failed: %s", e)
        return False


def send_escalation(alert: dict, target: str) -> bool:
    """Send modified alert with escalation info."""
    esc = dict(alert)
    esc["escalation_target"] = target
    esc["message"] = f"[ESCALATED to {target}] {alert.get('message', '')}"
    return send_alert(esc)
