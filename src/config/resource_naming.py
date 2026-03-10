"""Resource naming convention for AWS resources.

Pattern: {prefix}-{resource_type}-{deployment_id}-{environment}
Example: temp-sensor-platform-config-18i93d7c8d-dev

The deployment_id is a user-defined 10-character identifier that uniquely
identifies a deployment. Combined with environment, this allows multiple
isolated stacks within the same AWS account.
"""


def build_name(
    resource_type: str,
    prefix: str = "temp-sensor",
    deployment_id: str = "0000000000",
    environment: str = "dev",
) -> str:
    """Build a single resource name following the naming convention."""
    if not resource_type:
        raise ValueError("resource_type is required")
    return f"{prefix}-{resource_type}-{deployment_id}-{environment}"


def build_all_names(
    prefix: str = "temp-sensor",
    deployment_id: str = "0000000000",
    environment: str = "dev",
) -> dict[str, str]:
    """Build all resource names for a deployment."""

    def _n(rt):
        return build_name(rt, prefix, deployment_id, environment)

    return {
        "stack_name": _n("stack"),
        "platform_config_table": _n("platform-config"),
        "sensor_data_table": _n("sensor-data"),
        "alerts_table": _n("alerts"),
        "data_stream": _n("data-stream"),
        "data_bucket": _n("data-lake"),
        "critical_alert_topic": _n("critical-alerts"),
        "standard_alert_topic": _n("standard-alerts"),
        "batch_processor_fn": _n("batch-processor"),
        "critical_alert_fn": _n("critical-alert"),
        "scheduled_processor_fn": _n("scheduled-processor"),
        "lambda_layer": _n("deps-layer"),
    }
