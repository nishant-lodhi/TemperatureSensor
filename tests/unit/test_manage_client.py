"""Unit tests for scripts/manage_client.py — Secrets Manager client management CLI."""

import json
import os
import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import pytest
from botocore.exceptions import ClientError

from manage_client import (
    _new_token,
    _secret_name,
    cmd_add,
    cmd_list,
    cmd_remove,
    cmd_rotate,
)


# ── Helpers ───────────────────────────────────────────────


class TestHelpers:
    def test_secret_name_format(self):
        assert _secret_name("deploy123", "client_a") == "TempMonitor/deploy123/client_a"

    def test_secret_name_with_special_chars(self):
        result = _secret_name("abcdef1234", "my-client_v2")
        assert result == "TempMonitor/abcdef1234/my-client_v2"

    def test_new_token_is_uuid_format(self):
        token = _new_token()
        parts = token.split("-")
        assert len(parts) == 5
        assert len(token) == 36

    def test_new_token_unique(self):
        tokens = {_new_token() for _ in range(100)}
        assert len(tokens) == 100


# ── cmd_add ───────────────────────────────────────────────


class TestCmdAdd:
    @patch("manage_client.boto3")
    def test_creates_secret(self, mock_boto3, capsys):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm

        args = Namespace(
            region="us-east-1",
            deployment_id="deploy0001",
            client_id="client_a",
            client_name="Facility Alpha",
        )
        cmd_add(args)

        mock_sm.create_secret.assert_called_once()
        call_kwargs = mock_sm.create_secret.call_args[1]
        assert call_kwargs["Name"] == "TempMonitor/deploy0001/client_a"
        secret_data = json.loads(call_kwargs["SecretString"])
        assert secret_data["client_id"] == "client_a"
        assert secret_data["client_name"] == "Facility Alpha"
        assert "access_token" in secret_data

        out = capsys.readouterr().out
        assert "Client created" in out
        assert "/connect/" in out

    @patch("manage_client.boto3")
    def test_duplicate_client_exits(self, mock_boto3):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_sm.create_secret.side_effect = ClientError(
            {"Error": {"Code": "ResourceExistsException", "Message": "exists"}},
            "CreateSecret",
        )

        args = Namespace(
            region="us-east-1",
            deployment_id="deploy0001",
            client_id="client_a",
            client_name="Alpha",
        )
        with pytest.raises(SystemExit) as exc:
            cmd_add(args)
        assert exc.value.code == 1

    @patch("manage_client.boto3")
    def test_uses_client_id_as_name_when_empty(self, mock_boto3, capsys):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm

        args = Namespace(
            region="us-east-1",
            deployment_id="deploy0001",
            client_id="my_client",
            client_name="",
        )
        cmd_add(args)

        call_kwargs = mock_sm.create_secret.call_args[1]
        secret_data = json.loads(call_kwargs["SecretString"])
        assert secret_data["client_name"] == "my_client"


# ── cmd_list ──────────────────────────────────────────────


class TestCmdList:
    @patch("manage_client.boto3")
    def test_lists_clients(self, mock_boto3, capsys):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_paginator = MagicMock()
        mock_sm.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{
            "SecretList": [{"Name": "TempMonitor/deploy0001/client_a"}]
        }]
        mock_sm.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "access_token": "tok-123",
                "client_id": "client_a",
                "client_name": "Alpha",
                "created_at": "2026-01-01T00:00:00Z",
            })
        }

        args = Namespace(region="us-east-1", deployment_id="deploy0001")
        cmd_list(args)

        out = capsys.readouterr().out
        assert "client_a" in out
        assert "Alpha" in out
        assert "/connect/" in out

    @patch("manage_client.boto3")
    def test_empty_list(self, mock_boto3, capsys):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_paginator = MagicMock()
        mock_sm.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [{"SecretList": []}]

        args = Namespace(region="us-east-1", deployment_id="deploy0001")
        cmd_list(args)

        out = capsys.readouterr().out
        assert "No clients found" in out


# ── cmd_remove ────────────────────────────────────────────


class TestCmdRemove:
    @patch("manage_client.boto3")
    def test_removes_secret(self, mock_boto3, capsys):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm

        args = Namespace(region="us-east-1", deployment_id="deploy0001", client_id="client_a")
        cmd_remove(args)

        mock_sm.delete_secret.assert_called_once_with(
            SecretId="TempMonitor/deploy0001/client_a",
            ForceDeleteWithoutRecovery=True,
        )
        out = capsys.readouterr().out
        assert "removed" in out.lower()

    @patch("manage_client.boto3")
    def test_not_found_exits(self, mock_boto3):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_sm.delete_secret.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "DeleteSecret",
        )

        args = Namespace(region="us-east-1", deployment_id="deploy0001", client_id="unknown")
        with pytest.raises(SystemExit) as exc:
            cmd_remove(args)
        assert exc.value.code == 1


# ── cmd_rotate ────────────────────────────────────────────


class TestCmdRotate:
    @patch("manage_client.boto3")
    def test_rotates_token(self, mock_boto3, capsys):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_sm.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "access_token": "old-token",
                "client_id": "client_a",
                "client_name": "Alpha",
                "created_at": "2026-01-01T00:00:00Z",
            })
        }

        args = Namespace(region="us-east-1", deployment_id="deploy0001", client_id="client_a")
        cmd_rotate(args)

        mock_sm.put_secret_value.assert_called_once()
        call_kwargs = mock_sm.put_secret_value.call_args[1]
        new_data = json.loads(call_kwargs["SecretString"])
        assert new_data["access_token"] != "old-token"
        assert "rotated_at" in new_data
        assert new_data["client_id"] == "client_a"

        out = capsys.readouterr().out
        assert "rotated" in out.lower()
        assert "/connect/" in out

    @patch("manage_client.boto3")
    def test_not_found_exits(self, mock_boto3):
        mock_sm = MagicMock()
        mock_boto3.client.return_value = mock_sm
        mock_sm.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
            "DeleteSecret",
        )

        args = Namespace(region="us-east-1", deployment_id="deploy0001", client_id="unknown")
        with pytest.raises(SystemExit) as exc:
            cmd_rotate(args)
        assert exc.value.code == 1
