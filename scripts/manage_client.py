#!/usr/bin/env python3
"""Client management CLI — add, list, remove, and rotate access tokens.

Each client gets a Secrets Manager secret at:
  {project_prefix}/{deployment_id}/{client_id}

The secret contains:
  {
    "access_token": "<uuid>",
    "client_id": "<client_id>",
    "client_name": "<human name>",
    "created_at": "<iso timestamp>"
  }

Usage:
  python scripts/manage_client.py add    --deployment-id X --client-id Y --client-name "Z"
  python scripts/manage_client.py list   --deployment-id X
  python scripts/manage_client.py remove --deployment-id X --client-id Y
  python scripts/manage_client.py rotate --deployment-id X --client-id Y
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


DEFAULT_PREFIX = os.environ.get("PROJECT_PREFIX", "TempSensor")


def _secret_name(deployment_id: str, client_id: str, prefix: str = "") -> str:
    return f"{prefix or DEFAULT_PREFIX}/{deployment_id}/{client_id}"


def _new_token() -> str:
    return str(uuid.uuid4())


def _resolve_dashboard_url(region: str, deployment_id: str, prefix: str = "") -> str:
    """Try to get the dashboard URL from CloudFormation stack outputs."""
    prefix = prefix or DEFAULT_PREFIX
    cf = boto3.client("cloudformation", region_name=region)
    for suffix in ["dev", "staging", "prod", "saas-dev", "govcloud-dev", "govcloud-prod"]:
        stack_name = f"{prefix}-{suffix}"
        try:
            resp = cf.describe_stacks(StackName=stack_name)
            outputs = resp["Stacks"][0].get("Outputs", [])
            for o in outputs:
                if o["OutputKey"] == "DashboardUrl":
                    dep_id = None
                    for p in resp["Stacks"][0].get("Parameters", []):
                        if p["ParameterKey"] == "DeploymentId":
                            dep_id = p["ParameterValue"]
                    if dep_id == deployment_id:
                        return o["OutputValue"]
        except Exception:
            continue
    return ""


def cmd_add(args):
    sm = boto3.client("secretsmanager", region_name=args.region)
    name = _secret_name(args.deployment_id, args.client_id, args.project_prefix)
    token = _new_token()

    secret_value = {
        "access_token": token,
        "client_id": args.client_id,
        "client_name": args.client_name or args.client_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        sm.create_secret(
            Name=name,
            SecretString=json.dumps(secret_value),
            Description=f"TempMonitor access token for {args.client_id}",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceExistsException":
            print(f"ERROR: Client '{args.client_id}' already exists. Use 'rotate' to generate a new token.")
            sys.exit(1)
        raise

    base_url = args.dashboard_url or _resolve_dashboard_url(args.region, args.deployment_id, args.project_prefix)
    url_display = f"{base_url}/connect/{token}" if base_url else f"https://<YOUR-DASHBOARD-URL>/connect/{token}"

    print("Client created successfully.")
    print(f"  Client ID:    {args.client_id}")
    print(f"  Client Name:  {args.client_name}")
    print(f"  Secret Name:  {name}")
    print(f"  Access URL:   {url_display}")
    if not base_url:
        print()
        print("  TIP: Could not auto-detect dashboard URL. Pass --dashboard-url or run:")
        print(f"    aws cloudformation describe-stacks --stack-name {args.project_prefix}-<env> --query 'Stacks[0].Outputs' --output table")
    print()
    print("Share the access URL with facility officers.")
    print("They only need to visit this link once — a session cookie will persist access.")


def cmd_list(args):
    sm = boto3.client("secretsmanager", region_name=args.region)
    prefix = f"{args.project_prefix}/{args.deployment_id}/"
    clients = []

    paginator = sm.get_paginator("list_secrets")
    for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
        for entry in page.get("SecretList", []):
            try:
                resp = sm.get_secret_value(SecretId=entry["Name"])
                data = json.loads(resp["SecretString"])
                clients.append({
                    "client_id": data.get("client_id", "?"),
                    "client_name": data.get("client_name", "?"),
                    "token": data.get("access_token", "?"),
                    "created_at": data.get("created_at", "?"),
                })
            except Exception:
                continue

    if not clients:
        print(f"No clients found for deployment '{args.deployment_id}'.")
        return

    base_url = args.dashboard_url or _resolve_dashboard_url(args.region, args.deployment_id, args.project_prefix)
    domain = base_url if base_url else "https://<DASHBOARD-URL>"

    print(f"Clients for deployment '{args.deployment_id}':")
    print(f"{'Client ID':<20} {'Name':<30} {'Created':<24} {'Access URL'}")
    print("-" * 120)
    for c in sorted(clients, key=lambda x: x["client_id"]):
        url = f"{domain}/connect/{c['token']}"
        print(f"{c['client_id']:<20} {c['client_name']:<30} {c['created_at'][:19]:<24} {url}")


def cmd_remove(args):
    sm = boto3.client("secretsmanager", region_name=args.region)
    name = _secret_name(args.deployment_id, args.client_id, args.project_prefix)

    try:
        sm.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        print(f"Client '{args.client_id}' removed. Access revoked immediately.")
        print("Officers will see 'session expired' within 5 minutes (cache TTL).")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"ERROR: Client '{args.client_id}' not found.")
            sys.exit(1)
        raise


def cmd_rotate(args):
    sm = boto3.client("secretsmanager", region_name=args.region)
    name = _secret_name(args.deployment_id, args.client_id, args.project_prefix)

    try:
        resp = sm.get_secret_value(SecretId=name)
        data = json.loads(resp["SecretString"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"ERROR: Client '{args.client_id}' not found.")
            sys.exit(1)
        raise

    new_token = _new_token()
    data["access_token"] = new_token
    data["rotated_at"] = datetime.now(timezone.utc).isoformat()

    sm.put_secret_value(SecretId=name, SecretString=json.dumps(data))

    base_url = args.dashboard_url or _resolve_dashboard_url(args.region, args.deployment_id, args.project_prefix)
    domain = base_url if base_url else "https://<DASHBOARD-URL>"

    print(f"Token rotated for client '{args.client_id}'.")
    print(f"  New Access URL: {domain}/connect/{new_token}")
    print()
    print("The old URL will stop working within 5 minutes (cache TTL).")
    print("Officers using the old link will see a 'session expired' page.")
    print("Share the new URL with facility officers.")


def main():
    parser = argparse.ArgumentParser(description="TempSensor client management")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"), help="AWS region")
    parser.add_argument("--project-prefix", default=DEFAULT_PREFIX,
                        help=f"Project prefix for resource naming (default: {DEFAULT_PREFIX})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a new client")
    p_add.add_argument("--deployment-id", required=True, help="10-char deployment ID")
    p_add.add_argument("--client-id", required=True, help="Unique client identifier")
    p_add.add_argument("--client-name", default="", help="Human-readable client/facility name")
    p_add.add_argument("--dashboard-url", default="", help="Dashboard base URL (auto-detected from CloudFormation if omitted)")

    p_list = sub.add_parser("list", help="List all clients for a deployment")
    p_list.add_argument("--deployment-id", required=True, help="10-char deployment ID")
    p_list.add_argument("--dashboard-url", default="", help="Dashboard base URL (auto-detected if omitted)")

    p_rm = sub.add_parser("remove", help="Remove a client (revoke access)")
    p_rm.add_argument("--deployment-id", required=True, help="10-char deployment ID")
    p_rm.add_argument("--client-id", required=True, help="Client to remove")

    p_rot = sub.add_parser("rotate", help="Generate new access token for a client")
    p_rot.add_argument("--deployment-id", required=True, help="10-char deployment ID")
    p_rot.add_argument("--client-id", required=True, help="Client to rotate")
    p_rot.add_argument("--dashboard-url", default="", help="Dashboard base URL (auto-detected if omitted)")

    args = parser.parse_args()
    cmds = {"add": cmd_add, "list": cmd_list, "remove": cmd_remove, "rotate": cmd_rotate}
    cmds[args.command](args)


if __name__ == "__main__":
    main()
