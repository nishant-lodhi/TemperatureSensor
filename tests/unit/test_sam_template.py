"""Validation tests for infra/template.yaml — SAM template structure and resources."""

import os

import pytest
import yaml

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "template.yaml")


class _CfnLoader(yaml.SafeLoader):
    """YAML loader that handles CloudFormation intrinsic functions (!Ref, !Sub, etc.)."""
    pass


for tag in ("!Ref", "!Sub", "!GetAtt", "!If", "!Equals", "!Select", "!Split",
            "!Join", "!FindInMap", "!ImportValue", "!Condition", "!Not", "!And", "!Or"):
    _CfnLoader.add_multi_constructor(
        tag, lambda loader, suffix, node: loader.construct_mapping(node)
        if isinstance(node, yaml.MappingNode) else loader.construct_sequence(node)
        if isinstance(node, yaml.SequenceNode) else loader.construct_scalar(node)
    )


@pytest.fixture(scope="module")
def template():
    with open(TEMPLATE_PATH) as f:
        return yaml.load(f, Loader=_CfnLoader)


# ── Template structure ────────────────────────────────────


class TestTemplateStructure:
    def test_has_aws_version(self, template):
        assert template.get("AWSTemplateFormatVersion") == "2010-09-09"

    def test_has_transform(self, template):
        assert "AWS::Serverless" in template.get("Transform", "")

    def test_has_description(self, template):
        assert len(template.get("Description", "")) > 0

    def test_has_parameters(self, template):
        params = template.get("Parameters", {})
        assert "Environment" in params
        assert "DeploymentId" in params
        assert "ProjectPrefix" in params
        assert "CookieSecret" in params

    def test_has_resources(self, template):
        assert len(template.get("Resources", {})) > 0

    def test_has_outputs(self, template):
        assert len(template.get("Outputs", {})) > 0


# ── New Parameters ───────────────────────────────────────────


class TestNewParameters:
    def test_synthetic_mode_param(self, template):
        p = template["Parameters"]["SyntheticMode"]
        assert p["Default"] == "true"
        assert set(p["AllowedValues"]) == {"true", "false"}

    def test_enable_iot_rule_param(self, template):
        p = template["Parameters"]["EnableIoTRule"]
        assert p["Default"] == "false"
        assert set(p["AllowedValues"]) == {"true", "false"}

    def test_iot_topic_pattern_param(self, template):
        p = template["Parameters"]["IoTTopicPattern"]
        assert p["Default"] == "sensors/temp"

    def test_synthetic_sensor_count_param(self, template):
        p = template["Parameters"]["SyntheticSensorCount"]
        assert p["Default"] == 20


# ── Parameters ────────────────────────────────────────────


class TestParameters:
    def test_environment_allowed_values(self, template):
        env = template["Parameters"]["Environment"]
        assert set(env["AllowedValues"]) == {"dev", "staging", "prod"}
        assert env["Default"] == "dev"

    def test_deployment_id_pattern(self, template):
        did = template["Parameters"]["DeploymentId"]
        assert did["AllowedPattern"] == "[a-z0-9]{10}"

    def test_cookie_secret_no_echo(self, template):
        cs = template["Parameters"]["CookieSecret"]
        assert cs.get("NoEcho") is True

    def test_kinesis_shard_count_default(self, template):
        ksc = template["Parameters"]["KinesisShardCount"]
        assert ksc["Default"] == 1


# ── Conditions ───────────────────────────────────────────────


class TestConditions:
    def test_has_synthetic_condition(self, template):
        assert "IsSyntheticMode" in template["Conditions"]

    def test_has_iot_rule_condition(self, template):
        assert "IsIoTRuleEnabled" in template["Conditions"]

    def test_has_generic_iot_condition(self, template):
        assert "IsGenericIoT" in template["Conditions"]

    def test_has_cookie_secret_condition(self, template):
        assert "GenerateCookieSecret" in template["Conditions"]


# ── Architecture ─────────────────────────────────────────────


class TestArchitecture:
    def test_global_architecture_x86(self, template):
        arch = template["Globals"]["Function"]["Architectures"]
        assert "x86_64" in arch
        assert "arm64" not in arch

    def test_layer_architecture_x86(self, template):
        layer = template["Resources"]["SharedDependenciesLayer"]
        assert "x86_64" in layer["Properties"]["CompatibleArchitectures"]


# ── Lambda Functions ──────────────────────────────────────


class TestLambdaFunctions:
    def test_batch_processor_exists(self, template):
        assert "BatchProcessorFunction" in template["Resources"]
        func = template["Resources"]["BatchProcessorFunction"]
        assert func["Type"] == "AWS::Serverless::Function"
        assert "batch_handler" in func["Properties"]["Handler"]

    def test_critical_alert_exists(self, template):
        assert "CriticalAlertFunction" in template["Resources"]
        func = template["Resources"]["CriticalAlertFunction"]
        assert "critical_handler" in func["Properties"]["Handler"]

    def test_scheduled_processor_exists(self, template):
        assert "ScheduledProcessorFunction" in template["Resources"]
        func = template["Resources"]["ScheduledProcessorFunction"]
        assert "scheduled_handler" in func["Properties"]["Handler"]

    def test_dashboard_function_exists(self, template):
        assert "DashboardFunction" in template["Resources"]
        func = template["Resources"]["DashboardFunction"]
        assert "lambda_handler" in func["Properties"]["Handler"]

    def test_dashboard_has_aws_mode_env(self, template):
        func = template["Resources"]["DashboardFunction"]
        env_vars = func["Properties"]["Environment"]["Variables"]
        assert env_vars.get("AWS_MODE") == "true"

    def test_dashboard_has_cookie_secret_env(self, template):
        func = template["Resources"]["DashboardFunction"]
        env_vars = func["Properties"]["Environment"]["Variables"]
        assert "COOKIE_SECRET" in env_vars

    def test_batch_processor_kinesis_event(self, template):
        func = template["Resources"]["BatchProcessorFunction"]
        events = func["Properties"]["Events"]
        kinesis_event = events.get("KinesisEvent", {})
        assert kinesis_event.get("Type") == "Kinesis"
        assert kinesis_event["Properties"]["BatchSize"] == 500

    def test_scheduled_processor_has_4_schedules(self, template):
        func = template["Resources"]["ScheduledProcessorFunction"]
        events = func["Properties"]["Events"]
        schedule_events = [k for k, v in events.items() if v.get("Type") == "Schedule"]
        assert len(schedule_events) == 4

    def test_critical_function_low_memory(self, template):
        func = template["Resources"]["CriticalAlertFunction"]
        assert func["Properties"]["MemorySize"] == 128

    def test_dashboard_medium_memory(self, template):
        func = template["Resources"]["DashboardFunction"]
        assert func["Properties"]["MemorySize"] == 512


# ── Synthetic Generator Lambda ──────────────────────────────


class TestSyntheticGenerator:
    def test_exists(self, template):
        assert "SyntheticGeneratorFunction" in template["Resources"]
        func = template["Resources"]["SyntheticGeneratorFunction"]
        assert func["Type"] == "AWS::Serverless::Function"

    def test_handler(self, template):
        func = template["Resources"]["SyntheticGeneratorFunction"]
        assert "synthetic_generator" in func["Properties"]["Handler"]

    def test_has_condition(self, template):
        func = template["Resources"]["SyntheticGeneratorFunction"]
        assert func["Condition"] == "IsSyntheticMode"

    def test_has_stream_env(self, template):
        func = template["Resources"]["SyntheticGeneratorFunction"]
        env = func["Properties"]["Environment"]["Variables"]
        assert "SENSOR_DATA_STREAM" in env

    def test_has_sensor_count_env(self, template):
        func = template["Resources"]["SyntheticGeneratorFunction"]
        env = func["Properties"]["Environment"]["Variables"]
        assert "SYNTHETIC_SENSOR_COUNT" in env

    def test_has_schedule_event(self, template):
        func = template["Resources"]["SyntheticGeneratorFunction"]
        events = func["Properties"]["Events"]
        assert any(v.get("Type") == "Schedule" for v in events.values())


# ── IoT Adapter Lambda ──────────────────────────────────────


class TestIoTAdapter:
    def test_exists(self, template):
        assert "IoTAdapterFunction" in template["Resources"]
        func = template["Resources"]["IoTAdapterFunction"]
        assert func["Type"] == "AWS::Serverless::Function"

    def test_handler(self, template):
        func = template["Resources"]["IoTAdapterFunction"]
        assert "iot_adapter" in func["Properties"]["Handler"]

    def test_has_condition(self, template):
        func = template["Resources"]["IoTAdapterFunction"]
        assert func["Condition"] == "IsIoTRuleEnabled"

    def test_has_stream_env(self, template):
        func = template["Resources"]["IoTAdapterFunction"]
        env = func["Properties"]["Environment"]["Variables"]
        assert "SENSOR_DATA_STREAM" in env

    def test_iot_rule_exists(self, template):
        assert "TempMonitorIoTRule" in template["Resources"]
        rule = template["Resources"]["TempMonitorIoTRule"]
        assert rule["Type"] == "AWS::IoT::TopicRule"
        assert rule["Condition"] == "IsIoTRuleEnabled"

    def test_iot_adapter_permission(self, template):
        assert "IoTAdapterInvokePermission" in template["Resources"]
        perm = template["Resources"]["IoTAdapterInvokePermission"]
        assert perm["Condition"] == "IsIoTRuleEnabled"


# ── Generic IoT Rules (conditional) ─────────────────────────


class TestGenericIoTRules:
    def test_critical_temp_rule_conditional(self, template):
        rule = template["Resources"]["CriticalTempRule"]
        assert rule.get("Condition") == "IsGenericIoT"

    def test_all_data_rule_conditional(self, template):
        rule = template["Resources"]["AllDataRule"]
        assert rule.get("Condition") == "IsGenericIoT"

    def test_iot_kinesis_role_conditional(self, template):
        role = template["Resources"]["IoTKinesisRole"]
        assert role.get("Condition") == "IsGenericIoT"

    def test_critical_alert_permission_conditional(self, template):
        perm = template["Resources"]["IoTInvokeCriticalAlertPermission"]
        assert perm.get("Condition") == "IsGenericIoT"

    def test_all_data_rule_has_role_arn(self, template):
        rule = template["Resources"]["AllDataRule"]
        actions = rule["Properties"]["TopicRulePayload"]["Actions"]
        kinesis_action = actions[0]["Kinesis"]
        assert "RoleArn" in kinesis_action

    def test_iot_kinesis_role_trust_policy(self, template):
        role = template["Resources"]["IoTKinesisRole"]
        assert role["Type"] == "AWS::IAM::Role"
        trust = str(role["Properties"]["AssumeRolePolicyDocument"])
        assert "iot.amazonaws.com" in trust


# ── No CloudFront ────────────────────────────────────────────


class TestNoCloudFront:
    def test_no_cloudfront_resource(self, template):
        for name, res in template["Resources"].items():
            assert res.get("Type") != "AWS::CloudFront::Distribution", \
                f"CloudFront resource {name} should not exist"

    def test_no_cloudfront_in_outputs(self, template):
        for name, out in template.get("Outputs", {}).items():
            val = str(out.get("Value", ""))
            assert "CloudFront" not in val and "cloudfront" not in val.lower(), \
                f"Output {name} should not reference CloudFront"


# ── DynamoDB Tables ───────────────────────────────────────


class TestDynamoDBTables:
    def test_platform_config_table_exists(self, template):
        assert "PlatformConfigTable" in template["Resources"]
        tbl = template["Resources"]["PlatformConfigTable"]
        assert tbl["Type"] == "AWS::DynamoDB::Table"
        assert tbl["Properties"]["BillingMode"] == "PAY_PER_REQUEST"

    def test_sensor_data_table_exists(self, template):
        assert "SensorDataTable" in template["Resources"]

    def test_alerts_table_exists(self, template):
        assert "AlertsTable" in template["Resources"]

    def test_sensor_data_has_client_index_gsi(self, template):
        tbl = template["Resources"]["SensorDataTable"]
        gsis = tbl["Properties"].get("GlobalSecondaryIndexes", [])
        gsi_names = [g["IndexName"] for g in gsis]
        assert "client-index" in gsi_names

    def test_alerts_has_client_index_gsi(self, template):
        tbl = template["Resources"]["AlertsTable"]
        gsis = tbl["Properties"].get("GlobalSecondaryIndexes", [])
        gsi_names = [g["IndexName"] for g in gsis]
        assert "client-index" in gsi_names

    def test_platform_config_has_zone_index_gsi(self, template):
        tbl = template["Resources"]["PlatformConfigTable"]
        gsis = tbl["Properties"].get("GlobalSecondaryIndexes", [])
        gsi_names = [g["IndexName"] for g in gsis]
        assert "zone-index" in gsi_names

    def test_sensor_data_client_gsi_keys(self, template):
        tbl = template["Resources"]["SensorDataTable"]
        gsis = tbl["Properties"]["GlobalSecondaryIndexes"]
        client_gsi = next(g for g in gsis if g["IndexName"] == "client-index")
        keys = {k["AttributeName"]: k["KeyType"] for k in client_gsi["KeySchema"]}
        assert keys["client_id"] == "HASH"
        assert keys["sk"] == "RANGE"

    def test_tables_have_pk_sk_schema(self, template):
        for name in ("PlatformConfigTable", "SensorDataTable", "AlertsTable"):
            tbl = template["Resources"][name]
            key_schema = tbl["Properties"]["KeySchema"]
            attr_names = {k["AttributeName"] for k in key_schema}
            assert {"pk", "sk"} == attr_names

    def test_ttl_enabled_on_sensor_data(self, template):
        tbl = template["Resources"]["SensorDataTable"]
        ttl = tbl["Properties"].get("TimeToLiveSpecification", {})
        assert ttl.get("Enabled") is True
        assert ttl.get("AttributeName") == "ttl"

    def test_ttl_enabled_on_alerts(self, template):
        tbl = template["Resources"]["AlertsTable"]
        ttl = tbl["Properties"].get("TimeToLiveSpecification", {})
        assert ttl.get("Enabled") is True


# ── API Gateway ───────────────────────────────────────────


class TestApiGateway:
    def test_dashboard_api_exists(self, template):
        assert "DashboardApi" in template["Resources"]
        api = template["Resources"]["DashboardApi"]
        assert api["Type"] == "AWS::Serverless::HttpApi"

    def test_cors_configuration(self, template):
        api = template["Resources"]["DashboardApi"]
        cors = api["Properties"].get("CorsConfiguration", {})
        assert "*" in cors.get("AllowOrigins", [])

    def test_dashboard_function_has_http_api_events(self, template):
        func = template["Resources"]["DashboardFunction"]
        events = func["Properties"]["Events"]
        assert "CatchAll" in events
        assert events["CatchAll"]["Type"] == "HttpApi"
        assert "Root" in events
        assert events["Root"]["Type"] == "HttpApi"

    def test_catch_all_uses_proxy(self, template):
        func = template["Resources"]["DashboardFunction"]
        catch_all = func["Properties"]["Events"]["CatchAll"]
        assert catch_all["Properties"]["Path"] == "/{proxy+}"
        assert catch_all["Properties"]["Method"] == "ANY"


# ── SNS Topics ────────────────────────────────────────────


class TestSNSTopics:
    def test_critical_alert_topic(self, template):
        assert "CriticalAlertTopic" in template["Resources"]
        assert template["Resources"]["CriticalAlertTopic"]["Type"] == "AWS::SNS::Topic"

    def test_standard_alert_topic(self, template):
        assert "StandardAlertTopic" in template["Resources"]


# ── S3 Bucket ─────────────────────────────────────────────


class TestS3Bucket:
    def test_data_lake_bucket_exists(self, template):
        assert "DataLakeBucket" in template["Resources"]
        bucket = template["Resources"]["DataLakeBucket"]
        assert bucket["Type"] == "AWS::S3::Bucket"

    def test_lifecycle_rules(self, template):
        bucket = template["Resources"]["DataLakeBucket"]
        rules = bucket["Properties"]["LifecycleConfiguration"]["Rules"]
        assert len(rules) >= 2


# ── IAM Policies ──────────────────────────────────────────


class TestIAMPolicies:
    def test_dashboard_has_secrets_manager_policy(self, template):
        func = template["Resources"]["DashboardFunction"]
        policies = func["Properties"]["Policies"]
        policy_strs = str(policies)
        assert "secretsmanager:GetSecretValue" in policy_strs
        assert "secretsmanager:ListSecrets" in policy_strs

    def test_dashboard_has_dynamodb_read_policies(self, template):
        func = template["Resources"]["DashboardFunction"]
        policies = func["Properties"]["Policies"]
        policy_strs = str(policies)
        assert "DynamoDBReadPolicy" in policy_strs

    def test_batch_processor_has_dynamodb_crud(self, template):
        func = template["Resources"]["BatchProcessorFunction"]
        policies = func["Properties"]["Policies"]
        policy_strs = str(policies)
        assert "DynamoDBCrudPolicy" in policy_strs

    def test_batch_processor_has_kinesis_read(self, template):
        func = template["Resources"]["BatchProcessorFunction"]
        policies = func["Properties"]["Policies"]
        policy_strs = str(policies)
        assert "KinesisStreamReadPolicy" in policy_strs

    def test_batch_processor_has_sns_publish(self, template):
        func = template["Resources"]["BatchProcessorFunction"]
        policies = func["Properties"]["Policies"]
        policy_strs = str(policies)
        assert "SNSPublishMessagePolicy" in policy_strs

    def test_secrets_manager_uses_partition(self, template):
        func = template["Resources"]["DashboardFunction"]
        policies_str = str(func["Properties"]["Policies"])
        assert "AWS::Partition" in policies_str or "${AWS::Partition}" in policies_str


# ── Outputs ───────────────────────────────────────────────


class TestOutputs:
    def test_dashboard_url_output(self, template):
        outputs = template.get("Outputs", {})
        assert "DashboardUrl" in outputs
        assert "API Gateway" in outputs["DashboardUrl"].get("Description", "")

    def test_no_separate_api_url_output(self, template):
        outputs = template.get("Outputs", {})
        assert "DashboardApiUrl" not in outputs

    def test_batch_processor_arn_output(self, template):
        outputs = template.get("Outputs", {})
        assert "BatchProcessorArn" in outputs

    def test_data_lake_bucket_output(self, template):
        outputs = template.get("Outputs", {})
        assert "DataLakeBucketName" in outputs

    def test_sensor_data_table_output(self, template):
        outputs = template.get("Outputs", {})
        assert "SensorDataTableName" in outputs

    def test_alerts_table_output(self, template):
        outputs = template.get("Outputs", {})
        assert "AlertsTableName" in outputs
